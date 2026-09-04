"""SMTP email delivery for verification and password-reset emails.

Uses aiosmtplib so sending doesn't block the event loop. Requires
SMTP_* settings to be configured in .env for outbound mail to actually
leave the box — in APP_ENV=development with no SMTP_HOST configured we
log the email instead of raising, so local auth flows are testable
without a mail server.
"""
import logging
from email.message import EmailMessage

import aiosmtplib

from app.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    def __init__(self) -> None:
        self.host = settings.SMTP_HOST
        self.port = settings.SMTP_PORT
        self.user = settings.SMTP_USER
        self.password = settings.SMTP_PASSWORD
        self.sender = settings.SMTP_FROM
        self.use_tls = settings.SMTP_TLS

    async def _send(self, to: str, subject: str, html_body: str) -> None:
        if not self.host:
            # No SMTP configured (e.g. local dev) — log instead of failing the request.
            logger.warning("SMTP not configured; email to %s not sent. Subject: %s", to, subject)
            logger.debug("Email body:\n%s", html_body)
            return

        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content("This email requires an HTML-capable client.")
        message.add_alternative(html_body, subtype="html")

        await aiosmtplib.send(
            message,
            hostname=self.host,
            port=self.port,
            username=self.user or None,
            password=self.password or None,
            start_tls=self.use_tls,
        )

    async def send_verification_email(self, to: str, full_name: str, token: str) -> None:
        link = f"{settings.FRONTEND_URL}/verify-email?token={token}"
        html = f"""
        <p>Hi {full_name},</p>
        <p>Welcome to {settings.APP_NAME}. Please verify your email address:</p>
        <p><a href="{link}">Verify my email</a></p>
        <p>This link expires in 24 hours.</p>
        """
        await self._send(to, f"Verify your {settings.APP_NAME} account", html)

    async def send_password_reset_email(self, to: str, full_name: str, token: str) -> None:
        link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
        html = f"""
        <p>Hi {full_name},</p>
        <p>We received a request to reset your {settings.APP_NAME} password.</p>
        <p><a href="{link}">Reset my password</a></p>
        <p>If you didn't request this, you can safely ignore this email. This link expires in 1 hour.</p>
        """
        await self._send(to, f"Reset your {settings.APP_NAME} password", html)


email_service = EmailService()
