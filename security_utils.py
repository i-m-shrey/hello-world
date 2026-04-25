import os
import base64
from typing import Tuple, Optional

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except Exception:
    AESGCM = None  # cryptography may not be installed in this environment yet

# Fallback 32-byte key (base64) used if PORTAL_PASSWORD_KEY is not set.
# WARNING: Embedding keys in code is less secure. Replace in production.
FALLBACK_KEY_B64 = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="


def _get_key() -> bytes:
    key_b64 = os.getenv('PORTAL_PASSWORD_KEY', '').strip()
    if not key_b64:
        key_b64 = FALLBACK_KEY_B64  # fallback embedded key
    try:
        # Support raw 32-byte base64 or urlsafe base64
        # Normalize padding
        pad = '=' * (-len(key_b64) % 4)
        key = base64.urlsafe_b64decode((key_b64 + pad).encode())
    except Exception:
        # Try standard base64
        key = base64.b64decode(key_b64)
    if len(key) not in (16, 24, 32):
        # AES-GCM requires 128/192/256-bit keys; prefer 32
        raise RuntimeError('PORTAL_PASSWORD_KEY/FALLBACK_KEY must decode to 16/24/32 bytes (AES key)')
    return key


def encrypt_portal_password(plaintext: str) -> Tuple[str, str, str]:
    if AESGCM is None:
        raise RuntimeError('cryptography not installed; cannot encrypt')
    key = _get_key()
    aes = AESGCM(key)
    iv = os.urandom(12)
    # AAD can be None; AESGCM.encrypt returns ciphertext||tag
    ct = aes.encrypt(iv, plaintext.encode('utf-8'), None)
    # Split ciphertext and tag: last 16 bytes are tag
    tag = ct[-16:]
    ciph = ct[:-16]
    b64 = base64.b64encode
    return b64(ciph).decode(), b64(iv).decode(), b64(tag).decode()


def decrypt_portal_password(cipher_b64: str, iv_b64: str, tag_b64: str) -> Optional[str]:
    if not cipher_b64 or not iv_b64 or not tag_b64:
        return None
    if AESGCM is None:
        # cryptography not present; cannot decrypt
        return None
    key = _get_key()
    aes = AESGCM(key)
    b64 = base64.b64decode
    ciph = b64(cipher_b64)
    iv = b64(iv_b64)
    tag = b64(tag_b64)
    try:
        pt = aes.decrypt(iv, ciph + tag, None)
        return pt.decode('utf-8')
    except Exception:
        return None
