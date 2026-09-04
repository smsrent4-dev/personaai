import pytest

from app.core.crypto import decrypt_json, encrypt_json


def test_encrypt_decrypt_round_trip():
    data = {"bot_token": "123456:AAExampleTokenValue"}
    ciphertext = encrypt_json(data)
    assert ciphertext != str(data)
    assert "123456" not in ciphertext
    assert decrypt_json(ciphertext) == data


def test_empty_token_decrypts_to_empty_dict():
    assert decrypt_json("") == {}


def test_tampered_ciphertext_raises():
    ciphertext = encrypt_json({"bot_token": "abc"})
    tampered = ciphertext[:-4] + "abcd"
    with pytest.raises(ValueError):
        decrypt_json(tampered)
