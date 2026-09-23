"""
Gemini implementation of AIProvider.
This is the only file in the codebase that should import google.genai.
Everything else talks to the AIProvider interface in app/ai/base.py.
"""
import json
from google import genai
from google.genai import types
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from app.ai.base import (
    AIProvider,
    EmbeddingResult,
    GenerationResult,
    ImageGenerationResult,
    MediaInput,
    Message,
    StructuredResult,
)
from app.core.config import settings
from app.core.logging import get_logger
logger = get_logger(__name__)
_RETRYABLE_EXCEPTIONS = (
    TimeoutError,
    ConnectionError,
)
# Gemini native image-generation model.
#
# This is intentionally separate from settings.gemini_model.
# Your normal/routine Gemini model is still used for:
# - text generation
# - structured generation
# - media understanding
#
# Image generation uses this model only.
_GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"
def _to_gemini_contents(
    messages: list[Message],
) -> list[types.Content]:
    """
    Convert application Message objects into
    Gemini Content objects.
    """
    contents: list[types.Content] = []
    for message in messages:
        role = (
            "model"
            if message.role == "assistant"
            else "user"
        )
        contents.append(
            types.Content(
                role=role,
                parts=[
                    types.Part.from_text(
                        text=message.content,
                    )
                ],
            )
        )
    return contents
class GeminiProvider(AIProvider):
    """
    Gemini implementation of the AIProvider interface.
    Supports:
    - Text generation
    - Structured JSON generation
    - Image/document/audio understanding
    - Text embeddings
    - Image generation
    Only this file should import google.genai.
    """
    def __init__(
        self,
        api_key: str | None = None,
    ):
        api_key = (
            api_key
            or settings.gemini_api_key
        )
        if not api_key:
            raise ValueError(
                "Gemini API key is not configured"
            )
        self._client = genai.Client(
            api_key=api_key,
        )
        self._ai = self._client.aio
        # Your existing routine/text model.
        self._text_model_name = (
            settings.gemini_model
        )
        # Embedding model.
        self._embedding_model_name = (
            "gemini-embedding-2"
        )
        # Your pgvector embedding dimension.
        self._embedding_dimension = 768
    # ================================================================
    # TEXT GENERATION
    # ================================================================
    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(
            multiplier=1,
            min=1,
            max=8,
        ),
        retry=retry_if_exception_type(
            _RETRYABLE_EXCEPTIONS
        ),
    )
    async def generate_text(
        self,
        messages: list[Message],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_output_tokens: int = 2048,
    ) -> GenerationResult:
        """
        Generate normal text using the configured
        Gemini routine model.
        """
        if not messages:
            raise ValueError(
                "At least one message is required"
            )
        contents = _to_gemini_contents(
            messages
        )
        response = (
            await self._ai.models.generate_content(
                model=self._text_model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                ),
            )
        )
        usage = getattr(
            response,
            "usage_metadata",
            None,
        )
        return GenerationResult(
            text=response.text or "",
            raw=response,
            input_tokens=getattr(
                usage,
                "prompt_token_count",
                None,
            ),
            output_tokens=getattr(
                usage,
                "candidates_token_count",
                None,
            ),
        )
    # ================================================================
    # STRUCTURED GENERATION
    # ================================================================
    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(
            multiplier=1,
            min=1,
            max=8,
        ),
        retry=retry_if_exception_type(
            _RETRYABLE_EXCEPTIONS
        ),
    )
    async def generate_structured(
        self,
        messages: list[Message],
        *,
        schema: dict,
        system_prompt: str | None = None,
        temperature: float = 0.0,
    ) -> StructuredResult:
        """
        Generate structured JSON using Gemini.
        """
        if not messages:
            raise ValueError(
                "At least one message is required"
            )
        contents = _to_gemini_contents(
            messages
        )
        response = (
            await self._ai.models.generate_content(
                model=self._text_model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
        )
        raw_text = response.text or ""
        try:
            data = json.loads(
                raw_text
            )
        except (
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            logger.error(
                "gemini_structured_parse_failed",
                error=str(exc),
                response=raw_text[:1000],
            )
            raise ValueError(
                "Gemini returned non-JSON output "
                "for a structured request"
            ) from exc
        return StructuredResult(
            data=data,
            raw=response,
        )
    # ================================================================
    # MEDIA UNDERSTANDING
    # ================================================================
    async def understand_media(
        self,
        media: MediaInput,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> GenerationResult:
        """
        Understand images, audio, PDFs, and other
        supported media using the configured
        Gemini routine model.
        """
        if not media.data:
            raise ValueError(
                "Media data cannot be empty"
            )
        if not media.media_type:
            raise ValueError(
                "Media MIME type is required"
            )
        response = (
            await self._ai.models.generate_content(
                model=self._text_model_name,
                contents=[
                    types.Part.from_bytes(
                        data=media.data,
                        mime_type=media.media_type,
                    ),
                    types.Part.from_text(
                        text=prompt,
                    ),
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                ),
            )
        )
        usage = getattr(
            response,
            "usage_metadata",
            None,
        )
        return GenerationResult(
            text=response.text or "",
            raw=response,
            input_tokens=getattr(
                usage,
                "prompt_token_count",
                None,
            ),
            output_tokens=getattr(
                usage,
                "candidates_token_count",
                None,
            ),
        )
    # ================================================================
    # EMBEDDINGS
    # ================================================================
    async def embed(
        self,
        texts: list[str],
    ) -> EmbeddingResult:
        """
        Generate embeddings for a list of texts.
        """
        if not texts:
            return EmbeddingResult(
                vectors=[],
                model=self._embedding_model_name,
            )
        response = (
            await self._ai.models.embed_content(
                model=self._embedding_model_name,
                contents=texts,
                config=types.EmbedContentConfig(
                    output_dimensionality=(
                        self._embedding_dimension
                    ),
                ),
            )
        )
        vectors = [
            embedding.values
            for embedding in response.embeddings
        ]
        return EmbeddingResult(
            vectors=vectors,
            model=self._embedding_model_name,
        )
    # ================================================================
    # IMAGE GENERATION
    # ================================================================
    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(
            multiplier=1,
            min=1,
            max=8,
        ),
        retry=retry_if_exception_type(
            _RETRYABLE_EXCEPTIONS
        ),
    )
    async def generate_image(
        self,
        prompt: str,
        *,
        aspect_ratio: str = "1:1",
    ) -> ImageGenerationResult:
        """
        Generate an image using Gemini 2.5 Flash Image.
        The image model is deliberately hard-coded here so
        it cannot accidentally use the normal GEMINI_MODEL
        or an obsolete Imagen model.
        Generated image data is returned as bytes.
        """
        if not prompt or not prompt.strip():
            raise ValueError(
                "Image generation prompt cannot be empty"
            )
        supported_aspect_ratios = {
            "1:1",
            "1:4",
            "4:1",
            "1:8",
            "8:1",
            "2:3",
            "3:2",
            "3:4",
            "4:3",
            "4:5",
            "5:4",
            "9:16",
            "16:9",
            "21:9",
        }
        if aspect_ratio not in supported_aspect_ratios:
            raise ValueError(
                "Unsupported aspect ratio: "
                f"{aspect_ratio}. "
                "Supported values: "
                f"{', '.join(sorted(supported_aspect_ratios))}"
            )
        try:
            logger.info(
                "gemini_image_generation_started",
                model=_GEMINI_IMAGE_MODEL,
                aspect_ratio=aspect_ratio,
            )
            # IMPORTANT:
            #
            # Do NOT use:
            #
            # response_format={
            #     "image": {
            #         "aspect_ratio": aspect_ratio
            #     }
            # }
            #
            # GenerateContentConfig does not support
            # response_format.
            #
            # Image generation uses response_modalities
            # and image_config instead.
            response = (
                await self._ai.models.generate_content(
                    model=_GEMINI_IMAGE_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=[
                            "IMAGE"
                        ],
                        image_config=types.ImageConfig(
                            aspect_ratio=aspect_ratio,
                        ),
                    ),
                )
            )
            image_bytes: bytes | None = None
            mime_type = "image/png"
            if response.candidates:
                for candidate in response.candidates:
                    if not candidate.content:
                        continue
                    parts = (
                        candidate.content.parts
                        or []
                    )
                    for part in parts:
                        inline_data = getattr(
                            part,
                            "inline_data",
                            None,
                        )
                        if inline_data is None:
                            continue
                        data = getattr(
                            inline_data,
                            "data",
                            None,
                        )
                        if not data:
                            continue
                        image_bytes = data
                        mime_type = (
                            getattr(
                                inline_data,
                                "mime_type",
                                None,
                            )
                            or "image/png"
                        )
                        break
                    if image_bytes:
                        break
            if not image_bytes:
                logger.error(
                    "gemini_image_generation_empty",
                    model=_GEMINI_IMAGE_MODEL,
                    response=str(response)[:3000],
                )
                raise RuntimeError(
                    "Gemini returned no image data"
                )
            logger.info(
                "gemini_image_generation_completed",
                model=_GEMINI_IMAGE_MODEL,
                mime_type=mime_type,
                bytes=len(image_bytes),
            )
            return ImageGenerationResult(
                image_data=image_bytes,
                mime_type=mime_type,
            )
        except (
            TimeoutError,
            ConnectionError,
        ):
            raise
        except Exception as exc:
            logger.error(
                "gemini_image_generation_failed",
                model=_GEMINI_IMAGE_MODEL,
                error=str(exc),
            )
            raise RuntimeError(
                f"Image generation failed: {exc}"
            ) from exc
