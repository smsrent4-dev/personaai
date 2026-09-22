"""
Gemini AI provider.

Production-ready Gemini REST client with:
- Persistent HTTP connection pooling
- Explicit timeout profiles
- Bounded retries
- Transient HTTP error handling
- Secure API-key headers
- Request timing logs
- Text generation
- Function/tool calling
- Single and batch embeddings
- Image understanding
- Audio transcription
- Summarization
- Classification

The provider is cached by app.services.ai.factory, so the underlying
httpx.AsyncClient is reused across requests.
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any, Awaitable, Callable

import httpx

from app.config import settings
from app.services.ai.base import AIProvider
from app.services.ai.exceptions import AIProviderError


GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

DEFAULT_GENERATION_TIMEOUT = 35.0
DEFAULT_EMBEDDING_TIMEOUT = 20.0
DEFAULT_IMAGE_TIMEOUT = 35.0
DEFAULT_TRANSCRIPTION_TIMEOUT = 60.0

DEFAULT_MAX_OUTPUT_TOKENS = 512

MAX_RETRIES = 2
MAX_TOOL_ITERATIONS = 3


class _TransientAIError(Exception):
    """Internal exception for retryable Gemini failures."""


class GeminiProvider(AIProvider):
    """
    Gemini REST API implementation.

    The provider owns one reusable AsyncClient. The factory caches the
    provider instance, allowing HTTP keep-alive connections to survive
    across requests.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout: float = DEFAULT_GENERATION_TIMEOUT,
    ) -> None:
        self.api_key = (
            api_key
            or getattr(settings, "GEMINI_API_KEY", None)
            or getattr(settings, "GOOGLE_API_KEY", None)
        )

        if not self.api_key:
            raise AIProviderError(
                "Gemini API key is not configured.",
                "gemini",
            )

        self._timeout = timeout

        self._limits = httpx.Limits(
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=30.0,
        )

        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

        self._create_client()

    # ------------------------------------------------------------------
    # CLIENT
    # ------------------------------------------------------------------

    def _create_client(self) -> None:
        """
        Create the reusable HTTP client.

        HTTP/2 is intentionally not enabled. This avoids requiring the
        optional `h2` dependency on Railway while retaining HTTP keep-alive
        and connection pooling.
        """
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
                self._create_client()

        return self._client

    async def aclose(self) -> None:
        """
        Close the persistent HTTP client.

        This should only be called during application shutdown, not after
        every request or Celery task.
        """
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # CONFIGURATION
    # ------------------------------------------------------------------

    def _generation_model(self) -> str:
        return (
            getattr(settings, "GEMINI_MODEL", None)
            or getattr(settings, "AI_MODEL", None)
            or "gemini-2.5-flash"
        )

    def _embedding_model(self) -> str:
        return (
            getattr(settings, "GEMINI_EMBEDDING_MODEL", None)
            or "gemini-embedding-001"
        )

    # ------------------------------------------------------------------
    # RETRY HELPERS
    # ------------------------------------------------------------------

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

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        """
        Bounded retry delay.

        Attempt 1 -> 1 second
        Attempt 2 -> 2 seconds
        """
        return min(
            2.0,
            float(2 ** (attempt - 1)),
        )

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    async def _post_once(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Execute a single Gemini POST request."""
        client = await self._ensure_client()

        started = time.perf_counter()

        request_timeout = None

        if timeout is not None:
            request_timeout = httpx.Timeout(
                connect=10.0,
                read=timeout,
                write=20.0,
                pool=10.0,
            )

        try:
            response = await client.post(
                path,
                headers={
                    "x-goog-api-key": self.api_key,
                },
                json=payload,
                timeout=request_timeout,
            )

        except httpx.TimeoutException as exc:
            elapsed_ms = (
                time.perf_counter() - started
            ) * 1000

            logger.warning(
                "Gemini timeout: path=%s elapsed_ms=%.0f",
                path,
                elapsed_ms,
            )

            raise _TransientAIError(
                "Gemini request timed out."
            ) from exc

        except httpx.TransportError as exc:
            elapsed_ms = (
                time.perf_counter() - started
            ) * 1000

            logger.warning(
                "Gemini transport error: path=%s elapsed_ms=%.0f error=%s",
                path,
                elapsed_ms,
                exc,
            )

            raise _TransientAIError(
                "Gemini transport error."
            ) from exc

        elapsed_ms = (
            time.perf_counter() - started
        ) * 1000

        logger.info(
            "Gemini request completed: path=%s status=%s elapsed_ms=%.0f",
            path,
            response.status_code,
            elapsed_ms,
        )

        # Rate limit.
        if response.status_code == 429:
            retry_after = response.headers.get(
                "retry-after"
            )

            message = "Gemini rate limit exceeded."

            if retry_after:
                message += (
                    f" Retry-After: {retry_after}s."
                )

            raise _TransientAIError(message)

        # Other retryable HTTP failures.
        if self._is_retryable_status(
            response.status_code
        ):
            body = response.text[:500]

            logger.warning(
                "Gemini transient error: path=%s status=%s body=%s",
                path,
                response.status_code,
                body,
            )

            raise _TransientAIError(
                f"Gemini returned HTTP {response.status_code}."
            )

        # Permanent API failure.
        if response.status_code >= 400:
            body = response.text[:1000]

            logger.error(
                "Gemini API error: path=%s status=%s body=%s",
                path,
                response.status_code,
                body,
            )

            raise AIProviderError(
                f"Gemini API error ({response.status_code}): {body}",
                "gemini",
            )

        try:
            return response.json()

        except ValueError as exc:
            raise AIProviderError(
                "Gemini returned invalid JSON.",
                "gemini",
            ) from exc

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        Execute a Gemini request with bounded retries.

        We deliberately keep retries low because Telegram requests should
        not wait through multiple long retry cycles.
        """
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return await self._post_once(
                    path,
                    payload,
                    timeout=timeout,
                )

            except _TransientAIError as exc:
                last_error = exc

                if attempt >= MAX_RETRIES:
                    break

                delay = self._retry_delay(attempt)

                logger.warning(
                    "Retrying Gemini request: "
                    "path=%s attempt=%s/%s delay=%.1fs error=%s",
                    path,
                    attempt,
                    MAX_RETRIES,
                    delay,
                    exc,
                )

                await asyncio.sleep(delay)

        raise AIProviderError(
            "Gemini unavailable after retries.",
            "gemini",
        ) from last_error

    # ------------------------------------------------------------------
    # RESPONSE HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(
        response: dict[str, Any],
    ) -> str:
        """Extract generated text from Gemini response."""
        candidates = response.get(
            "candidates"
        ) or []

        if not candidates:
            raise AIProviderError(
                "Gemini returned no candidates.",
                "gemini",
            )

        content = candidates[0].get(
            "content"
        ) or {}

        parts = content.get("parts") or []

        texts: list[str] = []

        for part in parts:
            text = part.get("text")

            if isinstance(text, str) and text:
                texts.append(text)

        result = "\n".join(texts).strip()

        if not result:
            raise AIProviderError(
                "Gemini returned an empty response.",
                "gemini",
            )

        return result

    @staticmethod
    def _extract_function_calls(
        response: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Extract function calls from Gemini response."""
        candidates = response.get(
            "candidates"
        ) or []

        if not candidates:
            return []

        content = candidates[0].get(
            "content"
        ) or {}

        parts = content.get("parts") or []

        calls: list[dict[str, Any]] = []

        for part in parts:
            function_call = part.get(
                "functionCall"
            )

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
        """Generate text using Gemini."""
        model_name = (
            model
            or self._generation_model()
        )

        payload: dict[str, Any] = {
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
                "maxOutputTokens": max_output_tokens,
            },
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

        elapsed_ms = (
            time.perf_counter() - started
        ) * 1000

        logger.info(
            "Gemini generate completed: "
            "model=%s elapsed_ms=%.0f",
            model_name,
            elapsed_ms,
        )

        return result

    # ------------------------------------------------------------------
    # FUNCTION CALLING
    # ------------------------------------------------------------------

    async def generate_with_tools(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_executor: Callable[
            [str, dict[str, Any]],
            Awaitable[Any],
        ],
        system_instruction: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        **kwargs: Any,
    ) -> str:
        """Generate a response using Gemini function calling."""
        model_name = (
            model
            or self._generation_model()
        )

        contents = list(messages)

        function_declarations: list[
            dict[str, Any]
        ] = []

        for tool in tools:
            if "function" in tool:
                function_declarations.append(
                    tool["function"]
                )
            else:
                function_declarations.append(
                    tool
                )

        tool_definition = {
            "functionDeclarations":
                function_declarations,
        }

        for iteration in range(
            MAX_TOOL_ITERATIONS
        ):
            payload: dict[str, Any] = {
                "contents": contents,
                "tools": [
                    tool_definition,
                ],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens":
                        max_output_tokens,
                },
            }

            if system_instruction:
                payload["systemInstruction"] = {
                    "parts": [
                        {
                            "text":
                                system_instruction,
                        }
                    ]
                }

            response = await self._post(
                f"/models/{model_name}:generateContent",
                payload,
                timeout=DEFAULT_GENERATION_TIMEOUT,
            )

            function_calls = (
                self._extract_function_calls(
                    response
                )
            )

            if not function_calls:
                return self._extract_text(
                    response
                )

            candidates = response.get(
                "candidates"
            ) or []

            if not candidates:
                raise AIProviderError(
                    "Gemini returned no candidates during tool calling.",
                    "gemini",
                )

            model_content = candidates[0].get(
                "content"
            )

            if model_content:
                contents.append(
                    model_content
                )

            tool_response_parts: list[
                dict[str, Any]
            ] = []

            for function_call in function_calls:
                function_name = (
                    function_call.get("name")
                )

                function_args = (
                    function_call.get("args")
                    or {}
                )

                if not function_name:
                    continue

                logger.info(
                    "Gemini tool call: "
                    "tool=%s iteration=%s",
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
                        "Tool execution failed: tool=%s",
                        function_name,
                    )

                    result = {
                        "error": str(exc),
                    }

                tool_response_parts.append(
                    {
                        "functionResponse": {
                            "name":
                                function_name,
                            "response": {
                                "result":
                                    result,
                            },
                        }
                    }
                )

            if tool_response_parts:
                contents.append(
                    {
                        "role": "user",
                        "parts":
                            tool_response_parts,
                    }
                )

        logger.warning(
            "Gemini reached maximum tool iterations: max=%s",
            MAX_TOOL_ITERATIONS,
        )

        # Final response without another tool cycle.
        final_payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens":
                    max_output_tokens,
            },
        }

        if system_instruction:
            final_payload["systemInstruction"] = {
                "parts": [
                    {
                        "text":
                            system_instruction,
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
        """Generate one embedding."""
        embeddings = await self.embed_batch(
            [text],
            model=model,
            **kwargs,
        )

        if not embeddings:
            raise AIProviderError(
                "Gemini returned no embedding.",
                "gemini",
            )

        return embeddings[0]

    async def embed_batch(
        self,
        texts: list[str],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> list[list[float]]:
        """Generate embeddings using Gemini batch embedding."""
        if not texts:
            return []

        model_name = (
            model
            or self._embedding_model()
        )

        payload = {
            "requests": [
                {
                    "model":
                        f"models/{model_name}",
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
        }

        response = await self._post(
            f"/models/{model_name}:batchEmbedContents",
            payload,
            timeout=DEFAULT_EMBEDDING_TIMEOUT,
        )

        embeddings = response.get(
            "embeddings"
        ) or []

        results: list[list[float]] = []

        for item in embeddings:
            values = item.get("values")

            if not isinstance(values, list):
                raise AIProviderError(
                    "Gemini returned an invalid embedding.",
                    "gemini",
                )

            results.append(values)

        if len(results) != len(texts):
            raise AIProviderError(
                "Gemini returned an incomplete embedding batch.",
                "gemini",
            )

        return results

    # ------------------------------------------------------------------
    # IMAGE
    # ------------------------------------------------------------------

    async def describe_image(
        self,
        image_bytes: bytes,
        *,
        mime_type: str = "image/jpeg",
        prompt: str = (
            "Describe this image in detail."
        ),
        model: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Analyze an image using Gemini."""
        model_name = (
            model
            or self._generation_model()
        )

        encoded_image = base64.b64encode(
            image_bytes
        ).decode("utf-8")

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": prompt,
                        },
                        {
                            "inlineData": {
                                "mimeType":
                                    mime_type,
                                "data":
                                    encoded_image,
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 768,
            },
        }

        response = await self._post(
            f"/models/{model_name}:generateContent",
            payload,
            timeout=DEFAULT_IMAGE_TIMEOUT,
        )

        return self._extract_text(
            response
        )

    # ------------------------------------------------------------------
    # AUDIO
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
        """Transcribe audio using Gemini."""
        model_name = (
            model
            or self._generation_model()
        )

        encoded_audio = base64.b64encode(
            audio_bytes
        ).decode("utf-8")

        transcription_prompt = (
            prompt
            or (
                "Transcribe this audio exactly. "
                "Return only the spoken words. "
                "Do not add commentary."
            )
        )

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text":
                                transcription_prompt,
                        },
                        {
                            "inlineData": {
                                "mimeType":
                                    mime_type,
                                "data":
                                    encoded_audio,
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

        return self._extract_text(
            response
        )

    # ------------------------------------------------------------------
    # SUMMARIZE
    # ------------------------------------------------------------------

    async def summarize(
        self,
        text: str,
        *,
        model: str | None = None,
        max_output_tokens: int = 512,
        **kwargs: Any,
    ) -> str:
        """Summarize text with Gemini."""
        prompt = (
            "Summarize the following content clearly "
            "and accurately. Preserve the important "
            "facts and key points.\n\n"
            f"{text}"
        )

        return await self.generate(
            prompt=prompt,
            model=model,
            temperature=0.2,
            max_output_tokens=max_output_tokens,
        )

    # ------------------------------------------------------------------
    # CLASSIFY
    # ------------------------------------------------------------------

    async def classify(
        self,
        text: str,
        categories: list[str],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Classify text into one supplied category."""
        if not categories:
            raise AIProviderError(
                "Classification categories cannot be empty.",
                "gemini",
            )

        category_text = ", ".join(
            categories
        )

        prompt = (
            "Classify the following text into "
            "exactly one of these categories:\n"
            f"{category_text}\n\n"
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
    # HEALTH CHECK
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Check Gemini connectivity."""
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
