from decimal import Decimal

import httpx
import pytest
import respx

from app.services.billing.paystack_service import (
    PAYSTACK_API_BASE,
    PaystackError,
    PaystackService,
    _from_subunit,
    _to_subunit,
)


def test_to_subunit_and_back():
    assert _to_subunit(Decimal("500.00")) == 50000
    assert _to_subunit(Decimal("29.99")) == 2999
    assert _from_subunit(50000) == Decimal("500")


@pytest.fixture
def service():
    return PaystackService(secret_key="sk_test_fake")


@pytest.mark.asyncio
@respx.mock
async def test_create_plan_returns_plan_code(service: PaystackService):
    respx.post(f"{PAYSTACK_API_BASE}/plan").mock(
        return_value=httpx.Response(
            200, json={"status": True, "message": "ok", "data": {"plan_code": "PLN_abc123"}}
        )
    )
    code = await service.create_plan("Growth", Decimal("99.00"), "monthly", "NGN")
    assert code == "PLN_abc123"
    await service.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_create_plan_raises_on_paystack_error(service: PaystackService):
    respx.post(f"{PAYSTACK_API_BASE}/plan").mock(
        return_value=httpx.Response(400, json={"status": False, "message": "Invalid amount"})
    )
    with pytest.raises(PaystackError):
        await service.create_plan("Growth", Decimal("99.00"), "monthly", "NGN")
    await service.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_initialize_transaction_returns_checkout_details(service: PaystackService):
    respx.post(f"{PAYSTACK_API_BASE}/transaction/initialize").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": True,
                "message": "ok",
                "data": {
                    "authorization_url": "https://checkout.paystack.com/abc",
                    "access_code": "abc",
                    "reference": "ref_123",
                },
            },
        )
    )
    result = await service.initialize_transaction(
        email="a@b.com", amount=Decimal("99.00"), currency="NGN", callback_url="https://app/callback"
    )
    assert result["reference"] == "ref_123"
    assert result["authorization_url"] == "https://checkout.paystack.com/abc"
    await service.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_verify_transaction_returns_data(service: PaystackService):
    respx.get(f"{PAYSTACK_API_BASE}/transaction/verify/ref_123").mock(
        return_value=httpx.Response(200, json={"status": True, "message": "ok", "data": {"status": "success"}})
    )
    data = await service.verify_transaction("ref_123")
    assert data["status"] == "success"
    await service.aclose()


def test_webhook_signature_round_trip():
    import hashlib
    import hmac

    secret = "sk_test_abc"
    body = b'{"event":"charge.success"}'
    valid_sig = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()

    assert PaystackService.verify_webhook_signature(body, valid_sig, secret) is True
    assert PaystackService.verify_webhook_signature(body, "wrong", secret) is False
    assert PaystackService.verify_webhook_signature(body, None, secret) is False
