import mimetypes
from typing import Any

import httpx

from app.models.message import MessageType
from app.services.platforms.base import IncomingMessage, PlatformAdapter

GRAPH_API_BASE = "https://graph.facebook.com"


class WhatsAppAPIError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: int | None = None,
        error_subcode: int | None = None,
        error_type: str | None = None,
        fbtrace_id: str | None = None,
        error_data: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.error_subcode = error_subcode
        self.error_type = error_type
        self.fbtrace_id = fbtrace_id
        self.error_data = error_data or {}

    def __str__(self) -> str:
        return self.message


class WhatsAppAdapter(PlatformAdapter):
    platform_name = "whatsapp"

    def __init__(
        self,
        phone_number_id: str,
        access_token: str,
        graph_api_version: str = "v25.0",
        timeout: float = 20.0,
    ):
        phone_number_id = phone_number_id.strip()
        access_token = access_token.strip()
        graph_api_version = graph_api_version.strip()

        if not phone_number_id:
            raise WhatsAppAPIError(
                "WhatsApp Phone Number ID is required."
            )

        if not access_token:
            raise WhatsAppAPIError(
                "WhatsApp access token is required."
            )

        if not graph_api_version:
            raise WhatsAppAPIError(
                "Meta Graph API version is required."
            )

        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.graph_api_version = graph_api_version

        self._client = httpx.AsyncClient(
            base_url=(
                f"{GRAPH_API_BASE}/"
                f"{graph_api_version}"
            ),
            timeout=httpx.Timeout(timeout),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(
                method,
                path,
                params=params,
                json=json,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise WhatsAppAPIError(
                "Meta Graph API request timed out. Please try again.",
            ) from exc
        except httpx.HTTPError as exc:
            raise WhatsAppAPIError(
                f"Unable to reach Meta Graph API: {exc}",
            ) from exc

        try:
            data = response.json()
        except ValueError:
            data = {}

        if response.status_code >= 400:
            raise self._parse_error(
                response,
                data,
            )

        if isinstance(data, dict) and data.get("error"):
            raise self._parse_error(
                response,
                data,
            )

        if not isinstance(data, dict):
            raise WhatsAppAPIError(
                "Meta Graph API returned an unexpected response.",
                status_code=response.status_code,
            )

        return data

    @staticmethod
    def _parse_error(
        response: httpx.Response,
        data: dict[str, Any],
    ) -> WhatsAppAPIError:
        error = data.get("error")

        if not isinstance(error, dict):
            message = (
                data.get("message")
                or response.text
                or "Meta Graph API request failed."
            )

            return WhatsAppAPIError(
                message,
                status_code=response.status_code,
            )

        message = (
            error.get("message")
            or "Meta Graph API request failed."
        )

        return WhatsAppAPIError(
            message,
            status_code=response.status_code,
            error_code=error.get("code"),
            error_subcode=error.get("error_subcode"),
            error_type=error.get("type"),
            fbtrace_id=error.get("fbtrace_id"),
            error_data=error.get("error_data"),
        )

    @staticmethod
    def _error_message(
        error: WhatsAppAPIError,
        *,
        resource: str,
    ) -> str:
        code = error.error_code

        if code == 190:
            return (
                "The Meta access token is invalid, expired, or no "
                "longer authorized. Reconnect WhatsApp with Meta."
            )

        if code == 100:
            return (
                f"Meta could not access the requested {resource}. "
                "The ID may be incorrect, the access token may not "
                "have permission for this resource, or the resource "
                "may belong to another Meta Business or WABA."
            )

        if code in {10, 200, 294}:
            return (
                f"The Meta access token does not have permission to "
                f"access this {resource}. Make sure the token was "
                "generated by the correct Meta App and that the "
                "WhatsApp Business Account was shared with that app."
            )

        if error.status_code == 429:
            return (
                "Meta temporarily rate-limited this request. "
                "Please try again shortly."
            )

        if error.status_code in {401, 403}:
            return (
                f"Meta denied access to this {resource}. "
                "Reconnect WhatsApp and make sure the required "
                "WhatsApp permissions were granted."
            )

        return (
            f"Meta rejected the {resource} request: "
            f"{error.message}"
        )

    async def validate_access_token(
        self,
    ) -> dict[str, Any]:
        try:
            data = await self._request(
                "GET",
                "/me",
                params={
                    "fields": "id,name",
                },
            )

            if not data.get("id"):
                raise WhatsAppAPIError(
                    "Meta returned an invalid access-token response."
                )

            return data

        except WhatsAppAPIError as exc:
            raise WhatsAppAPIError(
                self._error_message(
                    exc,
                    resource="access token",
                ),
                status_code=exc.status_code,
                error_code=exc.error_code,
                error_subcode=exc.error_subcode,
                error_type=exc.error_type,
                fbtrace_id=exc.fbtrace_id,
                error_data=exc.error_data,
            ) from exc

    async def debug_access_token(
        self,
        app_access_token: str,
        input_token: str | None = None,
    ) -> dict[str, Any]:
        app_access_token = app_access_token.strip()

        if not app_access_token:
            raise WhatsAppAPIError(
                "Meta App access token is required to debug a user token."
            )

        input_token = (
            input_token.strip()
            if input_token
            else self.access_token
        )

        if not input_token:
            raise WhatsAppAPIError(
                "Meta user access token is required."
            )

        try:
            return await self._request(
                "GET",
                "/debug_token",
                params={
                    "input_token": input_token,
                    "access_token": app_access_token,
                },
            )
        except WhatsAppAPIError as exc:
            raise WhatsAppAPIError(
                f"Meta token validation failed: {exc}",
                status_code=exc.status_code,
                error_code=exc.error_code,
                error_subcode=exc.error_subcode,
                error_type=exc.error_type,
                fbtrace_id=exc.fbtrace_id,
                error_data=exc.error_data,
            ) from exc

    async def get_embedded_signup_waba_ids(
        self,
        app_access_token: str,
    ) -> list[str]:
        token_data = await self.debug_access_token(
            app_access_token=app_access_token,
        )

        data = token_data.get("data")

        if not isinstance(data, dict):
            raise WhatsAppAPIError(
                "Meta returned an invalid debug-token response."
            )

        if data.get("is_valid") is False:
            raise WhatsAppAPIError(
                "The Meta access token returned by Embedded Signup is invalid.",
                error_code=190,
            )

        granular_scopes = data.get("granular_scopes") or []

        if not isinstance(granular_scopes, list):
            raise WhatsAppAPIError(
                "Meta returned an invalid granular scopes response."
            )

        waba_ids: list[str] = []

        for scope in granular_scopes:
            if not isinstance(scope, dict):
                continue

            scope_name = scope.get("scope")

            if scope_name != "whatsapp_business_management":
                continue

            target_ids = scope.get("target_ids") or []

            if not isinstance(target_ids, list):
                continue

            for target_id in target_ids:
                if not target_id:
                    continue

                target_id = str(target_id)

                if target_id not in waba_ids:
                    waba_ids.append(target_id)

        if not waba_ids:
            raise WhatsAppAPIError(
                (
                    "Meta authentication succeeded, but the access "
                    "token does not contain a WhatsApp Business Account "
                    "target. Make sure the Embedded Signup configuration "
                    "includes whatsapp_business_management and that the "
                    "selected WhatsApp Business Account was shared with "
                    "the app."
                ),
                error_code=100,
            )

        return waba_ids

    async def get_phone_number_info(
        self,
        phone_number_id: str | None = None,
    ) -> dict[str, Any]:
        target_id = (
            phone_number_id.strip()
            if phone_number_id
            else self.phone_number_id
        )

        if not target_id:
            raise WhatsAppAPIError(
                "WhatsApp Phone Number ID is required."
            )

        try:
            return await self._request(
                "GET",
                f"/{target_id}",
                params={
                    "fields": (
                        "id,"
                        "verified_name,"
                        "display_phone_number,"
                        "quality_rating,"
                        "messaging_limit_tier,"
                        "code_verification_status,"
                        "platform_type"
                    )
                },
            )

        except WhatsAppAPIError as exc:
            raise WhatsAppAPIError(
                self._error_message(
                    exc,
                    resource="WhatsApp Phone Number",
                ),
                status_code=exc.status_code,
                error_code=exc.error_code,
                error_subcode=exc.error_subcode,
                error_type=exc.error_type,
                fbtrace_id=exc.fbtrace_id,
                error_data=exc.error_data,
            ) from exc

    async def get_waba_info(
        self,
        whatsapp_business_account_id: str,
    ) -> dict[str, Any]:
        whatsapp_business_account_id = (
            whatsapp_business_account_id.strip()
        )

        if not whatsapp_business_account_id:
            raise WhatsAppAPIError(
                "WhatsApp Business Account ID is required."
            )

        try:
            return await self._request(
                "GET",
                f"/{whatsapp_business_account_id}",
                params={
                    "fields": (
                        "id,"
                        "name,"
                        "currency,"
                        "timezone_id"
                    )
                },
            )

        except WhatsAppAPIError as exc:
            raise WhatsAppAPIError(
                self._error_message(
                    exc,
                    resource="WhatsApp Business Account",
                ),
                status_code=exc.status_code,
                error_code=exc.error_code,
                error_subcode=exc.error_subcode,
                error_type=exc.error_type,
                fbtrace_id=exc.fbtrace_id,
                error_data=exc.error_data,
            ) from exc

    async def get_waba_phone_numbers(
        self,
        whatsapp_business_account_id: str,
    ) -> list[dict[str, Any]]:
        whatsapp_business_account_id = (
            whatsapp_business_account_id.strip()
        )

        if not whatsapp_business_account_id:
            raise WhatsAppAPIError(
                "WhatsApp Business Account ID is required."
            )

        try:
            data = await self._request(
                "GET",
                f"/{whatsapp_business_account_id}/phone_numbers",
                params={
                    "fields": (
                        "id,"
                        "display_phone_number,"
                        "verified_name,"
                        "quality_rating,"
                        "messaging_limit_tier,"
                        "code_verification_status,"
                        "platform_type"
                    ),
                    "limit": 100,
                },
            )

        except WhatsAppAPIError as exc:
            raise WhatsAppAPIError(
                self._error_message(
                    exc,
                    resource=(
                        "WhatsApp Business Account phone numbers"
                    ),
                ),
                status_code=exc.status_code,
                error_code=exc.error_code,
                error_subcode=exc.error_subcode,
                error_type=exc.error_type,
                fbtrace_id=exc.fbtrace_id,
                error_data=exc.error_data,
            ) from exc

        numbers = data.get("data", [])

        if not isinstance(numbers, list):
            return []

        return numbers

    async def verify_phone_number_belongs_to_waba(
        self,
        whatsapp_business_account_id: str,
        phone_number_id: str,
    ) -> dict[str, Any]:
        numbers = await self.get_waba_phone_numbers(
            whatsapp_business_account_id
        )

        target_phone_number_id = str(
            phone_number_id
        ).strip()

        for number in numbers:
            if str(number.get("id")) == target_phone_number_id:
                return number

        raise WhatsAppAPIError(
            (
                f"Phone Number ID {target_phone_number_id} was not "
                f"found inside WhatsApp Business Account "
                f"{whatsapp_business_account_id}. The phone number "
                "and WABA may not belong together, or the access "
                "token cannot access that phone number."
            ),
            status_code=400,
            error_code=100,
        )

    async def subscribe_webhook(
        self,
        whatsapp_business_account_id: str,
    ) -> None:
        whatsapp_business_account_id = (
            whatsapp_business_account_id.strip()
        )

        if not whatsapp_business_account_id:
            raise WhatsAppAPIError(
                "WhatsApp Business Account ID is required."
            )

        try:
            data = await self._request(
                "POST",
                f"/{whatsapp_business_account_id}/subscribed_apps",
            )

        except WhatsAppAPIError as exc:
            raise WhatsAppAPIError(
                self._error_message(
                    exc,
                    resource=(
                        "WhatsApp Business Account webhook "
                        "subscription"
                    ),
                ),
                status_code=exc.status_code,
                error_code=exc.error_code,
                error_subcode=exc.error_subcode,
                error_type=exc.error_type,
                fbtrace_id=exc.fbtrace_id,
                error_data=exc.error_data,
            ) from exc

        if data.get("success") is not True:
            raise WhatsAppAPIError(
                f"Meta did not confirm webhook subscription: {data}"
            )

    async def _send(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return await self._request(
                "POST",
                f"/{self.phone_number_id}/messages",
                json=payload,
            )

        except WhatsAppAPIError as exc:
            raise WhatsAppAPIError(
                self._error_message(
                    exc,
                    resource="WhatsApp message",
                ),
                status_code=exc.status_code,
                error_code=exc.error_code,
                error_subcode=exc.error_subcode,
                error_type=exc.error_type,
                fbtrace_id=exc.fbtrace_id,
                error_data=exc.error_data,
            ) from exc

    async def send_text(
        self,
        external_conversation_id: str,
        text: str,
    ) -> None:
        for part in _split_for_whatsapp(text):
            await self._send(
                {
                    "messaging_product": "whatsapp",
                    "to": external_conversation_id,
                    "type": "text",
                    "text": {
                        "body": part,
                    },
                }
            )

    async def send_image(
        self,
        external_conversation_id: str,
        image_url: str,
        caption: str | None = None,
    ) -> None:
        image: dict[str, Any] = {
            "link": image_url,
        }

        if caption:
            image["caption"] = caption[:1024]

        await self._send(
            {
                "messaging_product": "whatsapp",
                "to": external_conversation_id,
                "type": "image",
                "image": image,
            }
        )

    async def send_photo(
        self,
        external_conversation_id: str,
        image_url: str,
        caption: str | None = None,
    ) -> None:
        await self.send_image(
            external_conversation_id,
            image_url,
            caption,
        )

    async def send_document(
        self,
        external_conversation_id: str,
        document_url: str,
        filename: str | None = None,
        caption: str | None = None,
    ) -> None:
        document: dict[str, Any] = {
            "link": document_url,
        }

        if filename:
            document["filename"] = filename

        if caption:
            document["caption"] = caption[:1024]

        await self._send(
            {
                "messaging_product": "whatsapp",
                "to": external_conversation_id,
                "type": "document",
                "document": document,
            }
        )

    async def send_audio(
        self,
        external_conversation_id: str,
        audio_url: str,
    ) -> None:
        await self._send(
            {
                "messaging_product": "whatsapp",
                "to": external_conversation_id,
                "type": "audio",
                "audio": {
                    "link": audio_url,
                },
            }
        )

    async def send_video(
        self,
        external_conversation_id: str,
        video_url: str,
        caption: str | None = None,
    ) -> None:
        video: dict[str, Any] = {
            "link": video_url,
        }

        if caption:
            video["caption"] = caption[:1024]

        await self._send(
            {
                "messaging_product": "whatsapp",
                "to": external_conversation_id,
                "type": "video",
                "video": video,
            }
        )

    async def send_location(
        self,
        external_conversation_id: str,
        latitude: float,
        longitude: float,
        name: str | None = None,
    ) -> None:
        location: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
        }

        if name:
            location["name"] = name

        await self._send(
            {
                "messaging_product": "whatsapp",
                "to": external_conversation_id,
                "type": "location",
                "location": location,
            }
        )

    async def send_contact(
        self,
        external_conversation_id: str,
        name: str,
        phone: str,
    ) -> None:
        await self._send(
            {
                "messaging_product": "whatsapp",
                "to": external_conversation_id,
                "type": "contacts",
                "contacts": [
                    {
                        "name": {
                            "formatted_name": name,
                            "first_name": name,
                        },
                        "phones": [
                            {
                                "phone": phone,
                            }
                        ],
                    }
                ],
            }
        )

    async def mark_read(
        self,
        external_message_id: str,
        show_typing: bool = False,
    ) -> None:
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": external_message_id,
        }

        if show_typing:
            payload["typing_indicator"] = {
                "type": "text",
            }

        await self._send(payload)

    async def download_media(
        self,
        media_id: str,
    ) -> tuple[bytes, str]:
        media_id = media_id.strip()

        if not media_id:
            raise WhatsAppAPIError(
                "WhatsApp media ID is required."
            )

        try:
            metadata = await self._request(
                "GET",
                f"/{media_id}",
            )

        except WhatsAppAPIError as exc:
            raise WhatsAppAPIError(
                self._error_message(
                    exc,
                    resource="WhatsApp media",
                ),
                status_code=exc.status_code,
                error_code=exc.error_code,
                error_subcode=exc.error_subcode,
                error_type=exc.error_type,
                fbtrace_id=exc.fbtrace_id,
                error_data=exc.error_data,
            ) from exc

        media_url = metadata.get("url")

        if not media_url:
            raise WhatsAppAPIError(
                f"Meta did not return a media URL for {media_id}."
            )

        try:
            response = await self._client.get(
                media_url,
                headers={
                    "Authorization": (
                        f"Bearer {self.access_token}"
                    ),
                },
            )

        except httpx.TimeoutException as exc:
            raise WhatsAppAPIError(
                "WhatsApp media download timed out."
            ) from exc

        except httpx.HTTPError as exc:
            raise WhatsAppAPIError(
                f"Unable to download WhatsApp media: {exc}"
            ) from exc

        if response.status_code >= 400:
            try:
                error_data = response.json()
            except ValueError:
                error_data = {}

            error = self._parse_error(
                response,
                error_data,
            )

            raise WhatsAppAPIError(
                self._error_message(
                    error,
                    resource="WhatsApp media",
                ),
                status_code=error.status_code,
                error_code=error.error_code,
                error_subcode=error.error_subcode,
                error_type=error.error_type,
                fbtrace_id=error.fbtrace_id,
                error_data=error.error_data,
            )

        mime_type = (
            metadata.get("mime_type")
            or response.headers.get("content-type")
            or "application/octet-stream"
        )

        mime_type = mime_type.split(
            ";",
            1,
        )[0].strip()

        return response.content, mime_type

    def parse_incoming(
        self,
        payload: dict,
    ) -> IncomingMessage | None:
        try:
            value = payload["entry"][0]["changes"][0]["value"]
        except (
            KeyError,
            IndexError,
            TypeError,
        ):
            return None

        messages = value.get("messages")

        if not messages:
            return None

        message = messages[0]

        contacts = value.get("contacts") or []
        contact = contacts[0] if contacts else {}

        external_conversation_id = message.get("from")

        if not external_conversation_id:
            return None

        common = {
            "external_conversation_id": (
                external_conversation_id
            ),
            "external_user_id": external_conversation_id,
            "external_user_name": (
                contact.get("profile", {}).get("name")
            ),
            "external_message_id": message.get("id"),
        }

        msg_type = message.get("type")

        if msg_type == "text":
            text = message.get(
                "text",
                {},
            ).get("body")

            return IncomingMessage(
                message_type=MessageType.TEXT,
                text=text,
                **common,
            )

        if msg_type == "image":
            image = message.get("image", {})

            return IncomingMessage(
                message_type=MessageType.IMAGE,
                text=image.get("caption"),
                media_file_id=image.get("id"),
                platform_metadata={
                    "mime_type": image.get("mime_type"),
                },
                **common,
            )

        if msg_type == "video":
            video = message.get("video", {})

            return IncomingMessage(
                message_type=MessageType.VIDEO,
                text=video.get("caption"),
                media_file_id=video.get("id"),
                platform_metadata={
                    "mime_type": video.get("mime_type"),
                },
                **common,
            )

        if msg_type == "document":
            document = message.get("document", {})

            return IncomingMessage(
                message_type=MessageType.DOCUMENT,
                text=document.get("caption"),
                media_file_id=document.get("id"),
                platform_metadata={
                    "filename": document.get("filename"),
                    "mime_type": document.get("mime_type"),
                },
                **common,
            )

        if msg_type == "audio":
            audio = message.get("audio", {})

            media_file_id = audio.get("id")

            if not media_file_id:
                return IncomingMessage(
                    message_type=MessageType.OTHER,
                    text=None,
                    platform_metadata={
                        "error": (
                            "WhatsApp audio message has no "
                            "media ID."
                        ),
                    },
                    **common,
                )

            return IncomingMessage(
                message_type=MessageType.VOICE,
                text=None,
                media_file_id=media_file_id,
                platform_metadata={
                    "mime_type": audio.get("mime_type"),
                    "voice": audio.get("voice", False),
                    "sha256": audio.get("sha256"),
                },
                **common,
            )

        if msg_type == "location":
            location = message.get(
                "location",
                {},
            )

            return IncomingMessage(
                message_type=MessageType.LOCATION,
                text=None,
                latitude=location.get("latitude"),
                longitude=location.get("longitude"),
                platform_metadata={
                    "name": location.get("name"),
                    "address": location.get("address"),
                },
                **common,
            )

        if msg_type == "contacts":
            people = message.get("contacts") or []
            first = people[0] if people else {}

            name = first.get(
                "name",
                {},
            ).get("formatted_name")

            phones = first.get("phones") or []

            phone = (
                phones[0].get("phone")
                if phones
                else None
            )

            return IncomingMessage(
                message_type=MessageType.CONTACT,
                text=(
                    f"Shared contact: {name} ({phone})"
                    if name
                    else "Shared a contact"
                ),
                platform_metadata={
                    "contacts": people,
                },
                **common,
            )

        if msg_type == "interactive":
            interactive = message.get(
                "interactive",
                {},
            )

            reply_type = interactive.get("type")

            if reply_type == "button_reply":
                reply = interactive.get(
                    "button_reply",
                    {},
                )

            elif reply_type == "list_reply":
                reply = interactive.get(
                    "list_reply",
                    {},
                )

            else:
                reply = None

            if reply is not None:
                return IncomingMessage(
                    message_type=MessageType.TEXT,
                    text=reply.get("title"),
                    platform_metadata={
                        "interactive_reply_id": (
                            reply.get("id")
                        ),
                        "interactive_type": reply_type,
                    },
                    **common,
                )

        return IncomingMessage(
            message_type=MessageType.OTHER,
            text=None,
            **common,
        )


def _split_for_whatsapp(
    text: str,
    limit: int = 4096,
) -> list[str]:
    if len(text) <= limit:
        return [text]

    return [
        text[index:index + limit]
        for index in range(0, len(text), limit)
    ]


def guess_mime_type(
    filename: str,
) -> str:
    return (
        mimetypes.guess_type(filename)[0]
        or "application/octet-stream"
    )