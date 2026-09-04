"""Provider factory.

This is the ONLY place in the codebase that knows which concrete
provider classes exist. `settings.AI_DEFAULT_PROVIDER` picks the
default; per-agent overrides (an agent's `model` field, e.g. a user
wants one agent on Gemini Flash and another on a future OpenAI model)
are resolved the same way — pass provider_name explicitly.

Adding a new provider (OpenAI/Claude/OpenRouter/Ollama/Groq):
1. Implement AIProvider in a new file (e.g. openai_provider.py).
2. Add one line to _PROVIDER_REGISTRY below.
Nothing else in the codebase changes.
"""
from app.config import settings
from app.services.ai.base import AIProvider
from app.services.ai.exceptions import AIProviderError
from app.services.ai.gemini_provider import GeminiProvider

_PROVIDER_REGISTRY: dict[str, type[AIProvider]] = {
    "gemini": GeminiProvider,
    # "openai": OpenAIProvider,      # future
    # "claude": ClaudeProvider,      # future
    # "openrouter": OpenRouterProvider,  # future
    # "ollama": OllamaProvider,      # future
    # "groq": GroqProvider,          # future
}

_instances: dict[str, AIProvider] = {}


def get_ai_provider(provider_name: str | None = None) -> AIProvider:
    """Returns a cached provider instance. Instances are reused (not
    recreated per call) so the underlying httpx.AsyncClient's
    connection pool is actually reused across requests."""
    name = (provider_name or settings.AI_DEFAULT_PROVIDER).lower()

    if name not in _PROVIDER_REGISTRY:
        raise AIProviderError(
            f"Unknown AI provider '{name}'. Available: {list(_PROVIDER_REGISTRY)}", name
        )

    if name not in _instances:
        _instances[name] = _PROVIDER_REGISTRY[name]()

    return _instances[name]


async def close_all_providers() -> None:
    """Call on app shutdown to release HTTP connections cleanly."""
    for provider in _instances.values():
        aclose = getattr(provider, "aclose", None)
        if aclose is not None:
            await aclose()
    _instances.clear()
