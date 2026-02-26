
import sys
import os
import sqlite3
import pandas as pd
import json

# Fix import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.prediction.db import DB_PATH

def debug_load(limit=5):
    print(f"Connecting to {DB_PATH}...")
    try:
        conn = sqlite3.connect(DB_PATH)
        query = f"SELECT timestamp, raw_data FROM apr_history WHERE data_type='opportunity' ORDER BY timestamp DESC LIMIT {limit}"
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        print(f"Loaded {len(df)} rows.")
        if df.empty:
            print("No data.")
            return

        for _, row in df.iterrows():
            print(f"\nRow Time: {row['timestamp']}")
            try:
                data = json.loads(row['raw_data'])
                print(f"  Token: {data.get('currency')}")
                print(f"  Net APR: {data.get('net_apr')}")
            except Exception as e:
                print(f"  JSON Error: {e}")

    except Exception as e:
        print(f"DB Error: {e}")

if __name__ == "__main__":
    debug_load()
