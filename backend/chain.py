"""Persistent adapter for the real, local BlackChain PoS demonstration.

Demo keys are public and reproducible. This ledger never represents FIG or
Ethereum balances, and it must never be used to custody real cryptocurrency.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any

from blackchain.ai import AIOracle, TinySentimentModel
from blackchain.core import Blockchain, Genesis, LedgerError, Transaction, integer, schema
from blackchain.crypto import Wallet


class ChainStore:
    """Own a validated ledger; commit memory only after an atomic disk write."""

    def __init__(self, data_dir: Path):
        self.lock = RLock()
        self.path = Path(data_dir) / "chain-state.json"
        self.wallets = {
            name: Wallet.from_seed(f"blackchain-demo-{name}".encode())
            for name in ("alice", "bob", "carol", "ai-worker")
        }
        self._names = {wallet.address: name for name, wallet in self.wallets.items()}
        self._by_address = {wallet.address: wallet for wallet in self.wallets.values()}
        self._oracle = AIOracle(self.wallets["ai-worker"], TinySentimentModel())
        with self.lock:
            if self.path.exists():
                self.chain = self._load()
            else:
                self.chain = self._demo()
                self._persist(self.chain)

    def _demo(self) -> Blockchain:
        genesis = Genesis.create(
            allocations={
                self.wallets["alice"].address: {"balance": 1000, "stake": 700},
                self.wallets["bob"].address: {"balance": 1000, "stake": 300},
                self.wallets["carol"].address: {"balance": 250, "stake": 0},
            },
            ai_workers=[self.wallets["ai-worker"].address],
            ai_models=[self._oracle.model.model_hash],
        )
        chain = Blockchain(genesis)
        receipt = self._oracle.attest("Questo progetto è ottimo e fantastico", chain.chain_id)
        for name, kind, data in (
            ("carol", "transfer", {"recipient": self.wallets["alice"].address, "amount": 30}),
            ("carol", "stake", {"amount": 50}),
            ("alice", "ai_result", receipt),
            ("carol", "unstake", {"amount": 20}),
        ):
            chain.submit(chain.make_transaction(self.wallets[name], kind, data))
            chain.forge_block(self._by_address[chain.expected_proposer()])
        return chain

    @staticmethod
    def _unique_keys(pairs: list[tuple[str, Any]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise LedgerError("Chiave JSON duplicata nello stato blockchain")
            result[key] = value
        return result

    def _load(self) -> Blockchain:
        if self.path.stat().st_size > 10 * 1024 * 1024:
            raise LedgerError("Stato blockchain troppo grande (massimo 10 MiB)")
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"), object_pairs_hook=self._unique_keys)
            schema(value, {"version", "archive", "pending"}, "stato blockchain")
            if type(value["version"]) is not int or value["version"] != 1:
                raise LedgerError("Versione stato blockchain non supportata")
            if type(value["pending"]) is not list:
                raise LedgerError("Elenco transazioni in attesa non valido")
            chain = Blockchain.from_dict(value["archive"])
            for transaction in value["pending"]:
                chain.submit(Transaction.from_dict(transaction))
            return chain
        except (TypeError, KeyError, json.JSONDecodeError, RecursionError) as exc:
            raise LedgerError("Stato blockchain locale non valido") from exc

    def _persist(self, chain: Blockchain) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".chain-state-", delete=False) as handle:
                temporary = handle.name
                json.dump({"version": 1, "archive": chain.export(),
                           "pending": [transaction.to_dict() for transaction in chain.pending]},
                          handle, ensure_ascii=False, allow_nan=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def _candidate(self) -> Blockchain:
        chain = Blockchain.from_dict(self.chain.export())
        for transaction in self.chain.pending:
            chain.submit(transaction)
        return chain

    def _wallet(self, name_or_address: str) -> Wallet:
        if type(name_or_address) is not str:
            raise LedgerError("Mittente: nome o indirizzo del wallet demo richiesto")
        wallet = self.wallets.get(name_or_address) or self._by_address.get(name_or_address)
        if wallet is None:
            raise LedgerError("Chiave privata non disponibile: scegli alice, bob o carol")
        return wallet

    def snapshot(self) -> dict:
        with self.lock:
            state = self.chain.state
            accounts = [{"address": owner, "name": self._names.get(owner, owner[:12]),
                         "controllable": owner in self._by_address, **account}
                        for owner, account in state["accounts"].items()]
            try:
                expected = self.chain.expected_proposer()
            except LedgerError:
                expected = None
            blocks = [{**block.to_dict(), "hash": block.hash} for block in self.chain.blocks]
            pending = [{**transaction.to_dict(), "txid": transaction.txid}
                       for transaction in self.chain.pending]
            return {
                "chain_id": self.chain.chain_id,
                "height": self.chain.height,
                "tip_hash": self.chain.tip_hash,
                "state_root": self.chain.state_root,
                "network": self.chain.genesis.network,
                "expected_proposer": expected,
                "expected_proposer_name": self._names.get(expected, expected[:12] if expected else None),
                "can_forge": expected in self._by_address,
                "accounts": accounts,
                "blocks": blocks,
                "pending": pending,
                "pending_count": len(pending),
                "ai_results": copy.deepcopy(state["ai_results"]),
                "total_stake": sum(account["stake"] for account in accounts),
                "total_balance": sum(account["balance"] for account in accounts),
                "transaction_count": sum(len(block["transactions"]) for block in blocks),
                "block_reward": self.chain.genesis.block_reward,
                "transaction_fee": self.chain.genesis.transaction_fee,
                "minimum_stake": self.chain.genesis.minimum_stake,
                "mode": "local-demo",
                "unit": "BCA demo",
            }

    def transaction(self, sender: str, kind: str, amount: Any = None,
                    recipient: str | None = None, text: str | None = None) -> dict:
        with self.lock:
            wallet = self._wallet(sender)
            if kind in ("transfer", "stake", "unstake"):
                data = {"amount": integer(amount, "amount", 1)}
                if kind == "transfer":
                    if type(recipient) is not str:
                        raise LedgerError("Destinatario richiesto")
                    data["recipient"] = self.wallets[recipient].address if recipient in self.wallets else recipient
            elif kind == "ai_result":
                if type(text) is not str or not text.strip():
                    raise LedgerError("Inserisci il testo per l'attestazione IA")
                try:
                    data = self._oracle.attest(text, self.chain.chain_id)
                except (TypeError, ValueError) as exc:
                    raise LedgerError(str(exc)) from exc
            else:
                raise LedgerError("Tipo transazione non supportato")
            candidate = self._candidate()
            txid = candidate.submit(candidate.make_transaction(wallet, kind, data))
            self._persist(candidate)
            self.chain = candidate
            return {"txid": txid, "pending_count": len(candidate.pending)}

    def forge(self) -> dict:
        with self.lock:
            candidate = self._candidate()
            wallet = self._by_address.get(candidate.expected_proposer())
            if wallet is None:
                raise LedgerError("La chiave del validatore selezionato non è disponibile in questa demo")
            block = candidate.forge_block(wallet)
            self._persist(candidate)
            self.chain = candidate
            return {**block.to_dict(), "hash": block.hash}

    def export(self) -> dict:
        with self.lock:
            return self.chain.export()

    def import_archive(self, value: Any) -> dict:
        with self.lock:
            try:
                candidate = Blockchain.from_dict(value)
            except (TypeError, KeyError, RecursionError) as exc:
                raise LedgerError("Archivio blockchain non valido") from exc
            self._persist(candidate)
            self.chain = candidate
            return self.snapshot()
