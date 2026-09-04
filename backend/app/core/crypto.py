"""Encrypts integration credentials (bot tokens, etc.) before they hit
the database, using Fernet (AES-128-CBC + HMAC) with a key derived from
SECRET_KEY. This means a raw database dump alone doesn't expose bot
tokens - you'd also need SECRET_KEY.

This is symmetric, application-level encryption, not envelope
encryption with a KMS/HSM. For a real production deployment handling
many customers' credentials, rotating to a managed key-management
service (AWS KMS, GCP KMS, HashiCorp Vault) is the next step up - noted
here rather than silently treated as equivalent.
"""
import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _derive_fernet_key() -> bytes:
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


_fernet = Fernet(_derive_fernet_key())


def encrypt_json(data: dict) -> str:
    plaintext = json.dumps(data).encode("utf-8")
    return _fernet.encrypt(plaintext).decode("utf-8")


def decrypt_json(token: str) -> dict:
    if not token:
        return {}
    try:
        plaintext = _fernet.decrypt(token.encode("utf-8"))
    except InvalidToken as exc:
        raise ValueError("Could not decrypt stored credentials - SECRET_KEY may have changed") from exc
    return json.loads(plaintext.decode("utf-8"))
