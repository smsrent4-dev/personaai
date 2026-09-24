"""Google Gemini implementation of AIProvider.

PersonaAI Gemini provider using the Gemini REST API over httpx.

Supports:
- Text generation
- Text embeddings
- Image understanding
- Audio transcription
- Text summarization
- Text classification
- Gemini function/tool calling

Production reliability features:
- Automatic retry for transient Gemini failures
- Exponential backoff with jitter
- Retry-After header support
- Retry handling for HTTP 429/502/503/504
- Configurable fallback Gemini model
- Graceful handling of temporary model unavailability
- Detailed production logging
- Gemini function-call preservation
- Thought-signature-safe tool-call message preservation

Embedding configuration:
- Model: gemini-embedding-001
- Output dimensionality: 768

PersonaAI stores embeddings as 768-dimensional vectors, so the embedding
dimension is explicitly requested to remain compatible with the existing
pgvector schema.
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


# ---------------------------------------------------------------------------
# Gemini REST configuration
# ---------------------------------------------------------------------------

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# PersonaAI's existing pgvector schema uses 768 dimensions.
GEMINI_EMBEDDING_DIMENSION = 768

# Current Gemini embedding model.
DEFAULT_GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"

# Gemini models that should never be used.
RETIRED_EMBEDDING_MODELS = {
    "text-embedding-004",
    "models/text-embedding-004",
}

# HTTP statuses that are normally transient.
TRANSIENT_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}

# Retry configuration.
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0
MAX_RETRY_DELAY = 10.0

# Maximum Retry-After value we will honor.
MAX_RETRY_AFTER = 30.0


class _TransientAIError(Exception):
    """Internal marker for Gemini errors that are safe to retry."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


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

        # Primary model.
        self.model = self._clean_model_name(
            model or settings.GEMINI_MODEL
        )

        # Optional fallback model.
        #
        # getattr() is intentional so the application does not crash if
        # GEMINI_FALLBACK_MODEL has not yet been added to the Settings class.
        configured_fallback = getattr(
            settings,
            "GEMINI_FALLBACK_MODEL",
            None,
        )

        self.fallback_model = self._clean_model_name(
            configured_fallback
        ) if configured_fallback else None

        # Never treat the primary model as its own fallback.
        if self.fallback_model == self.model:
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
                "GeminiProvider initialized without an API key. "
                "Gemini requests will fail until GEMINI_API_KEY is set."
            )

        logger.info(
            "GeminiProvider initialized: "
            "model=%s fallback_model=%s embedding_model=%s "
            "embedding_dimension=%s timeout=%ss",
            self.model,
            self.fallback_model or "<disabled>",
            self.embedding_model,
            GEMINI_EMBEDDING_DIMENSION,
            timeout,
        )

    # -----------------------------------------------------------------------
    # Model helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _clean_model_name(model: str) -> str:
        """Remove an optional leading 'models/' prefix."""
        return model.strip().removeprefix("models/")

    @classmethod
    def _normalize_embedding_model(cls, model: str) -> str:
        """Normalize embedding model and protect against retired models."""

        clean_model = cls._clean_model_name(model)

        if clean_model in RETIRED_EMBEDDING_MODELS:
            logger.warning(
                "Configured Gemini embedding model '%s' is retired. "
                "Automatically using '%s' instead.",
                model,
                DEFAULT_GEMINI_EMBEDDING_MODEL,
            )

            return DEFAULT_GEMINI_EMBEDDING_MODEL

        return clean_model

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> float | None:
        """Read Retry-After from a Gemini response when available."""

        value = response.headers.get("Retry-After")

        if not value:
            return None

        try:
            seconds = float(value)

            if seconds < 0:
                return None

            return min(seconds, MAX_RETRY_AFTER)

        except (TypeError, ValueError):
            return None

    @staticmethod
    def _calculate_backoff(attempt: int) -> float:
        """Calculate exponential backoff with jitter."""

        base_delay = min(
            INITIAL_RETRY_DELAY * (2 ** (attempt - 1)),
            MAX_RETRY_DELAY,
        )

        # Add 0-25% jitter.
        jitter = random.uniform(
            0,
            base_delay * 0.25,
        )

        return min(
            base_delay + jitter,
            MAX_RETRY_DELAY,
        )

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""

        await self._client.aclose()

    # -----------------------------------------------------------------------
    # HTTP transport
    # -----------------------------------------------------------------------

    async def _post(
        self,
        path: str,
        json_body: dict[str, Any],
    ) -> dict[str, Any]:
        """POST JSON to Gemini with production retry handling.

        Retries:
        - HTTP 429
        - HTTP 500
        - HTTP 502
        - HTTP 503
        - HTTP 504
        - Timeout
        - Network/transport errors

        Does not retry:
        - HTTP 400
        - HTTP 401
        - HTTP 403
        - HTTP 404
        - HTTP 422
        - Other permanent errors
        """

        if not self.api_key:
            raise AIAuthenticationError(
                "Gemini API key is not configured",
                self.name,
            )

        last_error: _TransientAIError | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self._client.post(
                    path,
                    params={"key": self.api_key},
                    json=json_body,
                )

            except httpx.TimeoutException as exc:
                last_error = _TransientAIError(
                    f"Gemini request timed out: {exc}",
                )

                logger.warning(
                    "Gemini timeout attempt=%s/%s path=%s",
                    attempt,
                    MAX_RETRIES,
                    path,
                )

            except httpx.TransportError as exc:
                last_error = _TransientAIError(
                    f"Gemini transport error: {exc}",
                )

                logger.warning(
                    "Gemini transport error attempt=%s/%s path=%s "
                    "error=%s",
                    attempt,
                    MAX_RETRIES,
                    path,
                    exc,
                )

            else:
                status = response.status_code

                # -----------------------------------------------------------
                # Authentication errors
                # -----------------------------------------------------------

                if status in (401, 403):
                    raise AIAuthenticationError(
                        "Invalid, missing, or unauthorized Gemini API key",
                        self.name,
                    )

                # -----------------------------------------------------------
                # Rate limiting
                # -----------------------------------------------------------

                if status == 429:
                    retry_after = self._parse_retry_after(response)

                    last_error = _TransientAIError(
                        f"Gemini rate limit exceeded: {response.text}",
                        status_code=status,
                        retry_after=retry_after,
                    )

                    logger.warning(
                        "Gemini rate limited attempt=%s/%s "
                        "retry_after=%s path=%s",
                        attempt,
                        MAX_RETRIES,
                        retry_after,
                        path,
                    )

                # -----------------------------------------------------------
                # Transient server failures
                # -----------------------------------------------------------

                elif status in {
                    500,
                    502,
                    503,
                    504,
                }:
                    last_error = _TransientAIError(
                        f"Gemini returned {status}: {response.text}",
                        status_code=status,
                    )

                    logger.warning(
                        "Gemini transient error attempt=%s/%s "
                        "status=%s path=%s",
                        attempt,
                        MAX_RETRIES,
                        status,
                        path,
                    )

                # -----------------------------------------------------------
                # Permanent client errors
                # -----------------------------------------------------------

                elif status >= 400:
                    raise AIProviderError(
                        f"Gemini request failed ({status}): "
                        f"{response.text}",
                        self.name,
                    )

                # -----------------------------------------------------------
                # Successful response
                # -----------------------------------------------------------

                else:
                    try:
                        return response.json()

                    except ValueError as exc:
                        raise AIProviderError(
                            f"Gemini returned invalid JSON: "
                            f"{response.text}",
                            self.name,
                            exc,
                        ) from exc

            # ----------------------------------------------------------------
            # Retry handling
            # ----------------------------------------------------------------

            if attempt >= MAX_RETRIES:
                break

            if last_error is None:
                break

            if last_error.retry_after is not None:
                delay = last_error.retry_after
            else:
                delay = self._calculate_backoff(attempt)

            logger.info(
                "Retrying Gemini request in %.2fs "
                "(attempt %s/%s)",
                delay,
                attempt + 1,
                MAX_RETRIES,
            )

            await asyncio.sleep(delay)

        if last_error is not None:
            raise last_error

        raise AIProviderError(
            "Gemini request failed for an unknown reason",
            self.name,
        )

    # -----------------------------------------------------------------------
    # Generation with model fallback
    # -----------------------------------------------------------------------

    async def _generate_content_with_fallback(
        self,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate Gemini content using primary model then fallback.

        The fallback is only attempted for transient availability problems.
        Authentication and permanent API errors are never hidden by the
        fallback mechanism.
        """

        models: list[str] = [self.model]

        if self.fallback_model:
            models.append(self.fallback_model)

        last_error: Exception | None = None

        for index, model in enumerate(models):
            is_fallback = index > 0

            try:
                logger.debug(
                    "Sending Gemini generation request "
                    "model=%s fallback=%s",
                    model,
                    is_fallback,
                )

                return await self._post(
                    f"/models/{model}:generateContent",
                    body,
                )

            except _TransientAIError as exc:
                last_error = exc

                if is_fallback:
                    logger.error(
                        "Gemini fallback model also unavailable: "
                        "model=%s status=%s error=%s",
                        model,
                        exc.status_code,
                        exc,
                    )

                    continue

                if not self.fallback_model:
                    logger.error(
                        "Gemini primary model unavailable after retries "
                        "and no fallback model is configured. "
                        "model=%s status=%s",
                        model,
                        exc.status_code,
                    )

                    continue

                logger.warning(
                    "Gemini primary model unavailable after retries. "
                    "Switching to fallback model=%s "
                    "primary=%s status=%s",
                    self.fallback_model,
                    self.model,
                    exc.status_code,
                )

            except (AIAuthenticationError, AIProviderError):
                raise

        if isinstance(last_error, _TransientAIError):
            if last_error.status_code == 429:
                raise AIRateLimitError(
                    "Gemini rate limit exceeded after retries",
                    self.name,
                ) from last_error

            raise AIProviderError(
                "Gemini unavailable after retries"
                + (
                    " and fallback model also failed"
                    if self.fallback_model
                    else ""
                ),
                self.name,
                last_error,
            ) from last_error

        raise AIProviderError(
            "Gemini generation failed",
            self.name,
        )

    # -----------------------------------------------------------------------
    # Response extraction
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        """Extract combined text from Gemini's first candidate."""

        try:
            candidates = data["candidates"]

            if not candidates:
                raise AIProviderError(
                    "Gemini returned no candidates "
                    "(likely blocked by safety filters)",
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
                    f"Gemini returned no text content: {data}",
                    "gemini",
                )

            return text

        except AIProviderError:
            raise

        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(
                f"Unexpected Gemini response shape: {data}",
                "gemini",
                exc,
            ) from exc

    @staticmethod
    def _extract_candidate_parts(
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return all parts from Gemini's first candidate."""

        try:
            candidates = data["candidates"]

            if not candidates:
                raise AIProviderError(
                    "Gemini returned no candidates "
                    "(likely blocked by safety filters)",
                    "gemini",
                )

            content = candidates[0]["content"]
            parts = content["parts"]

            if not isinstance(parts, list):
                raise AIProviderError(
                    f"Gemini returned invalid parts: {parts}",
                    "gemini",
                )

            return parts

        except AIProviderError:
            raise

        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(
                f"Unexpected Gemini tool response shape: {data}",
                "gemini",
                exc,
            ) from exc

    @staticmethod
    def _extract_function_calls(
        parts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return every functionCall part in a Gemini response."""

        return [
            part["functionCall"]
            for part in parts
            if (
                isinstance(part, dict)
                and "functionCall" in part
                and isinstance(part["functionCall"], dict)
            )
        ]

    # -----------------------------------------------------------------------
    # Text generation
    # -----------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Generate a text response with Gemini."""

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
            "generationConfig": {
                "temperature": temperature,
            },
        }

        if max_tokens is not None:
            body["generationConfig"]["maxOutputTokens"] = max_tokens

        if system_instruction:
            body["systemInstruction"] = {
                "parts": [
                    {
                        "text": system_instruction,
                    }
                ]
            }

        data = await self._generate_content_with_fallback(body)

        return self._extract_text(data)

    # -----------------------------------------------------------------------
    # Embeddings
    # -----------------------------------------------------------------------

    async def embed(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Generate 768-dimensional embeddings for multiple texts.

        Uses Gemini's batchEmbedContents endpoint with
        gemini-embedding-001.

        PersonaAI uses Vector(768), so outputDimensionality is explicitly
        set to 768 on every embedding request.
        """

        if not texts:
            return []

        clean_texts = [
            text.strip()
            for text in texts
            if isinstance(text, str) and text.strip()
        ]

        if not clean_texts:
            return []

        clean_model = self._normalize_embedding_model(
            self.embedding_model
        )

        self.embedding_model = clean_model

        body = {
            "requests": [
                {
                    "model": f"models/{clean_model}",
                    "content": {
                        "parts": [
                            {
                                "text": text,
                            }
                        ]
                    },
                    "outputDimensionality": GEMINI_EMBEDDING_DIMENSION,
                }
                for text in clean_texts
            ]
        }

        logger.debug(
            "Generating %s Gemini embeddings using "
            "model=%s dimension=%s",
            len(clean_texts),
            clean_model,
            GEMINI_EMBEDDING_DIMENSION,
        )

        try:
            data = await self._post(
                f"/models/{clean_model}:batchEmbedContents",
                body,
            )

        except _TransientAIError as exc:
            if exc.status_code == 429:
                raise AIRateLimitError(
                    "Gemini embedding rate limit exceeded",
                    self.name,
                ) from exc

            raise AIProviderError(
                "Gemini embedding service unavailable after retries",
                self.name,
                exc,
            ) from exc

        try:
            embeddings = data["embeddings"]

        except (KeyError, TypeError) as exc:
            raise AIProviderError(
                f"Unexpected Gemini embedding response shape: {data}",
                self.name,
                exc,
            ) from exc

        if not isinstance(embeddings, list):
            raise AIProviderError(
                f"Gemini returned invalid embeddings: {data}",
                self.name,
            )

        if len(embeddings) != len(clean_texts):
            raise AIProviderError(
                "Gemini returned a different number of embeddings "
                f"than inputs. inputs={len(clean_texts)}, "
                f"embeddings={len(embeddings)}",
                self.name,
            )

        vectors: list[list[float]] = []

        for index, item in enumerate(embeddings):
            if not isinstance(item, dict) or "values" not in item:
                raise AIProviderError(
                    f"Gemini embedding #{index} has an invalid response: "
                    f"{item}",
                    self.name,
                )

            values = item["values"]

            if not isinstance(values, list):
                raise AIProviderError(
                    f"Gemini embedding #{index} returned invalid values: "
                    f"{values}",
                    self.name,
                )

            if len(values) != GEMINI_EMBEDDING_DIMENSION:
                raise AIProviderError(
                    f"Gemini embedding #{index} returned "
                    f"{len(values)} dimensions; expected "
                    f"{GEMINI_EMBEDDING_DIMENSION}",
                    self.name,
                )

            vectors.append(values)

        return vectors

    # -----------------------------------------------------------------------
    # Summarization
    # -----------------------------------------------------------------------

    async def summarize(
        self,
        text: str,
        max_words: int | None = None,
    ) -> str:
        """Summarize text using Gemini."""

        constraint = (
            f" in no more than {max_words} words"
            if max_words
            else " concisely"
        )

        prompt = (
            f"Summarize the following text{constraint}. "
            "Output only the summary, no preamble.\n\n"
            f"TEXT:\n{text}"
        )

        return await self.generate(
            prompt,
            temperature=0.3,
        )

    # -----------------------------------------------------------------------
    # Classification
    # -----------------------------------------------------------------------

    async def classify(
        self,
        text: str,
        labels: list[str],
    ) -> str:
        """Classify text into exactly one supplied label."""

        if not labels:
            raise AIProviderError(
                "classify() called with an empty label set",
                self.name,
            )

        label_list = "\n".join(
            f"- {label}"
            for label in labels
        )

        prompt = (
            "Classify the following text into exactly one of these "
            "categories. Respond with only the category name, exactly "
            "as written below, and nothing else.\n\n"
            f"Categories:\n{label_list}\n\n"
            f"Text:\n{text}"
        )

        raw = await self.generate(
            prompt,
            temperature=0.0,
        )

        cleaned = raw.strip().strip('"').strip("'")

        # Exact case-insensitive match first.
        for label in labels:
            if cleaned.lower() == label.lower():
                return label

        # Then allow a response containing the label.
        for label in labels:
            if label.lower() in cleaned.lower():
                return label

        raise AIProviderError(
            f"Gemini returned '{raw}', which doesn't match "
            f"any of {labels}",
            self.name,
        )

    # -----------------------------------------------------------------------
    # Image understanding
    # -----------------------------------------------------------------------

    async def describe_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        instruction: str | None = None,
    ) -> str:
        """Analyze an image using Gemini multimodal generation."""

        if not image_bytes:
            raise AIProviderError(
                "describe_image() received empty image data",
                self.name,
            )

        if not mime_type:
            raise AIProviderError(
                "describe_image() requires a MIME type",
                self.name,
            )

        prompt_text = instruction or (
            "Describe this image in detail. Note any visible text, numbers, "
            "amounts, dates, or reference/transaction IDs exactly as they "
            "appear. Describe any products, packaging, labels, clothing, "
            "documents, or app/screenshot UI shown."
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
                                "data": base64.b64encode(
                                    image_bytes
                                ).decode("ascii"),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
            },
        }

        data = await self._generate_content_with_fallback(body)

        return self._extract_text(data)

    # -----------------------------------------------------------------------
    # Audio transcription
    # -----------------------------------------------------------------------

    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        mime_type: str,
    ) -> str:
        """Transcribe an audio clip using Gemini multimodal generation."""

        if not audio_bytes:
            raise AIProviderError(
                "transcribe_audio() received empty audio data",
                self.name,
            )

        if not mime_type:
            raise AIProviderError(
                "transcribe_audio() requires a MIME type",
                self.name,
            )

        prompt_text = (
            "Transcribe the speech in this audio clip verbatim, in its "
            "original language. Output only the transcript — no preamble, "
            "no translation, no description of tone."
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
                                "data": base64.b64encode(
                                    audio_bytes
                                ).decode("ascii"),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
            },
        }

        data = await self._generate_content_with_fallback(body)

        return self._extract_text(data)

    # -----------------------------------------------------------------------
    # Function / tool calling
    # -----------------------------------------------------------------------

    async def generate_with_tools(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        tool_executor: ToolExecutor,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tool_iterations: int = 5,
    ) -> str:
        """Generate a response using Gemini REST function calling.

        Flow:

            user prompt
                ↓
            Gemini
                ↓
            functionCall(s)
                ↓
            execute tools
                ↓
            functionResponse(s)
                ↓
            Gemini
                ↓
            final text

        The complete Gemini model response parts are preserved when sending
        the model turn back to Gemini. This is important for newer Gemini
        models that may include thought-signature metadata.
        """

        if not tools:
            return await self.generate(
                prompt,
                system_instruction=system_instruction,
                temperature=temperature,
            )

        if max_tool_iterations < 1:
            raise AIProviderError(
                "max_tool_iterations must be at least 1",
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

        base_system_prompt = system_instruction or ""

        tool_guidance = (
            "\n\nAfter calling tools and receiving their results, "
            "synthesize the findings into a clear final text answer "
            "for the user. Do not expose internal tool execution details "
            "unless they are relevant to the user's request."
        )

        body_base: dict[str, Any] = {
            "generationConfig": {
                "temperature": temperature,
            },
            "tools": [
                {
                    "functionDeclarations": function_declarations,
                }
            ],
            "systemInstruction": {
                "parts": [
                    {
                        "text": base_system_prompt + tool_guidance,
                    }
                ]
            },
        }

        for iteration in range(
            1,
            max_tool_iterations + 1,
        ):
            logger.info(
                "Gemini tool-calling iteration %s/%s "
                "primary=%s fallback=%s",
                iteration,
                max_tool_iterations,
                self.model,
                self.fallback_model or "<disabled>",
            )

            body = {
                **body_base,
                "contents": contents,
            }

            # ---------------------------------------------------------------
            # Gemini generation with automatic fallback.
            # ---------------------------------------------------------------

            data = await self._generate_content_with_fallback(body)

            parts = self._extract_candidate_parts(data)

            function_calls = self._extract_function_calls(parts)

            # ---------------------------------------------------------------
            # Gemini returned normal text.
            # ---------------------------------------------------------------

            if not function_calls:
                text = "".join(
                    part.get("text", "")
                    for part in parts
                    if isinstance(part, dict)
                ).strip()

                if text:
                    logger.info(
                        "Gemini returned final text after %s "
                        "tool iteration(s)",
                        iteration,
                    )

                    return text

                raise AIProviderError(
                    "Gemini returned neither text nor function calls: "
                    f"{data}",
                    self.name,
                )

            logger.info(
                "Gemini requested %s function call(s): %s",
                len(function_calls),
                ", ".join(
                    str(call.get("name", "<unknown>"))
                    for call in function_calls
                ),
            )

            # ---------------------------------------------------------------
            # IMPORTANT:
            #
            # Preserve the complete Gemini model response.
            #
            # This is required for newer Gemini models that may return
            # thoughtSignature metadata alongside function calls.
            # ---------------------------------------------------------------

            contents.append(
                {
                    "role": "model",
                    "parts": parts,
                }
            )

            function_response_parts: list[dict[str, Any]] = []

            for function_call in function_calls:
                tool_name = function_call.get("name")

                tool_args = function_call.get("args") or {}

                tool_call_id = function_call.get("id")

                if not tool_name:
                    result: Any = {
                        "error": (
                            "Gemini returned a function call "
                            "without a name."
                        )
                    }

                    logger.warning(
                        "Gemini returned a function call without "
                        "a name: %s",
                        function_call,
                    )

                else:
                    logger.info(
                        "Executing Gemini tool name=%s id=%s args=%s",
                        tool_name,
                        tool_call_id,
                        tool_args,
                    )

                    try:
                        result = await tool_executor(
                            tool_name,
                            tool_args,
                        )

                    except Exception as exc:  # noqa: BLE001
                        logger.exception(
                            "Tool execution failed for Gemini tool=%s",
                            tool_name,
                        )

                        result = {
                            "error": str(exc),
                        }

                function_response: dict[str, Any] = {
                    "name": tool_name or "unknown",
                    "response": result,
                }

                # Preserve Gemini's call ID when supplied.
                if tool_call_id:
                    function_response["id"] = tool_call_id

                function_response_parts.append(
                    {
                        "functionResponse": function_response,
                    }
                )

            # ---------------------------------------------------------------
            # Send all tool results back together.
            # ---------------------------------------------------------------

            contents.append(
                {
                    "role": "user",
                    "parts": function_response_parts,
                }
            )

        # -------------------------------------------------------------------
        # Maximum tool iterations reached.
        # -------------------------------------------------------------------

        logger.warning(
            "Max Gemini tool iterations (%s) reached. "
            "Forcing final text generation.",
            max_tool_iterations,
        )

        forced_contents = contents + [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "Please provide the best possible final answer "
                            "based on the tool calls and results executed "
                            "so far. Do not call any more tools."
                        )
                    }
                ],
            }
        ]

        forced_body = {
            "generationConfig": {
                "temperature": temperature,
            },
            "contents": forced_contents,
        }

        try:
            fallback_data = await self._generate_content_with_fallback(
                forced_body
            )

            return self._extract_text(fallback_data)

        except AIProviderError:
            raise

        except Exception as exc:
            raise AIProviderError(
                "Gemini tool-calling loop exceeded "
                f"{max_tool_iterations} iterations without a "
                "final answer",
                self.name,
                exc,
            ) from exc
