"""Google Gemini implementation of AIProvider.

Talks to the Gemini REST API directly over httpx rather than using the
google-generativeai SDK.

This provider supports:

- Text generation
- Text embeddings
- Image understanding
- Audio transcription
- Text summarization
- Text classification
- Gemini function/tool calling

Embedding configuration:

- Model: gemini-embedding-001
- Output dimensionality: 768

PersonaAI stores embeddings as 768-dimensional vectors, so the embedding
dimension is explicitly requested to remain compatible with the existing
pgvector schema.

The HTTP transport implements bounded retries with exponential backoff and
jitter for transient Gemini failures such as 429, 500, 502, 503, and 504.
API credentials are sent through the x-goog-api-key header rather than being
placed in request URLs.
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

# Gemini embedding model.
DEFAULT_GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"

# Retired Gemini embedding models.
RETIRED_EMBEDDING_MODELS = {
    "text-embedding-004",
    "models/text-embedding-004",
}

# Gemini inline media should remain comfortably below the documented
# request-size limit. Larger media should use the Gemini Files API.
MAX_INLINE_IMAGE_BYTES = 15 * 1024 * 1024

# Default HTTP timeout configuration.
DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_READ_TIMEOUT = 45.0
DEFAULT_WRITE_TIMEOUT = 30.0
DEFAULT_POOL_TIMEOUT = 10.0

# Interactive requests should not consume workers indefinitely.
DEFAULT_MAX_ATTEMPTS = 3

# Exponential backoff configuration.
RETRY_MIN_SECONDS = 1.0
RETRY_MAX_SECONDS = 8.0

# Gemini/API failures that are considered transient.
TRANSIENT_STATUS_CODES = {
    408,
    500,
    502,
    503,
    504,
}


class _TransientAIError(Exception):
    """Internal-only marker for errors that are safe to retry."""


class GeminiProvider(AIProvider):
    """Gemini REST implementation of the AIProvider interface."""

    name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        embedding_model: str | None = None,
        timeout: float | None = None,
    ):
        self.api_key = api_key or settings.GEMINI_API_KEY

        self.model = self._clean_model_name(
            model or settings.GEMINI_MODEL
        )

        configured_embedding_model = (
            embedding_model
            or settings.GEMINI_EMBEDDING_MODEL
            or DEFAULT_GEMINI_EMBEDDING_MODEL
        )

        self.embedding_model = self._normalize_embedding_model(
            configured_embedding_model
        )

        self._client = httpx.AsyncClient(
            base_url=GEMINI_API_BASE,
            timeout=self._build_timeout(timeout),
            headers=self._build_headers(),
        )

        if not self.api_key:
            logger.warning(
                "GeminiProvider initialized without an API key. "
                "Requests will fail until GEMINI_API_KEY is configured."
            )

        logger.info(
            "GeminiProvider initialized: model=%s "
            "embedding_model=%s embedding_dimension=%s",
            self.model,
            self.embedding_model,
            GEMINI_EMBEDDING_DIMENSION,
        )

    # -----------------------------------------------------------------------
    # HTTP configuration
    # -----------------------------------------------------------------------

    @staticmethod
    def _build_timeout(
        timeout: float | None,
    ) -> httpx.Timeout:
        """Build an HTTPX timeout configuration."""

        if timeout is not None:
            if timeout <= 0:
                raise ValueError(
                    "GeminiProvider timeout must be greater than zero."
                )

            return httpx.Timeout(
                timeout,
                connect=timeout,
                read=timeout,
                write=timeout,
                pool=timeout,
            )

        return httpx.Timeout(
            connect=DEFAULT_CONNECT_TIMEOUT,
            read=DEFAULT_READ_TIMEOUT,
            write=DEFAULT_WRITE_TIMEOUT,
            pool=DEFAULT_POOL_TIMEOUT,
        )

    def _build_headers(self) -> dict[str, str]:
        """Build Gemini HTTP headers without exposing credentials in URLs."""

        headers = {
            "Content-Type": "application/json",
        }

        if self.api_key:
            headers["x-goog-api-key"] = self.api_key

        return headers

    # -----------------------------------------------------------------------
    # Model helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _clean_model_name(model: str) -> str:
        """Remove an optional leading 'models/' prefix."""

        return model.strip().removeprefix("models/")

    @classmethod
    def _normalize_embedding_model(
        cls,
        model: str,
    ) -> str:
        """Normalize embedding model configuration."""

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

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""

        await self._client.aclose()

    # -----------------------------------------------------------------------
    # Retry helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_retry_after(
        response: httpx.Response,
    ) -> float | None:
        """Parse a numeric Retry-After header."""

        value = response.headers.get("retry-after")

        if not value:
            return None

        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return None

        if seconds < 0:
            return None

        return min(
            seconds,
            RETRY_MAX_SECONDS,
        )

    @staticmethod
    async def _sleep_before_retry(
        attempt: int,
        retry_after: float | None = None,
    ) -> None:
        """Sleep using bounded exponential backoff with full jitter."""

        if retry_after is not None:
            delay = retry_after

        else:
            exponential_delay = min(
                RETRY_MAX_SECONDS,
                RETRY_MIN_SECONDS * (2 ** (attempt - 1)),
            )

            delay = random.uniform(
                0.0,
                exponential_delay,
            )

        logger.info(
            "Retrying Gemini request: next_attempt=%s delay=%.2fs",
            attempt + 1,
            delay,
        )

        await asyncio.sleep(delay)

    # -----------------------------------------------------------------------
    # Error helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _safe_error_message(
        response: httpx.Response,
    ) -> str:
        """Extract a bounded Gemini error message without leaking secrets."""

        try:
            payload = response.json()

        except ValueError:
            text = response.text.strip()

            if not text:
                return "Gemini returned an empty error response."

            return text[:1000]

        if isinstance(payload, dict):
            error = payload.get("error")

            if isinstance(error, dict):
                message = error.get("message")

                if isinstance(message, str) and message.strip():
                    return message.strip()[:1000]

        return "Gemini returned an unexpected error response."

    # -----------------------------------------------------------------------
    # HTTP transport
    # -----------------------------------------------------------------------

    async def _post(
        self,
        path: str,
        json_body: dict[str, Any],
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> dict[str, Any]:
        """POST JSON to Gemini with bounded transient-error retries."""

        if not self.api_key:
            raise AIAuthenticationError(
                "Gemini API key is not configured.",
                self.name,
            )

        if max_attempts < 1:
            raise ValueError(
                "max_attempts must be at least 1."
            )

        last_exception: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                response = await self._client.post(
                    path,
                    json=json_body,
                )

            except httpx.TimeoutException as exc:
                last_exception = exc

                logger.warning(
                    "Gemini request timeout: "
                    "attempt=%s/%s model=%s path=%s error=%s",
                    attempt,
                    max_attempts,
                    self.model,
                    path,
                    type(exc).__name__,
                )

                if attempt >= max_attempts:
                    raise _TransientAIError(
                        "Gemini request timed out after "
                        f"{max_attempts} attempts."
                    ) from exc

                await self._sleep_before_retry(attempt)
                continue

            except httpx.TransportError as exc:
                last_exception = exc

                logger.warning(
                    "Gemini transport error: "
                    "attempt=%s/%s model=%s path=%s error=%s",
                    attempt,
                    max_attempts,
                    self.model,
                    path,
                    type(exc).__name__,
                )

                if attempt >= max_attempts:
                    raise _TransientAIError(
                        "Gemini transport failed after "
                        f"{max_attempts} attempts."
                    ) from exc

                await self._sleep_before_retry(attempt)
                continue

            status_code = response.status_code

            # ---------------------------------------------------------------
            # Authentication / authorization
            # ---------------------------------------------------------------

            if status_code in {401, 403}:
                message = self._safe_error_message(response)

                raise AIAuthenticationError(
                    f"Gemini authentication or permission failed: "
                    f"{message}",
                    self.name,
                )

            # ---------------------------------------------------------------
            # Rate limiting
            # ---------------------------------------------------------------

            if status_code == 429:
                if attempt >= max_attempts:
                    raise AIRateLimitError(
                        "Gemini rate limit exceeded after retries.",
                        self.name,
                    )

                retry_after = self._parse_retry_after(response)

                logger.warning(
                    "Gemini rate limited: "
                    "attempt=%s/%s model=%s retry_after=%s",
                    attempt,
                    max_attempts,
                    self.model,
                    retry_after,
                )

                await self._sleep_before_retry(
                    attempt,
                    retry_after=retry_after,
                )

                continue

            # ---------------------------------------------------------------
            # Transient server errors
            # ---------------------------------------------------------------

            if status_code in TRANSIENT_STATUS_CODES:
                last_exception = _TransientAIError(
                    f"Gemini returned transient HTTP {status_code}."
                )

                if attempt >= max_attempts:
                    raise _TransientAIError(
                        "Gemini returned HTTP "
                        f"{status_code} after {max_attempts} attempts."
                    ) from last_exception

                logger.warning(
                    "Gemini transient failure: "
                    "status=%s attempt=%s/%s model=%s path=%s",
                    status_code,
                    attempt,
                    max_attempts,
                    self.model,
                    path,
                )

                retry_after = self._parse_retry_after(response)

                await self._sleep_before_retry(
                    attempt,
                    retry_after=retry_after,
                )

                continue

            # ---------------------------------------------------------------
            # Permanent client errors
            # ---------------------------------------------------------------

            if status_code >= 400:
                message = self._safe_error_message(response)

                raise AIProviderError(
                    f"Gemini request failed ({status_code}): "
                    f"{message}",
                    self.name,
                )

            # ---------------------------------------------------------------
            # Successful response
            # ---------------------------------------------------------------

            try:
                data = response.json()

            except ValueError as exc:
                raise AIProviderError(
                    "Gemini returned invalid JSON.",
                    self.name,
                    exc,
                ) from exc

            if not isinstance(data, dict):
                raise AIProviderError(
                    "Gemini returned an unexpected JSON response.",
                    self.name,
                )

            return data

        raise _TransientAIError(
            "Gemini request failed after retries."
        ) from last_exception

    # -----------------------------------------------------------------------
    # Response extraction
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_text(
        data: dict[str, Any],
    ) -> str:
        """Extract combined text from Gemini's first candidate."""

        try:
            candidates = data["candidates"]

            if not candidates:
                raise AIProviderError(
                    "Gemini returned no candidates "
                    "(likely blocked by safety filters).",
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
                    "Gemini returned no text content.",
                    "gemini",
                )

            return text

        except AIProviderError:
            raise

        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(
                "Unexpected Gemini response shape.",
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
                    "(likely blocked by safety filters).",
                    "gemini",
                )

            content = candidates[0]["content"]
            parts = content["parts"]

            if not isinstance(parts, list):
                raise AIProviderError(
                    "Gemini returned invalid candidate parts.",
                    "gemini",
                )

            return parts

        except AIProviderError:
            raise

        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(
                "Unexpected Gemini tool response shape.",
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

        try:
            data = await self._post(
                f"/models/{self.model}:generateContent",
                body,
            )

        except _TransientAIError as exc:
            raise AIProviderError(
                "Gemini is temporarily unavailable after retries.",
                self.name,
                exc,
            ) from exc

        return self._extract_text(data)

    # -----------------------------------------------------------------------
    # Embeddings
    # -----------------------------------------------------------------------

    async def embed(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Generate 768-dimensional embeddings for multiple texts."""

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
            raise AIProviderError(
                "Gemini embedding service is temporarily unavailable "
                "after retries.",
                self.name,
                exc,
            ) from exc

        try:
            embeddings = data["embeddings"]

        except (KeyError, TypeError) as exc:
            raise AIProviderError(
                "Unexpected Gemini embedding response shape.",
                self.name,
                exc,
            ) from exc

        if not isinstance(embeddings, list):
            raise AIProviderError(
                "Gemini returned invalid embeddings.",
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
                    f"Gemini embedding #{index} has an invalid response.",
                    self.name,
                )

            values = item["values"]

            if not isinstance(values, list):
                raise AIProviderError(
                    f"Gemini embedding #{index} returned invalid values.",
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
                "classify() called with an empty label set.",
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

        for label in labels:
            if cleaned.lower() == label.lower():
                return label

        for label in labels:
            if label.lower() in cleaned.lower():
                return label

        raise AIProviderError(
            f"Gemini returned '{raw}', which does not match "
            f"any supplied label.",
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
                "describe_image() received empty image data.",
                self.name,
            )

        if not mime_type:
            raise AIProviderError(
                "describe_image() requires a MIME type.",
                self.name,
            )

        if not mime_type.startswith("image/"):
            raise AIProviderError(
                f"Unsupported image MIME type: {mime_type}",
                self.name,
            )

        if len(image_bytes) > MAX_INLINE_IMAGE_BYTES:
            raise AIProviderError(
                "Image is too large for inline Gemini processing. "
                "Use the Gemini Files API for large images.",
                self.name,
            )

        prompt_text = instruction or (
            "Describe this image in detail. Note any visible text, numbers, "
            "amounts, dates, or reference/transaction IDs exactly as they "
            "appear. Describe any products, packaging, labels, clothing, "
            "documents, or app/screenshot UI shown."
        )

        encoded_image = base64.b64encode(
            image_bytes
        ).decode("ascii")

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
                                "data": encoded_image,
                            },
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
            },
        }

        try:
            data = await self._post(
                f"/models/{self.model}:generateContent",
                body,
                max_attempts=3,
            )

        except _TransientAIError as exc:
            logger.error(
                "Gemini image analysis failed after retries: "
                "model=%s mime_type=%s image_bytes=%s",
                self.model,
                mime_type,
                len(image_bytes),
            )

            raise AIProviderError(
                "Gemini image analysis is temporarily unavailable. "
                "Please try again shortly.",
                self.name,
                exc,
            ) from exc

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
                "transcribe_audio() received empty audio data.",
                self.name,
            )

        if not mime_type:
            raise AIProviderError(
                "transcribe_audio() requires a MIME type.",
                self.name,
            )

        prompt_text = (
            "Transcribe the speech in this audio clip verbatim, in its "
            "original language. Output only the transcript — no preamble, "
            "no translation, no description of tone."
        )

        encoded_audio = base64.b64encode(
            audio_bytes
        ).decode("ascii")

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
                                "data": encoded_audio,
                            },
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
            },
        }

        try:
            data = await self._post(
                f"/models/{self.model}:generateContent",
                body,
                max_attempts=3,
            )

        except _TransientAIError as exc:
            raise AIProviderError(
                "Gemini audio transcription is temporarily "
                "unavailable after retries.",
                self.name,
                exc,
            ) from exc

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

        The tool loop preserves Gemini's complete model response parts.
        This is important for newer Gemini models where model response
        metadata, including thought signatures, may need to be preserved
        when sending the model turn back to Gemini.
        """

        if not tools:
            return await self.generate(
                prompt,
                system_instruction=system_instruction,
                temperature=temperature,
            )

        if max_tool_iterations < 1:
            raise AIProviderError(
                "max_tool_iterations must be at least 1.",
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
                        "text": (
                            base_system_prompt
                            + tool_guidance
                        ),
                    }
                ]
            },
        }

        for iteration in range(
            1,
            max_tool_iterations + 1,
        ):
            logger.info(
                "Gemini tool-calling iteration %s/%s model=%s",
                iteration,
                max_tool_iterations,
                self.model,
            )

            body = {
                **body_base,
                "contents": contents,
            }

            try:
                data = await self._post(
                    f"/models/{self.model}:generateContent",
                    body,
                )

            except _TransientAIError as exc:
                raise AIProviderError(
                    "Gemini is temporarily unavailable after retries.",
                    self.name,
                    exc,
                ) from exc

            parts = self._extract_candidate_parts(data)

            function_calls = self._extract_function_calls(parts)

            # ---------------------------------------------------------------
            # Normal final text response.
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
                    "Gemini returned neither text nor function calls.",
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

            # Preserve Gemini's complete model response exactly as returned.
            # This is important for thought signatures and other model
            # response metadata used by newer Gemini models.

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
                        "a name."
                    )

                else:
                    logger.info(
                        "Executing Gemini tool name=%s id=%s",
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

                if tool_call_id:
                    function_response["id"] = tool_call_id

                function_response_parts.append(
                    {
                        "functionResponse": function_response,
                    }
                )

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
            fallback_data = await self._post(
                f"/models/{self.model}:generateContent",
                forced_body,
            )

            return self._extract_text(fallback_data)

        except _TransientAIError as exc:
            raise AIProviderError(
                "Gemini unavailable after retries while forcing "
                "a final tool-calling response.",
                self.name,
                exc,
            ) from exc

        except AIProviderError:
            raise

        except Exception as exc:
            raise AIProviderError(
                "Gemini tool-calling loop exceeded "
                f"{max_tool_iterations} iterations without a "
                "final answer.",
                self.name,
                exc,
            ) from exc
