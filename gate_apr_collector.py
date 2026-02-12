#!/usr/bin/env python3
"""
Gate APR Collector — Standalone Entry Point.

Usage:
    python gate_apr_collector.py              # Start collecting (30s interval)
    python gate_apr_collector.py --interval 60   # Custom interval
    python gate_apr_collector.py --stats         # Show DB stats only

Press Ctrl+C to stop gracefully.
"""

import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.prediction.collector import run_collector
from src.prediction.db import init_db, get_db_stats

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Gate APR Time-Series Collector")
    parser.add_argument(
        "--interval", type=int, default=30,
        help="Seconds between API polls (default: 30)"
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Show DB stats and exit"
    )
    args = parser.parse_args()

    if args.stats:
        init_db()
        stats = get_db_stats()
        print("\n📊 APR History Database Stats:")
        print(f"   Total observations: {stats['total_observations']:,}")
        print(f"   Unique tokens:      {stats['unique_tokens']}")
        print(f"   Latest data:        {stats['latest_timestamp'] or 'none'}")
        print(f"   Oldest data:        {stats['oldest_timestamp'] or 'none'}")
        print(f"   Collector runs:     {stats['total_runs']}")
        print(f"   Error runs:         {stats['error_runs']}")
        print(f"   DB size:            {stats['db_size_mb']} MB")
    else:
        run_collector(interval=args.interval)
