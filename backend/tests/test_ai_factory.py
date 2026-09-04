import pytest

from app.services.ai.exceptions import AIProviderError
from app.services.ai.factory import _instances, close_all_providers, get_ai_provider
from app.services.ai.gemini_provider import GeminiProvider


@pytest.fixture(autouse=True)
async def _clear_provider_cache():
    _instances.clear()
    yield
    await close_all_providers()


@pytest.mark.asyncio
async def test_default_provider_is_gemini():
    provider = get_ai_provider()
    assert isinstance(provider, GeminiProvider)
    assert provider.name == "gemini"


@pytest.mark.asyncio
async def test_unknown_provider_raises():
    with pytest.raises(AIProviderError):
        get_ai_provider("not-a-real-provider")


@pytest.mark.asyncio
async def test_provider_instances_are_cached():
    first = get_ai_provider("gemini")
    second = get_ai_provider("gemini")
    assert first is second


@pytest.mark.asyncio
async def test_close_all_providers_clears_cache():
    get_ai_provider("gemini")
    assert len(_instances) == 1
    await close_all_providers()
    assert len(_instances) == 0
