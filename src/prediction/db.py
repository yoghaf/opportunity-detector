# src/prediction/db.py
"""
SQLite time-series storage for APR history.

Design principles:
    - Append-only (never overwrite or UPDATE)
    - UTC timestamps throughout
    - Schema ready for PostgreSQL migration (standard SQL types)
    - Indexed for common query patterns:  token + time range
"""

import sqlite3
import os
import json
from datetime import datetime, timezone
from typing import Optional
from contextlib import contextmanager

# Database lives alongside data/ directory
DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
DB_PATH = os.path.join(DB_DIR, "apr_history.db")


def get_db_path() -> str:
    """Return absolute path to the SQLite database file."""
    os.makedirs(DB_DIR, exist_ok=True)
    return DB_PATH


@contextmanager
def get_connection(db_path: Optional[str] = None):
    """
    Context manager for SQLite connections.
    Uses WAL mode for concurrent read/write (collector writes while dashboard reads).
    """
    path = db_path or get_db_path()
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")       # Allow concurrent readers
    conn.execute("PRAGMA synchronous=NORMAL")      # Good balance: safe + fast
    conn.execute("PRAGMA busy_timeout=5000")       # Wait up to 5s if locked
    conn.row_factory = sqlite3.Row                 # Dict-like access
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    """
    Create tables if they don't exist.
    Safe to call multiple times (idempotent).
    """
    with get_connection(db_path) as conn:
        conn.executescript("""
            -- Core time-series table: one row per (token, timestamp) observation
            CREATE TABLE IF NOT EXISTS apr_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,    -- ISO 8601 UTC (e.g. '2026-02-12T06:18:35Z')
                data_type   TEXT    NOT NULL DEFAULT 'raw', -- 'raw' or 'opportunity'
                exchange    TEXT    NOT NULL DEFAULT 'gate',
                currency    TEXT    NOT NULL,
                apr         REAL    NOT NULL,    -- Annualized % (e.g. 499.32)
                raw_payload TEXT,                -- Full JSON from API for future flexibility
                
                -- Prevent exact duplicate inserts (same token at same second)
                UNIQUE(exchange, currency, timestamp)
            );

            -- Primary query pattern: "give me APR for token X over last N hours"
            CREATE INDEX IF NOT EXISTS idx_apr_currency_time
                ON apr_history(currency, timestamp);

            -- Secondary: "give me all tokens at a specific time" (for cross-token analysis)
            CREATE INDEX IF NOT EXISTS idx_apr_time
                ON apr_history(timestamp);
                
            -- Collector health tracking
            CREATE TABLE IF NOT EXISTS collector_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                tokens_collected INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                error       TEXT,
                UNIQUE(timestamp)
            );

            -- [PHASE 1] Cleaned/Feature Data
            CREATE TABLE IF NOT EXISTS apr_features (
                timestamp   TEXT    NOT NULL,
                currency    TEXT    NOT NULL,
                apr_raw     REAL,
                apr_clean   REAL,       -- Post-Hampel
                regime_prob TEXT,       -- JSON: {Low:0.1, High:0.9}
                volatility  REAL,
                PRIMARY KEY (currency, timestamp)
            );

            -- [PHASE 1] Survival Statistics Cache
            CREATE TABLE IF NOT EXISTS survival_curves (
                tier        TEXT    NOT NULL, -- '100-200', '200-400', '400+'
                minute      INTEGER NOT NULL,
                survival_prob REAL  NOT NULL,
                updated_at  TEXT    NOT NULL,
                PRIMARY KEY (tier, minute)
            );

            -- [PHASE 1] Ground-Truth Paper Trading (Supervision Signal)
            CREATE TABLE IF NOT EXISTS paper_trades (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                currency        TEXT    NOT NULL,
                entry_timestamp TEXT    NOT NULL,
                exit_timestamp  TEXT,
                entry_apr       REAL    NOT NULL,
                exit_apr        REAL,
                borrow_cost     REAL    DEFAULT 0,
                withdrawal_fee  REAL    DEFAULT 0,
                realized_pnl    REAL,   -- Actual profit/loss metric
                exit_reason     TEXT    -- 'decay', 'stop_loss', 'horizon'
            );
        """)

    # Schema Migration: Add data_type if missing (for existing DBs)
    with get_connection(db_path) as conn:
        try:
            conn.execute("ALTER TABLE apr_history ADD COLUMN data_type TEXT DEFAULT 'raw'")
        except Exception:
            pass  # Column likely exists

        # Phase 3.5: Paper Trades Migration
        columns_to_add = [
            ("holding_minutes", "INTEGER"),
            ("signal_snapshot_json", "TEXT"),
            ("created_at", "TEXT")
        ]
        
        for col_name, col_type in columns_to_add:
            try:
                conn.execute(f"ALTER TABLE paper_trades ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass # Column likely exists
                
        # Rename/Alias check (SQLite doesn't support easy rename of columns, so we'll stick to existing mapping or add new ones if strictly needed)
        # Required: borrow_cost_total. Existing: borrow_cost. We will use 'borrow_cost' as 'borrow_cost_total'.
        # Required: entry_time. Existing: entry_timestamp. mapping is fine.



def insert_apr_batch(records: list[dict], db_path: Optional[str] = None) -> int:
    """
    Insert a batch of APR observations.
    
    Each record: {
        'currency': 'ANIME',
        'apr': 499.32,
        'raw_payload': {...} or None,
        'exchange': 'gate',       # optional, defaults to 'gate'
        'timestamp': '2026-...'   # optional, defaults to now UTC
    }
    
    Returns: number of rows inserted (skips duplicates via IGNORE).
    """
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    with get_connection(db_path) as conn:
        inserted = 0
        for rec in records:
            try:
                # Quant: Explicitly store data_type ('raw' or 'opportunity')
                data_type = rec.get('data_type', 'raw')
                
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO apr_history 
                       (timestamp, data_type, exchange, currency, apr, raw_payload)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        rec.get('timestamp', now_utc),
                        data_type,
                        rec.get('exchange', 'gate'),
                        rec['currency'],
                        rec['apr'],
                        json.dumps(rec.get('raw_payload')) if rec.get('raw_payload') else None,
                    )
                )
                inserted += cursor.rowcount  # Correctly count checking rowcount
            except sqlite3.Error:
                continue  # Skip bad rows, don't crash batch
        
        return inserted


def log_collector_run(
    tokens_collected: int,
    duration_ms: int,
    error: Optional[str] = None,
    db_path: Optional[str] = None
) -> None:
    """Record a collector run for health monitoring."""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO collector_runs 
               (timestamp, tokens_collected, duration_ms, error)
               VALUES (?, ?, ?, ?)""",
            (now_utc, tokens_collected, duration_ms, error)
        )


def get_row_count(db_path: Optional[str] = None) -> int:
    """Quick row count for monitoring."""
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM apr_history").fetchone()
        return row[0] if row else 0


def get_latest_timestamp(db_path: Optional[str] = None) -> Optional[str]:
    """Get most recent observation timestamp."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT timestamp FROM apr_history ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None


def get_db_stats(db_path: Optional[str] = None) -> dict:
    """Quick DB health stats for monitoring."""
    with get_connection(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM apr_history").fetchone()[0]
        tokens = conn.execute("SELECT COUNT(DISTINCT currency) FROM apr_history").fetchone()[0]
        latest = conn.execute("SELECT timestamp FROM apr_history ORDER BY id DESC LIMIT 1").fetchone()
        oldest = conn.execute("SELECT timestamp FROM apr_history ORDER BY id ASC LIMIT 1").fetchone()
        runs = conn.execute("SELECT COUNT(*) FROM collector_runs").fetchone()[0]
        errors = conn.execute("SELECT COUNT(*) FROM collector_runs WHERE error IS NOT NULL").fetchone()[0]
        
        # DB file size
        path = db_path or get_db_path()
        size_mb = os.path.getsize(path) / (1024 * 1024) if os.path.exists(path) else 0
        
        return {
            'total_observations': total,
            'unique_tokens': tokens,
            'latest_timestamp': latest[0] if latest else None,
            'oldest_timestamp': oldest[0] if oldest else None,
            'total_runs': runs,
            'error_runs': errors,
            'db_size_mb': round(size_mb, 2),
        }


def get_token_history(token: str, hours: int = 24) -> list[dict]:
    """
    Quant Research Query: Fetch opportunity history for a specific token.
    
    Args:
        token: Token symbol (e.g. 'ETH')
        hours: How many hours of history to retrieve (default: 24)
        
    Returns:
        List of dicts with: timestamp, net_apr, gate_apr, borrow_rate, source
        Ordered by timestamp ASC (for time-series analysis)
    """
    # Calculate cutoff time in Python to avoid SQLite datetime nuances
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT timestamp, apr as net_apr, raw_payload FROM apr_history WHERE currency = ? AND data_type = 'opportunity' AND timestamp >= ? ORDER BY timestamp ASC",
            (token.upper(), cutoff)
        )
        
        results = []
        for row in cursor.fetchall():
            # Parse the stored JSON payload to get breakdown
            payload = json.loads(row['raw_payload']) if row['raw_payload'] else {}
            
            # Robust extraction of quant fields
            # We map database row + payload contents to a clean quant format
            results.append({
                'timestamp': row['timestamp'],
                'net_apr': row['net_apr'],
                'gate_apr': payload.get('gate_apr', 0.0),
                'borrow_rate': payload.get('best_loan_rate', 0.0),
                'source': payload.get('best_loan_source', 'Unknown'),
            })
            
        return results


def get_latest_features(limit: int = 100) -> list[dict]:
    """
    Fetch the latest probabilistic features for active tokens.
    Used for the /api/predictions endpoint.
    """
    with get_connection() as conn:
        # Get the most recent timestamp for each currency
        # This query assumes apr_features is updated regularly
        # We join with apr_features to get the full row
        
        # Simple approach: Get all rows from the last known timestamp
        # First find latest timestamp
        latest_ts_row = conn.execute("SELECT MAX(timestamp) FROM apr_features").fetchone()
        if not latest_ts_row or not latest_ts_row[0]:
            return []
            
        latest_ts = latest_ts_row[0]
        
        cursor = conn.execute(
            """
            SELECT currency, apr_clean, regime_prob, volatility, timestamp
            FROM apr_features 
            WHERE timestamp = ?
            ORDER BY apr_clean DESC
            LIMIT ?
            """,
            (latest_ts, limit)
        )
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'token': row['currency'],
                'timestamp': row['timestamp'],
                'apr_clean': row['apr_clean'],
                'regime_prob': json.loads(row['regime_prob']),
                'volatility': row['volatility']
            })
            
        return results


def get_last_known_opportunities() -> tuple[list[dict], str]:
    """
    Fetch the most recent batch of opportunities from history.
    Returns: (data_list, timestamp_str)
    """
    with get_connection() as conn:
        # 1. Find the latest timestamp
        latest = conn.execute(
            "SELECT MAX(timestamp) FROM apr_history WHERE data_type = 'opportunity'"
        ).fetchone()
        
        if not latest or not latest[0]:
            return [], None
            
        timestamp = latest[0]
        
        # 2. Get all records for that timestamp
        cursor = conn.execute(
            "SELECT raw_payload FROM apr_history WHERE timestamp = ? AND data_type = 'opportunity'",
            (timestamp,)
        )
        
        results = []
        for row in cursor.fetchall():
            if row['raw_payload']:
                try:
                    payload = json.loads(row['raw_payload'])
                    results.append(payload)
                except json.JSONDecodeError:
                    continue
        
        return results, timestamp
