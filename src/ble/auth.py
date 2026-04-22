"""
Huami BLE authentication: AES-128 encrypted challenge-response.

Protocol flow:
1. Send 16-byte random nonce to watch
2. Watch encrypts nonce with Auth Key (AES-128 ECB), sends back
3. We verify response matches our local encryption
4. If match, send our encrypted version of watch's nonce
5. Watch verifies — connection authenticated

Reference: Gadgetbridge Huami crypto implementation + huami-token
"""

import logging
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)


def encrypt_aes_ecb(key: bytes, plaintext: bytes) -> bytes:
    """Encrypt 16 bytes using AES-128 ECB mode."""
    cipher = Cipher(algorithms.AES(key), mode=modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(plaintext) + encryptor.finalize()


def compute_auth_response(auth_key: bytes, nonce: bytes) -> bytes:
    """Compute authentication response: AES-128-ECB(auth_key, nonce)."""
    return encrypt_aes_ecb(auth_key, nonce)


def parse_auth_key(key_str: str) -> bytes:
    """Parse hex auth key string to bytes.

    Auth key is a 32-char hex string (16 bytes).
    huami-token outputs it in this format.
    """
    key_str = key_str.strip().replace(" ", "").replace(":", "")
    if len(key_str) != 32:
        raise ValueError(f"Auth key must be 32 hex chars, got {len(key_str)}")
    return bytes.fromhex(key_str)
