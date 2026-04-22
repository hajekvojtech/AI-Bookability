"""
SQLite ledger for the tiered crawler pipeline.

Single source of truth for progress. Resume logic is one query:
    SELECT url FROM input_domains WHERE url NOT IN (SELECT url FROM results)
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS input_domains (
    url                     TEXT PRIMARY KEY,
    account_id              TEXT,
    merchant_name           TEXT,
    raw_website             TEXT,
    category_v3             TEXT,
    subcategory_v3          TEXT,
    vertical                TEXT,
    billingcity             TEXT,
    billingstate            TEXT,
    last_voucher_sold_date  TEXT,
    merchant_segmentation   TEXT,
    merchant_tier           TEXT
);

CREATE TABLE IF NOT EXISTS results (
    url          TEXT PRIMARY KEY,
    tier         INTEGER NOT NULL,
    status       TEXT NOT NULL,
    platform     TEXT,
    category     TEXT,
    evidence     TEXT,
    http_status  INTEGER,
    final_url    TEXT,
    error        TEXT,
    crawled_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_results_status ON results(status);
CREATE INDEX IF NOT EXISTS idx_results_tier ON results(tier);
"""

EVIDENCE_MAX_CHARS = 500


@contextmanager
def connect(db_path: str | Path):
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: str | Path) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def upsert_input_domain(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT INTO input_domains
            (url, account_id, merchant_name, raw_website,
             category_v3, subcategory_v3, vertical,
             billingcity, billingstate, last_voucher_sold_date,
             merchant_segmentation, merchant_tier)
        VALUES (:url, :account_id, :merchant_name, :raw_website,
                :category_v3, :subcategory_v3, :vertical,
                :billingcity, :billingstate, :last_voucher_sold_date,
                :merchant_segmentation, :merchant_tier)
        ON CONFLICT(url) DO UPDATE SET
            merchant_name = excluded.merchant_name,
            raw_website   = excluded.raw_website
        """,
        row,
    )


def upsert_result(
    conn: sqlite3.Connection,
    *,
    url: str,
    tier: int,
    status: str,
    platform: Optional[str] = None,
    category: Optional[str] = None,
    evidence: Optional[str] = None,
    http_status: Optional[int] = None,
    final_url: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    if evidence and len(evidence) > EVIDENCE_MAX_CHARS:
        evidence = evidence[:EVIDENCE_MAX_CHARS] + "…"
    conn.execute(
        """
        INSERT INTO results
            (url, tier, status, platform, category, evidence,
             http_status, final_url, error, crawled_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(url) DO UPDATE SET
            tier         = excluded.tier,
            status       = excluded.status,
            platform     = excluded.platform,
            category     = excluded.category,
            evidence     = excluded.evidence,
            http_status  = excluded.http_status,
            final_url    = excluded.final_url,
            error        = excluded.error,
            crawled_at   = CURRENT_TIMESTAMP
        """,
        (url, tier, status, platform, category, evidence, http_status, final_url, error),
    )


def todo_urls(conn: sqlite3.Connection) -> list[str]:
    """URLs in input_domains with no row in results — the Tier 1 queue."""
    rows = conn.execute(
        """
        SELECT url FROM input_domains
        WHERE url NOT IN (SELECT url FROM results)
        """
    ).fetchall()
    return [r["url"] for r in rows]


def tier2_urls(conn: sqlite3.Connection, statuses: tuple[str, ...] | None = None) -> list[str]:
    """URLs that Tier 1 didn't resolve — candidates for Playwright upgrade.

    `statuses` defaults to all non-bookable outcomes. Pass a narrower tuple
    (e.g. ('error','timeout','blocked')) to skip no_signature rows.
    """
    if statuses is None:
        statuses = ('no_signature', 'error', 'timeout', 'blocked')
    placeholders = ",".join("?" for _ in statuses)
    rows = conn.execute(
        f"""
        SELECT url FROM results
        WHERE status IN ({placeholders})
          AND tier < 2
        """,
        statuses,
    ).fetchall()
    return [r["url"] for r in rows]


def delete_error_rows(conn: sqlite3.Connection) -> int:
    """For --retry-errors: drop rows where Tier 1 errored so they requeue."""
    cur = conn.execute(
        "DELETE FROM results WHERE tier = 1 AND status IN ('error', 'timeout', 'blocked')"
    )
    return cur.rowcount


def stats(conn: sqlite3.Connection) -> dict:
    inputs = conn.execute("SELECT COUNT(*) AS n FROM input_domains").fetchone()["n"]
    done = conn.execute("SELECT COUNT(*) AS n FROM results").fetchone()["n"]
    return {"inputs": inputs, "done": done, "remaining": inputs - done}
