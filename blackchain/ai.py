"""Un piccolo classificatore testuale e un oracolo IA con attestazioni firmate.

Il classificatore ha pesi scelti manualmente: è un esempio didattico, non un
LLM addestrato. La firma prova chi ha attestato un risultato; non prova che
l'inferenza sia corretta. In catena rimane solo l'hash del testo, non il testo.
"""

from __future__ import annotations

import hashlib
import re
from types import MappingProxyType
from typing import Any

from .crypto import Wallet, canonical_bytes, digest, is_lower_hex, verify_signature


MAX_TEXT_BYTES = 16 * 1024
MAX_CHAIN_ID_BYTES = 128
LABELS = frozenset({"positivo", "negativo", "neutro"})
_TOKEN_PATTERN = r"[a-zà-öø-ÿ]+"
_TOKENIZER = re.compile(_TOKEN_PATTERN)
_WEIGHTS = MappingProxyType({
    "buono": 25,
    "bene": 20,
    "eccellente": 50,
    "ottimo": 40,
    "felice": 25,
    "fantastico": 45,
    "good": 25,
    "great": 40,
    "excellent": 50,
    "happy": 25,
    "love": 40,
    "cattivo": -25,
    "male": -20,
    "pessimo": -50,
    "triste": -25,
    "orribile": -45,
    "bad": -25,
    "terrible": -50,
    "sad": -25,
    "hate": -40,
})


def _validate_text(text: str) -> bytes:
    if type(text) is not str:
        raise TypeError("Il testo deve essere una stringa")
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_TEXT_BYTES:
        raise ValueError(f"Il testo supera il limite di {MAX_TEXT_BYTES} byte")
    return encoded


def _valid_chain_id(chain_id: Any) -> bool:
    if type(chain_id) is not str or not chain_id:
        return False
    try:
        return len(chain_id.encode("utf-8")) <= MAX_CHAIN_ID_BYTES
    except UnicodeEncodeError:
        return False


class TinySentimentModel:
    """Classificatore lineare a parole con punteggio intero in [-100, 100].

    Conta ogni parola, somma i pesi e limita il risultato all'intervallo.
    Non comprende negazioni, contesto o sarcasmo; i pesi non sono addestrati.
    """

    def __init__(self) -> None:
        specification = {
            "algorithm": "manual-word-sentiment-v1",
            "token_pattern": _TOKEN_PATTERN,
            "normalization": "str.casefold",
            "weights": dict(_WEIGHTS),
            "minimum": -100,
            "maximum": 100,
            "labels": {"positive": "positivo", "negative": "negativo", "zero": "neutro"},
        }
        self._model_hash = digest(specification)

    @property
    def model_hash(self) -> str:
        """Commitment SHA-256 dei parametri e delle regole del modello."""
        return self._model_hash

    def predict(self, text: str) -> dict[str, str | int]:
        _validate_text(text)
        score = sum(_WEIGHTS.get(token, 0) for token in _TOKENIZER.findall(text.casefold()))
        score = max(-100, min(100, score))
        label = "positivo" if score > 0 else "negativo" if score < 0 else "neutro"
        return {"label": label, "score": score}


class AIOracle:
    """Worker che pubblica risultati IA firmati per una specifica catena."""

    def __init__(self, wallet: Wallet, model: TinySentimentModel | None = None) -> None:
        if not isinstance(wallet, Wallet):
            raise TypeError("L'oracolo richiede un Wallet")
        self.wallet = wallet
        self.model = model if model is not None else TinySentimentModel()

    def attest(self, text: str, chain_id: str) -> dict[str, Any]:
        encoded = _validate_text(text)
        if not _valid_chain_id(chain_id):
            raise ValueError("chain_id deve essere una stringa non vuota di massimo 128 byte")
        statement = {
            "chain_id": chain_id,
            "worker": self.wallet.address,
            "request_hash": hashlib.sha256(encoded).hexdigest(),
            "model_hash": self.model.model_hash,
            "output": self.model.predict(text),
        }
        return {**statement, "attestation": self.wallet.sign(canonical_bytes(statement))}


def verify_attestation(
    payload: dict[str, Any],
    chain_id: str,
    authorized_workers: set[str],
    approved_models: set[str],
) -> bool:
    """Verifica schema, autorizzazioni e firma, non la correttezza dell'IA."""
    expected_fields = {"chain_id", "worker", "request_hash", "model_hash", "output", "attestation"}
    if type(payload) is not dict or set(payload) != expected_fields:
        return False
    if not _valid_chain_id(chain_id) or payload["chain_id"] != chain_id:
        return False
    if type(payload["chain_id"]) is not str:
        return False
    if not is_lower_hex(payload["worker"], 64):
        return False
    if not is_lower_hex(payload["request_hash"], 64):
        return False
    if not is_lower_hex(payload["model_hash"], 64):
        return False
    if not is_lower_hex(payload["attestation"], 128):
        return False
    if not isinstance(authorized_workers, (set, frozenset)):
        return False
    if not isinstance(approved_models, (set, frozenset)):
        return False
    if payload["worker"] not in authorized_workers or payload["model_hash"] not in approved_models:
        return False
    output = payload["output"]
    if type(output) is not dict or set(output) != {"label", "score"}:
        return False
    if type(output["label"]) is not str or output["label"] not in LABELS:
        return False
    score = output["score"]
    if type(score) is not int or not -100 <= score <= 100:
        return False
    expected_label = "positivo" if score > 0 else "negativo" if score < 0 else "neutro"
    if output["label"] != expected_label:
        return False
    statement = {key: value for key, value in payload.items() if key != "attestation"}
    return verify_signature(payload["worker"], canonical_bytes(statement), payload["attestation"])
