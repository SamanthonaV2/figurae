"""Integration tests exercise actual SQLite storage and signed ledger replay."""
from __future__ import annotations

import asyncio
import copy
import csv
import io
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import httpx

from backend.app import create_app
from blackchain.core import Blockchain, Genesis
from blackchain.crypto import Wallet


WALLET = "0x" + "1" * 40
TX_HASH = "0x" + "a" * 64
PASSWORD = "figurae-test-password"


class ConsoleAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.app = create_app(self.directory)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://testserver")
        # Restricted execution environments may block event-loop self-pipe
        # notifications from worker threads; a timer keeps socket-free tests live.
        async def timer():
            while True:
                await asyncio.sleep(0.01)
        self.timer = asyncio.create_task(timer())
        response = await self.client.post("/api/setup", json={"password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.csrf = {"X-CSRF-Token": response.json()["csrf_token"]}

    async def asyncTearDown(self):
        await self.client.aclose()
        self.timer.cancel()
        try:
            await self.timer
        except asyncio.CancelledError:
            pass
        self.temporary.cleanup()

    async def sale(self, **overrides):
        payload = {"customer": "Cliente", "wallet_address": WALLET, "quantity": "10",
                   "unit_price_eur": "0.025", "payment_currency": "EUR", "notes": ""}
        payload.update(overrides)
        return await self.client.post("/api/sales", json=payload, headers=self.csrf)

    async def delivery(self, sale_id: int, **overrides):
        payload = {"tx_hash": TX_HASH, "chain_id": 11155111, "contract_address": "0x" + "3" * 40}
        payload.update(overrides)
        return await self.client.post(f"/api/sales/{sale_id}/delivery", json=payload, headers=self.csrf)

    async def test_private_endpoints_and_csrf(self):
        anonymous = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://testserver")
        try:
            self.assertEqual((await anonymous.get("/api/health")).json(), {"ok": True})
            self.assertEqual((await anonymous.get("/api/session")).json(), {"authenticated": False, "setup_required": False})
            for path in ("/api/overview", "/api/chain", "/api/token", "/api/artifact", "/api/settings",
                         "/api/sales", "/api/prices", "/api/whitepaper", "/api/backup", "/api/contract/source"):
                with self.subTest(path=path):
                    self.assertEqual((await anonymous.get(path)).status_code, 401)
            result = await self.client.post("/api/prices", json={"price_eur": "1", "source": "manuale"})
            self.assertEqual(result.status_code, 403)
            result = await self.client.post("/api/prices", json={"price_eur": "1", "source": "manuale"}, headers={"X-CSRF-Token": "wrong"})
            self.assertEqual(result.status_code, 403)
        finally:
            await anonymous.aclose()

    async def test_origin_and_host_rejection_including_login(self):
        for path, payload in (("/api/login", {"password": PASSWORD}), ("/api/setup", {"password": PASSWORD}),
                              ("/api/prices", {"price_eur": "1", "source": "manuale"})):
            result = await self.client.post(path, json=payload, headers={**self.csrf, "Origin": "https://attacker.example"})
            self.assertEqual(result.status_code, 403)
        self.assertEqual((await self.client.get("/api/session", headers={"Host": "attacker.example"})).status_code, 400)
        same = await self.client.get("/api/session", headers={"Origin": "http://testserver"})
        self.assertEqual(same.status_code, 200)

    async def test_session_cookie_logout_and_login(self):
        self.assertIn("figurae_session", self.client.cookies)
        session = (await self.client.get("/api/session")).json()
        self.assertEqual(session["csrf_token"], self.csrf["X-CSRF-Token"])
        result = await self.client.post("/api/logout", headers=self.csrf)
        self.assertEqual(result.status_code, 200)
        self.assertEqual((await self.client.get("/api/overview")).status_code, 401)
        result = await self.client.post("/api/login", json={"password": PASSWORD})
        self.assertEqual(result.status_code, 200)
        cookie = result.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        self.assertNotEqual(result.json()["csrf_token"], self.csrf["X-CSRF-Token"])
        self.assertEqual((await self.client.post("/api/setup", json={"password": PASSWORD})).status_code, 409)

    async def test_password_hash_and_login_throttling(self):
        with self.app.state.store.db() as db:
            password = self.app.state.store.get(db, "password")
            self.assertNotEqual(password["hash"], PASSWORD)
            self.assertGreaterEqual(password["iterations"], 600000)
            self.assertNotIn(PASSWORD, json.dumps(password))
        await self.client.post("/api/logout", headers=self.csrf)
        for _ in range(6):
            self.assertEqual((await self.client.post("/api/login", json={"password": "wrong"})).status_code, 401)
        self.assertEqual((await self.client.post("/api/login", json={"password": PASSWORD})).status_code, 429)

    async def test_initial_token_and_honest_empty_market(self):
        overview = (await self.client.get("/api/overview")).json()
        token = overview["token"]
        self.assertEqual(token["max_supply"], "100000000000")
        self.assertEqual(token["founders_supply"], "30000000000")
        self.assertEqual(token["distribution_supply"], "70000000000")
        self.assertEqual(overview["prices"], [])
        self.assertIsNone(overview["stats"]["price_eur"])
        self.assertIsNone(overview["stats"]["price_change_pct"])
        self.assertEqual(overview["stats"]["revenue_eur"], "0")
        self.assertEqual(overview["blockchain"]["height"], 4)
        artifact = (await self.client.get("/api/artifact")).json()
        self.assertIsInstance(artifact["abi"], list)
        self.assertTrue(artifact["bytecode"].startswith("0x"))

    async def test_settings_allocation_and_wallet_validation(self):
        invalid = [
            {"founders": [{"address": WALLET, "bps": 2999}]},
            {"founders": [{"address": WALLET, "bps": 1500}, {"address": WALLET, "bps": 1500}]},
            {"founders": [{"address": WALLET, "bps": 3000}], "distribution_wallet": WALLET},
            {"contract_address": "not-a-wallet"}, {"contract_address": "0x" + "0" * 40},
            {"unknown": "value"}, {"chain_id": 1.5},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertEqual((await self.client.patch("/api/settings", json=payload, headers=self.csrf)).status_code, 422)
        result = await self.client.patch("/api/settings", json={"founders": [{"address": WALLET, "bps": 1000},
                     {"address": "0x" + "2" * 40, "bps": 2000}], "distribution_wallet": "0x" + "3" * 40}, headers=self.csrf)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(sum(f["bps"] for f in result.json()["founders"]), 3000)

    async def test_exact_decimal_product_and_rejection(self):
        response = await self.sale(quantity="1234567890.123456789012345678", unit_price_eur="0.123456789012345678")
        self.assertEqual(response.status_code, 200)
        # Exact integer product of both amounts scaled by 10**18.
        self.assertEqual(response.json()["total_eur"], "152415787.532388366392318256527968299765279684")
        for amount in ("0", "-1", "1e6", "01", "0.1234567890123456789", 0.1, True):
            with self.subTest(amount=amount):
                self.assertEqual((await self.sale(quantity=amount)).status_code, 422)

    async def test_distribution_capacity_and_cancellation_release(self):
        sale = (await self.sale(quantity="70000000000")).json()
        self.assertEqual((await self.sale(quantity="0.000000000000000001")).status_code, 409)
        result = await self.client.patch(f"/api/sales/{sale['id']}", json={"status": "cancelled"}, headers=self.csrf)
        self.assertEqual(result.status_code, 200)
        self.assertEqual((await self.sale(quantity="70000000000")).status_code, 200)
        self.assertEqual((await self.sale(quantity="70000000001")).status_code, 409)

    async def test_sales_transitions_and_delivery_hash(self):
        sale = (await self.sale(payment_currency="QNT")).json()
        endpoint = f"/api/sales/{sale['id']}"
        self.assertEqual((await self.client.patch(endpoint, json={"status": "completed", "tx_hash": TX_HASH}, headers=self.csrf)).status_code, 409)
        self.assertEqual((await self.client.patch(endpoint, json={"status": "paid", "payment_reference": "manual-ref"}, headers=self.csrf)).status_code, 200)
        self.assertEqual((await self.client.patch(endpoint, json={"status": "completed"}, headers=self.csrf)).status_code, 422)
        self.assertEqual((await self.delivery(sale["id"])).status_code, 200)
        completed = await self.client.patch(endpoint, json={"status": "completed", "tx_hash": TX_HASH}, headers=self.csrf)
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.json()["payment_reference"], "manual-ref")
        self.assertEqual((await self.client.patch(endpoint, json={"status": "cancelled"}, headers=self.csrf)).status_code, 409)
        second = (await self.sale()).json()
        await self.client.patch(f"/api/sales/{second['id']}", json={"status": "paid"}, headers=self.csrf)
        self.assertEqual((await self.delivery(second["id"], tx_hash="0x" + "A" * 64)).status_code, 409)
        stats = (await self.client.get("/api/overview")).json()["stats"]
        self.assertEqual(stats["sold_tokens"], "10")
        self.assertEqual(stats["reserved_tokens"], "20")
        self.assertEqual(stats["revenue_eur"], "0.5")

    async def test_submitted_delivery_is_idempotent_persistent_and_unique(self):
        sale = (await self.sale()).json()
        endpoint = f"/api/sales/{sale['id']}"
        self.assertEqual((await self.delivery(sale["id"])).status_code, 409)
        await self.client.patch(endpoint, json={"status": "paid"}, headers=self.csrf)
        for invalid in ({"tx_hash": "bad"}, {"chain_id": 0}, {"chain_id": 1.5}, {"contract_address": "0x" + "0" * 40}):
            self.assertEqual((await self.delivery(sale["id"], **invalid)).status_code, 422)
        recorded = await self.delivery(sale["id"])
        self.assertEqual(recorded.status_code, 200)
        self.assertEqual(recorded.json()["status"], "paid")
        self.assertEqual(recorded.json()["tx_hash"], TX_HASH)
        self.assertEqual(recorded.json()["delivery_chain_id"], 11155111)
        self.assertEqual(recorded.json()["delivery_contract"], "0x" + "3" * 40)
        self.assertEqual((await self.client.patch(endpoint, json={"status": "cancelled"}, headers=self.csrf)).status_code, 409)
        self.assertEqual((await self.delivery(sale["id"])).json(), recorded.json())
        self.assertEqual((await self.delivery(sale["id"], tx_hash="0x" + "b" * 64)).status_code, 409)
        self.assertEqual((await self.delivery(sale["id"], chain_id=1)).status_code, 409)
        self.assertEqual((await self.delivery(sale["id"], contract_address="0x" + "4" * 40)).status_code, 409)
        duplicate = (await self.sale()).json()
        await self.client.patch(f"/api/sales/{duplicate['id']}", json={"status": "paid"}, headers=self.csrf)
        self.assertEqual((await self.delivery(duplicate["id"])).status_code, 409)
        restarted = create_app(self.directory)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url="http://testserver", cookies=self.client.cookies) as client:
            rows = (await client.get("/api/sales")).json()
            restored = next(row for row in rows if row["id"] == sale["id"])
            self.assertEqual(restored["status"], "paid")
            self.assertEqual(restored["tx_hash"], TX_HASH)
            self.assertEqual(restored["delivery_chain_id"], 11155111)
            bad = await client.patch(endpoint, json={"status": "completed", "tx_hash": "0x" + "b" * 64}, headers=self.csrf)
            self.assertEqual(bad.status_code, 409)
            done = await client.patch(endpoint, json={"status": "completed", "tx_hash": TX_HASH}, headers=self.csrf)
            self.assertEqual(done.status_code, 200)
            self.assertEqual(done.json()["status"], "completed")

    async def test_csv_exports_escape_spreadsheet_formulas(self):
        await self.sale(customer="=HYPERLINK(\"https://evil.example\")", notes="\t=1+1")
        response = await self.client.get("/api/sales/export.csv")
        self.assertEqual(response.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(response.text.lstrip("\ufeff"))))
        self.assertTrue(rows[0]["customer"].startswith("'="))
        self.assertTrue(rows[0]["notes"].startswith("'\t"))
        await self.client.post("/api/prices", json={"price_eur": "1", "source": "@formula"}, headers=self.csrf)
        result = await self.client.get("/api/prices/export.csv")
        self.assertIn("'@formula", result.text)

    async def test_prices_persist_manual_source_and_change(self):
        for price in ("0.000000000000000002", "0.000000000000000003"):
            response = await self.client.post("/api/prices", json={"price_eur": price, "source": "annotazione manuale"}, headers=self.csrf)
            self.assertEqual(response.status_code, 200)
        overview = (await self.client.get("/api/overview")).json()
        self.assertEqual(overview["stats"]["price_change_pct"], "50")
        self.assertEqual(overview["prices"][0]["source"], "annotazione manuale")
        self.assertEqual((await self.client.post("/api/prices", json={"price_eur": "0", "source": "manuale"}, headers=self.csrf)).status_code, 422)

    async def test_chain_signed_transfer_and_forge(self):
        initial = (await self.client.get("/api/chain")).json()
        result = await self.client.post("/api/chain/transactions", json={"sender": "alice", "kind": "transfer", "recipient": "bob", "amount": 20}, headers=self.csrf)
        self.assertEqual(result.status_code, 200)
        pending = (await self.client.get("/api/chain")).json()
        self.assertEqual(pending["height"], 4)
        self.assertEqual(len(pending["pending"]), 1)
        self.assertEqual(len(pending["pending"][0]["signature"]), 128)
        forged = await self.client.post("/api/chain/forge", json={}, headers=self.csrf)
        self.assertEqual(forged.status_code, 200)
        archive = (await self.client.get("/api/chain/export")).json()
        replay = Blockchain.from_dict(archive)
        self.assertEqual(replay.height, 5)
        self.assertNotEqual(replay.state_root, initial["state_root"])
        self.assertEqual(len((await self.client.get("/api/chain")).json()["pending"]), 0)

    async def test_chain_import_replays_signatures_atomically(self):
        archive = (await self.client.get("/api/chain/export")).json()
        initial = (await self.client.get("/api/chain")).json()
        await self.client.post("/api/chain/transactions", json={"sender": "alice", "kind": "stake", "amount": 5}, headers=self.csrf)
        tampered = copy.deepcopy(archive)
        tampered["blocks"][0]["state_root"] = "0" * 64
        invalid = await self.client.post("/api/chain/import", json=tampered, headers=self.csrf)
        self.assertEqual(invalid.status_code, 400)
        current = (await self.client.get("/api/chain")).json()
        self.assertEqual(current["state_root"], initial["state_root"])
        self.assertEqual(len(current["pending"]), 1)
        valid = await self.client.post("/api/chain/import", json=archive, headers=self.csrf)
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.json()["pending"], [])

    async def test_external_genesis_cannot_forge_without_private_key(self):
        wallet = Wallet.from_seed(b"unavailable-external-demo-key")
        genesis = Genesis.create({wallet.address: {"balance": 1000, "stake": 500}}, [], [])
        archive = Blockchain(genesis).export()
        imported = await self.client.post("/api/chain/import", json=archive, headers=self.csrf)
        self.assertEqual(imported.status_code, 200)
        self.assertFalse(imported.json()["can_forge"])
        self.assertEqual((await self.client.post("/api/chain/forge", json={}, headers=self.csrf)).status_code, 400)

    async def test_persistent_restart_retains_chain_pending_sales_and_login(self):
        sale = (await self.sale(quantity="2.000000000000000001")).json()
        await self.client.post("/api/prices", json={"price_eur": "0.4", "source": "manuale"}, headers=self.csrf)
        await self.client.post("/api/chain/transactions", json={"sender": "alice", "kind": "transfer", "recipient": "bob", "amount": 4}, headers=self.csrf)
        restarted = create_app(self.directory)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url="http://testserver", cookies=self.client.cookies) as client:
            self.assertTrue((await client.get("/api/session")).json()["authenticated"])
            self.assertEqual((await client.get("/api/sales")).json()[0]["quantity"], sale["quantity"])
            self.assertEqual((await client.get("/api/overview")).json()["stats"]["price_eur"], "0.4")
            chain = (await client.get("/api/chain")).json()
            self.assertEqual(chain["height"], 4)
            self.assertEqual(len(chain["pending"]), 1)
            self.assertEqual((await client.post("/api/chain/forge", json={}, headers=self.csrf)).status_code, 200)

    async def test_atomic_chain_disk_failure_does_not_change_memory(self):
        store = self.app.state.chain_store
        previous = store.snapshot()
        with patch.object(store, "_persist", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                store.transaction("alice", "stake", amount=5)
        self.assertEqual(store.snapshot(), previous)

    async def test_whitepaper_real_tokenomics_and_version(self):
        original = (await self.client.get("/api/whitepaper")).json()
        fields = original["fields"]
        fields["mission"] = "Missione personalizzata"
        response = await self.client.put("/api/whitepaper", json={"fields": fields}, headers=self.csrf)
        self.assertEqual(response.status_code, 200)
        paper = response.json()
        self.assertEqual(paper["version"], original["version"] + 1)
        for text in ("100.000.000.000 FIG", "30.000.000.000 FIG (30%)", "70.000.000.000 FIG (70%)",
                     "locale e separato", "branding", "non gira su QNT", "Missione personalizzata"):
            self.assertIn(text, paper["markdown"])
        exported = await self.client.get("/api/whitepaper/export.md")
        self.assertEqual(exported.text, paper["markdown"])
        self.assertIn("attachment", exported.headers["content-disposition"])

    async def test_backup_never_exposes_passwords_sessions_or_private_keys(self):
        await self.sale()
        result = await self.client.get("/api/backup")
        self.assertEqual(result.status_code, 200)
        backup = result.json()
        self.assertIn("sales", backup)
        self.assertIn("blockchain", backup)
        self.assertIn("whitepaper", backup)
        for secret in (PASSWORD, "token_hash", "password", "csrf", "private_key", self.client.cookies.get("figurae_session")):
            self.assertNotIn(secret, result.text)


if __name__ == "__main__":
    unittest.main()
