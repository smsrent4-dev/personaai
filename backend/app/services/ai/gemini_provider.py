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
"""

import base64
import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

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

# Gemini's current embedding model.
DEFAULT_GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"

# text-embedding-004 is retired and must never be sent to Gemini.
RETIRED_EMBEDDING_MODELS = {
    "text-embedding-004",
    "models/text-embedding-004",
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
        timeout: float = 30.0,
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
            timeout=timeout,
        )

        if not self.api_key:
            logger.warning(
                "GeminiProvider initialized without an API key — "
                "requests will fail until GEMINI_API_KEY is set."
            )

        logger.info(
            "GeminiProvider initialized: model=%s embedding_model=%s "
            "embedding_dimension=%s",
            self.model,
            self.embedding_model,
            GEMINI_EMBEDDING_DIMENSION,
        )

    # -----------------------------------------------------------------------
    # Model helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _clean_model_name(model: str) -> str:
        """Remove an optional leading 'models/' prefix.

        Internally this provider stores model names without the REST resource
        prefix and adds it only where the Gemini API requires it.
        """
        return model.strip().removeprefix("models/")

    @classmethod
    def _normalize_embedding_model(cls, model: str) -> str:
        """Normalize and protect against the retired text-embedding-004.

        Older .env/config values may still contain text-embedding-004.
        Rather than allowing that stale configuration to produce a 404,
        automatically migrate it to gemini-embedding-001.
        """
        clean_model = cls._clean_model_name(model)

        if clean_model in {
            "text-embedding-004",
            "models/text-embedding-004",
        }:
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
    # HTTP transport
    # -----------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(_TransientAIError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(
            multiplier=1,
            min=1,
            max=8,
        ),
        reraise=True,
    )
    async def _post(
        self,
        path: str,
        json_body: dict[str, Any],
    ) -> dict[str, Any]:
        """POST JSON to Gemini with retry handling for transient failures."""

        try:
            response = await self._client.post(
                path,
                params={"key": self.api_key},
                json=json_body,
            )

        except httpx.TimeoutException as exc:
            raise _TransientAIError(
                f"Gemini request timed out: {exc}"
            ) from exc

        except httpx.TransportError as exc:
            raise _TransientAIError(
                f"Gemini transport error: {exc}"
            ) from exc

        if response.status_code in (401, 403):
            raise AIAuthenticationError(
                "Invalid or missing Gemini API key",
                self.name,
            )

        if response.status_code == 429:
            raise AIRateLimitError(
                "Gemini rate limit exceeded",
                self.name,
            )

        if 500 <= response.status_code < 600:
            raise _TransientAIError(
                f"Gemini returned {response.status_code}: {response.text}"
            )

        if response.status_code >= 400:
            raise AIProviderError(
                f"Gemini request failed ({response.status_code}): "
                f"{response.text}",
                self.name,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise AIProviderError(
                f"Gemini returned invalid JSON: {response.text}",
                self.name,
                exc,
            ) from exc

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
            if isinstance(part, dict)
            and "functionCall" in part
            and isinstance(part["functionCall"], dict)
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
                "Gemini unavailable after retries",
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
        """Generate 768-dimensional embeddings for multiple texts.

        Uses Gemini's batchEmbedContents endpoint with
        gemini-embedding-001.

        PersonaAI uses Vector(768), so outputDimensionality is explicitly
        set to 768 on every embedding request.

        The model is also normalized here so stale configuration containing
        'models/' or the retired 'text-embedding-004' cannot produce the
        previous 404 error.
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

        # Keep the provider's runtime value synchronized in case the model
        # was normalized from an older configuration value.
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
            "Generating %s Gemini embeddings using model=%s dimension=%s",
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
                "Gemini unavailable after retries",
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
        """Analyze an image using Gemini multimodal generation.

        The image is sent as inline base64 data.

        Gemini inline image data is intended for reasonably sized payloads.
        Larger files should use the Gemini Files API instead.
        """

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

        The model may execute multiple tools in one response and may
        perform several sequential tool-calling iterations.
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
                    "Gemini unavailable after retries",
                    self.name,
                    exc,
                ) from exc

            parts = self._extract_candidate_parts(data)

            function_calls = self._extract_function_calls(parts)

            # ---------------------------------------------------------------
            # Gemini returned a normal text response.
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
            # Preserve the complete model response exactly as Gemini sent it.
            #
            # This is especially important for Gemini models that return
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

                # Preserve the call ID when Gemini supplies one.
                if tool_call_id:
                    function_response["id"] = tool_call_id

                function_response_parts.append(
                    {
                        "functionResponse": function_response,
                    }
                )

            # ---------------------------------------------------------------
            # Send all tool results back together.
            #
            # We preserve the same role behavior already used by the
            # existing PersonaAI implementation.
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
            fallback_data = await self._post(
                f"/models/{self.model}:generateContent",
                forced_body,
            )

            return self._extract_text(fallback_data)

        except _TransientAIError as exc:
            raise AIProviderError(
                "Gemini unavailable after retries while forcing "
                "a final tool-calling response",
                self.name,
                exc,
            ) from exc

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
