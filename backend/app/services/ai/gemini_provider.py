
"""Google Gemini implementation of AIProvider.

PersonaAI Gemini provider using the Gemini REST API over httpx.

Production features:
- Retry handling for transient Gemini failures
- Exponential backoff with jitter
- Retry-After support
- Primary + fallback model routing
- Automatic fallback on repeated transient failures
- Correct authentication/error handling
- Gemini function/tool calling
- Preservation of Gemini model response parts
- Thought-signature-safe conversation history
- Multimodal image understanding
- Audio transcription
- 768-dimensional Gemini embeddings
- Gemini 3.x thinking-level support
- Low-latency settings for normal customer conversations
- API key sent through secure request headers
"""

from __future__ import annotations

import asyncio
import base64
import logging
import random
from typing import Any

import httpx

from app.config import settings
from app.services.ai.base import AIProvider, ToolDefinition, ToolExecutor
from app.services.ai.exceptions import (
    AIAuthenticationError,
    AIProviderError,
    AIRateLimitError,
)

logger = logging.getLogger(__name__)


GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


# ============================================================================
# EMBEDDINGS
# ============================================================================

# PersonaAI's pgvector schema currently uses 768 dimensions.
GEMINI_EMBEDDING_DIMENSION = 768

DEFAULT_GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"

RETIRED_EMBEDDING_MODELS = {
    "text-embedding-004",
    "models/text-embedding-004",
}


# ============================================================================
# RETRIES
# ============================================================================

# Gemini documents these as transient/retryable errors:
#
#   408 Request Timeout
#   429 Resource Exhausted / Rate Limit
#   5xx Server Errors
#
# Do NOT retry normal client/configuration errors such as:
#
#   400 Bad Request
#   401 Unauthorized
#   402 Payment Required / depleted credits
#   403 Forbidden
#   404 Not Found

TRANSIENT_STATUS_CODES = {
    408,
    429,
    500,
    502,
    503,
    504,
}

# Number of RETRIES after the initial request.
#
# Total requests per model:
#
#   Initial request
#   Retry 1
#   Retry 2
#   Retry 3
#   Retry 4
#
# = 5 total attempts per model.
MAX_RETRIES_PER_MODEL = 4

# Exponential backoff:
#
# Retry 1 -> approximately 1 second
# Retry 2 -> approximately 2 seconds
# Retry 3 -> approximately 4 seconds
# Retry 4 -> approximately 8 seconds
#
# Jitter is added to prevent multiple workers from retrying at exactly
# the same time.

INITIAL_RETRY_DELAY = 1.0
MAX_RETRY_DELAY = 60.0

# Maximum amount of time PersonaAI will honor from Gemini's Retry-After
# header. This prevents a single customer request from being blocked
# indefinitely.

MAX_RETRY_AFTER = 60.0


# ============================================================================
# GEMINI 3 THINKING
# ============================================================================

# Gemini 3.x supports:
#
#   low
#   medium
#   high
#
# PersonaAI is a real-time customer conversation system, so LOW is the
# default. This keeps latency and token consumption under control.

DEFAULT_THINKING_LEVEL = "low"

VALID_THINKING_LEVELS = {
    "low",
    "medium",
    "high",
}


# ============================================================================
# INTERNAL TRANSIENT ERROR
# ============================================================================


class _TransientAIError(Exception):
    """Internal marker for retryable Gemini failures."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message)

        self.status_code = status_code
        self.retry_after = retry_after


# ============================================================================
# PROVIDER
# ============================================================================


class GeminiProvider(AIProvider):
    """Gemini REST implementation of the AIProvider interface."""

    name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        embedding_model: str | None = None,
        timeout: float = 30.0,
    ):
        self.api_key = api_key or settings.GEMINI_API_KEY

        self.model = self._clean_model_name(
            model or settings.GEMINI_MODEL
        )

        configured_fallback = getattr(
            settings,
            "GEMINI_FALLBACK_MODEL",
            "",
        )

        self.fallback_model = (
            self._clean_model_name(configured_fallback)
            if configured_fallback
            else None
        )

        # Never use the same model twice.
        if self.fallback_model == self.model:
            logger.warning(
                "GEMINI_FALLBACK_MODEL is the same as "
                "GEMINI_MODEL. Disabling fallback."
            )
            self.fallback_model = None

        configured_embedding_model = (
            embedding_model
            or getattr(
                settings,
                "GEMINI_EMBEDDING_MODEL",
                None,
            )
            or DEFAULT_GEMINI_EMBEDDING_MODEL
        )

        self.embedding_model = self._normalize_embedding_model(
            configured_embedding_model
        )

        self._client = httpx.AsyncClient(
            base_url=GEMINI_API_BASE,
            timeout=httpx.Timeout(
                timeout,
                connect=min(timeout, 10.0),
            ),
        )

        if not self.api_key:
            logger.warning(
                "GeminiProvider initialized without GEMINI_API_KEY."
            )

        logger.info(
            (
                "GeminiProvider initialized: "
                "primary=%s fallback=%s embedding=%s "
                "dimensions=%s thinking=%s"
            ),
            self.model,
            self.fallback_model or "<disabled>",
            self.embedding_model,
            GEMINI_EMBEDDING_DIMENSION,
            DEFAULT_THINKING_LEVEL,
        )

    # =========================================================================
    # NORMALIZATION
    # =========================================================================

    @staticmethod
    def _clean_model_name(model: str) -> str:
        """Remove optional models/ prefix."""

        return model.strip().removeprefix("models/")

    @classmethod
    def _normalize_embedding_model(
        cls,
        model: str,
    ) -> str:
        """Normalize embedding model and protect against retired models."""

        clean_model = cls._clean_model_name(model)

        if clean_model in RETIRED_EMBEDDING_MODELS:
            logger.warning(
                (
                    "Embedding model '%s' is retired. "
                    "Using '%s' instead."
                ),
                model,
                DEFAULT_GEMINI_EMBEDDING_MODEL,
            )

            return DEFAULT_GEMINI_EMBEDDING_MODEL

        return clean_model

    @staticmethod
    def _normalize_thinking_level(
        thinking_level: str | None,
    ) -> str:
        """Validate Gemini 3.x thinking level."""

        level = (
            thinking_level or DEFAULT_THINKING_LEVEL
        ).strip().lower()

        if level not in VALID_THINKING_LEVELS:
            logger.warning(
                (
                    "Invalid Gemini thinking level '%s'. "
                    "Using '%s'."
                ),
                thinking_level,
                DEFAULT_THINKING_LEVEL,
            )

            return DEFAULT_THINKING_LEVEL

        return level

    @staticmethod
    def _is_gemini_3_model(
        model: str,
    ) -> bool:
        """Return whether the supplied model is Gemini 3.x."""

        clean_model = model.strip().removeprefix("models/")

        return clean_model.startswith("gemini-3.")

    # =========================================================================
    # RETRY HELPERS
    # =========================================================================

    @staticmethod
    def _parse_retry_after(
        response: httpx.Response,
    ) -> float | None:
        """Read Retry-After header if Gemini provides one."""

        value = response.headers.get("Retry-After")

        if not value:
            return None

        try:
            seconds = float(value)

            if seconds < 0:
                return None

            return min(
                seconds,
                MAX_RETRY_AFTER,
            )

        except (TypeError, ValueError):
            return None

    @staticmethod
    def _calculate_backoff(
        retry_number: int,
    ) -> float:
        """Calculate exponential backoff with jitter.

        Approximate delays:

            retry 1 -> 1s + jitter
            retry 2 -> 2s + jitter
            retry 3 -> 4s + jitter
            retry 4 -> 8s + jitter

        The delay is capped at MAX_RETRY_DELAY.
        """

        base_delay = min(
            INITIAL_RETRY_DELAY
            * (2 ** (retry_number - 1)),
            MAX_RETRY_DELAY,
        )

        # Add up to 25% random jitter.
        jitter = random.uniform(
            0,
            base_delay * 0.25,
        )

        return min(
            base_delay + jitter,
            MAX_RETRY_DELAY,
        )

    # =========================================================================
    # HTTP
    # =========================================================================

    async def aclose(self) -> None:
        """Close the HTTP client."""

        await self._client.aclose()

    async def _post(
        self,
        path: str,
        json_body: dict[str, Any],
    ) -> dict[str, Any]:
        """POST request to Gemini with production retry handling.

        Retryable:
            408
            429
            500
            502
            503
            504
            timeouts
            transport errors

        Non-retryable:
            400
            401
            402
            403
            404
            other client errors

        Retry strategy:
            exponential backoff + jitter

        Retry-After:
            respected when Gemini provides it.

        The API key is sent through x-goog-api-key instead of a URL
        query parameter so it does not appear in request URLs.
        """

        if not self.api_key:
            raise AIAuthenticationError(
                "Gemini API key is not configured.",
                self.name,
            )

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        last_error: _TransientAIError | None = None

        # MAX_RETRIES_PER_MODEL = 4 means:
        #
        # attempt 1 = initial request
        # attempt 2 = retry 1
        # attempt 3 = retry 2
        # attempt 4 = retry 3
        # attempt 5 = retry 4
        #
        # Therefore range() goes through 5 total requests.

        total_attempts = MAX_RETRIES_PER_MODEL + 1

        for attempt in range(
            1,
            total_attempts + 1,
        ):
            last_error = None

            try:
                response = await self._client.post(
                    path,
                    headers=headers,
                    json=json_body,
                )

            except httpx.TimeoutException as exc:
                # Network timeout is transient and should be retried.
                last_error = _TransientAIError(
                    f"Gemini request timed out: {exc}"
                )

                logger.warning(
                    (
                        "Gemini timeout "
                        "attempt=%s/%s path=%s"
                    ),
                    attempt,
                    total_attempts,
                    path,
                )

            except httpx.TransportError as exc:
                # Transport errors are transient.
                last_error = _TransientAIError(
                    f"Gemini transport error: {exc}"
                )

                logger.warning(
                    (
                        "Gemini transport error "
                        "attempt=%s/%s path=%s error=%s"
                    ),
                    attempt,
                    total_attempts,
                    path,
                    exc,
                )

            else:
                status = response.status_code

                # =============================================================
                # SUCCESS
                # =============================================================

                if 200 <= status < 300:
                    try:
                        return response.json()

                    except ValueError as exc:
                        raise AIProviderError(
                            "Gemini returned invalid JSON.",
                            self.name,
                            exc,
                        ) from exc

                # =============================================================
                # AUTHENTICATION / AUTHORIZATION
                #
                # Do NOT retry these.
                # =============================================================

                if status in (401, 403):
                    raise AIAuthenticationError(
                        (
                            "Gemini API key is invalid, missing, "
                            "or not authorized for this request."
                        ),
                        self.name,
                    )

                # =============================================================
                # TRANSIENT ERROR
                #
                # Retry 408, 429 and 5xx.
                # =============================================================

                if status in TRANSIENT_STATUS_CODES:
                    retry_after = self._parse_retry_after(
                        response
                    )

                    last_error = _TransientAIError(
                        (
                            f"Gemini returned {status}: "
                            f"{response.text}"
                        ),
                        status_code=status,
                        retry_after=retry_after,
                    )

                    logger.warning(
                        (
                            "Gemini transient error "
                            "attempt=%s/%s status=%s "
                            "retry_after=%s path=%s"
                        ),
                        attempt,
                        total_attempts,
                        status,
                        retry_after,
                        path,
                    )

                # =============================================================
                # NON-RETRYABLE ERROR
                #
                # 400 / 402 / 403 / 404 and other client/configuration errors
                # are returned immediately.
                # =============================================================

                elif status >= 400:
                    raise AIProviderError(
                        (
                            f"Gemini request failed ({status}): "
                            f"{response.text}"
                        ),
                        self.name,
                    )

                else:
                    raise AIProviderError(
                        (
                            f"Unexpected Gemini HTTP status "
                            f"{status}: {response.text}"
                        ),
                        self.name,
                    )

            # =================================================================
            # RETRY DECISION
            # =================================================================

            if last_error is None:
                continue

            # All attempts for this model have been exhausted.
            if attempt >= total_attempts:
                break

            # Gemini explicitly supplied Retry-After.
            if last_error.retry_after is not None:
                delay = last_error.retry_after

                logger.info(
                    (
                        "Gemini Retry-After received: "
                        "%.2fs"
                    ),
                    delay,
                )

            # Otherwise use exponential backoff + jitter.
            else:
                retry_number = attempt

                delay = self._calculate_backoff(
                    retry_number
                )

            logger.info(
                (
                    "Retrying Gemini request in %.2fs "
                    "(retry=%s/%s status=%s)"
                ),
                delay,
                attempt,
                MAX_RETRIES_PER_MODEL,
                last_error.status_code,
            )

            await asyncio.sleep(delay)

        # =====================================================================
        # ALL RETRIES EXHAUSTED
        # =====================================================================

        if last_error is not None:
            raise last_error

        raise AIProviderError(
            "Gemini request failed for an unknown reason.",
            self.name,
        )

    # =========================================================================
    # GENERATION + FALLBACK
    # =========================================================================

    async def _generate_content_with_fallback(
        self,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate content using primary and optional fallback model."""

        models: list[str] = [self.model]

        if self.fallback_model:
            models.append(self.fallback_model)

        last_error: Exception | None = None

        for index, model in enumerate(models):
            is_fallback = index > 0

            request_path = (
                f"/models/{model}:generateContent"
            )

            logger.info(
                (
                    "Gemini generation request "
                    "model=%s fallback=%s"
                ),
                model,
                is_fallback,
            )

            try:
                # Make a shallow copy so one model's generation configuration
                # cannot mutate the next model's request.

                model_body = dict(body)

                original_generation_config = body.get(
                    "generationConfig"
                )

                if isinstance(
                    original_generation_config,
                    dict,
                ):
                    generation_config = dict(
                        original_generation_config
                    )

                    # Gemini 3.x does not use the old temperature parameter.
                    if self._is_gemini_3_model(model):
                        generation_config.pop(
                            "temperature",
                            None,
                        )

                        if "thinkingConfig" not in generation_config:
                            generation_config[
                                "thinkingConfig"
                            ] = {
                                "thinkingLevel": (
                                    DEFAULT_THINKING_LEVEL
                                )
                            }

                    model_body["generationConfig"] = (
                        generation_config
                    )

                return await self._post(
                    request_path,
                    model_body,
                )

            except _TransientAIError as exc:
                last_error = exc

                logger.warning(
                    (
                        "Gemini model unavailable "
                        "model=%s fallback=%s status=%s"
                    ),
                    model,
                    is_fallback,
                    exc.status_code,
                )

                # -------------------------------------------------------------
                # PRIMARY FAILED -> FALLBACK
                # -------------------------------------------------------------

                if (
                    not is_fallback
                    and self.fallback_model
                ):
                    logger.warning(
                        (
                            "Primary Gemini model failed "
                            "after retries. Switching to "
                            "fallback model=%s"
                        ),
                        self.fallback_model,
                    )

                    continue

                # -------------------------------------------------------------
                # FALLBACK FAILED
                # -------------------------------------------------------------

                logger.error(
                    (
                        "Gemini model failed and no usable "
                        "fallback remains. model=%s status=%s"
                    ),
                    model,
                    exc.status_code,
                )

            except AIAuthenticationError:
                raise

            except AIProviderError:
                raise

        # ---------------------------------------------------------------------
        # FINAL TRANSIENT ERROR
        # ---------------------------------------------------------------------

        if isinstance(
            last_error,
            _TransientAIError,
        ):
            if last_error.status_code == 429:
                raise AIRateLimitError(
                    (
                        "Gemini rate limit exceeded "
                        "after retries and fallback."
                    ),
                    self.name,
                ) from last_error

            raise AIProviderError(
                (
                    "Gemini is temporarily unavailable "
                    "after retries"
                    + (
                        " and the fallback model also failed."
                        if self.fallback_model
                        else "."
                    )
                ),
                self.name,
                last_error,
            ) from last_error

        raise AIProviderError(
            "Gemini generation failed.",
            self.name,
        )

    # =========================================================================
    # GENERATION CONFIG
    # =========================================================================

    def _build_generation_config(
        self,
        *,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        thinking_level: str | None = None,
    ) -> dict[str, Any]:
        """Build Gemini generation configuration.

        Gemini 3.x:
            - Do not send temperature.
            - Use thinkingConfig.thinkingLevel.

        Older Gemini models:
            - Temperature remains supported.
        """

        config: dict[str, Any] = {}

        if max_tokens is not None:
            config["maxOutputTokens"] = max_tokens

        if self._is_gemini_3_model(model):
            level = self._normalize_thinking_level(
                thinking_level
            )

            config["thinkingConfig"] = {
                "thinkingLevel": level,
            }

        elif temperature is not None:
            config["temperature"] = temperature

        return config

    # =========================================================================
    # RESPONSE EXTRACTION
    # =========================================================================

    @staticmethod
    def _extract_text(
        data: dict[str, Any],
    ) -> str:
        """Extract text from Gemini response."""

        try:
            candidates = data["candidates"]

            if not candidates:
                raise AIProviderError(
                    (
                        "Gemini returned no candidates. "
                        "The response may have been blocked "
                        "by safety filters."
                    ),
                    "gemini",
                )

            content = candidates[0].get(
                "content",
                {},
            )

            parts = content.get(
                "parts",
                [],
            )

            if not isinstance(
                parts,
                list,
            ):
                raise AIProviderError(
                    (
                        "Gemini returned invalid content "
                        f"parts: {parts}"
                    ),
                    "gemini",
                )

            text = "".join(
                part.get("text", "")
                for part in parts
                if isinstance(part, dict)
                and isinstance(
                    part.get("text"),
                    str,
                )
            ).strip()

            if not text:
                finish_reason = candidates[0].get(
                    "finishReason"
                )

                raise AIProviderError(
                    (
                        "Gemini returned no text content. "
                        f"finishReason={finish_reason} "
                        f"response={data}"
                    ),
                    "gemini",
                )

            return text

        except AIProviderError:
            raise

        except (
            KeyError,
            IndexError,
            TypeError,
        ) as exc:
            raise AIProviderError(
                (
                    "Unexpected Gemini response shape: "
                    f"{data}"
                ),
                "gemini",
                exc,
            ) from exc

    @staticmethod
    def _extract_candidate_parts(
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Extract all response parts from first candidate."""

        try:
            candidates = data["candidates"]

            if not candidates:
                raise AIProviderError(
                    "Gemini returned no candidates.",
                    "gemini",
                )

            content = candidates[0].get(
                "content",
                {},
            )

            parts = content.get(
                "parts",
                [],
            )

            if not isinstance(
                parts,
                list,
            ):
                raise AIProviderError(
                    (
                        "Gemini returned invalid parts: "
                        f"{parts}"
                    ),
                    "gemini",
                )

            return parts

        except AIProviderError:
            raise

        except (
            KeyError,
            IndexError,
            TypeError,
        ) as exc:
            raise AIProviderError(
                (
                    "Unexpected Gemini tool response "
                    f"shape: {data}"
                ),
                "gemini",
                exc,
            ) from exc

    @staticmethod
    def _extract_function_calls(
        parts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Extract Gemini functionCall objects."""

        calls: list[dict[str, Any]] = []

        for part in parts:
            if not isinstance(
                part,
                dict,
            ):
                continue

            function_call = part.get(
                "functionCall"
            )

            if isinstance(
                function_call,
                dict,
            ):
                calls.append(
                    function_call
                )

        return calls

    # =========================================================================
    # TEXT GENERATION
    # =========================================================================

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Generate normal customer-facing text."""

        body: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": prompt,
                        }
                    ],
                }
            ],
            "generationConfig": (
                self._build_generation_config(
                    model=self.model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    thinking_level=DEFAULT_THINKING_LEVEL,
                )
            ),
        }

        if system_instruction:
            body["systemInstruction"] = {
                "parts": [
                    {
                        "text": system_instruction,
                    }
                ],
            }

        data = await self._generate_content_with_fallback(
            body
        )

        return self._extract_text(data)

    # =========================================================================
    # EMBEDDINGS
    # =========================================================================

    async def embed(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Generate 768-dimensional Gemini embeddings."""

        if not texts:
            return []

        clean_texts = [
            text.strip()
            for text in texts
            if isinstance(text, str)
            and text.strip()
        ]

        if not clean_texts:
            return []

        self.embedding_model = (
            self._normalize_embedding_model(
                self.embedding_model
            )
        )

        body = {
            "requests": [
                {
                    "model": (
                        f"models/{self.embedding_model}"
                    ),
                    "content": {
                        "parts": [
                            {
                                "text": text,
                            }
                        ]
                    },
                    "outputDimensionality": (
                        GEMINI_EMBEDDING_DIMENSION
                    ),
                }
                for text in clean_texts
            ]
        }

        logger.debug(
            (
                "Generating Gemini embeddings "
                "count=%s model=%s dimensions=%s"
            ),
            len(clean_texts),
            self.embedding_model,
            GEMINI_EMBEDDING_DIMENSION,
        )

        try:
            data = await self._post(
                (
                    f"/models/{self.embedding_model}:"
                    "batchEmbedContents"
                ),
                body,
            )

        except _TransientAIError as exc:
            if exc.status_code == 429:
                raise AIRateLimitError(
                    "Gemini embedding rate limit exceeded.",
                    self.name,
                ) from exc

            raise AIProviderError(
                (
                    "Gemini embedding service is "
                    "temporarily unavailable."
                ),
                self.name,
                exc,
            ) from exc

        try:
            embeddings = data["embeddings"]

        except (
            KeyError,
            TypeError,
        ) as exc:
            raise AIProviderError(
                (
                    "Unexpected Gemini embedding "
                    f"response: {data}"
                ),
                self.name,
                exc,
            ) from exc

        if not isinstance(
            embeddings,
            list,
        ):
            raise AIProviderError(
                "Gemini returned invalid embeddings.",
                self.name,
            )

        if len(embeddings) != len(
            clean_texts
        ):
            raise AIProviderError(
                (
                    "Gemini returned a different number "
                    "of embeddings than inputs. "
                    f"inputs={len(clean_texts)}, "
                    f"embeddings={len(embeddings)}"
                ),
                self.name,
            )

        vectors: list[list[float]] = []

        for index, item in enumerate(
            embeddings
        ):
            if (
                not isinstance(item, dict)
                or "values" not in item
            ):
                raise AIProviderError(
                    (
                        f"Invalid Gemini embedding "
                        f"#{index}: {item}"
                    ),
                    self.name,
                )

            values = item["values"]

            if not isinstance(
                values,
                list,
            ):
                raise AIProviderError(
                    (
                        f"Invalid embedding values "
                        f"#{index}: {values}"
                    ),
                    self.name,
                )

            if len(values) != (
                GEMINI_EMBEDDING_DIMENSION
            ):
                raise AIProviderError(
                    (
                        f"Gemini embedding #{index} "
                        f"returned {len(values)} "
                        "dimensions; expected "
                        f"{GEMINI_EMBEDDING_DIMENSION}."
                    ),
                    self.name,
                )

            vectors.append(values)

        return vectors

    # =========================================================================
    # SUMMARIZATION
    # =========================================================================

    async def summarize(
        self,
        text: str,
        max_words: int | None = None,
    ) -> str:
        """Summarize text."""

        constraint = (
            f" in no more than {max_words} words"
            if max_words
            else " concisely"
        )

        prompt = (
            f"Summarize the following text{constraint}. "
            "Output only the summary.\n\n"
            f"TEXT:\n{text}"
        )

        return await self.generate(
            prompt,
            temperature=0.3,
        )

    # =========================================================================
    # CLASSIFICATION
    # =========================================================================

    async def classify(
        self,
        text: str,
        labels: list[str],
    ) -> str:
        """Classify text into exactly one supplied label."""

        if not labels:
            raise AIProviderError(
                (
                    "classify() received an empty "
                    "label set."
                ),
                self.name,
            )

        label_list = "\n".join(
            f"- {label}"
            for label in labels
        )

        prompt = (
            "Classify the following text into exactly "
            "one of these categories.\n\n"
            "Respond with only the category name exactly "
            "as written.\n\n"
            f"Categories:\n{label_list}\n\n"
            f"Text:\n{text}"
        )

        raw = await self.generate(
            prompt,
            temperature=0.0,
        )

        cleaned = (
            raw.strip()
            .strip('"')
            .strip("'")
        )

        for label in labels:
            if cleaned.lower() == label.lower():
                return label

        for label in labels:
            if label.lower() in cleaned.lower():
                return label

        raise AIProviderError(
            (
                f"Gemini returned '{raw}', which does "
                "not match any supplied label: "
                f"{labels}"
            ),
            self.name,
        )

    # =========================================================================
    # IMAGE UNDERSTANDING
    # =========================================================================

    async def describe_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        instruction: str | None = None,
    ) -> str:
        """Analyze an image with Gemini."""

        if not image_bytes:
            raise AIProviderError(
                (
                    "describe_image() received "
                    "empty image data."
                ),
                self.name,
            )

        if not mime_type:
            raise AIProviderError(
                (
                    "describe_image() requires "
                    "a MIME type."
                ),
                self.name,
            )

        prompt_text = instruction or (
            "Describe this image in detail. "
            "Extract visible text, numbers, amounts, dates, "
            "reference numbers, transaction IDs, product names, "
            "labels, documents, screenshots, and other relevant "
            "information exactly as shown."
        )

        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": prompt_text,
                        },
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": (
                                    base64.b64encode(
                                        image_bytes
                                    ).decode("ascii")
                                ),
                            },
                        },
                    ],
                }
            ],
            "generationConfig": (
                self._build_generation_config(
                    model=self.model,
                    temperature=0.2,
                    thinking_level=DEFAULT_THINKING_LEVEL,
                )
            ),
        }

        data = (
            await self._generate_content_with_fallback(
                body
            )
        )

        return self._extract_text(data)

    # =========================================================================
    # AUDIO TRANSCRIPTION
    # =========================================================================

    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        mime_type: str,
    ) -> str:
        """Transcribe audio with Gemini."""

        if not audio_bytes:
            raise AIProviderError(
                (
                    "transcribe_audio() received "
                    "empty audio data."
                ),
                self.name,
            )

        if not mime_type:
            raise AIProviderError(
                (
                    "transcribe_audio() requires "
                    "a MIME type."
                ),
                self.name,
            )

        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                "Transcribe the speech in this "
                                "audio clip verbatim, in its "
                                "original language. "
                                "Output only the transcript."
                            )
                        },
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": (
                                    base64.b64encode(
                                        audio_bytes
                                    ).decode("ascii")
                                ),
                            },
                        },
                    ],
                }
            ],
            "generationConfig": (
                self._build_generation_config(
                    model=self.model,
                    temperature=0.0,
                    thinking_level=DEFAULT_THINKING_LEVEL,
                )
            ),
        }

        data = (
            await self._generate_content_with_fallback(
                body
            )
        )

        return self._extract_text(data)

    # =========================================================================
    # TOOL / FUNCTION CALLING
    # =========================================================================

    async def generate_with_tools(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        tool_executor: ToolExecutor,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tool_iterations: int = 5,
    ) -> str:
        """Generate a response using Gemini function calling.

        Important Gemini function-calling behavior:

        1. Preserve the COMPLETE model response parts.
           This protects Gemini 3 thought signatures.

        2. Execute each function call locally.

        3. Return the tool result using functionResponse.

        4. Do NOT put call_id inside functionResponse.

        5. The model's original functionCall part is preserved in the
           preceding role=model content.
        """

        if not tools:
            return await self.generate(
                prompt,
                system_instruction=system_instruction,
                temperature=temperature,
            )

        if max_tool_iterations < 1:
            raise AIProviderError(
                (
                    "max_tool_iterations must "
                    "be at least 1."
                ),
                self.name,
            )

        contents: list[dict[str, Any]] = [
            {
                "role": "user",
                "parts": [
                    {
                        "text": prompt,
                    }
                ],
            }
        ]

        function_declarations = [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in tools
        ]

        base_system_prompt = (
            system_instruction or ""
        ).strip()

        tool_guidance = (
            "After using tools and receiving their results, "
            "produce a natural final answer for the user. "
            "Do not expose internal tool execution details."
        )

        if base_system_prompt:
            system_text = (
                f"{base_system_prompt}\n\n"
                f"{tool_guidance}"
            )
        else:
            system_text = tool_guidance

        # =====================================================================
        # TOOL LOOP
        # =====================================================================

        for iteration in range(
            1,
            max_tool_iterations + 1,
        ):
            logger.info(
                "Gemini tool iteration %s/%s",
                iteration,
                max_tool_iterations,
            )

            generation_config = (
                self._build_generation_config(
                    model=self.model,
                    temperature=temperature,
                    thinking_level=DEFAULT_THINKING_LEVEL,
                )
            )

            body: dict[str, Any] = {
                "contents": contents,
                "generationConfig": generation_config,
                "tools": [
                    {
                        "functionDeclarations": (
                            function_declarations
                        ),
                    }
                ],
                "systemInstruction": {
                    "parts": [
                        {
                            "text": system_text,
                        }
                    ],
                },
            }

            data = (
                await self._generate_content_with_fallback(
                    body
                )
            )

            parts = self._extract_candidate_parts(
                data
            )

            function_calls = (
                self._extract_function_calls(
                    parts
                )
            )

            # =================================================================
            # NO TOOL CALL -> FINAL TEXT
            # =================================================================

            if not function_calls:
                text = "".join(
                    part.get("text", "")
                    for part in parts
                    if (
                        isinstance(part, dict)
                        and isinstance(
                            part.get("text"),
                            str,
                        )
                    )
                ).strip()

                if text:
                    logger.info(
                        (
                            "Gemini produced final "
                            "response after %s "
                            "tool iteration(s)."
                        ),
                        iteration,
                    )

                    return text

                raise AIProviderError(
                    (
                        "Gemini returned neither "
                        "text nor function calls."
                    ),
                    self.name,
                )

            # =================================================================
            # PRESERVE COMPLETE MODEL RESPONSE
            # =================================================================

            contents.append(
                {
                    "role": "model",
                    "parts": parts,
                }
            )

            # =================================================================
            # EXECUTE TOOLS
            # =================================================================

            function_response_parts: list[
                dict[str, Any]
            ] = []

            for function_call in function_calls:
                tool_name = function_call.get(
                    "name"
                )

                tool_args = function_call.get(
                    "args"
                ) or {}

                # Gemini may provide an identifier.
                #
                # We only use it for logging.
                #
                # IMPORTANT:
                # Do not send this value inside functionResponse.

                tool_call_id = (
                    function_call.get("id")
                    or function_call.get("call_id")
                )

                logger.info(
                    (
                        "Executing Gemini tool=%s "
                        "id=%s"
                    ),
                    tool_name or "<missing>",
                    tool_call_id or "<none>",
                )

                # -------------------------------------------------------------
                # Missing tool name
                # -------------------------------------------------------------

                if not tool_name:
                    result: Any = {
                        "error": (
                            "Gemini returned a function "
                            "call without a name."
                        )
                    }

                    logger.warning(
                        (
                            "Gemini returned function "
                            "call without a name: %s"
                        ),
                        function_call,
                    )

                # -------------------------------------------------------------
                # Validate tool arguments
                # -------------------------------------------------------------

                elif not isinstance(
                    tool_args,
                    dict,
                ):
                    result = {
                        "error": (
                            "Gemini returned invalid tool "
                            "arguments. Expected an object."
                        ),
                        "received": tool_args,
                    }

                    logger.warning(
                        (
                            "Invalid arguments for Gemini "
                            "tool=%s: %r"
                        ),
                        tool_name,
                        tool_args,
                    )

                # -------------------------------------------------------------
                # Execute tool
                # -------------------------------------------------------------

                else:
                    try:
                        result = await tool_executor(
                            tool_name,
                            tool_args,
                        )

                    except Exception as exc:
                        logger.exception(
                            "Tool execution failed: %s",
                            tool_name,
                        )

                        result = {
                            "error": str(exc),
                        }

                # -------------------------------------------------------------
                # Gemini functionResponse
                #
                # IMPORTANT:
                # There is intentionally NO call_id here.
                # -------------------------------------------------------------

                function_response = {
                    "name": (
                        tool_name
                        or "unknown"
                    ),
                    "response": result,
                }

                function_response_parts.append(
                    {
                        "functionResponse": (
                            function_response
                        ),
                    }
                )

            # =================================================================
            # SEND TOOL RESULTS BACK TO GEMINI
            # =================================================================

            contents.append(
                {
                    "role": "user",
                    "parts": function_response_parts,
                }
            )

        # =====================================================================
        # MAX TOOL ITERATIONS
        # =====================================================================

        logger.warning(
            (
                "Gemini reached maximum tool "
                "iterations=%s. Forcing final response."
            ),
            max_tool_iterations,
        )

        forced_contents = contents + [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "Provide the best possible final "
                            "answer using the tool results "
                            "already collected. "
                            "Do not call any more tools."
                        )
                    }
                ],
            }
        ]

        forced_body: dict[str, Any] = {
            "contents": forced_contents,
            "generationConfig": (
                self._build_generation_config(
                    model=self.model,
                    temperature=temperature,
                    thinking_level=DEFAULT_THINKING_LEVEL,
                )
            ),
        }

        if system_text:
            forced_body["systemInstruction"] = {
                "parts": [
                    {
                        "text": system_text,
                    }
                ],
            }

        data = (
            await self._generate_content_with_fallback(
                forced_body
            )
        )

        return self._extract_text(data)
