
import sys
import os
import sqlite3

# Fix import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.prediction.db import DB_PATH

def dump_schema():
    print(f"Connecting to {DB_PATH}...")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # List tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"Tables: {tables}")
        
        # Dump schema for apr_history
        cursor.execute("PRAGMA table_info(apr_history);")
        columns = cursor.fetchall()
        print("\nColumns in apr_history:")
        for col in columns:
            print(col)
            
        # Sample row
        print("\nSample Row:")
        cursor.execute("SELECT * FROM apr_history LIMIT 1")
        row = cursor.fetchone()
        print(row)
        
        conn.close()

    except Exception as e:
        print(f"DB Error: {e}")

if __name__ == "__main__":
    dump_schema()
