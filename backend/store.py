from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .models import Settings, WhitepaperFields


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "console.sqlite3"
        self.lock = threading.RLock()
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS auth_failures(id INTEGER PRIMARY KEY, client TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sales(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, customer TEXT NOT NULL, wallet_address TEXT NOT NULL,
                    quantity TEXT NOT NULL, unit_price_eur TEXT NOT NULL, total_eur TEXT NOT NULL,
                    payment_currency TEXT NOT NULL, notes TEXT NOT NULL,
                    status TEXT NOT NULL, payment_reference TEXT NOT NULL DEFAULT '', tx_hash TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS prices(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, price_eur TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS activity(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL);
            """)
            sale_columns = {column["name"] for column in db.execute("PRAGMA table_info(sales)")}
            for name, specification in (
                ("delivery_chain_id", "INTEGER"),
                ("delivery_contract", "TEXT NOT NULL DEFAULT ''"),
            ):
                if name not in sale_columns:
                    db.execute(f"ALTER TABLE sales ADD COLUMN {name} {specification}")
            for key, value in (
                ("settings", Settings().model_dump()),
                ("whitepaper", {"fields": WhitepaperFields().model_dump(), "version": 1, "updated_at": now()}),
            ):
                db.execute("INSERT OR IGNORE INTO kv(key,value) VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False)))
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        with self.lock:
            connection = sqlite3.connect(self.path, timeout=30)
            connection.row_factory = sqlite3.Row
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

    @staticmethod
    def get(db, key, default=None):
        row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    @staticmethod
    def put(db, key, value):
        db.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, json.dumps(value, ensure_ascii=False)))

    @staticmethod
    def log(db, label: str, kind: str):
        db.execute("INSERT INTO activity(label,kind,created_at) VALUES(?,?,?)", (label, kind, now()))

    @staticmethod
    def rows(db, table: str, limit: int | None = None):
        if table not in {"sales", "prices", "activity"}:
            raise ValueError("Tabella non esportabile")
        return [dict(row) for row in db.execute(
            f"SELECT * FROM {table} ORDER BY id DESC" + (" LIMIT ?" if limit is not None else ""),
            (limit,) if limit is not None else (),
        )]
