"""Registro PoS deterministico; nessun networking o finalità BFT è implementato."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ai import verify_attestation
from .crypto import Wallet, canonical_bytes, digest, is_lower_hex, verify_signature


MAX_INTEGER = 2**63 - 1
MAX_TRANSACTIONS = 100
MAX_TRANSACTION_BYTES = 32_768


class LedgerError(ValueError):
    """Transazione, configurazione o blocco non valido."""


def integer(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= MAX_INTEGER:
        raise LedgerError(f"{name}: intero richiesto tra {minimum} e {MAX_INTEGER}")
    return value


def schema(value: Any, keys: set[str], name: str) -> None:
    if type(value) is not dict or set(value) != keys:
        raise LedgerError(f"Schema {name} non valido")


def address(value: Any) -> str:
    if not is_lower_hex(value, 64):
        raise LedgerError("Indirizzo: chiave pubblica Ed25519 in hex richiesta")
    return value


@dataclass(frozen=True)
class Genesis:
    network: str
    allocations: tuple[tuple[str, int, int], ...]
    ai_workers: tuple[str, ...]
    ai_models: tuple[str, ...]
    block_reward: int = 5
    transaction_fee: int = 1
    minimum_stake: int = 1

    @classmethod
    def create(
        cls,
        allocations: dict[str, dict[str, int]],
        ai_workers: list[str],
        ai_models: list[str],
        network: str = "blackchain-local-v1",
        block_reward: int = 5,
        transaction_fee: int = 1,
        minimum_stake: int = 1,
    ) -> Genesis:
        if type(allocations) is not dict:
            raise LedgerError("allocations deve essere un dizionario")
        rows = []
        for owner, funds in allocations.items():
            schema(funds, {"balance", "stake"}, "allocazione")
            rows.append({"address": owner, **funds})
        return cls.from_dict({
            "network": network,
            "allocations": sorted(rows, key=lambda row: row["address"]),
            "ai_workers": sorted(ai_workers),
            "ai_models": sorted(ai_models),
            "block_reward": block_reward,
            "transaction_fee": transaction_fee,
            "minimum_stake": minimum_stake,
        })

    @classmethod
    def from_dict(cls, value: dict) -> Genesis:
        schema(value, {"network", "allocations", "ai_workers", "ai_models",
                       "block_reward", "transaction_fee", "minimum_stake"}, "genesis")
        network = value["network"]
        if type(network) is not str or not 1 <= len(network) <= 100:
            raise LedgerError("Nome rete non valido")
        minimum = integer(value["minimum_stake"], "minimum_stake", 1)
        reward = integer(value["block_reward"], "block_reward")
        fee = integer(value["transaction_fee"], "transaction_fee", 1)
        rows = value["allocations"]
        if type(rows) is not list or not rows:
            raise LedgerError("Allocazioni genesis mancanti")
        allocations = []
        for row in rows:
            schema(row, {"address", "balance", "stake"}, "allocazione")
            allocations.append((address(row["address"]),
                                integer(row["balance"], "balance"),
                                integer(row["stake"], "stake")))
        owners = [row[0] for row in allocations]
        if owners != sorted(set(owners)):
            raise LedgerError("Allocazioni duplicate o non ordinate")
        if not any(stake >= minimum for _, _, stake in allocations):
            raise LedgerError("Serve almeno un validatore con stake sufficiente")
        lists = []
        for name in ("ai_workers", "ai_models"):
            items = value[name]
            if type(items) is not list or any(not is_lower_hex(item, 64) for item in items):
                raise LedgerError(f"{name} non valido")
            if items != sorted(set(items)):
                raise LedgerError(f"{name} duplicati o non ordinati")
            lists.append(tuple(items))
        return cls(network, tuple(allocations), lists[0], lists[1], reward, fee, minimum)

    def to_dict(self) -> dict:
        return {
            "network": self.network,
            "allocations": [{"address": owner, "balance": balance, "stake": stake}
                            for owner, balance, stake in self.allocations],
            "ai_workers": list(self.ai_workers),
            "ai_models": list(self.ai_models),
            "block_reward": self.block_reward,
            "transaction_fee": self.transaction_fee,
            "minimum_stake": self.minimum_stake,
        }


@dataclass(frozen=True)
class Transaction:
    chain_id: str
    sender: str
    nonce: int
    kind: str
    data: dict
    signature: str

    def unsigned(self) -> dict:
        return {"chain_id": self.chain_id, "sender": self.sender, "nonce": self.nonce,
                "kind": self.kind, "data": copy.deepcopy(self.data)}

    def to_dict(self) -> dict:
        return {**self.unsigned(), "signature": self.signature}

    @property
    def txid(self) -> str:
        return digest(self.to_dict())

    @classmethod
    def create(cls, wallet: Wallet, chain_id: str, nonce: int, kind: str, data: dict) -> Transaction:
        body = {"chain_id": chain_id, "sender": wallet.address, "nonce": nonce,
                "kind": kind, "data": copy.deepcopy(data)}
        return cls.from_dict({**body, "signature": wallet.sign(canonical_bytes(body))})

    @classmethod
    def from_dict(cls, value: dict) -> Transaction:
        schema(value, {"chain_id", "sender", "nonce", "kind", "data", "signature"}, "transazione")
        if not is_lower_hex(value["chain_id"], 64):
            raise LedgerError("chain_id non valido")
        address(value["sender"])
        integer(value["nonce"], "nonce", 1)
        if type(value["kind"]) is not str or value["kind"] not in {"transfer", "stake", "unstake", "ai_result"}:
            raise LedgerError("Tipo transazione non supportato")
        if type(value["data"]) is not dict or not is_lower_hex(value["signature"], 128):
            raise LedgerError("Dati o firma non validi")
        try:
            if len(canonical_bytes(value)) > MAX_TRANSACTION_BYTES:
                raise LedgerError("Transazione troppo grande")
        except (TypeError, ValueError) as exc:
            raise LedgerError("Serializzazione transazione non valida") from exc
        return cls(value["chain_id"], value["sender"], value["nonce"], value["kind"],
                   copy.deepcopy(value["data"]), value["signature"])


@dataclass(frozen=True)
class Block:
    chain_id: str
    height: int
    previous_hash: str
    proposer: str
    transactions: tuple[Transaction, ...]
    state_root: str
    signature: str

    def unsigned(self) -> dict:
        return {"chain_id": self.chain_id, "height": self.height,
                "previous_hash": self.previous_hash, "proposer": self.proposer,
                "transactions": [tx.to_dict() for tx in self.transactions],
                "state_root": self.state_root}

    def to_dict(self) -> dict:
        return {**self.unsigned(), "signature": self.signature}

    @property
    def hash(self) -> str:
        return digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: dict) -> Block:
        schema(value, {"chain_id", "height", "previous_hash", "proposer", "transactions",
                       "state_root", "signature"}, "blocco")
        for name in ("chain_id", "previous_hash", "state_root"):
            if not is_lower_hex(value[name], 64):
                raise LedgerError(f"{name} non valido")
        integer(value["height"], "height", 1)
        address(value["proposer"])
        if not is_lower_hex(value["signature"], 128):
            raise LedgerError("Firma blocco non valida")
        transactions = value["transactions"]
        if type(transactions) is not list or len(transactions) > MAX_TRANSACTIONS:
            raise LedgerError("Numero transazioni non valido")
        return cls(value["chain_id"], value["height"], value["previous_hash"], value["proposer"],
                   tuple(Transaction.from_dict(tx) for tx in transactions),
                   value["state_root"], value["signature"])


@dataclass
class Account:
    balance: int = 0
    stake: int = 0
    nonce: int = 0

    def to_dict(self) -> dict:
        return {"balance": self.balance, "stake": self.stake, "nonce": self.nonce}


@dataclass
class State:
    accounts: dict[str, Account] = field(default_factory=dict)
    ai_results: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"accounts": {owner: self.accounts[owner].to_dict() for owner in sorted(self.accounts)},
                "ai_results": copy.deepcopy(self.ai_results)}

    @property
    def root(self) -> str:
        return digest(self.to_dict())


class Blockchain:
    """Un nodo locale: propone, verifica, applica e ricarica blocchi PoS."""

    def __init__(self, genesis: Genesis):
        # Revalidate also directly constructed dataclasses, then keep a private snapshot.
        self._genesis = Genesis.from_dict(genesis.to_dict())
        self._chain_id = digest(self._genesis.to_dict())
        self._state = State({owner: Account(balance, stake)
                             for owner, balance, stake in self._genesis.allocations})
        self._blocks: list[Block] = []
        self._pending: list[Transaction] = []

    @property
    def genesis(self) -> Genesis:
        return self._genesis

    @property
    def chain_id(self) -> str:
        return self._chain_id

    @property
    def height(self) -> int:
        return len(self._blocks)

    @property
    def tip_hash(self) -> str:
        return self._blocks[-1].hash if self._blocks else self.chain_id

    @property
    def state_root(self) -> str:
        return self._state.root

    @property
    def blocks(self) -> tuple[Block, ...]:
        return tuple(copy.deepcopy(self._blocks))

    @property
    def pending(self) -> tuple[Transaction, ...]:
        return tuple(copy.deepcopy(self._pending))

    @property
    def state(self) -> dict:
        return self._state.to_dict()

    def account(self, owner: str) -> dict:
        address(owner)
        return self._state.accounts.get(owner, Account()).to_dict()

    def next_nonce(self, owner: str) -> int:
        return self.account(owner)["nonce"] + 1 + sum(tx.sender == owner for tx in self._pending)

    def make_transaction(self, wallet: Wallet, kind: str, data: dict) -> Transaction:
        return Transaction.create(wallet, self.chain_id, self.next_nonce(wallet.address), kind, data)

    def expected_proposer(self) -> str:
        eligible = sorted((owner, account.stake) for owner, account in self._state.accounts.items()
                          if account.stake >= self._genesis.minimum_stake)
        total = sum(stake for _, stake in eligible)
        if not total:
            raise LedgerError("Nessun validatore attivo")
        seed = digest({"chain_id": self.chain_id, "previous_hash": self.tip_hash,
                       "height": self.height + 1})
        ticket = int(seed, 16) % total
        for owner, stake in eligible:
            if ticket < stake:
                return owner
            ticket -= stake
        raise AssertionError("Selezione PoS incoerente")

    def _apply_transaction(self, state: State, tx: Transaction, height: int) -> int:
        tx = Transaction.from_dict(tx.to_dict())
        if tx.chain_id != self.chain_id:
            raise LedgerError("Transazione destinata a un'altra rete")
        if not verify_signature(tx.sender, canonical_bytes(tx.unsigned()), tx.signature):
            raise LedgerError("Firma transazione non valida")
        sender = state.accounts.get(tx.sender)
        if sender is None or tx.nonce != sender.nonce + 1:
            raise LedgerError("Mittente sconosciuto o nonce non valido")
        fee = self._genesis.transaction_fee
        if tx.kind == "transfer":
            schema(tx.data, {"recipient", "amount"}, "transfer")
            recipient = address(tx.data["recipient"])
            amount = integer(tx.data["amount"], "amount", 1)
            if sender.balance < amount + fee:
                raise LedgerError("Saldo insufficiente")
            sender.balance -= amount + fee
            receiver = state.accounts.setdefault(recipient, Account())
            receiver.balance = integer(receiver.balance + amount, "balance")
        elif tx.kind == "stake":
            schema(tx.data, {"amount"}, "stake")
            amount = integer(tx.data["amount"], "amount", 1)
            if sender.balance < amount + fee:
                raise LedgerError("Saldo insufficiente per lo stake")
            sender.balance -= amount + fee
            sender.stake = integer(sender.stake + amount, "stake")
        elif tx.kind == "unstake":
            schema(tx.data, {"amount"}, "unstake")
            amount = integer(tx.data["amount"], "amount", 1)
            if sender.stake < amount or sender.balance < fee:
                raise LedgerError("Stake o saldo per commissione insufficienti")
            sender.stake -= amount
            sender.balance = integer(sender.balance - fee + amount, "balance")
        else:
            if not verify_attestation(tx.data, self.chain_id, set(self._genesis.ai_workers),
                                      set(self._genesis.ai_models)):
                raise LedgerError("Attestazione IA non valida o worker/modello non autorizzato")
            if sender.balance < fee:
                raise LedgerError("Saldo insufficiente per la commissione IA")
            sender.balance -= fee
            state.ai_results.append({"transaction_id": tx.txid, "height": height,
                                     "sender": tx.sender, "attestation": copy.deepcopy(tx.data)})
        sender.nonce = integer(sender.nonce + 1, "nonce")
        return fee

    def _execute(self, transactions: tuple[Transaction, ...], proposer: str | None = None) -> State:
        if len(transactions) > MAX_TRANSACTIONS:
            raise LedgerError("Troppe transazioni nel blocco")
        state = copy.deepcopy(self._state)
        ids = set()
        fees = 0
        for tx in transactions:
            if tx.txid in ids:
                raise LedgerError("Transazione duplicata")
            ids.add(tx.txid)
            fees += self._apply_transaction(state, tx, self.height + 1)
        if not any(account.stake >= self._genesis.minimum_stake for account in state.accounts.values()):
            raise LedgerError("Non è possibile rimuovere l'ultimo validatore attivo")
        if proposer is not None:
            winner = state.accounts[proposer]
            winner.balance = integer(winner.balance + fees + self._genesis.block_reward, "balance")
        return state

    def submit(self, transaction: Transaction) -> str:
        tx = Transaction.from_dict(transaction.to_dict())
        candidate = (*self._pending, tx)
        self._execute(candidate)
        self._pending.append(tx)
        return tx.txid

    def build_block(self, validator: Wallet, transactions: tuple[Transaction, ...] | None = None) -> Block:
        if validator.address != self.expected_proposer():
            raise LedgerError("Il wallet non è il validatore selezionato per questo blocco")
        txs = tuple(copy.deepcopy(self._pending if transactions is None else transactions))
        state = self._execute(txs, validator.address)
        body = {"chain_id": self.chain_id, "height": self.height + 1,
                "previous_hash": self.tip_hash, "proposer": validator.address,
                "transactions": [tx.to_dict() for tx in txs], "state_root": state.root}
        return Block.from_dict({**body, "signature": validator.sign(canonical_bytes(body))})

    def accept_block(self, block: Block) -> None:
        candidate = Block.from_dict(block.to_dict())
        if candidate.chain_id != self.chain_id or candidate.height != self.height + 1:
            raise LedgerError("Rete o altezza del blocco non valida")
        if candidate.previous_hash != self.tip_hash:
            raise LedgerError("Collegamento al blocco precedente non valido")
        if candidate.proposer != self.expected_proposer():
            raise LedgerError("Proponente non selezionato dal PoS")
        if not verify_signature(candidate.proposer, canonical_bytes(candidate.unsigned()), candidate.signature):
            raise LedgerError("Firma blocco non valida")
        next_state = self._execute(candidate.transactions, candidate.proposer)
        if next_state.root != candidate.state_root:
            raise LedgerError("State root non corrispondente alle transazioni")
        # Commit only after every transaction, signature and commitment has been checked.
        self._state = next_state
        self._blocks.append(candidate)
        included = {tx.txid for tx in candidate.transactions}
        remaining = [tx for tx in self._pending if tx.txid not in included]
        self._pending = []
        for tx in remaining:
            try:
                self.submit(tx)
            except LedgerError:
                pass  # Transactions made stale by a competing block leave the local mempool.

    def forge_block(self, validator: Wallet) -> Block:
        block = self.build_block(validator)
        self.accept_block(block)
        return block

    def export(self) -> dict:
        return {"version": 1, "genesis": self._genesis.to_dict(),
                "blocks": [block.to_dict() for block in self._blocks]}

    @classmethod
    def from_dict(cls, value: dict) -> Blockchain:
        schema(value, {"version", "genesis", "blocks"}, "archivio blockchain")
        if type(value["version"]) is not int or value["version"] != 1:
            raise LedgerError("Versione archivio non supportata")
        if type(value["blocks"]) is not list:
            raise LedgerError("Elenco blocchi non valido")
        chain = cls(Genesis.from_dict(value["genesis"]))
        for block in value["blocks"]:
            chain.accept_block(Block.from_dict(block))
        return chain

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent,
                                             prefix=".blackchain-", delete=False) as handle:
                temporary = handle.name
                json.dump(self.export(), handle, ensure_ascii=False, allow_nan=False, indent=2)
                handle.write("\n")
            os.replace(temporary, target)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    @classmethod
    def load(cls, path: str | Path, expected_chain_id: str | None = None) -> Blockchain:
        target = Path(path)
        if target.stat().st_size > 10 * 1024 * 1024:
            raise LedgerError("Archivio troppo grande per il prototipo (max 10 MiB)")

        def unique_keys(pairs: list) -> dict:
            result = {}
            for key, value in pairs:
                if key in result:
                    raise LedgerError("Chiave JSON duplicata nell'archivio")
                result[key] = value
            return result

        try:
            value = json.loads(target.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
            chain = cls.from_dict(value)
            if expected_chain_id is not None and expected_chain_id != chain.chain_id:
                raise LedgerError("Genesis diversa dalla Chain ID fidata")
            return chain
        except (TypeError, KeyError, json.JSONDecodeError) as exc:
            raise LedgerError("Archivio blockchain non valido") from exc
