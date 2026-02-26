
import numpy as np
import pandas as pd
from typing import List, Dict, Tuple, Optional
from datetime import datetime
import json
from .db import get_connection

class SurvivalStats:
    """
    Phase 1: Conditional Survival Analysis (Kaplan-Meier)
    """

    @staticmethod
    def compute_kaplan_meier(durations: List[float], event_observed: List[bool]) -> pd.DataFrame:
        """
        Computes Kaplan-Meier survival curve from scratch.
        durations: time until event or censoring
        event_observed: True if decay occurred, False if censored (still active)
        """
        df = pd.DataFrame({'duration': durations, 'event': event_observed})
        
        # Group by duration
        # Count deaths (d_i) and at-risk (n_i)
        summary = df.group_by('duration').agg(
            d_i=('event', 'sum'),
            n_i=('event', 'count')
        ).sort_index()
        
        # Adjust n_i to be "at risk" (reverse cumsum of total counts)
        # Note: The count above is just count at that specific time.
        # We need cumulative count from end to start.
        total_counts = df['duration'].value_counts().sort_index(ascending=False)
        at_risk = total_counts.cumsum().sort_index()
        
        summary['n_i'] = at_risk
        
        # KM Formula: S(t) = prod(1 - d_i / n_i)
        summary['survival_prob'] = (1 - summary['d_i'] / summary['n_i']).cumprod()
        
        return summary[['survival_prob']]

    @staticmethod
    def get_apr_tier(apr: float) -> str:
        if apr < 200:
            return "100-200"
        elif apr < 400:
            return "200-400"
        else:
            return "400+"

class RiskEngine:
    """
    Phase 1: Discrete Risk-Adjusted Valuation
    """
    
    @staticmethod
    def calculate_ra_ev(
        current_apr: float,
        survival_curve: pd.DataFrame,
        horizon_minutes: int = 60,
        borrow_cost: float = 0.0,
        volatility: float = 0.0,
        risk_aversion: float = 0.5
    ) -> float:
        """
        Discrete RA-EV = sum(APR_t * S(t) * dt) - Cost - (lambda * vol)
        """
        dt = 1.0 / (365 * 24 * 60) # 1 minute in years
        
        expected_yield = 0.0
        
        # Iterate up to horizon (or max curve length)
        max_t = min(horizon_minutes, len(survival_curve))
        
        for t in range(max_t):
            # Get survival prob at time t (or last available)
            try:
                prob = survival_curve.iloc[t]['survival_prob']
            except IndexError:
                prob = survival_curve.iloc[-1]['survival_prob']
                
            # Expected APR yield for this minute
            # Assumption: APR decays if event happens, but we model the "surviving" path yield
            # Simpler model: Yield is accrued only if survived.
            expected_yield += (current_apr * prob * dt)
            
        # Total Expected Value
        total_ev = expected_yield - borrow_cost - (risk_aversion * volatility)
        
        return total_ev

class PaperTrader:
    """
    Phase 1: Ground-Truth Logging
    """
    
    @staticmethod
    def log_entry(currency: str, apr: float, timestamp: str) -> int:
        """Start a paper trade."""
        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO paper_trades 
                   (currency, entry_timestamp, entry_apr) 
                   VALUES (?, ?, ?)""",
                (currency, timestamp, apr)
            )
            return cursor.lastrowid

    @staticmethod
    def log_exit(trade_id: int, exit_apr: float, timestamp: str, reason: str, pnl: float):
        """Close a paper trade."""
        with get_connection() as conn:
            conn.execute(
                """UPDATE paper_trades 
                   SET exit_timestamp = ?, exit_apr = ?, exit_reason = ?, realized_pnl = ?
                   WHERE id = ?""",
                (timestamp, exit_apr, reason, pnl, trade_id)
            )
