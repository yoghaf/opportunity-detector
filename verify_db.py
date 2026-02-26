
import sys
import os
sys.path.insert(0, os.getcwd())
from src.prediction.db import get_db_stats

stats = get_db_stats()
print(f"Latest: {stats['latest_timestamp']}")
print(f"Total: {stats['total_observations']}")
