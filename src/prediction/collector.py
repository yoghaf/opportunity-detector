# src/prediction/collector.py
"""
Net APR Opportunity Collector (Phase-4).

Polls data from Gate, OKX, and Binance to compute "Net APR" (Spread).
Stores tradable opportunities in SQLite for quant research.

Strict Quant Requirements:
- Store 'opportunity' data type
- Full breakdown in raw_payload
- Mandatory sanity checks (reject anomalies)
"""

import time
import sys
import os
import signal
import logging
import json
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.settings import Config
from src.prediction.db import init_db, insert_apr_batch, log_collector_run, get_db_stats
from src.exchanges.gate_client import GateClient
from src.exchanges.okx_client import OKXClient
from src.exchanges.binance_client import BinanceClient
from src.strategies.opportunity_finder import OpportunityFinder

# ============================================================
# Configuration
# ============================================================
COLLECT_INTERVAL = 60       # seconds (OpportunityFinder is heavier, so 60s is safer)
MAX_CONSECUTIVE_ERRORS = 10
ERROR_BACKOFF_SECONDS = 60
STARTUP_BANNER = """
╔══════════════════════════════════════════════════════╗
║  📊 Net APR Opportunity Collector v2.0              ║
║  Interval: {interval}s | DB: {db_path}              ║
║  Mode: Quant Research (Strict Sanity Checks)        ║
╚══════════════════════════════════════════════════════╝
"""

# ============================================================
# Logging setup
# ============================================================
def setup_collector_logger() -> logging.Logger:
    logger = logging.getLogger("apr_collector")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    fh = logging.FileHandler(os.path.join(log_dir, "apr_collector.log"), encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    return logger

logger = setup_collector_logger()

# ============================================================
# Sanity Checks (Quant Requirement #6)
# ============================================================
def validate_opportunity(row: pd.Series) -> bool:
    """
    Returns True if row passes all quant sanity checks.
    """
    currency = row.get('currency', 'UNKNOWN')
    gate_apr = row.get('gate_apr', 0.0)
    net_apr = row.get('net_apr', 0.0)
    borrow_rate = row.get('best_loan_rate', 0.0)
    
    # Check 1: NaN or Infinite
    if pd.isna(net_apr) or np.isinf(net_apr) or pd.isna(gate_apr):
        logger.warning(f"❌ REJECT {currency}: NaN/Inf detected (Net: {net_apr})")
        return False

    # Check 2: Negative Rates (Impossible in this context)
    if borrow_rate < 0:
        logger.warning(f"❌ REJECT {currency}: Negative borrow rate ({borrow_rate})")
        return False
    if gate_apr < 0:
        logger.warning(f"❌ REJECT {currency}: Negative Gate APR ({gate_apr})")
        return False
        
    # Check 3: Anomaly (Net APR > 5x Gate APR)
    # This catches data glitches where borrow rate might be negative-huge or Gate APR massive
    if gate_apr > 0 and net_apr > (5 * gate_apr):
        logger.warning(f"❌ REJECT {currency}: Suspicious Spread (Net: {net_apr} > 5x Gate: {gate_apr})")
        return False
        
    return True

# ============================================================
# Fetch Logic
# ============================================================
def fetch_opportunities(finder: OpportunityFinder) -> list[dict]:
    """
    Uses OpportunityFinder to get Net APRs.
    Returns list of dicts ready for DB.
    """
    df = finder.find_opportunities()
    
    if df.empty:
        return []
        
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    records = []
    
    for _, row in df.iterrows():
        # Sanity Check
        if not validate_opportunity(row):
            continue
            
        # Build Raw Payload (Quant Requirement #2)
        payload = {
            'gate_apr': float(row['gate_apr']),
            'okx_loan_rate': float(row.get('okx_loan_rate', 0.0)),
            'binance_loan_rate': float(row.get('binance_loan_rate', 0.0)),
            'best_loan_rate': float(row.get('best_loan_rate', 0.0)),
            'best_loan_source': str(row.get('best_loan_source', 'None')),
            'available': bool(row.get('available', False)),
            'okx_total_quota': float(row.get('okx_total_quota', 0.0)),
            'okx_surplus_limit': float(row.get('okx_surplus_limit', 0.0))
        }
        
        records.append({
            'timestamp': now_utc,
            'data_type': 'opportunity',  # Quant Requirement #1
            'exchange': 'opportunity',   # Legacy field compatibility
            'currency': row['currency'],
            'apr': float(row['net_apr']),
            'raw_payload': payload
        })
        
    return records

# ============================================================
# Main Loop
# ============================================================
def run_collector(interval: int = COLLECT_INTERVAL, db_path: Optional[str] = None) -> None:
    init_db(db_path)
    from src.prediction.db import get_db_path
    actual_path = db_path or get_db_path()
    
    logger.info(STARTUP_BANNER.format(interval=interval, db_path=os.path.basename(actual_path)))
    
    # Initialize Clients
    try:
        gate_client = GateClient()
        okx_client = OKXClient()
        binance_client = BinanceClient()
        finder = OpportunityFinder(gate_client, okx_client, binance_client)
        logger.info("✅ Clients Initialized (Gate, OKX, Binance)")
    except Exception as e:
        logger.critical(f"🔥 Failed to initialize clients: {e}")
        return

    running = True
    def shutdown(signum, frame):
        nonlocal running
        logger.info("🛑 Shutdown signal received.")
        running = False
    
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    
    consecutive_errors = 0
    total_cycles = 0
    start_time = time.time()
    
    while running:
        cycle_start = time.time()
        total_cycles += 1
        error_msg = None
        count = 0
        
        try:
            records = fetch_opportunities(finder)
            count = len(records)
            
            if count > 0:
                insert_apr_batch(records, db_path)
                consecutive_errors = 0
                logger.info(f"✅ Cycle {total_cycles}: Stored {count} opportunities")
            else:
                logger.warning(f"⚠️ Cycle {total_cycles}: No valid opportunities found")
                
        except Exception as e:
            consecutive_errors += 1
            error_msg = str(e)
            logger.error(f"❌ Cycle {total_cycles} Failed: {e}")
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                time.sleep(ERROR_BACKOFF_SECONDS)
                
        # Calculate sleeps
        elapsed = time.time() - cycle_start
        sleep_time = max(0, interval - elapsed)
        
        try:
            log_collector_run(count, int(elapsed * 1000), error_msg, db_path)
        except:
            pass
            
        if running and sleep_time > 0:
            time.sleep(sleep_time)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=COLLECT_INTERVAL)
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()
    
    if args.stats:
        stats = get_db_stats()
        print(json.dumps(stats, indent=2))
    else:
        run_collector(args.interval)
