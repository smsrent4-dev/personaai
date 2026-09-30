"""Google Gemini implementation of AIProvider.
PersonaAI Gemini provider using the Gemini REST API over httpx.
Production features:
- Controlled retry handling for transient Gemini failures
- Exponential backoff with jitter
- Retry-After support
- Primary + fallback model routing
- No aggressive fallback on 429 rate limits
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
- Request-operation logging for production diagnostics
Important design goal:
PersonaAI is a real-time messaging application. A single customer
message must not accidentally create a large number of Gemini HTTP
requests.
Therefore this provider intentionally keeps retry counts and tool
iterations bounded.
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
# Retryable Gemini failures.
#
# 408 = Request Timeout
# 429 = Rate Limit / Resource Exhausted
# 500 = Internal Server Error
# 502 = Bad Gateway
# 503 = Service Unavailable
# 504 = Gateway Timeout
TRANSIENT_STATUS_CODES = {
    408,
    429,
    500,
    502,
    503,
    504,
}
# IMPORTANT:
#
# This means TOTAL attempts per model:
#
#   attempt 1 = initial request
#   attempt 2 = retry
#   attempt 3 = retry
#
# Maximum = 3 HTTP requests per model.
#
# This is intentionally lower than the previous 5 attempts because
# PersonaAI is a real-time application and excessive retries can
# amplify rate-limit pressure.
MAX_RETRIES_PER_MODEL = 2
INITIAL_RETRY_DELAY = 1.0
MAX_RETRY_DELAY = 8.0
MAX_RETRY_AFTER = 30.0
# ============================================================================
# RATE-LIMIT RETRIES
# ============================================================================
# A 429 can represent project/model quota or request-rate exhaustion.
#
# Therefore we do not repeatedly hammer Gemini after a 429.
#
# Maximum:
#
#   initial request
#   one retry
#
# = 2 HTTP requests for a rate-limited operation.
MAX_429_RETRIES = 1
# ============================================================================
# GEMINI 3 THINKING
# ============================================================================
# Gemini 3 supports thinking levels.
#
# PersonaAI is primarily a real-time customer conversation system,
# so LOW is used to keep latency and reasoning overhead under control.
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
                (
                    "GEMINI_FALLBACK_MODEL is the same as "
                    "GEMINI_MODEL. Disabling fallback."
                )
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
        # One shared HTTP client per provider instance.
        #
        # factory.py caches the provider, so this connection pool is
        # reused across requests instead of creating a new HTTP client
        # for every customer message.
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
                "dimensions=%s thinking=%s "
                "max_retries=%s max_429_retries=%s "
                "max_tool_iterations=%s"
            ),
            self.model,
            self.fallback_model or "<disabled>",
            self.embedding_model,
            GEMINI_EMBEDDING_DIMENSION,
            DEFAULT_THINKING_LEVEL,
            MAX_RETRIES_PER_MODEL,
            MAX_429_RETRIES,
            2,
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
        """Calculate exponential backoff with jitter."""
        base_delay = min(
            INITIAL_RETRY_DELAY
            * (2 ** max(retry_number - 1, 0)),
            MAX_RETRY_DELAY,
        )
        # 25% jitter prevents multiple workers from retrying
        # at exactly the same time.
        jitter = random.uniform(
            0,
            base_delay * 0.25,
        )
        return min(
            base_delay + jitter,
            MAX_RETRY_DELAY,
        )
    # =========================================================================
    # HTTP CLIENT
    # =========================================================================
    async def aclose(self) -> None:
        """Close the shared HTTP client."""
        await self._client.aclose()
    async def _post(
        self,
        path: str,
        json_body: dict[str, Any],
        *,
        operation: str = "unknown",
    ) -> dict[str, Any]:
        """POST request to Gemini with controlled retry handling.
        Important:
        This method deliberately avoids unlimited or aggressive retries.
        429:
            Maximum one retry.
        408 / 500 / 502 / 503 / 504:
            Maximum MAX_RETRIES_PER_MODEL retries.
        401 / 403:
            Authentication failure. No retry.
        400 / 402 / 404 / other client errors:
            No retry.
        The API key is sent using x-goog-api-key rather than a query
        parameter so it does not appear in request URLs.
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
        # Track 429 retries separately.
        rate_limit_retry_count = 0
        total_attempts = MAX_RETRIES_PER_MODEL + 1
        for attempt in range(
            1,
            total_attempts + 1,
        ):
            last_error = None
            logger.info(
                (
                    "Gemini HTTP request "
                    "operation=%s attempt=%s/%s path=%s"
                ),
                operation,
                attempt,
                total_attempts,
                path,
            )
            try:
                response = await self._client.post(
                    path,
                    headers=headers,
                    json=json_body,
                )
            except httpx.TimeoutException as exc:
                last_error = _TransientAIError(
                    f"Gemini request timed out: {exc}"
                )
                logger.warning(
                    (
                        "Gemini timeout "
                        "operation=%s attempt=%s/%s"
                    ),
                    operation,
                    attempt,
                    total_attempts,
                )
            except httpx.TransportError as exc:
                last_error = _TransientAIError(
                    f"Gemini transport error: {exc}"
                )
                logger.warning(
                    (
                        "Gemini transport error "
                        "operation=%s attempt=%s/%s error=%s"
                    ),
                    operation,
                    attempt,
                    total_attempts,
                    exc,
                )
            else:
                status = response.status_code
                # =============================================================
                # SUCCESS
                # =============================================================
                if 200 <= status < 300:
                    try:
                        logger.info(
                            (
                                "Gemini HTTP success "
                                "operation=%s status=%s "
                                "attempt=%s"
                            ),
                            operation,
                            status,
                            attempt,
                        )
                        return response.json()
                    except ValueError as exc:
                        raise AIProviderError(
                            "Gemini returned invalid JSON.",
                            self.name,
                            exc,
                        ) from exc
                # =============================================================
                # AUTHENTICATION / AUTHORIZATION
                # =============================================================
                if status in (401, 403):
                    logger.error(
                        (
                            "Gemini authentication failure "
                            "operation=%s status=%s"
                        ),
                        operation,
                        status,
                    )
                    raise AIAuthenticationError(
                        (
                            "Gemini API key is invalid, missing, "
                            "expired, or not authorized for this request."
                        ),
                        self.name,
                    )
                # =============================================================
                # RATE LIMIT
                #
                # Do NOT aggressively retry or fall back.
                # =============================================================
                if status == 429:
                    retry_after = self._parse_retry_after(
                        response
                    )
                    last_error = _TransientAIError(
                        (
                            "Gemini returned 429 Resource Exhausted: "
                            f"{response.text}"
                        ),
                        status_code=429,
                        retry_after=retry_after,
                    )
                    logger.warning(
                        (
                            "Gemini rate limit "
                            "operation=%s attempt=%s "
                            "retry_after=%s"
                        ),
                        operation,
                        attempt,
                        retry_after,
                    )
                    if (
                        rate_limit_retry_count
                        >= MAX_429_RETRIES
                    ):
                        break
                    rate_limit_retry_count += 1
                # =============================================================
                # OTHER TRANSIENT ERRORS
                # =============================================================
                elif status in {
                    408,
                    500,
                    502,
                    503,
                    504,
                }:
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
                            "Gemini transient server error "
                            "operation=%s status=%s "
                            "attempt=%s/%s "
                            "retry_after=%s"
                        ),
                        operation,
                        status,
                        attempt,
                        total_attempts,
                        retry_after,
                    )
                # =============================================================
                # NON-RETRYABLE ERROR
                # =============================================================
                elif status >= 400:
                    logger.error(
                        (
                            "Gemini non-retryable error "
                            "operation=%s status=%s"
                        ),
                        operation,
                        status,
                    )
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
            # 429 has its own strict retry limit.
            if last_error.status_code == 429:
                if (
                    rate_limit_retry_count
                    > MAX_429_RETRIES
                ):
                    break
            # All normal transient attempts exhausted.
            elif attempt >= total_attempts:
                break
            # Explicit Retry-After takes priority.
            if last_error.retry_after is not None:
                delay = last_error.retry_after
            else:
                delay = self._calculate_backoff(
                    attempt
                )
            logger.info(
                (
                    "Retrying Gemini request "
                    "operation=%s in %.2fs "
                    "status=%s"
                ),
                operation,
                delay,
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
        *,
        operation: str = "generation",
    ) -> dict[str, Any]:
        """Generate content using primary and optional fallback model.
        Fallback policy:
        429:
            Do NOT switch models. A project/model rate limit should not
            be amplified by immediately sending the same request to
            another model.
        408 / 500 / 502 / 503 / 504:
            Retry the primary model, then use fallback if configured.
        Authentication/client errors:
            Fail immediately.
        """
        models: list[str] = [
            self.model
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
                    "Gemini generation "
                    "operation=%s model=%s fallback=%s"
                ),
                operation,
                model,
                is_fallback,
            )
            try:
                # Shallow copy prevents mutation of the caller's body.
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
                    # Gemini 3 uses thinkingLevel rather than the
                    # legacy temperature configuration.
                    if self._is_gemini_3_model(
                        model
                    ):
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
                    operation=operation,
                )
            except _TransientAIError as exc:
                last_error = exc
                logger.warning(
                    (
                        "Gemini model temporarily "
                        "unavailable "
                        "operation=%s "
                        "model=%s "
                        "fallback=%s "
                        "status=%s"
                    ),
                    operation,
                    model,
                    is_fallback,
                    exc.status_code,
                )
                # -------------------------------------------------------------
                # RATE LIMIT
                #
                # Never immediately fallback on 429.
                # -------------------------------------------------------------
                if exc.status_code == 429:
                    raise AIRateLimitError(
                        (
                            "Gemini rate limit exceeded. "
                            "The request was limited after a "
                            "controlled retry."
                        ),
                        self.name,
                    ) from exc
                # -------------------------------------------------------------
                # PRIMARY TEMPORARY FAILURE -> FALLBACK
                # -------------------------------------------------------------
                if (
                    not is_fallback
                    and self.fallback_model
                ):
                    logger.warning(
                        (
                            "Primary Gemini model failed "
                            "operation=%s status=%s. "
                            "Switching to fallback model=%s."
                        ),
                        operation,
                        exc.status_code,
                        self.fallback_model,
                    )
                    continue
                # -------------------------------------------------------------
                # FALLBACK ALSO FAILED
                # -------------------------------------------------------------
                logger.error(
                    (
                        "Gemini generation failed "
                        "operation=%s model=%s "
                        "status=%s. No usable fallback remains."
                    ),
                    operation,
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
            raise AIProviderError(
                (
                    "Gemini is temporarily unavailable "
                    "after controlled retries"
                    + (
                        " and fallback."
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
        """Build Gemini generation configuration."""
        config: dict[str, Any] = {}
        if max_tokens is not None:
            config["maxOutputTokens"] = max_tokens
        # Gemini 3.x.
        #
        # Temperature is deliberately not sent to Gemini 3.x.
        # Thinking is controlled through thinkingConfig.
        if self._is_gemini_3_model(model):
            level = self._normalize_thinking_level(
                thinking_level
            )
            config["thinkingConfig"] = {
                "thinkingLevel": level,
            }
        # Older Gemini models.
        else:
            if temperature is not None:
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
        """Extract all response parts from first candidate.
        IMPORTANT:
        The parts are returned exactly as Gemini supplied them.
        This is important for Gemini 3 thought signatures and function
        calling because those parts can contain metadata that must be
        preserved in the next request.
        """
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
            body,
            operation="generate",
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
        logger.info(
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
                operation="embedding",
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
                body,
                operation="image_analysis",
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
                body,
                operation="audio_transcription",
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
        max_tool_iterations: int = 2,
    ) -> str:
        """Generate a response using Gemini function calling.
        Production limits:
        max_tool_iterations defaults to 2.
        Normal flow:
            Gemini request
                ↓
            tool call
                ↓
            execute tool
                ↓
            Gemini final response
        This prevents a single customer message from creating an
        excessive number of Gemini requests.
        Gemini model response parts are preserved exactly because
        Gemini 3 thought signatures must be returned when function
        calling is used.
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
        # Hard safety ceiling.
        #
        # Even if a caller accidentally passes something like 100,
        # PersonaAI will never allow an uncontrolled tool loop.
        max_tool_iterations = min(
            max_tool_iterations,
            2,
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
            "Use tools only when they are necessary to answer "
            "the user's request. After receiving tool results, "
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
                (
                    "Gemini tool iteration "
                    "iteration=%s/%s"
                ),
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
                    body,
                    operation="tool_generation",
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
            #
            # Do not rebuild or simplify these parts.
            #
            # Gemini 3 can attach thought signatures to model parts.
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
                # Gemini may provide an ID.
                #
                # Current Gemini function-calling guidance uses this
                # identifier to associate the function response with
                # the function call.
                #
                # We preserve it when Gemini provides it.
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
                #
                # Use the Gemini-provided ID when available.
                #
                # Do not invent an ID when Gemini did not provide one.
                # -------------------------------------------------------------
                function_response: dict[str, Any] = {
                    "name": (
                        tool_name
                        or "unknown"
                    ),
                    "response": result,
                }
                if tool_call_id:
                    function_response["id"] = (
                        tool_call_id
                    )
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
        # At this point we already used the maximum permitted tool rounds.
        #
        # One final generation is still required because the tool result
        # may contain information that needs to be converted into a
        # customer-facing response.
        #
        # However, we do NOT give Gemini any tools in this final request.
        #
        # This guarantees:
        #
        #   maximum tool iterations = 2
        #   final response request = 1
        #
        # Therefore the normal maximum logical generation count is 3.
        logger.warning(
            (
                "Gemini reached maximum tool "
                "iterations=%s. Performing one "
                "tool-free final response."
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
                forced_body,
                operation="tool_final_generation",
            )
        )
        return self._extract_text(data)
