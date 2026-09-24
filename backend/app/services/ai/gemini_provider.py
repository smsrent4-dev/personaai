"""Google Gemini implementation of AIProvider.

PersonaAI Gemini provider using the Gemini REST API over httpx.

Production features:
- Retry handling for transient Gemini failures
- Exponential backoff with jitter
- Retry-After support
- Primary + fallback model routing
- Automatic fallback on repeated 429/5xx failures
- Correct authentication/error handling
- Gemini function/tool calling
- Preservation of Gemini model response parts
- Thought-signature-safe conversation history
- Multimodal image understanding
- Audio transcription
- 768-dimensional Gemini embeddings
- Gemini 3.x thinking-level support
- Low-latency settings for normal customer conversations
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

TRANSIENT_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}

# Two attempts per model:
#
# attempt 1
# attempt 2
#
# Then immediately move to fallback.
MAX_RETRIES_PER_MODEL = 2

INITIAL_RETRY_DELAY = 1.0

MAX_RETRY_DELAY = 4.0

# Do not allow Google's Retry-After header to make a customer wait forever.
MAX_RETRY_AFTER = 8.0


# ============================================================================
# GEMINI 3 THINKING
# ============================================================================

# Gemini 3.8 Flash supports:
#
#   low
#   medium
#   high
#
# "minimal" is NOT supported by Gemini 3.8 Flash.
#
# PersonaAI is a customer-facing chat application, so low is the default.
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

        self.embedding_model = (
            self._normalize_embedding_model(
                configured_embedding_model
            )
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
        """Validate Gemini 3 thinking level."""

        level = (
            thinking_level
            or DEFAULT_THINKING_LEVEL
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

    def _is_gemini_3_model(
        self,
        model: str | None = None,
    ) -> bool:
        """Return whether the model is a Gemini 3.x model."""

        target = self._clean_model_name(
            model or self.model
        )

        return target.startswith("gemini-3.")

    # =========================================================================
    # RETRY HELPERS
    # =========================================================================

    @staticmethod
    def _parse_retry_after(
        response: httpx.Response,
    ) -> float | None:
        """Read Retry-After header if Gemini provides one."""

        value = response.headers.get(
            "Retry-After"
        )

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

        except (
            TypeError,
            ValueError,
        ):
            return None

    @staticmethod
    def _calculate_backoff(
        attempt: int,
    ) -> float:
        """Exponential backoff with jitter."""

        base_delay = min(
            INITIAL_RETRY_DELAY * (
                2 ** (attempt - 1)
            ),
            MAX_RETRY_DELAY,
        )

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
        """Close HTTP client."""

        await self._client.aclose()

    async def _post(
        self,
        path: str,
        json_body: dict[str, Any],
    ) -> dict[str, Any]:
        """POST request to Gemini with transient retry handling."""

        if not self.api_key:
            raise AIAuthenticationError(
                "Gemini API key is not configured.",
                self.name,
            )

        last_error: _TransientAIError | None = None

        for attempt in range(
            1,
            MAX_RETRIES_PER_MODEL + 1,
        ):
            try:
                response = await self._client.post(
                    path,
                    params={
                        "key": self.api_key,
                    },
                    json=json_body,
                )

            except httpx.TimeoutException as exc:
                last_error = _TransientAIError(
                    f"Gemini request timed out: {exc}"
                )

                logger.warning(
                    (
                        "Gemini timeout "
                        "attempt=%s/%s path=%s"
                    ),
                    attempt,
                    MAX_RETRIES_PER_MODEL,
                    path,
                )

            except httpx.TransportError as exc:
                last_error = _TransientAIError(
                    f"Gemini transport error: {exc}"
                )

                logger.warning(
                    (
                        "Gemini transport error "
                        "attempt=%s/%s path=%s error=%s"
                    ),
                    attempt,
                    MAX_RETRIES_PER_MODEL,
                    path,
                    exc,
                )

            else:
                status = response.status_code

                # -------------------------------------------------------------
                # AUTHENTICATION
                # -------------------------------------------------------------

                if status in (401, 403):
                    raise AIAuthenticationError(
                        (
                            "Gemini API key is invalid, missing, "
                            "or not authorized for this request."
                        ),
                        self.name,
                    )

                # -------------------------------------------------------------
                # RATE LIMIT
                # -------------------------------------------------------------

                if status == 429:
                    retry_after = (
                        self._parse_retry_after(
                            response
                        )
                    )

                    last_error = _TransientAIError(
                        (
                            "Gemini rate limit exceeded: "
                            f"{response.text}"
                        ),
                        status_code=429,
                        retry_after=retry_after,
                    )

                    logger.warning(
                        (
                            "Gemini rate limit "
                            "attempt=%s/%s retry_after=%s"
                        ),
                        attempt,
                        MAX_RETRIES_PER_MODEL,
                        retry_after,
                    )

                # -------------------------------------------------------------
                # TRANSIENT SERVER FAILURE
                # -------------------------------------------------------------

                elif status in {
                    500,
                    502,
                    503,
                    504,
                }:
                    last_error = _TransientAIError(
                        (
                            f"Gemini returned {status}: "
                            f"{response.text}"
                        ),
                        status_code=status,
                    )

                    logger.warning(
                        (
                            "Gemini transient error "
                            "attempt=%s/%s status=%s path=%s"
                        ),
                        attempt,
                        MAX_RETRIES_PER_MODEL,
                        status,
                        path,
                    )

                # -------------------------------------------------------------
                # OTHER CLIENT ERROR
                # -------------------------------------------------------------

                elif status >= 400:
                    raise AIProviderError(
                        (
                            f"Gemini request failed ({status}): "
                            f"{response.text}"
                        ),
                        self.name,
                    )

                # -------------------------------------------------------------
                # SUCCESS
                # -------------------------------------------------------------

                else:
                    try:
                        return response.json()

                    except ValueError as exc:
                        raise AIProviderError(
                            "Gemini returned invalid JSON.",
                            self.name,
                            exc,
                        ) from exc

            # -----------------------------------------------------------------
            # RETRY
            # -----------------------------------------------------------------

            if last_error is None:
                break

            if attempt >= MAX_RETRIES_PER_MODEL:
                break

            if last_error.retry_after is not None:
                delay = last_error.retry_after
            else:
                delay = self._calculate_backoff(
                    attempt
                )

            logger.info(
                (
                    "Retrying Gemini request in %.2fs "
                    "(attempt %s/%s)"
                ),
                delay,
                attempt + 1,
                MAX_RETRIES_PER_MODEL,
            )

            await asyncio.sleep(delay)

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

        models: list[str] = [
            self.model,
        ]

        if self.fallback_model:
            models.append(
                self.fallback_model
            )

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
                return await self._post(
                    request_path,
                    body,
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
            - Do NOT send temperature.
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

            parts = candidates[0]["content"]["parts"]

            text = "".join(
                part.get("text", "")
                for part in parts
                if isinstance(part, dict)
            ).strip()

            if not text:
                raise AIProviderError(
                    (
                        "Gemini returned no text content: "
                        f"{data}"
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

            parts = candidates[0]["content"]["parts"]

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
        """Extract functionCall objects."""

        return [
            part["functionCall"]
            for part in parts
            if (
                isinstance(part, dict)
                and isinstance(
                    part.get("functionCall"),
                    dict,
                )
            )
        ]

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

        # Gemini 3.x ignores the old temperature concept and uses thinking
        # level instead.
        #
        # We intentionally use LOW here because PersonaAI is a real-time
        # customer conversation system.
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
            ]
        }

        if system_instruction:
            body["systemInstruction"] = {
                "parts": [
                    {
                        "text": system_instruction,
                    }
                ]
            }

        # The body must be generated separately for each model because
        # primary/fallback models may have different generation semantics.
        #
        # `_generate_content_with_fallback()` receives the same body, so use
        # a configuration that is valid for Gemini 3.x, which is the current
        # PersonaAI production configuration.
        body["generationConfig"] = (
            self._build_generation_config(
                model=self.model,
                temperature=temperature,
                max_tokens=max_tokens,
                thinking_level="low",
            )
        )

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
            (
                f" in no more than {max_words} words"
            )
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
            raw
            .strip()
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
                    thinking_level="low",
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
                    thinking_level="low",
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
        """Generate a response using Gemini function calling."""

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
        )

        tool_guidance = (
            "\n\n"
            "After using tools and receiving their results, "
            "produce a natural final answer for the user. "
            "Do not expose internal tool execution details."
        )

        system_text = (
            base_system_prompt
            + tool_guidance
        )

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
                    thinking_level="low",
                )
            )

            body: dict[str, Any] = {
                "contents": contents,
                "generationConfig": (
                    generation_config
                ),
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

            parts = (
                self._extract_candidate_parts(
                    data
                )
            )

            function_calls = (
                self._extract_function_calls(
                    parts
                )
            )

            # ---------------------------------------------------------------
            # FINAL RESPONSE
            # ---------------------------------------------------------------

            if not function_calls:
                text = "".join(
                    part.get("text", "")
                    for part in parts
                    if isinstance(part, dict)
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

            # ---------------------------------------------------------------
            # IMPORTANT:
            #
            # Preserve the ENTIRE model parts array.
            #
            # Gemini 3 models can return thought signatures associated with
            # tool calls. Removing or reconstructing these parts incorrectly
            # can break subsequent turns.
            # ---------------------------------------------------------------

            contents.append(
                {
                    "role": "model",
                    "parts": parts,
                }
            )

            function_response_parts: list[
                dict[str, Any]
            ] = []

            for function_call in function_calls:
                tool_name = function_call.get(
                    "name"
                )

                tool_args = (
                    function_call.get("args")
                    or {}
                )

                # Gemini generateContent function calling
                # may provide a call ID. Preserve it.
                tool_call_id = (
                    function_call.get("id")
                    or function_call.get("call_id")
                )

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
                            "call without name: %s"
                        ),
                        function_call,
                    )

                else:
                    logger.info(
                        (
                            "Executing Gemini tool=%s "
                            "id=%s"
                        ),
                        tool_name,
                        tool_call_id,
                    )

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

                function_response: dict[
                    str,
                    Any,
                ] = {
                    "name": (
                        tool_name
                        or "unknown"
                    ),
                    "response": result,
                }

                # Gemini's current function-calling format expects the call
                # identifier to be preserved when one is returned.
                if tool_call_id:
                    function_response["call_id"] = (
                        tool_call_id
                    )

                function_response_parts.append(
                    {
                        "functionResponse": (
                            function_response
                        ),
                    }
                )

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
                    thinking_level="low",
                )
            ),
        }

        data = (
            await self._generate_content_with_fallback(
                forced_body
            )
        )

        return self._extract_text(data)
