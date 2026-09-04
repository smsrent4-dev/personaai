"""Paystack API client.

Same approach as GeminiProvider/TelegramAdapter: talk to the REST API
directly over httpx rather than pulling in a third-party SDK. Endpoint
shapes here follow Paystack's documented API
(https://paystack.com/docs/api/) - I couldn't hit the live API from
this sandbox (no network access) to verify these calls end-to-end, so
treat this the same as every other "not sandbox-executed" piece: code
reviewed carefully against the documented contract, not live-tested.

Amounts: Paystack's API takes amounts in the currency's smallest unit
(kobo for NGN, cents for USD, etc.) - always *100 of the Decimal major-unit
price stored on BillingPlan. _to_subunit()/_from_subunit() are the only
places that conversion happens, deliberately centralized.
"""
import hashlib
import hmac
from decimal import Decimal

import httpx

from app.config import settings

PAYSTACK_API_BASE = "https://api.paystack.co"


class PaystackError(Exception):
    pass


def _to_subunit(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value())


def _from_subunit(amount: int) -> Decimal:
    return Decimal(amount) / Decimal(100)


class PaystackService:
    def __init__(self, secret_key: str | None = None, timeout: float = 20.0):
        self.secret_key = secret_key if secret_key is not None else settings.PAYSTACK_SECRET_KEY
        self._client = httpx.AsyncClient(
            base_url=PAYSTACK_API_BASE,
            timeout=timeout,
            headers={"Authorization": f"Bearer {self.secret_key}", "Content-Type": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, json_body: dict | None = None) -> dict:
        resp = await self._client.request(method, path, json=json_body)
        try:
            data = resp.json()
        except ValueError as exc:
            raise PaystackError(f"Paystack returned a non-JSON response ({resp.status_code})") from exc

        if not data.get("status"):
            raise PaystackError(data.get("message", f"Paystack request failed ({resp.status_code})"))
        return data

    # ---------- plans ----------

    async def create_plan(self, name: str, amount: Decimal, interval: str, currency: str) -> str:
        data = await self._request(
            "POST",
            "/plan",
            {"name": name, "amount": _to_subunit(amount), "interval": interval, "currency": currency},
        )
        return data["data"]["plan_code"]

    async def update_plan(self, plan_code: str, name: str, amount: Decimal, interval: str) -> None:
        await self._request(
            "PUT", f"/plan/{plan_code}", {"name": name, "amount": _to_subunit(amount), "interval": interval}
        )

    # ---------- transactions / checkout ----------

    async def initialize_transaction(
        self,
        email: str,
        amount: Decimal,
        currency: str,
        callback_url: str,
        plan_code: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        body = {
            "email": email,
            "amount": _to_subunit(amount),
            "currency": currency,
            "callback_url": callback_url,
        }
        if plan_code:
            body["plan"] = plan_code
        if metadata:
            body["metadata"] = metadata

        data = await self._request("POST", "/transaction/initialize", body)
        return {
            "authorization_url": data["data"]["authorization_url"],
            "access_code": data["data"]["access_code"],
            "reference": data["data"]["reference"],
        }

    async def verify_transaction(self, reference: str) -> dict:
        data = await self._request("GET", f"/transaction/verify/{reference}")
        return data["data"]

    # ---------- webhooks ----------

    @staticmethod
    def verify_webhook_signature(raw_body: bytes, signature_header: str | None, secret_key: str) -> bool:
        if not signature_header:
            return False
        expected = hmac.new(secret_key.encode("utf-8"), raw_body, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected, signature_header)
