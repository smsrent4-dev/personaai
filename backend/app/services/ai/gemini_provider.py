"""Production Gemini AI provider.
This module is the only Gemini-specific layer in PersonaAI.
The rest of the application depends on ``AIProvider`` and must not know
anything about Gemini's REST API, request format, response format, or
authentication mechanism.
"""
from __future__ import annotations
import asyncio
import base64
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any
import httpx
from app.config import settings
from app.services.ai.base import AIProvider, ToolDefinition
from app.services.ai.exceptions import AIProviderError
logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# Gemini API configuration
# ---------------------------------------------------------------------------
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GENERATION_TIMEOUT = 35.0
DEFAULT_EMBEDDING_TIMEOUT = 20.0
DEFAULT_VISION_TIMEOUT = 35.0
DEFAULT_TRANSCRIPTION_TIMEOUT = 60.0
DEFAULT_TOOL_TIMEOUT = 35.0
DEFAULT_MAX_OUTPUT_TOKENS = 512
DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"
# Number of total attempts, not number of retries after the first attempt.
MAX_ATTEMPTS = 2
MAX_TOOL_ITERATIONS = 3
MAX_PROMPT_LENGTH = 1_000_000
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024
RETRYABLE_STATUS_CODES = frozenset(
    {
        408,
        429,
        500,
        502,
        503,
        504,
    }
)
# Never log API response bodies by default. They may contain user data.
MAX_ERROR_BODY_LENGTH = 500
class GeminiProvider(AIProvider):
    """Google Gemini implementation of the provider-agnostic AIProvider."""
    name = "gemini"
    def __init__(self) -> None:
        self.api_key = self._get_api_key()
        self.default_model = self._get_setting(
            "GEMINI_MODEL",
            "AI_GEMINI_MODEL",
            "AI_MODEL",
            default="gemini-2.5-flash",
        )
        self.embedding_model = self._get_setting(
            "GEMINI_EMBEDDING_MODEL",
            "AI_GEMINI_EMBEDDING_MODEL",
            default=DEFAULT_EMBEDDING_MODEL,
        )
        self._client = httpx.AsyncClient(
            base_url=GEMINI_API_BASE,
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(
                connect=10.0,
                read=DEFAULT_GENERATION_TIMEOUT,
                write=15.0,
                pool=10.0,
            ),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30.0,
            ),
            follow_redirects=False,
        )
    # =========================================================================
    # Configuration
    # =========================================================================
    @staticmethod
    def _get_setting(
        *names: str,
        default: Any = None,
    ) -> Any:
        """Return the first configured setting from the supplied names."""
        for name in names:
            value = getattr(settings, name, None)
            if value is not None:
                return value
        return default
    @classmethod
    def _get_api_key(cls) -> str:
        """Resolve the configured Gemini API key."""
        value = cls._get_setting(
            "GEMINI_API_KEY",
            "AI_GEMINI_API_KEY",
            "GOOGLE_GEMINI_API_KEY",
            "GOOGLE_API_KEY",
        )
        if value is None:
            raise AIProviderError(
                "Gemini API key is not configured.",
                "gemini",
            )
        api_key = str(value).strip()
        if not api_key:
            raise AIProviderError(
                "Gemini API key is empty.",
                "gemini",
            )
        return api_key
    # =========================================================================
    # Validation
    # =========================================================================
    @staticmethod
    def _require_text(
        value: str,
        field_name: str,
    ) -> str:
        """Validate a required textual input."""
        if not isinstance(value, str):
            raise AIProviderError(
                f"{field_name} must be a string.",
                "gemini",
            )
        if not value.strip():
            raise AIProviderError(
                f"{field_name} cannot be empty.",
                "gemini",
            )
        if len(value) > MAX_PROMPT_LENGTH:
            raise AIProviderError(
                f"{field_name} exceeds the maximum allowed length.",
                "gemini",
            )
        return value
    @staticmethod
    def _validate_temperature(temperature: float) -> float:
        try:
            value = float(temperature)
        except (TypeError, ValueError) as exc:
            raise AIProviderError(
                "temperature must be a number.",
                "gemini",
            ) from exc
        if not 0.0 <= value <= 2.0:
            raise AIProviderError(
                "temperature must be between 0.0 and 2.0.",
                "gemini",
            )
        return value
    @staticmethod
    def _validate_max_tokens(max_tokens: int | None) -> int | None:
        if max_tokens is None:
            return None
        try:
            value = int(max_tokens)
        except (TypeError, ValueError) as exc:
            raise AIProviderError(
                "max_tokens must be an integer.",
                "gemini",
            ) from exc
        if value <= 0:
            raise AIProviderError(
                "max_tokens must be greater than zero.",
                "gemini",
            )
        return value
    @staticmethod
    def _validate_mime_type(mime_type: str) -> str:
        if not isinstance(mime_type, str) or not mime_type.strip():
            raise AIProviderError(
                "mime_type must be a non-empty string.",
                "gemini",
            )
        value = mime_type.strip().lower()
        if "/" not in value:
            raise AIProviderError(
                f"Invalid MIME type '{mime_type}'.",
                "gemini",
            )
        return value
    # =========================================================================
    # HTTP
    # =========================================================================
    @staticmethod
    def _retry_delay(
        attempt: int,
        retry_after: str | None = None,
    ) -> float:
        """Return a bounded retry delay.
        Prefer Google's Retry-After header when it contains a sane value.
        Otherwise use short exponential backoff with jitter.
        """
        if retry_after:
            try:
                delay = float(retry_after)
                if 0.0 <= delay <= 10.0:
                    return delay
            except (TypeError, ValueError):
                pass
        base = min(0.75 * (2 ** (attempt - 1)), 4.0)
        # Small jitter prevents synchronized worker retries.
        return min(base + random.uniform(0.0, 0.25), 5.0)
    @staticmethod
    def _safe_error_body(response: httpx.Response) -> str:
        """Extract a small, non-sensitive error description."""
        try:
            data = response.json()
            if isinstance(data, dict):
                error = data.get("error")
                if isinstance(error, dict):
                    message = error.get("message")
                    if isinstance(message, str):
                        return message[:MAX_ERROR_BODY_LENGTH]
                message = data.get("message")
                if isinstance(message, str):
                    return message[:MAX_ERROR_BODY_LENGTH]
        except (ValueError, json.JSONDecodeError):
            pass
        return response.text[:MAX_ERROR_BODY_LENGTH]
    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        """Execute a Gemini POST request with bounded transient retries."""
        last_exception: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.perf_counter()
            try:
                response = await self._client.post(
                    path,
                    json=payload,
                    timeout=httpx.Timeout(
                        connect=10.0,
                        read=timeout,
                        write=15.0,
                        pool=10.0,
                    ),
                )
                elapsed_ms = (time.perf_counter() - started) * 1000
                if response.status_code in RETRYABLE_STATUS_CODES:
                    if attempt < MAX_ATTEMPTS:
                        delay = self._retry_delay(
                            attempt,
                            response.headers.get("Retry-After"),
                        )
                        logger.warning(
                            "Gemini transient HTTP error "
                            "status=%s attempt=%s/%s elapsed_ms=%.2f "
                            "retry_in=%.2f",
                            response.status_code,
                            attempt,
                            MAX_ATTEMPTS,
                            elapsed_ms,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    error_message = self._safe_error_body(response)
                    raise AIProviderError(
                        (
                            f"Gemini request failed with HTTP "
                            f"{response.status_code} after "
                            f"{attempt} attempts: {error_message}"
                        ),
                        "gemini",
                    )
                if response.status_code >= 400:
                    error_message = self._safe_error_body(response)
                    raise AIProviderError(
                        (
                            f"Gemini request failed with HTTP "
                            f"{response.status_code}: {error_message}"
                        ),
                        "gemini",
                    )
                try:
                    data = response.json()
                except (ValueError, json.JSONDecodeError) as exc:
                    raise AIProviderError(
                        "Gemini returned invalid JSON.",
                        "gemini",
                    ) from exc
                if not isinstance(data, dict):
                    raise AIProviderError(
                        "Gemini returned an invalid response object.",
                        "gemini",
                    )
                logger.debug(
                    "Gemini request completed path=%s "
                    "status=%s elapsed_ms=%.2f",
                    path,
                    response.status_code,
                    elapsed_ms,
                )
                return data
            except AIProviderError:
                raise
            except (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
                httpx.TransportError,
            ) as exc:
                last_exception = exc
                elapsed_ms = (time.perf_counter() - started) * 1000
                if attempt < MAX_ATTEMPTS:
                    delay = self._retry_delay(attempt)
                    logger.warning(
                        "Gemini transport error "
                        "attempt=%s/%s elapsed_ms=%.2f "
                        "retry_in=%.2f error=%s",
                        attempt,
                        MAX_ATTEMPTS,
                        elapsed_ms,
                        delay,
                        type(exc).__name__,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise AIProviderError(
                    (
                        "Gemini request failed after "
                        f"{attempt} attempts "
                        f"({elapsed_ms:.0f}ms): "
                        f"{type(exc).__name__}"
                    ),
                    "gemini",
                ) from exc
        raise AIProviderError(
            f"Gemini request failed: {type(last_exception).__name__ if last_exception else 'unknown error'}",
            "gemini",
        )
    # =========================================================================
    # Response parsing
    # =========================================================================
    @staticmethod
    def _extract_candidates(
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        candidates = data.get("candidates")
        if not isinstance(candidates, list):
            return []
        return [
            candidate
            for candidate in candidates
            if isinstance(candidate, dict)
        ]
    @classmethod
    def _extract_text(
        cls,
        data: dict[str, Any],
    ) -> str:
        """Extract text from a Gemini generateContent response."""
        candidates = cls._extract_candidates(data)
        if not candidates:
            prompt_feedback = data.get("promptFeedback")
            raise AIProviderError(
                f"Gemini returned no candidates: {prompt_feedback}",
                "gemini",
            )
        text_parts: list[str] = []
        for candidate in candidates:
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            parts = content.get("parts")
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text:
                    text_parts.append(text)
        result = "".join(text_parts).strip()
        if result:
            return result
        finish_reasons = [
            candidate.get("finishReason")
            for candidate in candidates
            if candidate.get("finishReason")
        ]
        raise AIProviderError(
            (
                "Gemini returned no text content. "
                f"finishReason={finish_reasons or None}"
            ),
            "gemini",
        )
    @staticmethod
    def _extract_content(
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return None
        content = candidates[0].get("content")
        return content if isinstance(content, dict) else None
    @classmethod
    def _extract_function_calls(
        cls,
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Extract Gemini functionCall parts."""
        calls: list[dict[str, Any]] = []
        for candidate in cls._extract_candidates(data):
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            parts = content.get("parts")
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                function_call = part.get("functionCall")
                if not isinstance(function_call, dict):
                    continue
                name = function_call.get("name")
                if not isinstance(name, str) or not name:
                    continue
                arguments = function_call.get("args")
                if not isinstance(arguments, dict):
                    arguments = {}
                calls.append(
                    {
                        "name": name,
                        "arguments": arguments,
                    }
                )
        return calls
    # =========================================================================
    # Generation
    # =========================================================================
    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        """Generate free-form text.
        This signature intentionally matches AIProvider exactly.
        ``model`` and the legacy ``max_output_tokens`` keyword are accepted
        through kwargs for backward compatibility without changing the
        provider abstraction.
        """
        prompt = self._require_text(prompt, "prompt")
        if system_instruction is not None:
            system_instruction = self._require_text(
                system_instruction,
                "system_instruction",
            )
        temperature = self._validate_temperature(temperature)
        max_tokens = self._validate_max_tokens(max_tokens)
        model = kwargs.get("model") or self.default_model
        if not isinstance(model, str) or not model.strip():
            raise AIProviderError(
                "Gemini model is not configured.",
                "gemini",
            )
        if max_tokens is None:
            legacy_max_tokens = kwargs.get("max_output_tokens")
            if legacy_max_tokens is not None:
                max_tokens = self._validate_max_tokens(
                    legacy_max_tokens,
                )
        if max_tokens is None:
            max_tokens = DEFAULT_MAX_OUTPUT_TOKENS
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
                "maxOutputTokens": max_tokens,
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
        data = await self._post(
            f"/models/{model}:generateContent",
            payload,
            timeout=DEFAULT_GENERATION_TIMEOUT,
        )
        return self._extract_text(data)
    # =========================================================================
    # Embeddings
    # =========================================================================
    async def embed(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Generate one embedding vector per input string."""
        if not isinstance(texts, list):
            raise AIProviderError(
                "texts must be a list.",
                "gemini",
            )
        if not texts:
            return []
        for index, text in enumerate(texts):
            self._require_text(
                text,
                f"texts[{index}]",
            )
        requests = [
            {
                "model": f"models/{self.embedding_model}",
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
        data = await self._post(
            f"/models/{self.embedding_model}:batchEmbedContents",
            {
                "requests": requests,
            },
            timeout=DEFAULT_EMBEDDING_TIMEOUT,
        )
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list):
            raise AIProviderError(
                "Gemini returned no embeddings.",
                "gemini",
            )
        result: list[list[float]] = []
        for index, item in enumerate(embeddings):
            if not isinstance(item, dict):
                raise AIProviderError(
                    f"Gemini returned an invalid embedding at index {index}.",
                    "gemini",
                )
            values = item.get("values")
            if not isinstance(values, list) or not values:
                raise AIProviderError(
                    f"Gemini returned an empty embedding at index {index}.",
                    "gemini",
                )
            try:
                vector = [float(value) for value in values]
            except (TypeError, ValueError) as exc:
                raise AIProviderError(
                    f"Gemini returned an invalid embedding at index {index}.",
                    "gemini",
                ) from exc
            result.append(vector)
        if len(result) != len(texts):
            raise AIProviderError(
                (
                    f"Gemini returned {len(result)} embeddings for "
                    f"{len(texts)} inputs."
                ),
                "gemini",
            )
        return result
    # =========================================================================
    # Summarization
    # =========================================================================
    async def summarize(
        self,
        text: str,
        max_words: int | None = None,
    ) -> str:
        """Summarize text using Gemini."""
        text = self._require_text(text, "text")
        if max_words is None:
            word_limit = 150
        else:
            try:
                word_limit = int(max_words)
            except (TypeError, ValueError) as exc:
                raise AIProviderError(
                    "max_words must be an integer.",
                    "gemini",
                ) from exc
            if word_limit <= 0:
                raise AIProviderError(
                    "max_words must be greater than zero.",
                    "gemini",
                )
        prompt = (
            "Summarize the following text clearly and accurately. "
            f"Keep the summary within approximately {word_limit} words. "
            "Preserve important facts, names, numbers, decisions, and "
            "actionable information.\n\n"
            "TEXT:\n"
            f"{text}"
        )
        return await self.generate(
            prompt,
            temperature=0.2,
            max_tokens=min(max(word_limit * 2, 128), 768),
        )
    # =========================================================================
    # Classification
    # =========================================================================
    async def classify(
        self,
        text: str,
        labels: list[str],
    ) -> str:
        """Classify text into exactly one supplied label."""
        text = self._require_text(text, "text")
        if not labels:
            raise AIProviderError(
                "Classification requires at least one label.",
                "gemini",
            )
        clean_labels: list[str] = []
        for label in labels:
            if not isinstance(label, str) or not label.strip():
                raise AIProviderError(
                    "Classification labels must be non-empty strings.",
                    "gemini",
                )
            clean_labels.append(label)
        label_text = "\n".join(
            f"- {label}"
            for label in clean_labels
        )
        prompt = (
            "Classify the input into exactly one of the allowed labels.\n\n"
            "ALLOWED LABELS:\n"
            f"{label_text}\n\n"
            "INPUT:\n"
            f"{text}\n\n"
            "Return only the exact label. Do not explain your answer."
        )
        result = await self.generate(
            prompt,
            temperature=0.0,
            max_tokens=32,
        )
        normalized = result.strip()
        for label in clean_labels:
            if normalized == label:
                return label
        lowered = normalized.casefold()
        for label in clean_labels:
            if lowered == label.casefold():
                return label
        raise AIProviderError(
            (
                f"Gemini returned invalid classification "
                f"'{normalized}'."
            ),
            "gemini",
        )
    # =========================================================================
    # Vision
    # =========================================================================
    async def describe_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        instruction: str | None = None,
    ) -> str:
        """Analyze an image using Gemini multimodal generation."""
        if not image_bytes:
            raise AIProviderError(
                "Cannot analyze an empty image.",
                "gemini",
            )
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise AIProviderError(
                "Image exceeds the maximum supported size.",
                "gemini",
            )
        mime_type = self._validate_mime_type(mime_type)
        if instruction is not None:
            instruction = self._require_text(
                instruction,
                "instruction",
            )
        prompt = instruction or (
            "Analyze this image carefully and describe the relevant "
            "information clearly. If it contains text, transcribe the "
            "important text accurately. Do not invent information that "
            "cannot be established from the image."
        )
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
                                "mimeType": mime_type,
                                "data": base64.b64encode(
                                    image_bytes,
                                ).decode("ascii"),
                            },
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": DEFAULT_MAX_OUTPUT_TOKENS,
            },
        }
        data = await self._post(
            f"/models/{self.default_model}:generateContent",
            payload,
            timeout=DEFAULT_VISION_TIMEOUT,
        )
        return self._extract_text(data)
    # =========================================================================
    # Audio
    # =========================================================================
    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        mime_type: str,
    ) -> str:
        """Transcribe audio using Gemini multimodal generation."""
        if not audio_bytes:
            raise AIProviderError(
                "Cannot transcribe empty audio.",
                "gemini",
            )
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            raise AIProviderError(
                "Audio exceeds the maximum supported size.",
                "gemini",
            )
        mime_type = self._validate_mime_type(mime_type)
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                "Transcribe this audio accurately. "
                                "Return only the spoken transcription. "
                                "Do not summarize, interpret, or add commentary."
                            ),
                        },
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": base64.b64encode(
                                    audio_bytes,
                                ).decode("ascii"),
                            },
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 1024,
            },
        }
        data = await self._post(
            f"/models/{self.default_model}:generateContent",
            payload,
            timeout=DEFAULT_TRANSCRIPTION_TIMEOUT,
        )
        return self._extract_text(data)
    # =========================================================================
    # Function calling
    # =========================================================================
    async def generate_with_tools(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        tool_executor: Callable[[str, dict], Awaitable[dict]],
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tool_iterations: int = 3,
    ) -> str:
        """Execute Gemini's native function-calling loop."""
        prompt = self._require_text(prompt, "prompt")
        temperature = self._validate_temperature(temperature)
        if not tools:
            return await self.generate(
                prompt,
                system_instruction=system_instruction,
                temperature=temperature,
            )
        if max_tool_iterations <= 0:
            raise AIProviderError(
                "max_tool_iterations must be greater than zero.",
                "gemini",
            )
        iterations = min(
            int(max_tool_iterations),
            MAX_TOOL_ITERATIONS,
        )
        function_declarations: list[dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, ToolDefinition):
                raise AIProviderError(
                    "All tools must be ToolDefinition instances.",
                    "gemini",
                )
            if not tool.name.strip():
                raise AIProviderError(
                    "Tool name cannot be empty.",
                    "gemini",
                )
            function_declarations.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            )
        tool_names = {
            tool.name
            for tool in tools
        }
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
        payload: dict[str, Any] = {
            "contents": contents,
            "tools": [
                {
                    "functionDeclarations": function_declarations,
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": DEFAULT_MAX_OUTPUT_TOKENS,
            },
        }
        if system_instruction:
            system_instruction = self._require_text(
                system_instruction,
                "system_instruction",
            )
            payload["systemInstruction"] = {
                "parts": [
                    {
                        "text": system_instruction,
                    }
                ]
            }
        for iteration in range(iterations):
            data = await self._post(
                f"/models/{self.default_model}:generateContent",
                payload,
                timeout=DEFAULT_TOOL_TIMEOUT,
            )
            function_calls = self._extract_function_calls(data)
            if not function_calls:
                return self._extract_text(data)
            model_content = self._extract_content(data)
            if model_content is None:
                raise AIProviderError(
                    "Gemini returned a function call without content.",
                    "gemini",
                )
            contents.append(model_content)
            function_response_parts: list[dict[str, Any]] = []
            for call in function_calls:
                name = call["name"]
                arguments = call["arguments"]
                if name not in tool_names:
                    result: dict[str, Any] = {
                        "success": False,
                        "error": f"Unknown tool '{name}'.",
                    }
                else:
                    try:
                        result = await tool_executor(
                            name,
                            arguments,
                        )
                        if not isinstance(result, dict):
                            result = {
                                "success": True,
                                "result": result,
                            }
                    except Exception:
                        logger.exception(
                            "Gemini tool execution failed tool=%s "
                            "iteration=%s",
                            name,
                            iteration + 1,
                        )
                        result = {
                            "success": False,
                            "error": "Tool execution failed.",
                        }
                function_response_parts.append(
                    {
                        "functionResponse": {
                            "name": name,
                            "response": result,
                        }
                    }
                )
            contents.append(
                {
                    "role": "user",
                    "parts": function_response_parts,
                }
            )
        # Tool-call limit reached. One final model request is allowed so the
        # user gets a useful answer instead of an internal iteration error.
        payload.pop("tools", None)
        final_data = await self._post(
            f"/models/{self.default_model}:generateContent",
            payload,
            timeout=DEFAULT_TOOL_TIMEOUT,
        )
        return self._extract_text(final_data)
    # =========================================================================
    # Lifecycle
    # =========================================================================
    async def aclose(self) -> None:
        """Close the persistent HTTP client.
        Called once during application/worker shutdown, not once per request.
        """
        if not self._client.is_closed:
            await self._client.aclose()
    async def close(self) -> None:
        """Backward-compatible lifecycle alias."""
        await self.aclose()
    async def __aenter__(self) -> GeminiProvider:
        return self
    async def __aexit__(
        self,
        exc_type: Any,
        exc_value: Any,
        traceback: Any,
    ) -> None:
        await self.aclose()
