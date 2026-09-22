"""Google Gemini implementation of AIProvider.

Provides:
- Text generation
- Text embeddings
- Image understanding
- Audio transcription
- Text summarization
- Text classification
- Gemini function/tool calling

The provider is optimized for production messaging workloads:
- Persistent HTTP connection pooling
- Separate connect/read/write/pool timeouts
- Bounded retries
- Retry handling for transient failures and rate limits
- API-key header authentication
- Request timing instrumentation
- Bounded Telegram-friendly generation output
"""

from __future__ import annotations

import asyncio
import base64
import logging
import random
import time
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

GEMINI_EMBEDDING_DIMENSION = 768

DEFAULT_GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"

RETIRED_EMBEDDING_MODELS = {
    "text-embedding-004",
    "models/text-embedding-004",
}


class _TransientAIError(Exception):
    """Internal marker for retryable Gemini failures."""


class GeminiProvider(AIProvider):
    """Gemini REST implementation of the AIProvider interface."""

    name = "gemini"

    DEFAULT_CONNECT_TIMEOUT = 5.0
    DEFAULT_READ_TIMEOUT = 35.0
    DEFAULT_WRITE_TIMEOUT = 15.0
    DEFAULT_POOL_TIMEOUT = 5.0

    DEFAULT_MAX_RETRIES = 1

    DEFAULT_GENERATION_MAX_TOKENS = 512
    DEFAULT_CLASSIFICATION_MAX_TOKENS = 32
    DEFAULT_SUMMARY_MAX_TOKENS = 512
    DEFAULT_TRANSCRIPTION_MAX_TOKENS = 1024
    DEFAULT_IMAGE_MAX_TOKENS = 768
    DEFAULT_TOOL_MAX_TOKENS = 512

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        embedding_model: str | None = None,
        timeout: float | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
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

        self.max_retries = max(
            0,
            min(max_retries, 2),
        )

        read_timeout = (
            float(timeout)
            if timeout is not None
            else self.DEFAULT_READ_TIMEOUT
        )

        self._timeout = httpx.Timeout(
            connect=self.DEFAULT_CONNECT_TIMEOUT,
            read=read_timeout,
            write=self.DEFAULT_WRITE_TIMEOUT,
            pool=self.DEFAULT_POOL_TIMEOUT,
        )

        self._limits = httpx.Limits(
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=30.0,
        )

        self._client = httpx.AsyncClient(
            base_url=GEMINI_API_BASE,
            timeout=self._timeout,
            limits=self._limits,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            http2=True,
        )

        self._closed = False

        if not self.api_key:
            logger.warning(
                "GeminiProvider initialized without an API key."
            )

        logger.info(
            "GeminiProvider initialized: "
            "model=%s embedding_model=%s embedding_dimension=%s "
            "read_timeout=%ss max_retries=%s",
            self.model,
            self.embedding_model,
            GEMINI_EMBEDDING_DIMENSION,
            read_timeout,
            self.max_retries,
        )

    # ------------------------------------------------------------------
    # Model helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_model_name(model: str) -> str:
        """Normalize a Gemini model name."""

        return model.strip().removeprefix("models/")

    @classmethod
    def _normalize_embedding_model(cls, model: str) -> str:
        """Normalize embedding model and replace retired models."""

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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _ensure_client(self) -> None:
        """Recreate the HTTP client if it has been closed."""

        if not self._closed:
            return

        self._client = httpx.AsyncClient(
            base_url=GEMINI_API_BASE,
            timeout=self._timeout,
            limits=self._limits,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            http2=True,
        )

        self._closed = False

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""

        if self._closed:
            return

        self._closed = True

        await self._client.aclose()

    # ------------------------------------------------------------------
    # HTTP transport
    # ------------------------------------------------------------------

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        """Return a short bounded retry delay."""

        base = min(2.0, 0.5 * (2 ** max(0, attempt - 1)))
        return base + random.uniform(0.0, 0.25)

    @staticmethod
    def _retryable_status(status_code: int) -> bool:
        """Return whether a response should be retried."""

        return status_code in {
            408,
            429,
            500,
            502,
            503,
            504,
        }

    async def _post(
        self,
        path: str,
        json_body: dict[str, Any],
        *,
        timeout: httpx.Timeout | None = None,
        operation: str = "request",
    ) -> dict[str, Any]:
        """POST JSON to Gemini with bounded production retries."""

        if not self.api_key:
            raise AIAuthenticationError(
                "Gemini API key is missing",
                self.name,
            )

        await self._ensure_client()

        request_timeout = timeout or self._timeout

        attempts = self.max_retries + 1

        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            started = time.perf_counter()

            try:
                response = await self._client.post(
                    path,
                    headers={
                        "x-goog-api-key": self.api_key,
                    },
                    json=json_body,
                    timeout=request_timeout,
                )

                elapsed_ms = (
                    time.perf_counter() - started
                ) * 1000

                logger.info(
                    "Gemini %s completed: status=%s "
                    "elapsed_ms=%.2f attempt=%s/%s",
                    operation,
                    response.status_code,
                    elapsed_ms,
                    attempt,
                    attempts,
                )

            except httpx.TimeoutException as exc:
                elapsed_ms = (
                    time.perf_counter() - started
                ) * 1000

                last_error = exc

                logger.warning(
                    "Gemini %s timeout: elapsed_ms=%.2f "
                    "attempt=%s/%s error=%s",
                    operation,
                    elapsed_ms,
                    attempt,
                    attempts,
                    type(exc).__name__,
                )

                if attempt >= attempts:
                    raise _TransientAIError(
                        f"Gemini {operation} timed out "
                        f"after {attempts} attempt(s)"
                    ) from exc

                await asyncio.sleep(
                    self._retry_delay(attempt)
                )

                continue

            except httpx.TransportError as exc:
                elapsed_ms = (
                    time.perf_counter() - started
                ) * 1000

                last_error = exc

                logger.warning(
                    "Gemini %s transport error: elapsed_ms=%.2f "
                    "attempt=%s/%s error=%s",
                    operation,
                    elapsed_ms,
                    attempt,
                    attempts,
                    type(exc).__name__,
                )

                if attempt >= attempts:
                    raise _TransientAIError(
                        f"Gemini {operation} transport error"
                    ) from exc

                await asyncio.sleep(
                    self._retry_delay(attempt)
                )

                continue

            except Exception:
                logger.exception(
                    "Unexpected Gemini %s HTTP failure.",
                    operation,
                )
                raise

            if response.status_code in (401, 403):
                raise AIAuthenticationError(
                    "Invalid or unauthorized Gemini API key",
                    self.name,
                )

            if response.status_code == 429:
                retry_after = response.headers.get(
                    "retry-after"
                )

                logger.warning(
                    "Gemini rate limit: operation=%s "
                    "attempt=%s/%s retry_after=%s",
                    operation,
                    attempt,
                    attempts,
                    retry_after,
                )

                if attempt >= attempts:
                    raise AIRateLimitError(
                        "Gemini rate limit exceeded",
                        self.name,
                    )

                delay = self._retry_delay(attempt)

                if retry_after:
                    try:
                        delay = min(
                            float(retry_after),
                            5.0,
                        )
                    except ValueError:
                        pass

                await asyncio.sleep(delay)
                continue

            if self._retryable_status(
                response.status_code
            ):
                last_error = _TransientAIError(
                    f"Gemini returned {response.status_code}: "
                    f"{response.text[:1000]}"
                )

                logger.warning(
                    "Retryable Gemini response: "
                    "status=%s operation=%s attempt=%s/%s",
                    response.status_code,
                    operation,
                    attempt,
                    attempts,
                )

                if attempt >= attempts:
                    raise last_error

                await asyncio.sleep(
                    self._retry_delay(attempt)
                )

                continue

            if response.status_code >= 400:
                raise AIProviderError(
                    f"Gemini request failed "
                    f"({response.status_code}): "
                    f"{response.text[:2000]}",
                    self.name,
                )

            try:
                return response.json()

            except ValueError as exc:
                raise AIProviderError(
                    "Gemini returned invalid JSON",
                    self.name,
                    exc,
                ) from exc

        raise _TransientAIError(
            f"Gemini {operation} failed after retries"
        ) from last_error

    # ------------------------------------------------------------------
    # Response extraction
    # ------------------------------------------------------------------

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

        except (
            KeyError,
            IndexError,
            TypeError,
        ) as exc:
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

        except (
            KeyError,
            IndexError,
            TypeError,
        ) as exc:
            raise AIProviderError(
                f"Unexpected Gemini response shape: {data}",
                "gemini",
                exc,
            ) from exc

    @staticmethod
    def _extract_function_calls(
        parts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Extract all functionCall parts."""

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

    # ------------------------------------------------------------------
    # Timeout profiles
    # ------------------------------------------------------------------

    def _operation_timeout(
        self,
        read_timeout: float,
    ) -> httpx.Timeout:
        """Build a timeout profile for a Gemini operation."""

        return httpx.Timeout(
            connect=self.DEFAULT_CONNECT_TIMEOUT,
            read=read_timeout,
            write=self.DEFAULT_WRITE_TIMEOUT,
            pool=self.DEFAULT_POOL_TIMEOUT,
        )

    # ------------------------------------------------------------------
    # Text generation
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Generate a text response with Gemini."""

        output_tokens = (
            max_tokens
            if max_tokens is not None
            else self.DEFAULT_GENERATION_MAX_TOKENS
        )

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
                "maxOutputTokens": output_tokens,
            },
        }

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
                timeout=self._operation_timeout(
                    self.DEFAULT_READ_TIMEOUT
                ),
                operation="generate",
            )

        except _TransientAIError as exc:
            raise AIProviderError(
                "Gemini unavailable after retries",
                self.name,
                exc,
            ) from exc

        return self._extract_text(data)

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    async def embed(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Generate 768-dimensional embeddings."""

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
                    "outputDimensionality": (
                        GEMINI_EMBEDDING_DIMENSION
                    ),
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
                timeout=self._operation_timeout(20.0),
                operation="embedding",
            )

        except _TransientAIError as exc:
            raise AIProviderError(
                "Gemini unavailable after retries",
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
                f"Unexpected Gemini embedding response shape: "
                f"{data}",
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
            if not isinstance(item, dict):
                raise AIProviderError(
                    f"Gemini embedding #{index} has an invalid "
                    f"response: {item}",
                    self.name,
                )

            values = item.get("values")

            if not isinstance(values, list):
                raise AIProviderError(
                    f"Gemini embedding #{index} returned invalid "
                    f"values: {values}",
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

    # ------------------------------------------------------------------
    # Summarization
    # ------------------------------------------------------------------

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
            max_tokens=self.DEFAULT_SUMMARY_MAX_TOKENS,
        )

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

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
            max_tokens=self.DEFAULT_CLASSIFICATION_MAX_TOKENS,
        )

        cleaned = raw.strip().strip('"').strip("'")

        for label in labels:
            if cleaned.lower() == label.lower():
                return label

        for label in labels:
            if label.lower() in cleaned.lower():
                return label

        raise AIProviderError(
            f"Gemini returned '{raw}', which doesn't match "
            f"any of {labels}",
            self.name,
        )

    # ------------------------------------------------------------------
    # Image understanding
    # ------------------------------------------------------------------

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
            "Describe this image in detail. Note any visible text, "
            "numbers, amounts, dates, or reference/transaction IDs "
            "exactly as they appear. Describe any products, packaging, "
            "labels, clothing, documents, or app/screenshot UI shown."
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
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": encoded_image,
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": (
                    self.DEFAULT_IMAGE_MAX_TOKENS
                ),
            },
        }

        logger.info(
            "Sending image to Gemini: "
            "mime_type=%s bytes=%s",
            mime_type,
            len(image_bytes),
        )

        try:
            data = await self._post(
                f"/models/{self.model}:generateContent",
                body,
                timeout=self._operation_timeout(35.0),
                operation="image",
            )

        except _TransientAIError as exc:
            raise AIProviderError(
                "Gemini unavailable after retries",
                self.name,
                exc,
            ) from exc

        return self._extract_text(data)

    # ------------------------------------------------------------------
    # Audio transcription
    # ------------------------------------------------------------------

    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        mime_type: str,
    ) -> str:
        """Transcribe an audio clip using Gemini."""

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
            "Transcribe the speech in this audio clip accurately. "
            "Preserve the speaker's original language and wording. "
            "Do not translate, summarize, explain, or add commentary. "
            "Output only the transcription."
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
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": encoded_audio,
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": (
                    self.DEFAULT_TRANSCRIPTION_MAX_TOKENS
                ),
            },
        }

        logger.info(
            "Sending audio to Gemini for transcription: "
            "mime_type=%s bytes=%s",
            mime_type,
            len(audio_bytes),
        )

        try:
            data = await self._post(
                f"/models/{self.model}:generateContent",
                body,
                timeout=self._operation_timeout(60.0),
                operation="transcription",
            )

        except _TransientAIError as exc:
            raise AIProviderError(
                "Gemini unavailable after retries",
                self.name,
                exc,
            ) from exc

        transcript = self._extract_text(data)

        logger.info(
            "Gemini audio transcription completed: "
            "characters=%s",
            len(transcript),
        )

        return transcript

    # ------------------------------------------------------------------
    # Function / tool calling
    # ------------------------------------------------------------------

    async def generate_with_tools(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        tool_executor: ToolExecutor,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tool_iterations: int = 3,
    ) -> str:
        """Generate a response using Gemini REST function calling."""

        if not tools:
            return await self.generate(
                prompt,
                system_instruction=system_instruction,
                temperature=temperature,
                max_tokens=self.DEFAULT_TOOL_MAX_TOKENS,
            )

        if max_tool_iterations < 1:
            raise AIProviderError(
                "max_tool_iterations must be at least 1",
                self.name,
            )

        max_tool_iterations = min(
            max_tool_iterations,
            3,
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
            "\n\nAfter calling tools and receiving their results, "
            "synthesize the findings into a clear final text answer "
            "for the user. Do not expose internal tool execution "
            "details unless relevant."
        )

        body_base: dict[str, Any] = {
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": (
                    self.DEFAULT_TOOL_MAX_TOKENS
                ),
            },
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
                "Gemini tool-calling iteration %s/%s "
                "model=%s",
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
                    timeout=self._operation_timeout(35.0),
                    operation=f"tool_iteration_{iteration}",
                )

            except _TransientAIError as exc:
                raise AIProviderError(
                    "Gemini unavailable after retries",
                    self.name,
                    exc,
                ) from exc

            parts = self._extract_candidate_parts(data)

            function_calls = (
                self._extract_function_calls(parts)
            )

            if not function_calls:
                text = "".join(
                    part.get("text", "")
                    for part in parts
                    if isinstance(part, dict)
                ).strip()

                if text:
                    logger.info(
                        "Gemini returned final text after "
                        "%s tool iteration(s)",
                        iteration,
                    )
                    return text

                raise AIProviderError(
                    "Gemini returned neither text nor "
                    f"function calls: {data}",
                    self.name,
                )

            logger.info(
                "Gemini requested %s function call(s): %s",
                len(function_calls),
                ", ".join(
                    str(
                        call.get(
                            "name",
                            "<unknown>",
                        )
                    )
                    for call in function_calls
                ),
            )

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

                tool_call_id = function_call.get(
                    "id"
                )

                if not tool_name:
                    result: Any = {
                        "error": (
                            "Gemini returned a function "
                            "call without a name."
                        )
                    }

                    logger.warning(
                        "Gemini returned a function call "
                        "without a name: %s",
                        function_call,
                    )

                else:
                    logger.info(
                        "Executing Gemini tool name=%s "
                        "id=%s",
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
                            "Tool execution failed for "
                            "Gemini tool=%s",
                            tool_name,
                        )

                        result = {
                            "error": str(exc),
                        }

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

            contents.append(
                {
                    "role": "user",
                    "parts": function_response_parts,
                }
            )

        logger.warning(
            "Max Gemini tool iterations (%s) reached.",
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
                            "already available. Do not call "
                            "any more tools."
                        )
                    }
                ],
            }
        ]

        forced_body = {
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": (
                    self.DEFAULT_TOOL_MAX_TOKENS
                ),
            },
            "contents": forced_contents,
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            base_system_prompt
                            + tool_guidance
                        ),
                    }
                ],
            },
        }

        try:
            fallback_data = await self._post(
                f"/models/{self.model}:generateContent",
                forced_body,
                timeout=self._operation_timeout(35.0),
                operation="forced_tool_final",
            )

            return self._extract_text(
                fallback_data
            )

        except _TransientAIError as exc:
            raise AIProviderError(
                "Gemini unavailable while forcing "
                "a final tool-calling response",
                self.name,
                exc,
            ) from exc

        except AIProviderError:
            raise

        except Exception as exc:
            raise AIProviderError(
                "Gemini tool-calling loop exceeded "
                f"{max_tool_iterations} iterations without "
                "a final answer",
                self.name,
                exc,
            ) from exc
