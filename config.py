"""No --env: dev.json. With --env: settings from CLI. DB_URI from environment.

--mode and --limit apply in both cases (CLI overrides dev.json).
"""

import argparse
import json
import os

from dotenv import load_dotenv
from pymongo import MongoClient

_DIR = os.path.dirname(__file__)
MODES = ("daily", "weekly")

settings: dict = {}
client: MongoClient | None = None
collection = None
active_env: str | None = None


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument(
        "--env",
        default=None,
        metavar="NAME",
        help="If set, settings from CLI flags (not dev.json)",
    )
    p.add_argument("--db-name", dest="DB_name", default="stock_test")
    p.add_argument(
        "--collection-name", dest="collection_name", default="nasdaq_stocks_test"
    )
    p.add_argument(
        "--max-workers",
        dest="max_workers",
        type=int,
        default=5,
        help="Parallel MongoDB writers in daily mode",
    )
    p.add_argument(
        "--mode",
        choices=MODES,
        default=None,
        help="daily: price fields; weekly: company, sector, industry, country",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only the first N tickers of the universe (staging checks)",
    )
    return p.parse_args(argv)


def configure(args) -> None:
    global config, DB_URI, client, collection, active_env

    load_dotenv()

    if args.env is None:
        active_env = "dev"
        with open(os.path.join(_DIR, "dev.json")) as f:
            config = json.load(f)
    else:
        active_env = args.env
        pairs = [
            ("DB_name", args.DB_name, "--db-name"),
            ("collection_name", args.collection_name, "--collection-name"),
            ("max_workers", args.max_workers, "--max-workers"),
        ]
        missing = [flag for _, val, flag in pairs if val is None]
        if missing:
            raise ValueError("With --env, required: " + ", ".join(missing))
        config = {key: val for key, val, _ in pairs}

    config["mode"] = args.mode or config.get("mode", "daily")
    if args.limit is not None:
        config["limit"] = args.limit
    config.setdefault("limit", None)
    if config["limit"] is not None and config["limit"] < 1:
        raise ValueError("--limit must be >= 1")

    DB_URI = os.getenv("db_url")
    if not DB_URI:
        raise ValueError("db_url environment variable is required")

    client = MongoClient(DB_URI)
    collection = client[config["DB_name"]][config["collection_name"]]
