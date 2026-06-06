import base64
import hashlib
import secrets
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7


DEFAULT_ENC_SEC_KEY = "OuoCdl8xQh/OX6LbmgLEtZxZrvnOmrubsMhPW1VPRjk="


@dataclass(frozen=True)
class EncryptionParts:
    salt_hex: str
    iv_hex: str
    ciphertext_b64: str

    def as_cryptojs_string(self) -> str:
        return f"{self.salt_hex}{self.iv_hex}{self.ciphertext_b64}"


def encrypt_cryptojs_compatible(
    plaintext: str,
    enc_sec_key: str = DEFAULT_ENC_SEC_KEY,
    *,
    salt: bytes | None = None,
    iv: bytes | None = None,
) -> EncryptionParts:
    """Match the CryptoJS AES-CBC/PBKDF2 helper used by the login page."""
    salt = salt if salt is not None else secrets.token_bytes(16)
    iv = iv if iv is not None else secrets.token_bytes(16)

    if len(salt) != 16:
        raise ValueError("salt must be exactly 16 bytes")
    if len(iv) != 16:
        raise ValueError("iv must be exactly 16 bytes")

    key = hashlib.pbkdf2_hmac(
        "sha1",
        enc_sec_key.encode("utf-8"),
        salt,
        1000,
        dklen=32,
    )

    padder = PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    return EncryptionParts(
        salt_hex=salt.hex(),
        iv_hex=iv.hex(),
        ciphertext_b64=base64.b64encode(ciphertext).decode("ascii"),
    )


def build_login_authorization(username: str, password: str) -> str:
    encrypted = encrypt_cryptojs_compatible(f"{username}:{password}")
    return f"Basic {encrypted.as_cryptojs_string()}"
