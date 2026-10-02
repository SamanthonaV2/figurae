"""Avvia Figurae Console sul PC, con accesso limitato al loopback."""

import argparse
from pathlib import Path

import uvicorn

from backend.app import create_app


def main():
    parser = argparse.ArgumentParser(description="Figurae Console privata in locale")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).parent / "data")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("La porta deve essere tra 1 e 65535")
    print(f"Figurae Console: http://127.0.0.1:{args.port}", flush=True)
    uvicorn.run(create_app(data_dir=args.data_dir), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
