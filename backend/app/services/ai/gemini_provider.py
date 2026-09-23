"""Google Gemini implementation of AIProvider.

Talks to the REST API directly over httpx rather than pulling in the
`google-generativeai` SDK — one less heavyweight, fast-moving dependency
for a client that's really just two JSON endpoints. Swappable for the
official SDK later without changing this class's public surface.
"""
import base64
import logging

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.services.ai.base import AIProvider, ToolDefinition, ToolExecutor
from app.services.ai.exceptions import AIAuthenticationError, AIProviderError, AIRateLimitError

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class _TransientAIError(Exception):
    """Internal-only: marks an error as worth retrying (timeouts, 5xx)."""


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        embedding_model: str | None = None,
        timeout: float = 30.0,
    ):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        self.embedding_model = embedding_model or settings.GEMINI_EMBEDDING_MODEL
        self._client = httpx.AsyncClient(base_url=GEMINI_API_BASE, timeout=timeout)

        if not self.api_key:
            logger.warning(
                "GeminiProvider initialized without an API key — "
                "requests will fail until GEMINI_API_KEY is set."
            )

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(
        retry=retry_if_exception_type(_TransientAIError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _post(self, path: str, json_body: dict) -> dict:
        try:
            resp = await self._client.post(
                f"{path}", params={"key": self.api_key}, json=json_body
            )
        except httpx.TimeoutException as exc:
            raise _TransientAIError(str(exc)) from exc
        except httpx.TransportError as exc:
            raise _TransientAIError(str(exc)) from exc

        if resp.status_code == 401 or resp.status_code == 403:
            raise AIAuthenticationError("Invalid or missing Gemini API key", self.name)
        if resp.status_code == 429:
            raise AIRateLimitError("Gemini rate limit exceeded", self.name)
        if 500 <= resp.status_code < 600:
            raise _TransientAIError(f"Gemini returned {resp.status_code}: {resp.text}")
        if resp.status_code >= 400:
            raise AIProviderError(f"Gemini request failed ({resp.status_code}): {resp.text}", self.name)

        return resp.json()

    @staticmethod
    def _extract_text(data: dict) -> str:
        try:
            candidates = data["candidates"]
            if not candidates:
                raise AIProviderError("Gemini returned no candidates (likely blocked by safety filters)", "gemini")
            parts = candidates[0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError) as exc:
            raise AIProviderError(f"Unexpected Gemini response shape: {data}", "gemini", exc) from exc

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature},
        }
        if max_tokens is not None:
            body["generationConfig"]["maxOutputTokens"] = max_tokens
        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        try:
            data = await self._post(f"/models/{self.model}:generateContent", body)
        except _TransientAIError as exc:
            raise AIProviderError("Gemini unavailable after retries", self.name, exc) from exc

        return self._extract_text(data)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        body = {
            "requests": [
                {
                    "model": f"models/{self.embedding_model}",
                    "content": {"parts": [{"text": t}]},
                }
                for t in texts
            ]
        }

        try:
            data = await self._post(f"/models/{self.embedding_model}:batchEmbedContents", body)
        except _TransientAIError as exc:
            raise AIProviderError("Gemini unavailable after retries", self.name, exc) from exc

        try:
            return [item["values"] for item in data["embeddings"]]
        except (KeyError, IndexError) as exc:
            raise AIProviderError(f"Unexpected Gemini embedding response shape: {data}", self.name, exc) from exc

    async def summarize(self, text: str, max_words: int | None = None) -> str:
        constraint = f" in no more than {max_words} words" if max_words else " concisely"
        prompt = (
            f"Summarize the following text{constraint}. "
            f"Output only the summary, no preamble.\n\nTEXT:\n{text}"
        )
        return await self.generate(prompt, temperature=0.3)

    async def classify(self, text: str, labels: list[str]) -> str:
        if not labels:
            raise AIProviderError("classify() called with an empty label set", self.name)

        label_list = "\n".join(f"- {label}" for label in labels)
        prompt = (
            "Classify the following text into exactly one of these categories. "
            "Respond with only the category name, exactly as written below, and nothing else.\n\n"
            f"Categories:\n{label_list}\n\nText:\n{text}"
        )
        raw = await self.generate(prompt, temperature=0.0)
        cleaned = raw.strip().strip('"').strip("'")

        for label in labels:
            if cleaned.lower() == label.lower():
                return label
        for label in labels:
            if label.lower() in cleaned.lower():
                return label

        raise AIProviderError(
            f"Gemini returned '{raw}', which doesn't match any of {labels}", self.name
        )

    async def describe_image(self, image_bytes: bytes, mime_type: str, instruction: str | None = None) -> str:
        """Real vision call via Gemini's multimodal generateContent —
        the image goes in as an inline_data part alongside the prompt.
        Inline data is capped at ~20MB by the API; larger files would
        need the separate Files API upload flow, not implemented here
        since Telegram/WhatsApp photos and voice notes are well under
        that in practice."""
        prompt_text = instruction or (
            "Describe this image in detail. Note any visible text, numbers, amounts, dates, or "
            "reference/transaction IDs exactly as they appear, and describe any products, "
            "packaging, or app/screenshot UI shown."
        )
        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt_text},
                        {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("ascii")}},
                    ],
                }
            ],
            "generationConfig": {"temperature": 0.2},
        }
        try:
            data = await self._post(f"/models/{self.model}:generateContent", body)
        except _TransientAIError as exc:
            raise AIProviderError("Gemini unavailable after retries", self.name, exc) from exc
        return self._extract_text(data)

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str) -> str:
        prompt_text = (
            "Transcribe the speech in this audio clip verbatim, in its original language. "
            "Output only the transcript — no preamble, no translation, no description of tone."
        )
        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt_text},
                        {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(audio_bytes).decode("ascii")}},
                    ],
                }
            ],
            "generationConfig": {"temperature": 0.0},
        }
        try:
            data = await self._post(f"/models/{self.model}:generateContent", body)
        except _TransientAIError as exc:
            raise AIProviderError("Gemini unavailable after retries", self.name, exc) from exc
        return self._extract_text(data)

    async def generate_with_tools(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        tool_executor: ToolExecutor,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tool_iterations: int = 5,
    ) -> str:
        """Real function-calling via Gemini's REST API `tools` field. The
        model returns a `functionCall` part instead of `text` when it
        wants to call something; we execute it and feed a
        `functionResponse` part back in a new turn, repeating until the
        model settles on a plain-text answer.

        This is the concrete realization of the "AI decides when to
        search products / create orders" decision engine — no hardcoded
        if/else routing between "just reply" and "take an action";
        Gemini's own tool-choice reasoning makes that call each turn.
        """
        if not tools:
            return await self.generate(prompt, system_instruction=system_instruction, temperature=temperature)

        contents: list[dict] = [{"role": "user", "parts": [{"text": prompt}]}]
        function_declarations = [
            {"name": t.name, "description": t.description, "parameters": t.parameters} for t in tools
        ]
        body_base: dict = {
            "generationConfig": {"temperature": temperature},
            "tools": [{"functionDeclarations": function_declarations}],
        }
        if system_instruction:
            body_base["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        for _ in range(max_tool_iterations):
            body = {**body_base, "contents": contents}
            try:
                data = await self._post(f"/models/{self.model}:generateContent", body)
            except _TransientAIError as exc:
                raise AIProviderError("Gemini unavailable after retries", self.name, exc) from exc

            try:
                candidates = data["candidates"]
                if not candidates:
                    raise AIProviderError(
                        "Gemini returned no candidates (likely blocked by safety filters)", self.name
                    )
                model_content = candidates[0]["content"]
                parts = model_content.get("parts", [])
            except (KeyError, IndexError) as exc:
                raise AIProviderError(f"Unexpected Gemini response shape: {data}", self.name, exc) from exc

            function_call = next((p["functionCall"] for p in parts if "functionCall" in p), None)
            if function_call is None:
                return "".join(p.get("text", "") for p in parts).strip()

            tool_name = function_call["name"]
            tool_args = function_call.get("args", {})
            try:
                result = await tool_executor(tool_name, tool_args)
            except Exception as exc:  # noqa: BLE001 — feed the error back to the model, don't crash the reply
                result = {"error": str(exc)}

            # Gemini requires functionResponse payloads to strictly be a JSON object (dict)
            if not isinstance(result, dict):
                result = {"result": result}

            contents.append(model_content)
            contents.append(
                {"role": "user", "parts": [{"functionResponse": {"name": tool_name, "response": result}}]}
            )

        raise AIProviderError(
            f"Tool-calling loop exceeded {max_tool_iterations} iterations without a final answer", self.name
        )
