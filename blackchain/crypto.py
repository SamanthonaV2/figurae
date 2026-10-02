"""Primitive crittografiche Ed25519 e serializzazione JSON canonica.

Le chiavi create da ``from_seed`` servono solo a demo e test riproducibili.
Per un wallet reale usare ``generate`` e custodire la chiave privata.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def _validate_json(value: Any) -> None:
    """Evita conversioni implicite di chiavi o oggetti non JSON."""
    if value is None or type(value) in (str, bool, int, float):
        return
    if type(value) is list:
        for item in value:
            _validate_json(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("Le chiavi JSON devono essere stringhe")
            _validate_json(item)
        return
    raise TypeError(f"Tipo non JSON: {type(value).__name__}")


def canonical_bytes(obj: Any) -> bytes:
    """JSON UTF-8 ordinato, senza spazi e senza NaN o infinito."""
    _validate_json(obj)
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest(obj: Any) -> str:
    """Impronta SHA-256 della rappresentazione canonica."""
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def is_lower_hex(value: Any, length: int) -> bool:
    """True solo per una stringa esadecimale minuscola della lunghezza data."""
    return (
        type(value) is str
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def is_hex(value: Any, length: int) -> bool:
    """Alias per il formato esadecimale canonico usato dal protocollo."""
    return is_lower_hex(value, length)


def verify_signature(public_key_hex: str, message: bytes, signature_hex: str) -> bool:
    """Verifica Ed25519; dati malformati e firme errate restituiscono False."""
    if not is_lower_hex(public_key_hex, 64) or not is_lower_hex(signature_hex, 128):
        return False
    if type(message) is not bytes:
        return False
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        key.verify(bytes.fromhex(signature_hex), message)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


@dataclass(frozen=True)
class Wallet:
    """Wallet minimo: l'indirizzo è la chiave pubblica Ed25519 in esadecimale."""

    _private_key: Ed25519PrivateKey

    @classmethod
    def generate(cls) -> Wallet:
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_seed(cls, seed: bytes) -> Wallet:
        """Generazione deterministica SOLO per demo/test, non per fondi reali."""
        if type(seed) is not bytes:
            raise TypeError("Il seed deve essere bytes")
        private_bytes = hashlib.sha256(seed).digest()
        return cls(Ed25519PrivateKey.from_private_bytes(private_bytes))

    @property
    def address(self) -> str:
        return self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ).hex()

    def sign(self, message: bytes) -> str:
        if type(message) is not bytes:
            raise TypeError("Il messaggio da firmare deve essere bytes")
        return self._private_key.sign(message).hex()
