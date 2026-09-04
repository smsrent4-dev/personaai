"""AIProvider — the interface every model backend implements.

Nothing above this layer (agents, RAG, Teach My AI, conversation
training) is allowed to import a provider-specific SDK or know which
provider is active. They depend on this interface and get a concrete
instance from `app.services.ai.factory.get_ai_provider()`, which reads
`settings.AI_DEFAULT_PROVIDER`. Adding OpenAI/Claude/OpenRouter/Ollama/
Groq later means writing one new file that implements this interface
and registering it in the factory — nothing else in the codebase changes.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass
class ToolDefinition:
    """One callable tool the model can choose to invoke. `parameters` is a
    JSON-schema dict describing the arguments — see
    app/services/tools/base.py for how real tools build this."""

    name: str
    description: str
    parameters: dict


ToolExecutor = Callable[[str, dict], Awaitable[dict]]


class AIProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Free-form text generation. Used directly by agent reply generation."""
        raise NotImplementedError

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Returns one embedding vector per input string, same order.
        Used by the knowledge-base ingestion pipeline (Milestone 4) and
        by semantic memory search."""
        raise NotImplementedError

    @abstractmethod
    async def summarize(self, text: str, max_words: int | None = None) -> str:
        """Condenses text — used for conversation memory compaction and
        for the Knowledge page's document previews."""
        raise NotImplementedError

    @abstractmethod
    async def classify(self, text: str, labels: list[str]) -> str:
        """Returns exactly one of `labels`. Used by the Router agent to
        decide which agent should handle an incoming message."""
        raise NotImplementedError

    async def generate_with_tools(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        tool_executor: ToolExecutor,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tool_iterations: int = 3,
    ) -> str:
        """Runs a full tool-calling loop: the model can request a tool
        (e.g. search_product, create_order), we execute it via
        `tool_executor(name, arguments) -> result_dict`, feed the result
        back, and repeat until the model gives a final text answer or
        `max_tool_iterations` is hit.

        Deliberately a CONCRETE method with this no-op fallback (ignores
        tools, just calls generate()) rather than abstract — providers
        that don't implement real function-calling (or test doubles that
        only implement the four core methods) still work unmodified.
        GeminiProvider overrides this with Gemini's actual function-calling
        API; that's the only implementation with real tool-calling behavior
        today."""
        return await self.generate(prompt, system_instruction=system_instruction, temperature=temperature)

    async def describe_image(self, image_bytes: bytes, mime_type: str, instruction: str | None = None) -> str:
        """Vision: describes what's in an image, given its raw bytes.
        Used for photos a customer sends — a payment screenshot, a
        "does this match?" product photo, etc. (see
        MessagingPipeline._handle_image_message).

        Deliberately a CONCRETE method with this no-op fallback, same
        reasoning as generate_with_tools above: providers/test doubles
        that don't implement real vision still work, they just can't
        actually see the image. GeminiProvider overrides this with a
        real multimodal generateContent call."""
        return "(Image analysis is not supported by the current AI provider.)"

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str) -> str:
        """Speech-to-text for voice notes. Same fallback reasoning as
        describe_image above — GeminiProvider overrides this with a
        real multimodal call; other providers degrade to this notice
        rather than pretending to have heard something."""
        return "(Audio transcription is not supported by the current AI provider.)"
