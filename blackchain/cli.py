"""Comandi locali per eseguire una demo e verificare un archivio."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ai import AIOracle, TinySentimentModel
from .core import Blockchain, Genesis, LedgerError
from .crypto import Wallet


def run_demo(text: str, output: Path) -> Blockchain:
    # Public, predictable keys are intentional: this demo must never hold real funds.
    wallets = {name: Wallet.from_seed(f"blackchain-demo-{name}".encode())
               for name in ("alice", "bob", "carol", "ai-worker")}
    model = TinySentimentModel()
    genesis = Genesis.create(
        allocations={
            wallets["alice"].address: {"balance": 1000, "stake": 700},
            wallets["bob"].address: {"balance": 1000, "stake": 300},
            wallets["carol"].address: {"balance": 250, "stake": 0},
        },
        ai_workers=[wallets["ai-worker"].address],
        ai_models=[model.model_hash],
    )
    chain = Blockchain(genesis)
    names = {wallet.address: name for name, wallet in wallets.items()}
    by_address = {wallet.address: wallet for wallet in wallets.values()}
    oracle = AIOracle(wallets["ai-worker"], model)
    receipt = oracle.attest(text, chain.chain_id)

    actions = [
        ("carol", "transfer", {"recipient": wallets["alice"].address, "amount": 30}),
        ("carol", "stake", {"amount": 50}),
        ("alice", "ai_result", receipt),
        ("carol", "unstake", {"amount": 20}),
    ]
    print("BlackChain AI — demo locale PoS (unità intere simulate)")
    print(f"Chain ID: {chain.chain_id}")
    for name, kind, data in actions:
        transaction = chain.make_transaction(wallets[name], kind, data)
        chain.submit(transaction)
        validator = by_address[chain.expected_proposer()]
        block = chain.forge_block(validator)
        print(f"Blocco {block.height}: {kind}, validatore {names[block.proposer]}, hash {block.hash[:16]}")

    chain.save(output)
    # Replay independently instead of trusting the in-memory state.
    restored = Blockchain.load(output, expected_chain_id=chain.chain_id)
    if restored.state_root != chain.state_root:
        raise LedgerError("La verifica dell'archivio non corrisponde allo stato locale")
    print(f"Risultato IA: {receipt['output']['label']} (score {receipt['output']['score']})")
    print("Saldi finali:")
    for name in ("alice", "bob", "carol"):
        account = chain.account(wallets[name].address)
        print(f"  {name}: saldo={account['balance']}, stake={account['stake']}, nonce={account['nonce']}")
    print(f"Archivio verificato: {output}")
    return chain


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Blockchain PoS locale con attestazioni IA")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Esegui trasferimento, stake, inferenza IA e unstake")
    demo.add_argument("--text", default="Questo progetto è ottimo e fantastico")
    demo.add_argument("--out", type=Path, default=Path("demo-chain.json"))
    verify = commands.add_parser("verify", help="Ricalcola firme, stake e stato da genesis")
    verify.add_argument("file", type=Path)
    verify.add_argument("--chain-id", help="Chain ID atteso, ottenuto da una fonte fidata")
    inspect = commands.add_parser("inspect", help="Verifica e mostra lo stato in JSON")
    inspect.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            run_demo(args.text, args.out)
        else:
            chain = Blockchain.load(args.file, expected_chain_id=getattr(args, "chain_id", None))
            if args.command == "verify":
                print(f"OK: {chain.height} blocchi validi, {len(chain.state['ai_results'])} risultati IA")
                print(f"Chain ID: {chain.chain_id}")
                print(f"State root: {chain.state_root}")
            else:
                print(json.dumps({"chain_id": chain.chain_id, "height": chain.height,
                                  "tip_hash": chain.tip_hash, "state_root": chain.state_root,
                                  "state": chain.state}, ensure_ascii=False, indent=2))
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1
    return 0
