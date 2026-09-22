"""
Gemini AI provider.

Production-ready Gemini REST client with:
- Persistent HTTP connection pooling
- Explicit timeout profiles
- Bounded retries with exponential backoff
- Retry handling for transient HTTP failures
- API key sent securely through request headers
- Request timing logs
- Chat generation
- Tool/function calling
- Embeddings with batch support
- Image understanding
- Audio transcription
- Summarization and classification helpers
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt

from app.core.config import settings
from app.core.logging_config import get_logger

from app.services.ai.base import (
    AIProvider,
    AIProviderError,
    AIRateLimitError,
)

logger = get_logger(__name__)


GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

DEFAULT_GENERATION_TIMEOUT = 35.0
DEFAULT_EMBEDDING_TIMEOUT = 20.0
DEFAULT_IMAGE_TIMEOUT = 35.0
DEFAULT_TRANSCRIPTION_TIMEOUT = 60.0

DEFAULT_MAX_OUTPUT_TOKENS = 512

MAX_RETRIES = 2
MAX_TOOL_ITERATIONS = 3


class _TransientAIError(Exception):
    """Internal exception used for retryable Gemini failures."""


class GeminiProvider(AIProvider):
    """
    Gemini REST API provider.

    The HTTP client is intentionally kept alive for the lifetime of the
    provider so HTTP connections can be reused between requests.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout: float = DEFAULT_GENERATION_TIMEOUT,
    ) -> None:
        self.api_key = api_key or settings.GEMINI_API_KEY

        if not self.api_key:
            raise AIProviderError("Gemini API key is not configured.")

        self._timeout = timeout

        self._limits = httpx.Limits(
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=30.0,
        )

        self._client: httpx.AsyncClient | None = None

        self._client_lock = asyncio.Lock()

        self._ensure_client_sync()

    # ------------------------------------------------------------------
    # HTTP CLIENT
    # ------------------------------------------------------------------

    def _ensure_client_sync(self) -> None:
        """
        Create the HTTP client synchronously during provider construction.

        HTTP/2 is deliberately not enabled here because Railway images may
        not include the optional `h2` dependency. HTTP/1.1 keep-alive and
        connection pooling still provide the important latency benefits.
        """
        if self._client is not None and not self._client.is_closed:
            return

        self._client = httpx.AsyncClient(
            base_url=GEMINI_API_BASE,
            timeout=httpx.Timeout(
                connect=10.0,
                read=self._timeout,
                write=20.0,
                pool=10.0,
            ),
            limits=self._limits,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Return a live reusable HTTP client."""
        if self._client is not None and not self._client.is_closed:
            return self._client

        async with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    base_url=GEMINI_API_BASE,
                    timeout=httpx.Timeout(
                        connect=10.0,
                        read=self._timeout,
                        write=20.0,
                        pool=10.0,
                    ),
                    limits=self._limits,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )

        return self._client

    async def aclose(self) -> None:
        """
        Close the persistent HTTP client.

        Call this only when the worker/service is shutting down.
        Do not call it after every request or Celery task.
        """
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # REQUEST HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        """
        Return a small bounded exponential backoff.

        attempt=1 -> 1 second
        attempt=2 -> 2 seconds
        """
        return min(2.0, float(2 ** (attempt - 1)))

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code in {
            408,
            429,
            500,
            502,
            503,
            504,
        }

    async def _post_once(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Perform one Gemini POST request."""
        client = await self._ensure_client()

        started = time.perf_counter()

        request_timeout = (
            httpx.Timeout(
                connect=10.0,
                read=timeout,
                write=20.0,
                pool=10.0,
            )
            if timeout is not None
            else None
        )

        try:
            response = await client.post(
                path,
                params=None,
                headers={
                    "x-goog-api-key": self.api_key,
                },
                json=payload,
                timeout=request_timeout,
            )

        except httpx.TimeoutException as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000

            logger.warning(
                "Gemini request timeout: path=%s elapsed_ms=%.0f",
                path,
                elapsed_ms,
            )

            raise _TransientAIError(
                "Gemini request timed out."
            ) from exc

        except httpx.TransportError as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000

            logger.warning(
                "Gemini transport error: path=%s elapsed_ms=%.0f error=%s",
                path,
                elapsed_ms,
                exc,
            )

            raise _TransientAIError(
                "Gemini transport error."
            ) from exc

        elapsed_ms = (time.perf_counter() - started) * 1000

        logger.info(
            "Gemini request completed: path=%s status=%s elapsed_ms=%.0f",
            path,
            response.status_code,
            elapsed_ms,
        )

        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")

            raise AIRateLimitError(
                f"Gemini rate limit exceeded"
                + (
                    f"; retry-after={retry_after}s"
                    if retry_after
                    else ""
                )
            )

        if self._is_retryable_status(response.status_code):
            body = response.text[:500]

            logger.warning(
                "Gemini transient HTTP error: path=%s status=%s body=%s",
                path,
                response.status_code,
                body,
            )

            raise _TransientAIError(
                f"Gemini returned HTTP {response.status_code}."
            )

        if response.status_code >= 400:
            body = response.text[:1000]

            logger.error(
                "Gemini API error: path=%s status=%s body=%s",
                path,
                response.status_code,
                body,
            )

            raise AIProviderError(
                f"Gemini API error ({response.status_code})."
            )

        try:
            return response.json()

        except ValueError as exc:
            logger.error(
                "Gemini returned invalid JSON: path=%s",
                path,
            )

            raise AIProviderError(
                "Gemini returned an invalid JSON response."
            ) from exc

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        Perform a bounded retrying POST request.

        We deliberately keep retries low because Telegram responses should
        not wait through several long Gemini retry cycles.
        """
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return await self._post_once(
                    path,
                    payload,
                    timeout=timeout,
                )

            except AIRateLimitError:
                raise

            except _TransientAIError as exc:
                last_error = exc

                if attempt >= MAX_RETRIES:
                    break

                delay = self._retry_delay(attempt)

                logger.warning(
                    "Retrying Gemini request: path=%s attempt=%s/%s "
                    "delay=%.1fs error=%s",
                    path,
                    attempt,
                    MAX_RETRIES,
                    delay,
                    exc,
                )

                await asyncio.sleep(delay)

        raise AIProviderError(
            "Gemini unavailable after retries."
        ) from last_error

    # ------------------------------------------------------------------
    # RESPONSE EXTRACTION
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(response: dict[str, Any]) -> str:
        """
        Extract text from a Gemini generateContent response.
        """
        candidates = response.get("candidates") or []

        if not candidates:
            raise AIProviderError(
                "Gemini returned no candidates."
            )

        parts = (
            candidates[0]
            .get("content", {})
            .get("parts", [])
        )

        texts: list[str] = []

        for part in parts:
            text = part.get("text")

            if isinstance(text, str) and text:
                texts.append(text)

        result = "\n".join(texts).strip()

        if not result:
            raise AIProviderError(
                "Gemini returned an empty response."
            )

        return result

    @staticmethod
    def _extract_function_calls(
        response: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Extract Gemini function calls from a response."""
        candidates = response.get("candidates") or []

        if not candidates:
            return []

        parts = (
            candidates[0]
            .get("content", {})
            .get("parts", [])
        )

        calls: list[dict[str, Any]] = []

        for part in parts:
            function_call = part.get("functionCall")

            if function_call:
                calls.append(function_call)

        return calls

    # ------------------------------------------------------------------
    # GENERATION
    # ------------------------------------------------------------------

    async def generate(
        self,
        *,
        prompt: str,
        system_instruction: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        **kwargs: Any,
    ) -> str:
        """
        Generate a text response from Gemini.
        """
        model_name = (
            model
            or getattr(settings, "GEMINI_MODEL", None)
            or "gemini-2.5-flash"
        )

        contents = [
            {
                "role": "user",
                "parts": [
                    {
                        "text": prompt,
                    }
                ],
            }
        ]

        generation_config: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        }

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }

        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [
                    {
                        "text": system_instruction,
                    }
                ]
            }

        started = time.perf_counter()

        response = await self._post(
            f"/models/{model_name}:generateContent",
            payload,
            timeout=DEFAULT_GENERATION_TIMEOUT,
        )

        result = self._extract_text(response)

        elapsed_ms = (time.perf_counter() - started) * 1000

        logger.info(
            "Gemini generate completed: model=%s elapsed_ms=%.0f",
            model_name,
            elapsed_ms,
        )

        return result

    # ------------------------------------------------------------------
    # TOOL / FUNCTION CALLING
    # ------------------------------------------------------------------

    async def generate_with_tools(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_executor: Any,
        system_instruction: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        **kwargs: Any,
    ) -> str:
        """
        Generate a response using Gemini function calling.

        Tool execution is bounded to avoid long-running loops.
        """
        model_name = (
            model
            or getattr(settings, "GEMINI_MODEL", None)
            or "gemini-2.5-flash"
        )

        contents = list(messages)

        function_declarations: list[dict[str, Any]] = []

        for tool in tools:
            if "function" in tool:
                function_declarations.append(
                    tool["function"]
                )
            else:
                function_declarations.append(tool)

        tool_config = {
            "functionDeclarations": function_declarations,
        }

        for iteration in range(MAX_TOOL_ITERATIONS):
            generation_config: dict[str, Any] = {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            }

            payload: dict[str, Any] = {
                "contents": contents,
                "tools": [
                    tool_config,
                ],
                "generationConfig": generation_config,
            }

            if system_instruction:
                payload["systemInstruction"] = {
                    "parts": [
                        {
                            "text": system_instruction,
                        }
                    ]
                }

            response = await self._post(
                f"/models/{model_name}:generateContent",
                payload,
                timeout=DEFAULT_GENERATION_TIMEOUT,
            )

            function_calls = self._extract_function_calls(response)

            if not function_calls:
                return self._extract_text(response)

            candidates = response.get("candidates") or []

            if not candidates:
                raise AIProviderError(
                    "Gemini returned no candidates during tool calling."
                )

            model_content = candidates[0].get("content")

            if model_content:
                contents.append(model_content)

            tool_response_parts: list[dict[str, Any]] = []

            for function_call in function_calls:
                function_name = function_call.get("name")
                function_args = function_call.get("args") or {}

                if not function_name:
                    continue

                logger.info(
                    "Gemini tool call: tool=%s iteration=%s",
                    function_name,
                    iteration + 1,
                )

                try:
                    result = await tool_executor(
                        function_name,
                        function_args,
                    )

                except Exception as exc:
                    logger.exception(
                        "Gemini tool execution failed: tool=%s",
                        function_name,
                    )

                    result = {
                        "error": str(exc),
                    }

                tool_response_parts.append(
                    {
                        "functionResponse": {
                            "name": function_name,
                            "response": {
                                "result": result,
                            },
                        }
                    }
                )

            if tool_response_parts:
                contents.append(
                    {
                        "role": "user",
                        "parts": tool_response_parts,
                    }
                )

        logger.warning(
            "Gemini reached maximum tool iterations: max=%s",
            MAX_TOOL_ITERATIONS,
        )

        # Force one final response without another tool loop.
        final_payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }

        if system_instruction:
            final_payload["systemInstruction"] = {
                "parts": [
                    {
                        "text": system_instruction,
                    }
                ]
            }

        response = await self._post(
            f"/models/{model_name}:generateContent",
            final_payload,
            timeout=DEFAULT_GENERATION_TIMEOUT,
        )

        return self._extract_text(response)

    # ------------------------------------------------------------------
    # EMBEDDINGS
    # ------------------------------------------------------------------

    async def embed(
        self,
        text: str,
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> list[float]:
        """
        Generate an embedding for one text.
        """
        results = await self.embed_batch(
            [text],
            model=model,
            **kwargs,
        )

        if not results:
            raise AIProviderError(
                "Gemini returned no embedding."
            )

        return results[0]

    async def embed_batch(
        self,
        texts: list[str],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> list[list[float]]:
        """
        Generate embeddings for multiple texts in one Gemini request.
        """
        if not texts:
            return []

        model_name = (
            model
            or getattr(settings, "GEMINI_EMBEDDING_MODEL", None)
            or "gemini-embedding-001"
        )

        requests = [
            {
                "model": f"models/{model_name}",
                "content": {
                    "parts": [
                        {
                            "text": text,
                        }
                    ]
                },
            }
            for text in texts
        ]

        payload = {
            "requests": requests,
        }

        response = await self._post(
            f"/models/{model_name}:batchEmbedContents",
            payload,
            timeout=DEFAULT_EMBEDDING_TIMEOUT,
        )

        embeddings = response.get("embeddings") or []

        results: list[list[float]] = []

        for item in embeddings:
            values = item.get("values")

            if not isinstance(values, list):
                raise AIProviderError(
                    "Gemini returned an invalid embedding."
                )

            results.append(values)

        if len(results) != len(texts):
            raise AIProviderError(
                "Gemini returned an incomplete embedding batch."
            )

        return results

    # ------------------------------------------------------------------
    # IMAGE UNDERSTANDING
    # ------------------------------------------------------------------

    async def describe_image(
        self,
        image_bytes: bytes,
        *,
        mime_type: str = "image/jpeg",
        prompt: str = "Describe this image in detail.",
        model: str | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Analyze an image using Gemini vision.
        """
        import base64

        model_name = (
            model
            or getattr(settings, "GEMINI_MODEL", None)
            or "gemini-2.5-flash"
        )

        encoded_image = base64.b64encode(
            image_bytes
        ).decode("utf-8")

        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": prompt,
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
                "maxOutputTokens": max(
                    DEFAULT_MAX_OUTPUT_TOKENS,
                    768,
                ),
            },
        }

        response = await self._post(
            f"/models/{model_name}:generateContent",
            payload,
            timeout=DEFAULT_IMAGE_TIMEOUT,
        )

        return self._extract_text(response)

    # ------------------------------------------------------------------
    # AUDIO TRANSCRIPTION
    # ------------------------------------------------------------------

    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str = "audio/ogg",
        prompt: str | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Transcribe audio using Gemini multimodal generation.
        """
        import base64

        model_name = (
            model
            or getattr(settings, "GEMINI_MODEL", None)
            or "gemini-2.5-flash"
        )

        encoded_audio = base64.b64encode(
            audio_bytes
        ).decode("utf-8")

        transcription_prompt = (
            prompt
            or (
                "Transcribe this audio exactly. "
                "Return only the spoken words. "
                "Do not add commentary or explanations."
            )
        )

        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": transcription_prompt,
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
                "maxOutputTokens": 1024,
            },
        }

        response = await self._post(
            f"/models/{model_name}:generateContent",
            payload,
            timeout=DEFAULT_TRANSCRIPTION_TIMEOUT,
        )

        return self._extract_text(response)

    # ------------------------------------------------------------------
    # SUMMARIZATION
    # ------------------------------------------------------------------

    async def summarize(
        self,
        text: str,
        *,
        model: str | None = None,
        max_output_tokens: int = 512,
        **kwargs: Any,
    ) -> str:
        """
        Summarize text using Gemini.
        """
        prompt = (
            "Summarize the following content clearly and accurately. "
            "Preserve the important facts and key points.\n\n"
            f"{text}"
        )

        return await self.generate(
            prompt=prompt,
            model=model,
            temperature=0.2,
            max_output_tokens=max_output_tokens,
        )

    # ------------------------------------------------------------------
    # CLASSIFICATION
    # ------------------------------------------------------------------

    async def classify(
        self,
        text: str,
        categories: list[str],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Classify text into one of the supplied categories.
        """
        if not categories:
            raise AIProviderError(
                "Classification categories cannot be empty."
            )

        category_text = ", ".join(categories)

        prompt = (
            "Classify the following text into exactly one of these "
            f"categories: {category_text}\n\n"
            "Return only the category name.\n\n"
            f"Text:\n{text}"
        )

        result = await self.generate(
            prompt=prompt,
            model=model,
            temperature=0.0,
            max_output_tokens=64,
        )

        return result.strip()

    # ------------------------------------------------------------------
    # HEALTH
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """
        Perform a lightweight Gemini connectivity check.
        """
        try:
            await self.generate(
                prompt="Reply with OK.",
                temperature=0.0,
                max_output_tokens=8,
            )
            return True

        except Exception as exc:
            logger.warning(
                "Gemini health check failed: %s",
                exc,
            )
            return False
