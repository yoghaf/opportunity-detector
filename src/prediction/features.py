
import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple

class DataQuality:
    """
    Phase 1: Signal Processing & Outlier Rejection
    """
    
    @staticmethod
    def hampel_filter(series: pd.Series, window_size: int = 5, n_sigmas: int = 3) -> pd.Series:
        """
        Standard Hampel Filter for outlier detection.
        Replaces outliers with the rolling median.
        """
        rolling_median = series.rolling(window=window_size, center=True).median()
        rolling_mad = series.rolling(window=window_size, center=True).apply(
            lambda x: np.median(np.abs(x - np.median(x))), raw=True
        )
        threshold = n_sigmas * 1.4826 * rolling_mad
        outlier_idx = np.abs(series - rolling_median) > threshold
        
        cleaned_series = series.copy()
        cleaned_series[outlier_idx] = rolling_median[outlier_idx]
        return cleaned_series

    @classmethod
    def dual_stage_filter(cls, series: pd.Series) -> pd.Series:
        """
        Executes Dual-Stage Filtering:
        1. Micro-Glitch Filter (k=2, ~2-5 mins) - Removes API noise.
        2. Structural Spike Validator (k=10, ~21 mins) - Validates true regime shifts.
        """
        # Stage A: Micro-Glitch Filter
        # k=2 means window of 5 samples (centered)
        s1 = cls.hampel_filter(series, window_size=5, n_sigmas=3)
        
        # Stage B: Structural Spike Validator
        # k=10 means window of 21 samples. 
        # We need to distinguish between a massive noise spike vs a liquidity event (regime start).
        
        rolling_long_med = s1.rolling(window=21, center=True).median()
        rolling_long_std = s1.rolling(window=21, center=True).std()
        
        # Identification of Potential Spikes (Deviations > 3 sigma from long trend)
        # Note: If std is 0 (flat line), we handle div by zero by filling with small epsilon or ignoring
        z_scores = (s1 - rolling_long_med) / (rolling_long_std + 1e-6)
        potential_spikes = np.abs(z_scores) > 3
        
        # Validation Logic:
        # True Spike (Regime Shift) MUST have a supporting positive slope leading up to it or sustained.
        # Noise Spike usually has slope ~ 0 before/after (sudden jump, sudden drop).
        
        # We'll stick to the core requirement: 
        # "If |x - median| > 3sigma AND local slope ~ 0 -> REJECT"
        
        # Calculate Local Slope (3-point regression or simple diff)
        # Using simple diff for speed: (x_t - x_{t-2}) / 2
        local_slope = s1.diff(2).abs() # Absolute change over last 2 mins
        
        # If slope is very small but Z-score is huge, it's likely a data error (teleportation).
        # A real liquidity crunch implies rapid but continuous price/rate action.
        
        # Thresholds
        min_slope_for_validity = 0.5 # 0.5% change per 2 mins to justify a 3-sigma event
        
        mask_invalid = potential_spikes & (local_slope < min_slope_for_validity)
        
        final_series = s1.copy()
        # Impute invalid structural spikes with long median
        final_series[mask_invalid] = rolling_long_med[mask_invalid]
        
        return final_series.ffill().bfill()

class LightweightHMM:
    """
    Phase 1: Probabilistic Regime Modeling
    States: Low (0), Rising (1), High (2), Decay (3)
    """
    
    STATES = ['Low', 'Rising', 'High', 'Decay']
    
    def __init__(self):
        # Transition Matrix (Conceptual)
        # Low -> Rising
        # Rising -> High or Decay
        # High -> Decay or High
        # Decay -> Low or Rising
        self.trans_mat = np.array([
            [0.90, 0.10, 0.00, 0.00], # Low
            [0.05, 0.80, 0.15, 0.00], # Rising
            [0.00, 0.00, 0.90, 0.10], # High
            [0.20, 0.10, 0.00, 0.70], # Decay
        ])
        
        # Initial State Probability (Assume Low start)
        self.start_prob = np.array([0.9, 0.1, 0.0, 0.0])
        
        # Internal belief state
        self.belief = self.start_prob.copy()

    def emission_prob(self, features: dict) -> np.ndarray:
        """
        Calculate P(Observation | State) for each state.
        Features: apr, trend_strength (divergence), volatility, slope
        """
        apr = features.get('apr', 0)
        slope = features.get('slope', 0)
        div = features.get('divergence', 0)
        
        # Simplified Gaussian Emissions (normalized per feature usually, here heuristic for MVP)
        
        # State 0: Low (APR < 50, Flat Slope)
        p_low = 1.0 if apr < 50 and abs(slope) < 1 else 0.1
        
        # State 1: Rising (Positive Slope, Positive Divergence)
        p_rising = 1.0 if slope > 1 and div > 0 else 0.1
        
        # State 2: High (APR > 100, Sustained)
        p_high = 1.0 if apr > 100 else 0.1
        
        # State 3: Decay (Negative Slope)
        p_decay = 1.0 if slope < -1 else 0.1
        
        probs = np.array([p_low, p_rising, p_high, p_decay])
        return probs / (probs.sum() + 1e-9) # Normalize

    def update(self, features: dict) -> Dict[str, float]:
        """
        Online Forward Algorithm Update.
        Returns updated belief state as dict.
        """
        # 1. Prediction Step (Prior Belief using Transition Matrix)
        prior = self.belief @ self.trans_mat
        
        # 2. Update Step (Posterior using Emission)
        likelihood = self.emission_prob(features)
        posterior = prior * likelihood
        
        # Normalize
        self.belief = posterior / (posterior.sum() + 1e-9)
        
        return {s: round(p, 4) for s, p in zip(self.STATES, self.belief)}
