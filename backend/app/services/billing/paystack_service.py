"""Paystack API client.
PersonaAI talks to Paystack directly through the REST API using httpx.
No third-party Paystack SDK is required.
Paystack API:
https://paystack.com/docs/api/
Amounts:
    Paystack expects amounts in the currency's smallest unit.
    Examples:
        NGN 1,000.00 -> 100000 kobo
        NGN 5,000.00 -> 500000 kobo
        USD 10.00    -> 1000 cents
    BillingPlan prices are stored in major currency units as Decimal.
    Conversion is deliberately centralized in:
        _to_subunit()
        _from_subunit()
Checkout:
    PersonaAI enables Card and Bank Transfer by default.
    Paystack channel names used here:
        card
        bank_transfer
    Additional Paystack channels can be supplied through the optional
    `channels` argument when initializing a transaction.
Webhook security:
    Paystack signs webhook requests using HMAC-SHA512.
    `verify_webhook_signature()` validates the x-paystack-signature
    header against the raw request body.
"""
import hashlib
import hmac
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
import httpx
from app.config import settings
PAYSTACK_API_BASE = "https://api.paystack.co"
# Default payment channels shown during PersonaAI checkout.
#
# `card`:
#     Customer pays using a debit/credit card.
#
# `bank_transfer`:
#     Paystack provides the customer with transfer instructions /
#     a temporary account for the transaction where supported.
DEFAULT_PAYMENT_CHANNELS = [
    "card",
    "bank_transfer",
]
class PaystackError(Exception):
    """Raised when a Paystack API request fails."""
    pass
def _to_subunit(amount: Decimal) -> int:
    """Convert a major-unit Decimal amount to Paystack's smallest unit.
    Example:
        Decimal("1000.00") -> 100000
    ROUND_HALF_UP is used so currency conversion behaves predictably
    when Decimal values contain fractional subunits.
    """
    return int(
        (amount * Decimal("100"))
        .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
def _from_subunit(amount: int) -> Decimal:
    """Convert Paystack's smallest currency unit back to major units.
    Example:
        100000 -> Decimal("1000")
    """
    return Decimal(amount) / Decimal("100")
class PaystackService:
    """Async REST client for Paystack."""
    def __init__(
        self,
        secret_key: str | None = None,
        timeout: float = 20.0,
    ):
        self.secret_key = (
            secret_key
            if secret_key is not None
            else settings.PAYSTACK_SECRET_KEY
        )
        if not self.secret_key:
            raise PaystackError(
                "PAYSTACK_SECRET_KEY is not configured."
            )
        self._client = httpx.AsyncClient(
            base_url=PAYSTACK_API_BASE,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.secret_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
    async def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a request to Paystack and validate its response."""
        try:
            response = await self._client.request(
                method,
                path,
                json=json_body,
            )
        except httpx.TimeoutException as exc:
            raise PaystackError(
                "Paystack request timed out."
            ) from exc
        except httpx.RequestError as exc:
            raise PaystackError(
                f"Unable to connect to Paystack: {exc}"
            ) from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise PaystackError(
                f"Paystack returned a non-JSON response "
                f"({response.status_code})."
            ) from exc
        if not isinstance(data, dict):
            raise PaystackError(
                "Paystack returned an unexpected response format."
            )
        if not data.get("status"):
            message = data.get(
                "message",
                f"Paystack request failed ({response.status_code}).",
            )
            raise PaystackError(str(message))
        return data
    # ------------------------------------------------------------------
    # Plans
    # ------------------------------------------------------------------
    async def create_plan(
        self,
        name: str,
        amount: Decimal,
        interval: str,
        currency: str,
    ) -> str:
        """Create a Paystack subscription plan.
        Returns:
            Paystack plan_code.
        """
        data = await self._request(
            "POST",
            "/plan",
            {
                "name": name,
                "amount": _to_subunit(amount),
                "interval": interval,
                "currency": currency,
            },
        )
        try:
            return data["data"]["plan_code"]
        except (KeyError, TypeError) as exc:
            raise PaystackError(
                "Paystack returned an invalid plan response."
            ) from exc
    async def update_plan(
        self,
        plan_code: str,
        name: str,
        amount: Decimal,
        interval: str,
    ) -> None:
        """Update an existing Paystack subscription plan."""
        await self._request(
            "PUT",
            f"/plan/{plan_code}",
            {
                "name": name,
                "amount": _to_subunit(amount),
                "interval": interval,
            },
        )
    # ------------------------------------------------------------------
    # Transactions / Checkout
    # ------------------------------------------------------------------
    async def initialize_transaction(
        self,
        email: str,
        amount: Decimal,
        currency: str,
        callback_url: str,
        plan_code: str | None = None,
        metadata: dict[str, Any] | None = None,
        channels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Initialize a Paystack Checkout transaction.
        By default PersonaAI enables:
            - Card
            - Bank Transfer
        You can override the channels for a particular transaction:
            channels=["card", "bank_transfer"]
        Or add other Paystack-supported channels where enabled for
        the merchant account.
        Args:
            email:
                Customer email address.
            amount:
                Amount in major currency units as Decimal.
            currency:
                Transaction currency, e.g. "NGN".
            callback_url:
                URL Paystack redirects the customer to after checkout.
            plan_code:
                Optional Paystack subscription plan code.
            metadata:
                Optional transaction metadata.
            channels:
                Optional list of Paystack payment channels.
                Defaults to Card + Bank Transfer.
        Returns:
            Dictionary containing:
                authorization_url
                access_code
                reference
        """
        selected_channels = (
            channels
            if channels is not None
            else DEFAULT_PAYMENT_CHANNELS.copy()
        )
        if not selected_channels:
            raise PaystackError(
                "At least one Paystack payment channel must be provided."
            )
        body: dict[str, Any] = {
            "email": email,
            "amount": _to_subunit(amount),
            "currency": currency,
            "callback_url": callback_url,
            "channels": selected_channels,
        }
        if plan_code:
            body["plan"] = plan_code
        if metadata:
            body["metadata"] = metadata
        data = await self._request(
            "POST",
            "/transaction/initialize",
            body,
        )
        try:
            transaction_data = data["data"]
            return {
                "authorization_url": transaction_data["authorization_url"],
                "access_code": transaction_data["access_code"],
                "reference": transaction_data["reference"],
            }
        except (KeyError, TypeError) as exc:
            raise PaystackError(
                "Paystack returned an invalid transaction initialization response."
            ) from exc
    async def verify_transaction(
        self,
        reference: str,
    ) -> dict[str, Any]:
        """Verify a Paystack transaction by reference.
        Returns the complete Paystack transaction data.
        """
        if not reference:
            raise PaystackError(
                "Transaction reference is required."
            )
        data = await self._request(
            "GET",
            f"/transaction/verify/{reference}",
        )
        try:
            return data["data"]
        except (KeyError, TypeError) as exc:
            raise PaystackError(
                "Paystack returned an invalid transaction verification response."
            ) from exc
    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------
    @staticmethod
    def verify_webhook_signature(
        raw_body: bytes,
        signature_header: str | None,
        secret_key: str,
    ) -> bool:
        """Verify a Paystack webhook signature.
        Paystack sends the signature in:
            x-paystack-signature
        The signature is an HMAC-SHA512 hash of the raw request body
        using the Paystack secret key.
        Important:
            Pass the exact raw request body received by FastAPI.
            Do not parse and re-serialize JSON before calculating
            the signature.
        """
        if not signature_header:
            return False
        if not secret_key:
            return False
        expected_signature = hmac.new(
            secret_key.encode("utf-8"),
            raw_body,
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(
            expected_signature,
            signature_header.strip(),
        )
