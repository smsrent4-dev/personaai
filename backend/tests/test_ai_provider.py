"""GeminiProvider tests.

All HTTP calls are mocked with respx — no real API key or network
access needed. These tests verify: request shape sent to Gemini,
response parsing, retry-on-5xx behavior, and error mapping (401->auth
error, 429->rate limit error).
"""
import json

import httpx
import pytest
import respx

from app.services.ai.base import ToolDefinition
from app.services.ai.exceptions import AIAuthenticationError, AIProviderError, AIRateLimitError
from app.services.ai.gemini_provider import GEMINI_API_BASE, GeminiProvider


@pytest.fixture
def provider():
    p = GeminiProvider(api_key="test-key", model="gemini-2.0-flash", embedding_model="text-embedding-004")
    yield p


@pytest.mark.asyncio
@respx.mock
async def test_generate_returns_text(provider: GeminiProvider):
    route = respx.post(f"{GEMINI_API_BASE}/models/gemini-2.0-flash:generateContent").mock(
        return_value=httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "Hello there!"}]}}]},
        )
    )
    result = await provider.generate("Say hello", system_instruction="Be friendly")
    assert result == "Hello there!"
    assert route.called
    sent_body = route.calls[0].request.content
    assert b"Say hello" in sent_body
    assert b"Be friendly" in sent_body


@pytest.mark.asyncio
@respx.mock
async def test_generate_no_candidates_raises(provider: GeminiProvider):
    respx.post(f"{GEMINI_API_BASE}/models/gemini-2.0-flash:generateContent").mock(
        return_value=httpx.Response(200, json={"candidates": []})
    )
    with pytest.raises(AIProviderError):
        await provider.generate("test")


@pytest.mark.asyncio
@respx.mock
async def test_generate_401_raises_auth_error(provider: GeminiProvider):
    respx.post(f"{GEMINI_API_BASE}/models/gemini-2.0-flash:generateContent").mock(
        return_value=httpx.Response(401, text="invalid key")
    )
    with pytest.raises(AIAuthenticationError):
        await provider.generate("test")


@pytest.mark.asyncio
@respx.mock
async def test_generate_429_raises_rate_limit_error(provider: GeminiProvider):
    respx.post(f"{GEMINI_API_BASE}/models/gemini-2.0-flash:generateContent").mock(
        return_value=httpx.Response(429, text="slow down")
    )
    with pytest.raises(AIRateLimitError):
        await provider.generate("test")


@pytest.mark.asyncio
@respx.mock
async def test_generate_retries_on_5xx_then_succeeds(provider: GeminiProvider):
    route = respx.post(f"{GEMINI_API_BASE}/models/gemini-2.0-flash:generateContent").mock(
        side_effect=[
            httpx.Response(503, text="overloaded"),
            httpx.Response(503, text="overloaded"),
            httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}),
        ]
    )
    result = await provider.generate("test")
    assert result == "ok"
    assert route.call_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_embed_returns_vectors_in_order(provider: GeminiProvider):
    respx.post(f"{GEMINI_API_BASE}/models/text-embedding-004:batchEmbedContents").mock(
        return_value=httpx.Response(
            200,
            json={"embeddings": [{"values": [0.1, 0.2]}, {"values": [0.3, 0.4]}]},
        )
    )
    vectors = await provider.embed(["first", "second"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]


@pytest.mark.asyncio
async def test_embed_empty_list_short_circuits(provider: GeminiProvider):
    # No HTTP mock registered — if this made a real request it would error,
    # proving the empty-input short-circuit in embed() actually fires.
    assert await provider.embed([]) == []


@pytest.mark.asyncio
@respx.mock
async def test_classify_matches_exact_label(provider: GeminiProvider):
    respx.post(f"{GEMINI_API_BASE}/models/gemini-2.0-flash:generateContent").mock(
        return_value=httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "Sales"}]}}]}
        )
    )
    label = await provider.classify("How much for the website package?", ["Sales", "Support", "General"])
    assert label == "Sales"


@pytest.mark.asyncio
@respx.mock
async def test_classify_no_match_raises(provider: GeminiProvider):
    respx.post(f"{GEMINI_API_BASE}/models/gemini-2.0-flash:generateContent").mock(
        return_value=httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "Nonexistent"}]}}]}
        )
    )
    with pytest.raises(AIProviderError):
        await provider.classify("test", ["Sales", "Support"])


@pytest.mark.asyncio
async def test_classify_empty_labels_raises(provider: GeminiProvider):
    with pytest.raises(AIProviderError):
        await provider.classify("test", [])


@pytest.mark.asyncio
@respx.mock
async def test_summarize_uses_low_temperature_generate(provider: GeminiProvider):
    route = respx.post(f"{GEMINI_API_BASE}/models/gemini-2.0-flash:generateContent").mock(
        return_value=httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "A short summary."}]}}]}
        )
    )
    result = await provider.summarize("A very long piece of text " * 20, max_words=10)
    assert result == "A short summary."
    sent_body = route.calls[0].request.content
    assert b"no more than 10 words" in sent_body


# ---------- generate_with_tools ----------
#
# Regression tests for two real bugs, both confirmed live against
# Gemini 3-family models (400 INVALID_ARGUMENT in both cases), not
# hypothetical: previously the functionResponse turn used a "function"
# role — which doesn't exist in Gemini's API — and the model's
# functionCall turn was rebuilt from scratch, silently dropping the
# sibling "thoughtSignature" field Gemini 3-family (thinking) models
# attach and require echoed back unchanged on the next turn.


async def _single_tool_executor(name: str, args: dict) -> dict:
    return {"called_with": args}


@pytest.mark.asyncio
@respx.mock
async def test_generate_with_tools_no_tool_call_returns_text_directly(provider: GeminiProvider):
    """No functionCall in the response -> just returns the text, no
    second request."""
    route = respx.post(f"{GEMINI_API_BASE}/models/gemini-2.0-flash:generateContent").mock(
        return_value=httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "Just a plain answer."}]}}]}
        )
    )
    tools = [ToolDefinition(name="search_product", description="Search products", parameters={"type": "object"})]
    result = await provider.generate_with_tools("Hi", tools, _single_tool_executor)
    assert result == "Just a plain answer."
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_generate_with_tools_sends_function_response_as_user_role(provider: GeminiProvider):
    """The actual reported bug: previously sent role="function", which
    Gemini rejects outright (confirmed live: "Role 'function' is not
    supported"). Gemini's valid roles for this turn are user/model."""
    route = respx.post(f"{GEMINI_API_BASE}/models/gemini-2.0-flash:generateContent").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"functionCall": {"name": "search_product", "args": {"query": "crocs"}}}
                                ]
                            }
                        }
                    ]
                },
            ),
            httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Found it!"}]}}]}),
        ]
    )
    tools = [ToolDefinition(name="search_product", description="Search products", parameters={"type": "object"})]
    result = await provider.generate_with_tools("Do you have crocs?", tools, _single_tool_executor)

    assert result == "Found it!"
    assert route.call_count == 2

    second_request_body = json.loads(route.calls[1].request.content)
    roles_sent = [c["role"] for c in second_request_body["contents"]]
    assert "function" not in roles_sent
    # The turn carrying the functionResponse must be "user", not "function".
    function_response_turns = [
        c for c in second_request_body["contents"] if any("functionResponse" in p for p in c["parts"])
    ]
    assert len(function_response_turns) == 1
    assert function_response_turns[0]["role"] == "user"


@pytest.mark.asyncio
@respx.mock
async def test_generate_with_tools_preserves_thought_signature(provider: GeminiProvider):
    """The other reported bug: Gemini 3-family models attach a
    thoughtSignature alongside functionCall in the same part and require
    it echoed back unchanged on the next turn — confirmed live: "Function
    call is missing a thought_signature in functionCall parts". Rebuilding
    the part from just name/args silently dropped it."""
    route = respx.post(f"{GEMINI_API_BASE}/models/gemini-2.0-flash:generateContent").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "functionCall": {"name": "search_product", "args": {"query": "crocs"}},
                                        "thoughtSignature": "opaque-signature-abc123",
                                    }
                                ]
                            }
                        }
                    ]
                },
            ),
            httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Found it!"}]}}]}),
        ]
    )
    tools = [ToolDefinition(name="search_product", description="Search products", parameters={"type": "object"})]
    await provider.generate_with_tools("Do you have crocs?", tools, _single_tool_executor)

    second_request_body = json.loads(route.calls[1].request.content)
    model_turns = [c for c in second_request_body["contents"] if c["role"] == "model"]
    assert len(model_turns) == 1
    assert model_turns[0]["parts"][0]["thoughtSignature"] == "opaque-signature-abc123"
    assert model_turns[0]["parts"][0]["functionCall"]["name"] == "search_product"


@pytest.mark.asyncio
@respx.mock
async def test_generate_with_tools_feeds_tool_error_back_to_model(provider: GeminiProvider):
    respx.post(f"{GEMINI_API_BASE}/models/gemini-2.0-flash:generateContent").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "candidates": [
                        {"content": {"parts": [{"functionCall": {"name": "search_product", "args": {}}}]}}
                    ]
                },
            ),
            httpx.Response(
                200, json={"candidates": [{"content": {"parts": [{"text": "Sorry, something broke."}]}}]}
            ),
        ]
    )

    async def _failing_executor(name: str, args: dict) -> dict:
        raise RuntimeError("tool blew up")

    tools = [ToolDefinition(name="search_product", description="Search products", parameters={"type": "object"})]
    result = await provider.generate_with_tools("test", tools, _failing_executor)
    assert result == "Sorry, something broke."  # didn't crash — error was fed back as a tool result


@pytest.mark.asyncio
@respx.mock
async def test_generate_with_tools_no_tools_falls_back_to_generate(provider: GeminiProvider):
    route = respx.post(f"{GEMINI_API_BASE}/models/gemini-2.0-flash:generateContent").mock(
        return_value=httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "plain"}]}}]})
    )
    result = await provider.generate_with_tools("test", [], _single_tool_executor)
    assert result == "plain"
    assert route.call_count == 1
