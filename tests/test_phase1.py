
import unittest
import pandas as pd
import numpy as np
import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.prediction.features import DataQuality, LightweightHMM
from src.prediction.analytics import SurvivalStats, RiskEngine

class TestPhase1(unittest.TestCase):
    
    def test_hampel_filter(self):
        # Create data with a single spike
        # 100, 100, 100, 500, 100, 100, 100
        data = [100.0]*3 + [500.0] + [100.0]*3 
        s = pd.Series(data)
        
        # Test Micro-Glitch (k=2 -> window 5)
        # Median of [100, 100, 500, 100, 100] is 100.
        clean = DataQuality.hampel_filter(s, window_size=5, n_sigmas=2)
        
        # 4th element (original 500) should be replaced by median (100)
        self.assertLess(clean.iloc[3], 200) 
        
    def test_structural_spike(self):
        # Create a structural shift (start of high APR)
        # 100 -> 100 -> ... -> 400 -> 405 -> 410 -> 415 -> 420
        # Need enough context for k=10 (window 21).
        # We'll mock a smaller window for test simplicity if possible, or use full length.
        
        data = [100.0]*10 + [400.0, 405.0, 410.0, 415.0, 420.0] + [425.0]*5
        s = pd.Series(data)
        
        # Dual Stage uses k=10 (window 21). Our data is len 20.
        # It handles edge cases via rolling center=True which might result in NaN or smaller windows at edges depending on pandas version.
        # But features.py fills NaN.
        
        # Let's just ensure 400+ values remain.
        # The logic: Z-score high, but slope is high too.
        
        clean = DataQuality.dual_stage_filter(s)
        self.assertTrue(clean.iloc[10] >= 350) # Should PRESERVE the jump

if __name__ == '__main__':
    unittest.main()
