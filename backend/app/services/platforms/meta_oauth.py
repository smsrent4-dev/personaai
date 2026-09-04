from typing import Any

import httpx

from app.config import settings
from app.services.platforms.whatsapp_adapter import (
    WhatsAppAPIError,
    WhatsAppAdapter,
)

GRAPH_API_BASE = "https://graph.facebook.com"
GRAPH_TIMEOUT = 20.0


class MetaOAuthError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        meta_error_code: int | None = None,
        meta_error_subcode: int | None = None,
        fbtrace_id: str | None = None,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.meta_error_code = meta_error_code
        self.meta_error_subcode = meta_error_subcode
        self.fbtrace_id = fbtrace_id
        self.status_code = status_code

    def __str__(self) -> str:
        return self.message


def _graph_base_url() -> str:
    version = str(
        settings.META_GRAPH_API_VERSION
    ).strip()

    if not version:
        raise MetaOAuthError(
            "META_GRAPH_API_VERSION is not configured.",
            code="META_CONFIGURATION_ERROR",
        )

    return f"{GRAPH_API_BASE}/{version}"


def _get_oauth_redirect_uri() -> str:
    redirect_uri = getattr(
        settings,
        "META_OAUTH_REDIRECT_URI",
        "",
    )

    if not redirect_uri or not redirect_uri.strip():
        raise MetaOAuthError(
            "META_OAUTH_REDIRECT_URI is not configured.",
            code="META_CONFIGURATION_ERROR",
        )

    return redirect_uri.strip()


async def _graph_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        response = await client.request(
            method,
            path,
            params=params,
            json=json,
        )

    except httpx.TimeoutException as exc:
        raise MetaOAuthError(
            "Meta Graph API timed out. Please try again.",
            code="META_TIMEOUT",
        ) from exc

    except httpx.HTTPError as exc:
        raise MetaOAuthError(
            f"Unable to connect to Meta Graph API: {exc}",
            code="META_NETWORK_ERROR",
        ) from exc

    try:
        data = response.json()
    except ValueError:
        data = {}

    if not isinstance(data, dict):
        raise MetaOAuthError(
            "Meta Graph API returned an unexpected response.",
            code="META_INVALID_RESPONSE",
            status_code=response.status_code,
        )

    error = data.get("error")

    if response.status_code >= 400 or error:
        if isinstance(error, dict):
            meta_code = error.get("code")
            subcode = error.get("error_subcode")
            message = error.get(
                "message",
                "Meta request failed.",
            )
            fbtrace_id = error.get("fbtrace_id")

            if meta_code == 190:
                friendly = (
                    "Meta rejected the access token. "
                    "The token may be expired, invalid, or "
                    "was generated for a different Meta App."
                )
                error_code = "META_INVALID_ACCESS_TOKEN"

            elif meta_code == 100:
                friendly = (
                    "Meta could not access the requested WhatsApp "
                    "resource. The resource may not belong to this "
                    "token, the ID may be incorrect, or the required "
                    "WhatsApp permissions were not granted."
                )
                error_code = "META_RESOURCE_NOT_ACCESSIBLE"

            elif meta_code in {10, 200, 294}:
                friendly = (
                    "The Meta access token does not have permission "
                    "to access this WhatsApp resource. Make sure "
                    "the Embedded Signup flow granted the required "
                    "WhatsApp permissions."
                )
                error_code = "META_PERMISSION_DENIED"

            elif response.status_code == 429:
                friendly = (
                    "Meta temporarily rate-limited the request. "
                    "Please try again shortly."
                )
                error_code = "META_RATE_LIMITED"

            else:
                friendly = (
                    f"Meta rejected the request: {message}"
                )
                error_code = "META_API_ERROR"

            raise MetaOAuthError(
                friendly,
                code=error_code,
                meta_error_code=meta_code,
                meta_error_subcode=subcode,
                fbtrace_id=fbtrace_id,
                status_code=response.status_code,
            )

        raise MetaOAuthError(
            "Meta returned an unexpected error.",
            code="META_UNKNOWN_ERROR",
            status_code=response.status_code,
        )

    return data


async def exchange_code_for_token(
    code: str,
    redirect_uri: str,
) -> str:
    """
    Exchange the OAuth authorization code returned by Meta
    for an access token.
    """

    if not code or not code.strip():
        raise MetaOAuthError(
            "Meta did not provide an authorization code.",
            code="META_MISSING_CODE",
        )

    if not settings.META_APP_ID:
        raise MetaOAuthError(
            "META_APP_ID is not configured.",
            code="META_CONFIGURATION_ERROR",
        )

    if not settings.META_APP_SECRET:
        raise MetaOAuthError(
            "META_APP_SECRET is not configured.",
            code="META_CONFIGURATION_ERROR",
        )

    if not redirect_uri or not redirect_uri.strip():
        raise MetaOAuthError(
            "Meta OAuth redirect URI is missing.",
            code="META_MISSING_REDIRECT_URI",
        )

    redirect_uri = redirect_uri.strip()
    configured_redirect_uri = _get_oauth_redirect_uri()

    if redirect_uri != configured_redirect_uri:
        raise MetaOAuthError(
            (
                "The OAuth redirect URI does not match the "
                "configured Meta redirect URI."
            ),
            code="META_REDIRECT_URI_MISMATCH",
        )

    async with httpx.AsyncClient(
        base_url=_graph_base_url(),
        timeout=httpx.Timeout(GRAPH_TIMEOUT),
    ) as client:
        data = await _graph_request(
            client,
            "GET",
            "/oauth/access_token",
            params={
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,
                "redirect_uri": redirect_uri,
                "code": code.strip(),
            },
        )

    access_token = data.get("access_token")

    if not access_token:
        raise MetaOAuthError(
            (
                "Meta completed the code exchange but did not "
                "return an access token."
            ),
            code="META_TOKEN_MISSING",
        )

    return str(access_token).strip()


async def validate_access_token(
    access_token: str,
) -> dict[str, Any]:
    """
    Validate the Meta access token using /me.

    This only validates the token itself. It does NOT attempt
    to discover Business Manager businesses.
    """

    if not access_token or not access_token.strip():
        raise MetaOAuthError(
            "Meta access token is missing.",
            code="META_MISSING_ACCESS_TOKEN",
        )

    access_token = access_token.strip()

    async with httpx.AsyncClient(
        base_url=_graph_base_url(),
        timeout=httpx.Timeout(GRAPH_TIMEOUT),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    ) as client:
        data = await _graph_request(
            client,
            "GET",
            "/me",
            params={
                "fields": "id,name",
            },
        )

    if not data.get("id"):
        raise MetaOAuthError(
            "Meta returned an invalid access-token response.",
            code="META_INVALID_TOKEN_RESPONSE",
        )

    return data


async def _get_app_access_token() -> str:
    """
    Generate a Meta App Access Token.

    This token is used to call /debug_token against the
    Embedded Signup access token.
    """

    if not settings.META_APP_ID:
        raise MetaOAuthError(
            "META_APP_ID is not configured.",
            code="META_CONFIGURATION_ERROR",
        )

    if not settings.META_APP_SECRET:
        raise MetaOAuthError(
            "META_APP_SECRET is not configured.",
            code="META_CONFIGURATION_ERROR",
        )

    async with httpx.AsyncClient(
        base_url=_graph_base_url(),
        timeout=httpx.Timeout(GRAPH_TIMEOUT),
    ) as client:
        data = await _graph_request(
            client,
            "GET",
            "/oauth/access_token",
            params={
                "grant_type": "client_credentials",
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,
            },
        )

    app_access_token = data.get("access_token")

    if not app_access_token:
        raise MetaOAuthError(
            (
                "Meta did not return an App Access Token. "
                "Check META_APP_ID and META_APP_SECRET."
            ),
            code="META_APP_ACCESS_TOKEN_MISSING",
        )

    return str(app_access_token).strip()


async def discover_business_assets(
    access_token: str,
) -> dict[str, Any]:
    """
    Discover WhatsApp assets created/selected through
    Meta Embedded Signup.

    IMPORTANT:

    This function deliberately does NOT call:

        /me/businesses

    and does NOT call:

        /{business_id}/owned_whatsapp_business_accounts

    Those endpoints require Business Manager permissions that
    are not necessary for this Embedded Signup discovery flow.

    Instead:

        Embedded Signup access token
                    ↓
               /debug_token
                    ↓
             granular_scopes
                    ↓
      whatsapp_business_management
                    ↓
              target_ids
                    ↓
                  WABA
                    ↓
          /{waba_id}/phone_numbers
                    ↓
             Phone Number ID
    """

    if not access_token or not access_token.strip():
        raise MetaOAuthError(
            "Meta access token is missing.",
            code="META_MISSING_ACCESS_TOKEN",
        )

    access_token = access_token.strip()

    # ---------------------------------------------------------
    # 1. Validate the Embedded Signup access token.
    # ---------------------------------------------------------

    await validate_access_token(
        access_token,
    )

    # ---------------------------------------------------------
    # 2. Generate an App Access Token.
    #
    #    /debug_token requires the App Access Token.
    # ---------------------------------------------------------

    app_access_token = await _get_app_access_token()

    # ---------------------------------------------------------
    # 3. Create the WhatsApp adapter.
    #
    #    We don't know the phone number yet, so a temporary
    #    value is used until the WABA phone number is discovered.
    # ---------------------------------------------------------

    adapter = WhatsAppAdapter(
        phone_number_id="embedded-signup-discovery",
        access_token=access_token,
        graph_api_version=(
            settings.META_GRAPH_API_VERSION
        ),
    )

    try:
        # -----------------------------------------------------
        # 4. Get WABA IDs from the Embedded Signup token.
        #
        #    This reads:
        #
        #    granular_scopes
        #        ↓
        #    whatsapp_business_management
        #        ↓
        #    target_ids
        # -----------------------------------------------------

        try:
            waba_ids = (
                await adapter.get_embedded_signup_waba_ids(
                    app_access_token=app_access_token,
                )
            )

        except WhatsAppAPIError as exc:
            raise MetaOAuthError(
                (
                    "Meta authentication succeeded, but the "
                    "Embedded Signup token did not provide an "
                    "accessible WhatsApp Business Account. "
                    f"Meta said: {exc}"
                ),
                code="META_WABA_DISCOVERY_FAILED",
                meta_error_code=exc.error_code,
                meta_error_subcode=exc.error_subcode,
                fbtrace_id=exc.fbtrace_id,
                status_code=exc.status_code,
            ) from exc

        if not waba_ids:
            raise MetaOAuthError(
                (
                    "Meta authentication succeeded, but Embedded "
                    "Signup did not return a WhatsApp Business "
                    "Account ID."
                ),
                code="META_NO_WABA",
            )

        # -----------------------------------------------------
        # 5. Discover phone numbers belonging to the WABA(s).
        # -----------------------------------------------------

        candidates: list[dict[str, Any]] = []

        for waba_id in waba_ids:
            waba_id = str(waba_id).strip()

            if not waba_id:
                continue

            # -------------------------------------------------
            # Get WABA information.
            # -------------------------------------------------

            try:
                waba_info = await adapter.get_waba_info(
                    waba_id,
                )

            except WhatsAppAPIError:
                continue

            # -------------------------------------------------
            # Get phone numbers belonging to this WABA.
            # -------------------------------------------------

            try:
                phone_numbers = (
                    await adapter.get_waba_phone_numbers(
                        waba_id,
                    )
                )

            except WhatsAppAPIError:
                continue

            if not phone_numbers:
                continue

            for phone in phone_numbers:
                if not isinstance(phone, dict):
                    continue

                phone_id = phone.get("id")

                if not phone_id:
                    continue

                candidates.append(
                    {
                        "whatsapp_business_account_id": (
                            waba_id
                        ),
                        "waba_name": waba_info.get(
                            "name"
                        ),
                        "waba_currency": waba_info.get(
                            "currency"
                        ),
                        "waba_timezone_id": waba_info.get(
                            "timezone_id"
                        ),
                        "phone_number_id": str(
                            phone_id
                        ),
                        "display_phone_number": (
                            phone.get(
                                "display_phone_number"
                            )
                        ),
                        "verified_name": phone.get(
                            "verified_name"
                        ),
                        "quality_rating": phone.get(
                            "quality_rating"
                        ),
                        "messaging_limit_tier": phone.get(
                            "messaging_limit_tier"
                        ),
                        "code_verification_status": phone.get(
                            "code_verification_status"
                        ),
                        "platform_type": phone.get(
                            "platform_type"
                        ),
                    }
                )

        # -----------------------------------------------------
        # 6. Make sure at least one usable WhatsApp number
        #    was discovered.
        # -----------------------------------------------------

        if not candidates:
            raise MetaOAuthError(
                (
                    "Meta authentication succeeded and a "
                    "WhatsApp Business Account was found, but "
                    "no accessible WhatsApp phone number was "
                    "found. Complete Embedded Signup and make "
                    "sure the selected WhatsApp Business Account "
                    "has a phone number."
                ),
                code="META_NO_WHATSAPP_ASSET",
            )

        # -----------------------------------------------------
        # 7. Select the first usable phone number.
        #
        #    If your UI later allows the user to select a
        #    number, this list can be returned to the frontend
        #    instead of automatically selecting [0].
        # -----------------------------------------------------

        selected = candidates[0]

        selected_phone_number_id = selected[
            "phone_number_id"
        ]

        selected_waba_id = selected[
            "whatsapp_business_account_id"
        ]

        adapter.phone_number_id = (
            selected_phone_number_id
        )

        # -----------------------------------------------------
        # 8. Verify that the phone number is actually
        #    accessible using the Embedded Signup token.
        # -----------------------------------------------------

        try:
            phone_info = (
                await adapter.get_phone_number_info(
                    selected_phone_number_id,
                )
            )

        except WhatsAppAPIError as exc:
            raise MetaOAuthError(
                (
                    "Meta returned a WhatsApp phone number "
                    "during Embedded Signup, but the access "
                    "token could not access that phone number. "
                    f"Phone Number ID: "
                    f"{selected_phone_number_id}. "
                    f"WABA ID: {selected_waba_id}. "
                    f"Meta said: {exc}"
                ),
                code="META_PHONE_NUMBER_ACCESS_DENIED",
                meta_error_code=exc.error_code,
                meta_error_subcode=exc.error_subcode,
                fbtrace_id=exc.fbtrace_id,
                status_code=exc.status_code,
            ) from exc

        # -----------------------------------------------------
        # 9. Use the direct phone-number response as the
        #    authoritative information where available.
        # -----------------------------------------------------

        selected.update(
            {
                "verified_name": (
                    phone_info.get(
                        "verified_name"
                    )
                    or selected.get(
                        "verified_name"
                    )
                ),
                "display_phone_number": (
                    phone_info.get(
                        "display_phone_number"
                    )
                    or selected.get(
                        "display_phone_number"
                    )
                ),
                "quality_rating": (
                    phone_info.get(
                        "quality_rating"
                    )
                    or selected.get(
                        "quality_rating"
                    )
                ),
                "messaging_limit_tier": (
                    phone_info.get(
                        "messaging_limit_tier"
                    )
                    or selected.get(
                        "messaging_limit_tier"
                    )
                ),
                "code_verification_status": (
                    phone_info.get(
                        "code_verification_status"
                    )
                    or selected.get(
                        "code_verification_status"
                    )
                ),
                "platform_type": (
                    phone_info.get(
                        "platform_type"
                    )
                    or selected.get(
                        "platform_type"
                    )
                ),
            }
        )

        return selected

    finally:
        await adapter.aclose()