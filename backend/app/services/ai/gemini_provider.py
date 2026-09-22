"""Google Gemini implementation of AIProvider.

Talks to the Google Gemini REST API directly over httpx.

Supports:
- Text generation
- Text embeddings
- Image understanding
- Audio transcription
- Text summarization
- Text classification
- Gemini function/tool calling
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

GEMINI_EMBEDDING_DIMENSION = 768

DEFAULT_GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"

RETIRED_EMBEDDING_MODELS = {
    "text-embedding-004",
    "models/text-embedding-004",
}

DEFAULT_MAX_RETRIES = 3

DEFAULT_INITIAL_RETRY_DELAY = 1.0

DEFAULT_MAX_RETRY_DELAY = 8.0

RETRYABLE_STATUS_CODES = {
    408,
    429,
    500,
    502,
    503,
    504,
}


class _TransientAIError(Exception):
    """Internal marker for a transient Gemini failure."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
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
    ) -> None:
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

        self.timeout = timeout

        self.max_retries = DEFAULT_MAX_RETRIES

        self.initial_retry_delay = DEFAULT_INITIAL_RETRY_DELAY

        self.max_retry_delay = DEFAULT_MAX_RETRY_DELAY

        self._client = httpx.AsyncClient(
            base_url=GEMINI_API_BASE,
            timeout=httpx.Timeout(
                connect=min(timeout, 10.0),
                read=timeout,
                write=timeout,
                pool=timeout,
            ),
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
            ),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        if not self.api_key:
            logger.warning(
                "GeminiProvider initialized without an API key. "
                "Requests will fail until GEMINI_API_KEY is configured."
            )

        logger.info(
            "GeminiProvider initialized: "
            "model=%s embedding_model=%s embedding_dimension=%s",
            self.model,
            self.embedding_model,
            GEMINI_EMBEDDING_DIMENSION,
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

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""

        if not self._client.is_closed:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Retry helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        """Read a Retry-After response header when available."""

        value = response.headers.get("retry-after")

        if not value:
            return None

        try:
            delay = float(value)
        except (TypeError, ValueError):
            return None

        if delay < 0:
            return None

        return min(delay, 30.0)

    def _calculate_retry_delay(
        self,
        attempt: int,
        retry_after: float | None = None,
    ) -> float:
        """Calculate exponential backoff with bounded jitter."""

        if retry_after is not None:
            return retry_after

        exponential_delay = self.initial_retry_delay * (
            2 ** max(attempt - 1, 0)
        )

        bounded_delay = min(
            exponential_delay,
            self.max_retry_delay,
        )

        jitter = random.uniform(0.0, 1.0)

        return min(
            bounded_delay + jitter,
            self.max_retry_delay + 1.0,
        )

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        """Return whether an HTTP status represents a transient failure."""

        return status_code in RETRYABLE_STATUS_CODES

    async def _wait_before_retry(
        self,
        attempt: int,
        *,
        retry_after: float | None = None,
    ) -> None:
        """Wait before a transient request retry."""

        delay = self._calculate_retry_delay(
            attempt,
            retry_after=retry_after,
        )

        logger.warning(
            "Retrying Gemini request: attempt=%s/%s delay=%.2fs",
            attempt,
            self.max_retries,
            delay,
        )

        await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # HTTP transport
    # ------------------------------------------------------------------

    async def _post(
        self,
        path: str,
        json_body: dict[str, Any],
    ) -> dict[str, Any]:
        """POST JSON to Gemini with bounded transient-error retries."""

        if not self.api_key:
            raise AIAuthenticationError(
                "Gemini API key is missing",
                self.name,
            )

        last_transient_error: _TransientAIError | None = None

        for attempt in range(1, self.max_retries + 2):
            try:
                response = await self._client.post(
                    path,
                    headers={
                        "x-goog-api-key": self.api_key,
                    },
                    json=json_body,
                )

            except httpx.TimeoutException as exc:
                last_transient_error = _TransientAIError(
                    f"Gemini request timed out: {exc}",
                )

                if attempt > self.max_retries:
                    break

                await self._wait_before_retry(attempt)

                continue

            except httpx.TransportError as exc:
                last_transient_error = _TransientAIError(
                    f"Gemini transport error: {exc}",
                )

                if attempt > self.max_retries:
                    break

                await self._wait_before_retry(attempt)

                continue

            status_code = response.status_code

            if status_code in (401, 403):
                raise AIAuthenticationError(
                    "Invalid or unauthorized Gemini API key",
                    self.name,
                )

            if self._is_retryable_status(status_code):
                retry_after = self._retry_after(response)

                transient_error = _TransientAIError(
                    f"Gemini returned {status_code}: "
                    f"{response.text}",
                    status_code=status_code,
                    retry_after=retry_after,
                )

                last_transient_error = transient_error

                if attempt > self.max_retries:
                    break

                logger.warning(
                    "Gemini transient HTTP error: "
                    "status=%s attempt=%s/%s",
                    status_code,
                    attempt,
                    self.max_retries + 1,
                )

                await self._wait_before_retry(
                    attempt,
                    retry_after=retry_after,
                )

                continue

            if status_code >= 400:
                raise AIProviderError(
                    f"Gemini request failed ({status_code}): "
                    f"{response.text}",
                    self.name,
                )

            try:
                data = response.json()

            except ValueError as exc:
                raise AIProviderError(
                    f"Gemini returned invalid JSON: "
                    f"{response.text}",
                    self.name,
                    exc,
                ) from exc

            if not isinstance(data, dict):
                raise AIProviderError(
                    "Gemini returned an invalid response object",
                    self.name,
                )

            return data

        if last_transient_error is not None:
            if last_transient_error.status_code == 429:
                raise AIRateLimitError(
                    "Gemini rate limit exceeded after retries",
                    self.name,
                )

            raise last_transient_error

        raise AIProviderError(
            "Gemini request failed without a response",
            self.name,
        )

    # ------------------------------------------------------------------
    # Response extraction
    # ------------------------------------------------------------------

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

            candidate = candidates[0]

            content = candidate["content"]

            parts = content["parts"]

            if not isinstance(parts, list):
                raise AIProviderError(
                    f"Gemini returned invalid parts: {parts}",
                    "gemini",
                )

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
            body["generationConfig"]["maxOutputTokens"] = (
                max_tokens
            )

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
            )

        except _TransientAIError as exc:
            raise AIProviderError(
                "Gemini embedding service unavailable "
                "after retries",
                self.name,
                exc,
            ) from exc

        try:
            embeddings = data["embeddings"]

        except (KeyError, TypeError) as exc:
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
                "Gemini returned a different number of "
                "embeddings than inputs. "
                f"inputs={len(clean_texts)}, "
                f"embeddings={len(embeddings)}",
                self.name,
            )

        vectors: list[list[float]] = []

        for index, item in enumerate(embeddings):
            if not isinstance(item, dict):
                raise AIProviderError(
                    f"Gemini embedding #{index} returned "
                    f"an invalid response: {item}",
                    self.name,
                )

            values = item.get("values")

            if not isinstance(values, list):
                raise AIProviderError(
                    f"Gemini embedding #{index} returned "
                    f"invalid values: {values}",
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
            "Classify the following text into exactly one "
            "of these categories. Respond with only the "
            "category name, exactly as written below, and "
            "nothing else.\n\n"
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

        normalized_mime_type = mime_type.strip().lower()

        if not normalized_mime_type:
            raise AIProviderError(
                "describe_image() requires a MIME type",
                self.name,
            )

        supported_image_types = {
            "image/jpeg",
            "image/png",
            "image/webp",
            "image/heic",
            "image/heif",
        }

        if normalized_mime_type not in supported_image_types:
            raise AIProviderError(
                f"Unsupported image MIME type: "
                f"{normalized_mime_type}",
                self.name,
            )

        prompt_text = instruction or (
            "Analyze this image carefully. Describe what is visible "
            "and extract any useful information. If the image "
            "contains text, numbers, dates, amounts, names, "
            "reference numbers, transaction IDs, labels, "
            "documents, screenshots, products, packaging, "
            "clothing, or interface elements, reproduce the "
            "relevant information accurately. Do not invent "
            "information that is not visible."
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
                                "mimeType": normalized_mime_type,
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

        logger.info(
            "Sending image to Gemini: "
            "mime_type=%s bytes=%s model=%s",
            normalized_mime_type,
            len(image_bytes),
            self.model,
        )

        try:
            data = await self._post(
                f"/models/{self.model}:generateContent",
                body,
            )

        except _TransientAIError as exc:
            raise AIProviderError(
                "Gemini image analysis unavailable "
                "after retries",
                self.name,
                exc,
            ) from exc

        result = self._extract_text(data)

        logger.info(
            "Gemini image analysis completed: characters=%s",
            len(result),
        )

        return result

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

        normalized_mime_type = mime_type.strip().lower()

        if not normalized_mime_type:
            raise AIProviderError(
                "transcribe_audio() requires a MIME type",
                self.name,
            )

        encoded_audio = base64.b64encode(
            audio_bytes
        ).decode("ascii")

        prompt_text = (
            "Transcribe the speech in this audio clip accurately. "
            "Preserve the speaker's original language and wording. "
            "Do not translate, summarize, explain, or add commentary. "
            "Output only the transcription."
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
                            "inlineData": {
                                "mimeType": normalized_mime_type,
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

        logger.info(
            "Sending audio to Gemini for transcription: "
            "mime_type=%s bytes=%s model=%s",
            normalized_mime_type,
            len(audio_bytes),
            self.model,
        )

        try:
            data = await self._post(
                f"/models/{self.model}:generateContent",
                body,
            )

        except _TransientAIError as exc:
            raise AIProviderError(
                "Gemini audio transcription unavailable "
                "after retries",
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
        max_tool_iterations: int = 5,
    ) -> str:
        """Generate a response using Gemini REST function calling."""

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
            "\n\nAfter calling tools and receiving their "
            "results, synthesize the findings into a clear "
            "final text answer for the user. Do not expose "
            "internal tool execution details unless they "
            "are relevant to the user's request."
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
                )

            except _TransientAIError as exc:
                raise AIProviderError(
                    "Gemini tool-calling service "
                    "unavailable after retries",
                    self.name,
                    exc,
                ) from exc

            parts = self._extract_candidate_parts(data)

            function_calls = self._extract_function_calls(parts)

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
                    str(call.get("name", "<unknown>"))
                    for call in function_calls
                ),
            )

            contents.append(
                {
                    "role": "model",
                    "parts": parts,
                }
            )

            function_response_parts: list[dict[str, Any]] = []

            for function_call in function_calls:
                tool_name = function_call.get("name")

                tool_args = (
                    function_call.get("args") or {}
                )

                tool_call_id = function_call.get("id")

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
                        "Executing Gemini tool "
                        "name=%s id=%s",
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
                            "Please provide the best possible "
                            "final answer based on the tool "
                            "calls and results executed so far. "
                            "Do not call any more tools."
                        ),
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
                "Gemini unavailable after retries while "
                "forcing a final tool-calling response",
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
