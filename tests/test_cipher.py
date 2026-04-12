"""Tests for the byte-shift cipher used by the Obfuscator tab.

The cipher logic is duplicated across obfus.py and main.py.  These tests
validate the round-trip property (encode → decode == identity) without
importing either GUI module (which require Windows-only modules like winreg
and Tkinter).
"""

from __future__ import annotations

import hashlib
import os

# ---------------------------------------------------------------------------
# Pure re-implementation of the cipher (copied from obfus.py / main.py)
# so we can test the algorithm in isolation on any platform.
# ---------------------------------------------------------------------------


def _generate_key_values(version_key: str) -> list[int]:
    h = hashlib.sha256(version_key.encode("utf-8")).digest()
    return [b % 64 for b in h[:8]]


def _process_bytes(data: bytes, key_values: list[int], mode: str) -> bytes:
    byte_values = list(data)
    pipe = len(key_values)
    master_sign = 1 if mode == "encode" else -1

    for i in range(pipe):
        next_values: list[int] = []
        internal_sign = (-1) ** i
        for j, current_byte in enumerate(byte_values):
            k_idx = (j + i) % pipe
            shift = key_values[k_idx] * internal_sign * master_sign
            next_values.append((current_byte + shift) % 256)
        byte_values = next_values

    return bytes(byte_values)


def encode_bytes(data: bytes, version_key: str) -> bytes:
    return _process_bytes(data, _generate_key_values(version_key), "encode")


def decode_bytes(data: bytes, version_key: str) -> bytes:
    return _process_bytes(data, _generate_key_values(version_key), "decode")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_round_trip_simple() -> None:
    """encode then decode must return the original bytes."""
    original = b"Hello, lab world!"
    key = "1.0.0"
    assert decode_bytes(encode_bytes(original, key), key) == original


def test_round_trip_empty() -> None:
    """Round-trip of empty bytes must still equal empty bytes."""
    assert decode_bytes(encode_bytes(b"", "key"), "key") == b""


def test_round_trip_binary_data() -> None:
    """Round-trip must work for arbitrary binary data."""
    original = bytes(range(256))
    key = "v2.3.1"
    assert decode_bytes(encode_bytes(original, key), key) == original


def test_encode_is_not_identity() -> None:
    """Encoded bytes must differ from the original (non-trivial transformation)."""
    original = b"some_payload_data"
    encoded = encode_bytes(original, "secret-key")
    assert encoded != original


def test_different_keys_produce_different_ciphertext() -> None:
    """The same plaintext encrypted with two different keys must produce different ciphertext."""
    original = b"test_data"
    enc1 = encode_bytes(original, "key_a")
    enc2 = encode_bytes(original, "key_b")
    assert enc1 != enc2


def test_wrong_key_does_not_decrypt() -> None:
    """Decoding with the wrong key must NOT recover the original plaintext."""
    original = b"top_secret"
    encoded = encode_bytes(original, "correct_key")
    assert decode_bytes(encoded, "wrong_key") != original


def test_generate_key_values_length() -> None:
    """Key derivation must always produce exactly 8 values."""
    kv = _generate_key_values("any-version-string")
    assert len(kv) == 8


def test_generate_key_values_range() -> None:
    """All derived key values must be in [0, 63]."""
    kv = _generate_key_values("test")
    assert all(0 <= v <= 63 for v in kv)


def test_generate_key_values_deterministic() -> None:
    """Key derivation must be deterministic for the same input."""
    kv1 = _generate_key_values("stable-key")
    kv2 = _generate_key_values("stable-key")
    assert kv1 == kv2


def test_round_trip_large_payload() -> None:
    """Round-trip must work for a larger payload (64 KB)."""
    original = os.urandom(65536)
    key = "large-payload-key"
    assert decode_bytes(encode_bytes(original, key), key) == original
