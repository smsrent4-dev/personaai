"""Reliable SMTP email delivery for PersonaAI.
Email delivery must not crash authentication flows.
If SMTP is unavailable, the failure is logged and the caller can continue.
This is especially important in production environments such as Render,
where outbound SMTP connections can occasionally time out.
Requires:
    SMTP_HOST
    SMTP_PORT
    SMTP_USER
    SMTP_PASSWORD
    SMTP_FROM
    SMTP_TLS
Optional:
    SMTP_TIMEOUT
    SMTP_RETRIES
"""
import asyncio
import logging
from email.message import EmailMessage
from html import escape
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
        # Safe defaults if these settings don't exist yet.
        self.timeout = getattr(settings, "SMTP_TIMEOUT", 15)
        self.retries = getattr(settings, "SMTP_RETRIES", 2)
    @property
    def configured(self) -> bool:
        """Return True when enough SMTP configuration exists to attempt delivery."""
        return bool(self.host and self.sender)
    async def _send(
        self,
        to: str,
        subject: str,
        html_body: str,
    ) -> bool:
        """Send an email without allowing SMTP failure to crash the request.
        Returns:
            True  -> email was sent successfully.
            False -> email could not be sent.
        """
        if not self.configured:
            logger.warning(
                "SMTP is not configured; email to %s was not sent. "
                "Subject: %s",
                to,
                subject,
            )
            # Useful during local development.
            logger.debug("Email body:\n%s", html_body)
            return False
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(
            "This email requires an HTML-capable email client."
        )
        message.add_alternative(
            html_body,
            subtype="html",
        )
        for attempt in range(1, self.retries + 1):
            try:
                await aiosmtplib.send(
                    message,
                    hostname=self.host,
                    port=self.port,
                    username=self.user or None,
                    password=self.password or None,
                    start_tls=self.use_tls,
                    timeout=self.timeout,
                )
                logger.info(
                    "Email sent successfully to %s. Subject: %s",
                    to,
                    subject,
                )
                return True
            except (aiosmtplib.SMTPException, OSError, asyncio.TimeoutError) as exc:
                logger.warning(
                    "SMTP email attempt %s/%s failed for %s: %s",
                    attempt,
                    self.retries,
                    to,
                    exc,
                )
                if attempt < self.retries:
                    # Small delay before retrying.
                    await asyncio.sleep(1)
            except Exception:
                # Protect authentication flows from unexpected email-library
                # failures while preserving the full traceback in logs.
                logger.exception(
                    "Unexpected error while sending email to %s",
                    to,
                )
                return False
        logger.error(
            "Failed to send email to %s after %s attempt(s). "
            "Subject: %s",
            to,
            self.retries,
            subject,
        )
        return False
    async def send_verification_email(
        self,
        to: str,
        full_name: str,
        token: str,
    ) -> bool:
        """Send the account verification email."""
        safe_name = escape(full_name or "there")
        link = (
            f"{settings.FRONTEND_URL}"
            f"/verify-email?token={token}"
        )
        html = f"""
        <!DOCTYPE html>
        <html>
        <body>
            <p>Hi {safe_name},</p>
            <p>
                Welcome to {escape(settings.APP_NAME)}.
                Please verify your email address:
            </p>
            <p>
                <a href="{link}">
                    Verify my email
                </a>
            </p>
            <p>
                This verification link expires in 24 hours.
            </p>
            <p>
                If you did not create this account, you can safely ignore
                this email.
            </p>
        </body>
        </html>
        """
        return await self._send(
            to,
            f"Verify your {settings.APP_NAME} account",
            html,
        )
    async def send_password_reset_email(
        self,
        to: str,
        full_name: str,
        token: str,
    ) -> bool:
        """Send the password reset email."""
        safe_name = escape(full_name or "there")
        link = (
            f"{settings.FRONTEND_URL}"
            f"/reset-password?token={token}"
        )
        html = f"""
        <!DOCTYPE html>
        <html>
        <body>
            <p>Hi {safe_name},</p>
            <p>
                We received a request to reset your
                {escape(settings.APP_NAME)} password.
            </p>
            <p>
                <a href="{link}">
                    Reset my password
                </a>
            </p>
            <p>
                If you didn't request this, you can safely ignore this email.
                This link expires in 1 hour.
            </p>
        </body>
        </html>
        """
        return await self._send(
            to,
            f"Reset your {settings.APP_NAME} password",
            html,
        )
email_service = EmailService()