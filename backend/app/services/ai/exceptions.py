"""Exceptions raised by AI provider implementations.

Callers (agents, RAG pipeline, Teach My AI, etc.) catch AIProviderError
rather than provider-specific exceptions, so swapping Gemini for
OpenAI/Claude/Ollama later never requires touching call sites.
"""


class AIProviderError(Exception):
    def __init__(self, message: str, provider: str, original_error: Exception | None = None):
        self.provider = provider
        self.original_error = original_error
        super().__init__(f"[{provider}] {message}")


class AIRateLimitError(AIProviderError):
    """Raised on 429 responses — callers may want to back off/queue rather than fail the request."""


class AIAuthenticationError(AIProviderError):
    """Raised when the provider rejects the API key — almost always a config problem, not transient."""
