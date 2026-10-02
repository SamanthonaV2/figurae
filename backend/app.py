from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import secrets
import time
from decimal import Decimal, localcontext
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from blackchain.core import LedgerError

from .chain import ChainStore
from .documents import TOKEN, render_whitepaper
from .models import (ChainTransaction, DeliveryCreate, ForgeRequest, Password, PriceCreate, SaleCreate,
                     SaleUpdate, Settings, TX_HASH, WhitepaperUpdate)
from .store import Store, now


ROOT = Path(__file__).resolve().parent.parent
SESSION_COOKIE = "figurae_session"
SESSION_SECONDS = 12 * 60 * 60
PBKDF2_ITERATIONS = 600_000
MAX_BODY_BYTES = 11 * 1024 * 1024
DISTRIBUTION_LIMIT = Decimal("70000000000")


def money(value: Decimal) -> str:
    return format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else format(value, "f")


def spreadsheet_cell(value):
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def attachment(content: str, filename: str, media_type: str = "application/json") -> Response:
    return Response(content, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def create_app(data_dir: Path | None = None) -> FastAPI:
    directory = Path(data_dir) if data_dir is not None else ROOT / "data"
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    store = Store(directory)
    chain = ChainStore(directory)
    app = FastAPI(title="Figurae Console", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.chain_store = store, chain
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    @app.middleware("http")
    async def local_security(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin:
            try:
                parsed = urlsplit(origin)
                same_origin = parsed.scheme == request.url.scheme and parsed.netloc.lower() == request.headers.get("host", "").lower()
            except ValueError:
                same_origin = False
            if not same_origin:
                return JSONResponse({"detail": "Origine della richiesta non consentita"}, status_code=403)
        if request.url.path.startswith("/api/"):
            try:
                if int(request.headers.get("content-length", "0")) > MAX_BODY_BYTES:
                    return JSONResponse({"detail": "Richiesta troppo grande"}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "Content-Length non valido"}, status_code=400)
            body = await request.body()
            if len(body) > MAX_BODY_BYTES:
                return JSONResponse({"detail": "Richiesta troppo grande"}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    @app.exception_handler(LedgerError)
    async def ledger_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # Pydantic's default error includes the submitted input (including passwords).
        details = [{"loc": list(item["loc"]), "msg": item["msg"], "type": item["type"]}
                   for item in error.errors()]
        return JSONResponse({"detail": details}, status_code=422)

    def session_record(request: Request):
        token = request.cookies.get(SESSION_COOKIE, "")
        if not token or len(token) > 128:
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with store.db() as db:
            row = db.execute("SELECT * FROM sessions WHERE token_hash=? AND expires>?", (token_hash, time.time())).fetchone()
            return dict(row) if row else None

    def authenticated(request: Request):
        session = session_record(request)
        if not session:
            raise HTTPException(401, "Accedi alla console privata")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            supplied = request.headers.get("x-csrf-token", "")
            if not hmac.compare_digest(supplied.encode(), session["csrf"].encode()):
                raise HTTPException(403, "Token CSRF mancante o non valido")
        return session

    def issue_session(db, response: Response):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        db.execute("DELETE FROM sessions WHERE expires<=?", (time.time(),))
        db.execute("INSERT INTO sessions VALUES(?,?,?)", (
            hashlib.sha256(token.encode()).hexdigest(), csrf, time.time() + SESSION_SECONDS,
        ))
        response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                            samesite="strict", secure=False, path="/")
        return {"authenticated": True, "setup_required": False, "csrf_token": csrf}

    def paper(db):
        record = store.get(db, "whitepaper")
        return {**record, "markdown": render_whitepaper(record["fields"], store.get(db, "settings"),
                                                       record["version"], record["updated_at"])}

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/session")
    def session(request: Request):
        row = session_record(request)
        with store.db() as db:
            configured = bool(store.get(db, "password"))
        return {"authenticated": bool(row), "setup_required": not configured,
                **({"csrf_token": row["csrf"]} if row else {})}

    @app.post("/api/setup")
    def setup(payload: Password, response: Response):
        if len(payload.password) < 10:
            raise HTTPException(422, "La password deve contenere almeno 10 caratteri")
        with store.db() as db:
            if store.get(db, "password"):
                raise HTTPException(409, "La console è già configurata")
            salt = secrets.token_hex(32)
            digest = hashlib.pbkdf2_hmac("sha256", payload.password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS).hex()
            store.put(db, "password", {"salt": salt, "hash": digest, "iterations": PBKDF2_ITERATIONS})
            store.log(db, "Console privata configurata", "system")
            return issue_session(db, response)

    @app.post("/api/login")
    def login(payload: Password, request: Request, response: Response):
        client = request.client.host if request.client else "local"
        current = time.time()
        with store.db() as db:
            db.execute("DELETE FROM auth_failures WHERE created<?", (current - 600,))
            failures = db.execute("SELECT count(*) FROM auth_failures WHERE client=?", (client,)).fetchone()[0]
            if failures >= 6:
                raise HTTPException(429, "Troppi tentativi: riprova tra 10 minuti")
            password = store.get(db, "password")
            if not password:
                raise HTTPException(409, "Configura prima una password")
            candidate = hashlib.pbkdf2_hmac("sha256", payload.password.encode(), bytes.fromhex(password["salt"]), password["iterations"]).hex()
            if not hmac.compare_digest(candidate, password["hash"]):
                db.execute("INSERT INTO auth_failures(client,created) VALUES(?,?)", (client, current))
                # Persist the failed attempt before HTTPException rolls the transaction back.
                db.commit()
                raise HTTPException(401, "Password non valida")
            db.execute("DELETE FROM auth_failures WHERE client=?", (client,))
            return issue_session(db, response)

    @app.post("/api/logout")
    def logout(response: Response, row=Depends(authenticated)):
        with store.db() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (row["token_hash"],))
        response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
        return {"authenticated": False}

    @app.get("/api/token", dependencies=[Depends(authenticated)])
    def token():
        return {**TOKEN, "artifact_url": "/api/artifact", "source_url": "/api/contract/source"}

    @app.get("/api/artifact", dependencies=[Depends(authenticated)])
    def artifact():
        return json.loads((ROOT / "contracts" / "Figurae.json").read_text())

    @app.get("/api/contract/source", dependencies=[Depends(authenticated)])
    def source():
        return attachment((ROOT / "contracts" / "Figurae.sol").read_text(), "Figurae.sol", "text/plain")

    @app.get("/api/settings", dependencies=[Depends(authenticated)])
    def get_settings():
        with store.db() as db:
            return store.get(db, "settings")

    @app.patch("/api/settings", dependencies=[Depends(authenticated)])
    def patch_settings(payload: dict = Body(...)):
        with store.db() as db:
            try:
                value = Settings.model_validate({**store.get(db, "settings"), **payload}).model_dump()
            except ValidationError as exc:
                raise HTTPException(422, [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]) from exc
            store.put(db, "settings", value)
            store.log(db, "Configurazione del token aggiornata", "settings")
            return value

    @app.get("/api/chain", dependencies=[Depends(authenticated)])
    def get_chain():
        return chain.snapshot()

    @app.post("/api/chain/transactions", dependencies=[Depends(authenticated)])
    def transaction(payload: ChainTransaction):
        result = chain.transaction(**payload.model_dump())
        with store.db() as db:
            store.log(db, f"BlackChain: {payload.kind} firmata da {payload.sender}", "chain")
        return result

    @app.post("/api/chain/forge", dependencies=[Depends(authenticated)])
    def forge(payload: ForgeRequest | None = Body(default=None)):
        with chain.lock:
            if payload and payload.sender and chain.wallets[payload.sender].address != chain.chain.expected_proposer():
                raise LedgerError("Il wallet non è il validatore selezionato per questo blocco")
            block = chain.forge()
        with store.db() as db:
            store.log(db, f"BlackChain: blocco {block['height']} validato", "chain")
        return block

    @app.get("/api/chain/export", dependencies=[Depends(authenticated)])
    def export_chain():
        return attachment(json.dumps(chain.export(), ensure_ascii=False, indent=2), "blackchain.json")

    @app.post("/api/chain/import", dependencies=[Depends(authenticated)])
    def import_chain(payload: dict = Body(...)):
        result = chain.import_archive(payload)
        with store.db() as db:
            store.log(db, f"BlackChain: archivio verificato e importato ({result['height']} blocchi)", "chain")
        return result

    @app.get("/api/sales", dependencies=[Depends(authenticated)])
    def get_sales():
        with store.db() as db:
            return store.rows(db, "sales")

    @app.post("/api/sales", dependencies=[Depends(authenticated)])
    def create_sale(payload: SaleCreate):
        with store.db() as db, localcontext() as context:
            context.prec = 160
            reserved = sum((Decimal(r["quantity"]) for r in db.execute("SELECT quantity FROM sales WHERE status<>'cancelled'")), Decimal(0))
            quantity = Decimal(payload.quantity)
            if reserved + quantity > DISTRIBUTION_LIMIT:
                raise HTTPException(409, "La quantità supera i 70 miliardi FIG riservati alla distribuzione")
            timestamp = now()
            cursor = db.execute("""INSERT INTO sales(customer,wallet_address,quantity,unit_price_eur,total_eur,
                payment_currency,notes,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'pending',?,?)""",
                (payload.customer, payload.wallet_address, payload.quantity, payload.unit_price_eur,
                 money(quantity * Decimal(payload.unit_price_eur)), payload.payment_currency, payload.notes, timestamp, timestamp))
            sale_id = cursor.lastrowid
            store.log(db, f"Ordine #{sale_id} registrato: {payload.quantity} FIG", "sale")
            return dict(db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone())

    @app.patch("/api/sales/{sale_id}", dependencies=[Depends(authenticated)])
    def update_sale(sale_id: int, payload: SaleUpdate):
        with store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Ordine non trovato")
            transitions = {"pending": {"paid", "cancelled"}, "paid": {"completed", "cancelled"}, "completed": set(), "cancelled": set()}
            if payload.status not in transitions[row["status"]]:
                raise HTTPException(409, "Transizione di stato non consentita")
            if payload.status == "cancelled" and row["status"] == "paid" and row["tx_hash"]:
                raise HTTPException(409, "Un trasferimento è già stato inviato: verifica la consegna prima di modificare l'ordine")
            payment_ref = row["payment_reference"] if payload.payment_reference is None else payload.payment_reference
            tx_hash = row["tx_hash"]
            if payload.tx_hash is not None and payload.tx_hash.lower() != tx_hash.lower():
                raise HTTPException(409, "L'hash di consegna deve corrispondere al trasferimento già registrato")
            if payload.status == "completed" and not TX_HASH.fullmatch(tx_hash):
                raise HTTPException(422, "Registra prima l'hash del trasferimento inviato dal wallet")
            if tx_hash and db.execute(
                "SELECT id FROM sales WHERE lower(tx_hash)=lower(?) AND id<>?", (tx_hash, sale_id)
            ).fetchone():
                raise HTTPException(409, "Questo trasferimento è già registrato in un altro ordine")
            db.execute("UPDATE sales SET status=?,payment_reference=?,tx_hash=?,updated_at=? WHERE id=?",
                       (payload.status, payment_ref, tx_hash, now(), sale_id))
            store.log(db, f"Ordine #{sale_id}: {payload.status}", "sale")
            return dict(db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone())

    @app.post("/api/sales/{sale_id}/delivery", dependencies=[Depends(authenticated)])
    def record_delivery(sale_id: int, payload: DeliveryCreate):
        with store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Ordine non trovato")
            if row["status"] != "paid":
                raise HTTPException(409, "Registra una consegna solo per un ordine pagato")
            if row["tx_hash"]:
                if (row["tx_hash"].lower() != payload.tx_hash.lower()
                        or row["delivery_chain_id"] != payload.chain_id
                        or row["delivery_contract"].lower() != payload.contract_address.lower()):
                    raise HTTPException(409, "Questo ordine ha già un trasferimento registrato; verifica quello esistente")
                return dict(row)
            if db.execute("SELECT id FROM sales WHERE lower(tx_hash)=lower(?) AND id<>?", (payload.tx_hash, sale_id)).fetchone():
                raise HTTPException(409, "Questo trasferimento è già registrato in un altro ordine")
            db.execute("UPDATE sales SET tx_hash=?,delivery_chain_id=?,delivery_contract=?,updated_at=? WHERE id=?",
                       (payload.tx_hash, payload.chain_id, payload.contract_address, now(), sale_id))
            store.log(db, f"Ordine #{sale_id}: trasferimento inviato, in attesa di verifica", "sale")
            return dict(db.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone())

    @app.get("/api/sales/export.csv", dependencies=[Depends(authenticated)])
    def sales_csv():
        with store.db() as db:
            rows = store.rows(db, "sales")
        columns = ["id", "customer", "wallet_address", "quantity", "unit_price_eur", "total_eur", "payment_currency",
                   "status", "payment_reference", "tx_hash", "delivery_chain_id", "delivery_contract", "notes", "created_at", "updated_at"]
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([spreadsheet_cell(row[column]) for column in columns])
        return attachment("\ufeff" + output.getvalue(), "figurae-sales.csv", "text/csv")

    @app.get("/api/prices", dependencies=[Depends(authenticated)])
    def get_prices():
        with store.db() as db:
            return store.rows(db, "prices")

    @app.post("/api/prices", dependencies=[Depends(authenticated)])
    def create_price(payload: PriceCreate):
        with store.db() as db:
            cursor = db.execute("INSERT INTO prices(price_eur,source,created_at) VALUES(?,?,?)",
                                (payload.price_eur, payload.source, now()))
            store.log(db, f"Prezzo manuale aggiornato: {payload.price_eur} EUR", "price")
            return dict(db.execute("SELECT * FROM prices WHERE id=?", (cursor.lastrowid,)).fetchone())

    @app.get("/api/prices/export.csv", dependencies=[Depends(authenticated)])
    def prices_csv():
        with store.db() as db:
            rows = store.rows(db, "prices")
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        columns = ["id", "price_eur", "source", "created_at"]
        writer.writerow(columns)
        for row in rows:
            writer.writerow([spreadsheet_cell(row[column]) for column in columns])
        return attachment("\ufeff" + output.getvalue(), "figurae-prices.csv", "text/csv")

    @app.get("/api/whitepaper", dependencies=[Depends(authenticated)])
    def get_whitepaper():
        with store.db() as db:
            return paper(db)

    @app.put("/api/whitepaper", dependencies=[Depends(authenticated)])
    def save_whitepaper(payload: WhitepaperUpdate):
        with store.db() as db:
            version = store.get(db, "whitepaper")["version"] + 1
            store.put(db, "whitepaper", {"fields": payload.fields.model_dump(), "version": version, "updated_at": now()})
            store.log(db, f"Whitepaper salvato: versione {version}", "document")
            return paper(db)

    @app.get("/api/whitepaper/export.md", dependencies=[Depends(authenticated)])
    def export_paper():
        with store.db() as db:
            return attachment(paper(db)["markdown"], "figurae-whitepaper.md", "text/markdown")

    @app.get("/api/overview", dependencies=[Depends(authenticated)])
    def overview():
        snapshot = chain.snapshot()
        with store.db() as db, localcontext() as context:
            context.prec = 160
            sales = store.rows(db, "sales")
            prices = store.rows(db, "prices", limit=200)
            completed = [sale for sale in sales if sale["status"] == "completed"]
            paid = [sale for sale in sales if sale["status"] in {"paid", "completed"}]
            reserved = sum((Decimal(sale["quantity"]) for sale in sales if sale["status"] != "cancelled"), Decimal(0))
            change = None
            if len(prices) >= 2:
                change = money(((Decimal(prices[0]["price_eur"]) / Decimal(prices[1]["price_eur"]) - 1) * 100).quantize(Decimal("0.00000001")))
            return {
                "token": TOKEN, "settings": store.get(db, "settings"),
                "blockchain": {"height": snapshot["height"], "chain_id": snapshot["chain_id"],
                    "tip_hash": snapshot["tip_hash"], "state_root": snapshot["state_root"],
                    "validators_count": sum(a["stake"] >= chain.chain.genesis.minimum_stake for a in snapshot["accounts"]),
                    "total_stake": sum(a["stake"] for a in snapshot["accounts"])},
                "stats": {"sales_count": len(sales), "pending_count": len(snapshot["pending"]),
                    "pending_sales_count": sum(sale["status"] == "pending" for sale in sales),
                    "sold_tokens": money(sum((Decimal(sale["quantity"]) for sale in completed), Decimal(0))),
                    "reserved_tokens": money(reserved), "available_tokens": money(DISTRIBUTION_LIMIT - reserved),
                    "revenue_eur": money(sum((Decimal(sale["total_eur"]) for sale in paid), Decimal(0))),
                    "price_eur": prices[0]["price_eur"] if prices else None, "price_change_pct": change},
                "prices": prices, "activity": store.rows(db, "activity", limit=30),
            }

    @app.get("/api/backup", dependencies=[Depends(authenticated)])
    def backup():
        with chain.lock, store.db() as db:
            public_data = {"version": 1, "exported_at": now(), "token": TOKEN,
                "settings": store.get(db, "settings"), "whitepaper": paper(db),
                "sales": store.rows(db, "sales"), "prices": store.rows(db, "prices"),
                "activity": store.rows(db, "activity"), "blockchain": chain.export(),
                "pending": [tx.to_dict() for tx in chain.chain.pending]}
        return attachment(json.dumps(public_data, ensure_ascii=False, indent=2), "figurae-backup.json")

    web = ROOT / "web"
    if web.exists():
        app.mount("/", StaticFiles(directory=web, html=True), name="web")
    return app
