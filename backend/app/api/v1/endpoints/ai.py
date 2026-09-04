"""Endpoints for exercising the AI provider layer directly.

Useful now for verifying a GEMINI_API_KEY is wired up correctly.
Once agents exist (Milestone 3), agent replies call
`get_ai_provider()` directly from the service layer — these routes
aren't how agents will generate replies, they're a diagnostic surface.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.deps import get_current_active_user
from app.models.user import User
from app.services.ai import AIProvider, get_ai_provider

router = APIRouter(prefix="/ai", tags=["AI (diagnostic)"])


class GenerateRequest(BaseModel):
    prompt: str
    system_instruction: str | None = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class GenerateResponse(BaseModel):
    text: str
    provider: str


class EmbedRequest(BaseModel):
    texts: list[str]


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
    provider: str
    dimensions: int


class SummarizeRequest(BaseModel):
    text: str
    max_words: int | None = None


class ClassifyRequest(BaseModel):
    text: str
    labels: list[str]


class TextResponse(BaseModel):
    text: str
    provider: str


def _provider() -> AIProvider:
    return get_ai_provider()


@router.post("/generate", response_model=GenerateResponse)
async def generate(data: GenerateRequest, _: User = Depends(get_current_active_user)):
    provider = _provider()
    text = await provider.generate(
        data.prompt, system_instruction=data.system_instruction, temperature=data.temperature
    )
    return GenerateResponse(text=text, provider=provider.name)


@router.post("/embed", response_model=EmbedResponse)
async def embed(data: EmbedRequest, _: User = Depends(get_current_active_user)):
    provider = _provider()
    vectors = await provider.embed(data.texts)
    return EmbedResponse(
        embeddings=vectors, provider=provider.name, dimensions=len(vectors[0]) if vectors else 0
    )


@router.post("/summarize", response_model=TextResponse)
async def summarize(data: SummarizeRequest, _: User = Depends(get_current_active_user)):
    provider = _provider()
    text = await provider.summarize(data.text, max_words=data.max_words)
    return TextResponse(text=text, provider=provider.name)


@router.post("/classify", response_model=TextResponse)
async def classify(data: ClassifyRequest, _: User = Depends(get_current_active_user)):
    provider = _provider()
    label = await provider.classify(data.text, data.labels)
    return TextResponse(text=label, provider=provider.name)
