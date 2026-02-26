import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
import pandas as pd
import numpy as np

from .db import get_connection

logger = logging.getLogger("PaperTradingEngine")

class PaperTradingEngine:
    """
    Phase 3.5: Validation Layer
    Executes paper trades based on probabilistic signals (Regime, Confidence, RA-EV).
    """
    
    def __init__(self, config: Optional[dict] = None):
        self.config = config or {
            "min_confidence": 0.8,
            "min_ra_ev": 0.0,
            "max_holding_minutes": 1440, # 24 hours
            "capital_base": 1000.0,      # $1000 simulation
        }

    def update(self, current_signals: List[dict]):
        """
        Process a batch of current signals to Open or Close trades.
        """
        # 1. Get Active Trades
        active_trades = self._get_active_trades()
        active_tokens = {t['currency']: t for t in active_trades}
        
        for signal in current_signals:
            token = signal['token']
            
            if token in active_tokens:
                self._process_open_position(active_tokens[token], signal)
            else:
                self._process_potential_entry(signal)

    def _get_active_trades(self) -> List[dict]:
        with get_connection() as conn:
            return conn.execute(
                "SELECT * FROM paper_trades WHERE exit_timestamp IS NULL"
            ).fetchall()

    def _process_potential_entry(self, signal: dict):
        """Check entry conditions."""
        regime = signal.get('regime')
        conf = signal.get('confidence', 0)
        ra_ev = signal.get('ra_ev', 0)
        
        # Criteria: Regime Rising/High, Conf > Thresh, RA-EV > 0
        is_entry = (
            regime in ['Rising', 'High'] and
            conf >= self.config['min_confidence'] and
            ra_ev > self.config['min_ra_ev']
        )
        
        if is_entry:
            self._open_trade(signal)

    def _process_open_position(self, trade: dict, signal: dict):
        """Check exit conditions for an existing trade."""
        regime = signal.get('regime')
        ra_ev = signal.get('ra_ev', 0)
        
        # Duration check
        try:
            entry_time = datetime.fromisoformat(trade['entry_timestamp'].replace('Z', '+00:00'))
            current_time = datetime.fromisoformat(signal['timestamp'].replace('Z', '+00:00'))
            duration_mins = (current_time - entry_time).total_seconds() / 60
        except Exception:
            duration_mins = 0
        
        exit_reason = None
        
        # Exit Logic
        if regime == 'Decay':
            exit_reason = "Regime Decay"
        elif ra_ev < 0:
            exit_reason = "Negative RA-EV"
        elif duration_mins >= self.config['max_holding_minutes']:
            exit_reason = "Max Duration"
        
        if exit_reason:
            self._close_trade(trade, signal, exit_reason, duration_mins)

    def _open_trade(self, signal: dict):
        unique_id = f"{signal['token']}_{signal['timestamp']}"
        with get_connection() as conn:
            # Prevent duplicates if run frequently
            exists = conn.execute(
                "SELECT 1 FROM paper_trades WHERE currency = ? AND entry_timestamp = ?",
                (signal['token'], signal['timestamp'])
            ).fetchone()
            if exists: return

            conn.execute(
                """INSERT INTO paper_trades 
                   (currency, entry_timestamp, entry_apr, borrow_cost, withdrawal_fee, signal_snapshot_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    signal['token'],
                    signal['timestamp'],
                    signal['apr'],
                    0, # Initial borrow cost
                    signal.get('withdrawal_fee', 0),
                    json.dumps(signal),
                    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                )
            )
        logger.info(f"🟢 OPEN PAPER: {signal['token']} @ {signal['apr']}% (Regime: {signal.get('regime')})")

    def _close_trade(self, trade: dict, signal: dict, reason: str, duration_mins: float):
        entry_apr = trade['entry_apr']
        exit_apr = signal['apr']
        avg_apr = (entry_apr + exit_apr) / 2
        
        # --- HOURLY ACCRUAL MODEL (Discrete) ---
        entry_dt = datetime.fromisoformat(trade['entry_timestamp'].replace('Z', '+00:00'))
        exit_dt = datetime.fromisoformat(signal['timestamp'].replace('Z', '+00:00'))
        
        # 1. Earn Reward Calculation
        # Rule: Accrual starts at NEXT full hour boundary.
        # Example: Entry 12:30 -> Start 13:00.
        # Example: Entry 12:00 -> Start 13:00 (Standard conservative logic or strict > check).
        # We use ceil to next hour.
        
        # Find next full hour
        next_hour_ts = entry_dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        
        earn_hours = 0
        if exit_dt > next_hour_ts:
            # Count FULL hours completed after start
            delta = exit_dt - next_hour_ts
            earn_hours = int(delta.total_seconds() // 3600)
            
        # Earn Yield (Simple Interest per hour)
        # Formula: Capital * (APR / 100) / (365 * 24) * Earn_Hours
        capital = self.config['capital_base']
        hourly_earn_rate = (avg_apr / 100.0) / 8760.0 # 8760 = 24 * 365
        gross_yield_usd = capital * hourly_earn_rate * earn_hours
        
        # 2. Borrow Cost Calculation
        # Rule: Minimum 1 hour. Discrete hourly chunks.
        # Logic: "Assume full-hour cost unless proven otherwise".
        # We ceil the duration to hours. 15 mins -> 1 hour cost. 65 mins -> 2 hours cost.
        borrow_duration_hours = int(np.ceil(duration_mins / 60.0))
        if borrow_duration_hours < 1: borrow_duration_hours = 1
        
        borrow_apr = signal.get('borrow_cost_apr', 0)
        hourly_borrow_rate = (borrow_apr / 100.0) / 8760.0
        borrow_cost_usd = capital * hourly_borrow_rate * borrow_duration_hours
        
        # 3. Withdrawal Fee ($)
        wd_fee_usd = trade['withdrawal_fee']

        # 4. Net PnL ($)
        realized_pnl_usd = gross_yield_usd - borrow_cost_usd - wd_fee_usd
        
        # Convert to ROI %
        roi_pct = (realized_pnl_usd / capital) * 100.0

        with get_connection() as conn:
            conn.execute(
                """UPDATE paper_trades 
                   SET exit_timestamp = ?, 
                       exit_apr = ?, 
                       holding_minutes = ?, 
                       realized_pnl = ?, 
                       exit_reason = ?,
                       borrow_cost = ? 
                   WHERE id = ?""",
                (
                    signal['timestamp'],
                    exit_apr,
                    int(duration_mins),
                    roi_pct, 
                    f"{reason} (Earn:{earn_hours}h, Borrow:{borrow_duration_hours}h)", # Log details for audit
                    borrow_cost_usd,
                    trade['id']
                )
            )
        logger.info(f"🔴 CLOSE PAPER: {signal['token']} PnL: ${realized_pnl_usd:.2f} ({roi_pct:.2f}%) Reason: {reason}")


class PerformanceMonitor:
    """
    Computes rolling statistics for validation gate.
    """
    @staticmethod
    def get_stats(days: int = 30) -> dict:
        """Calculate metrics over the last N days."""
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        with get_connection() as conn:
            # Fetch completed trades
            df = pd.read_sql(
                "SELECT * FROM paper_trades WHERE exit_timestamp >= ? AND exit_timestamp IS NOT NULL",
                conn,
                params=(cutoff_date,)
            )
            
        if df.empty:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "cumulative_return": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "system_ready": False
            }
            
        # Metrics
        total_trades = len(df)
        wins = df[df['realized_pnl'] > 0]
        win_rate = len(wins) / total_trades if total_trades > 0 else 0
        
        # Cumulative PnL (Sum of % returns)
        # Assuming simple interest / non-compounding for this metric
        cumulative_return = df['realized_pnl'].sum()
        
        # Drawdown calculation (on cumulative equity curve)
        df['equity'] = df['realized_pnl'].cumsum()
        df['peak'] = df['equity'].cummax()
        df['drawdown'] = df['equity'] - df['peak']
        max_drawdown = df['drawdown'].min()
        
        # Sharpe (Simplified: Mean / StdDev of returns)
        returns = df['realized_pnl']
        if len(returns) > 1 and returns.std() > 0:
            sharpe = returns.mean() / returns.std()
        else:
            sharpe = 0.0
            
        # Validation Gate
        # Rules: > 100 trades, > 0 return, drawdown > -10% (allow 10% DD), Sharpe > 0.5
        ready = (
            total_trades >= 100 and 
            cumulative_return > 0 and 
            max_drawdown > -10.0 and 
            sharpe > 0.5
        )
        
        return {
            "total_trades": total_trades,
            "win_rate": round(win_rate * 100, 1),
            "cumulative_return": round(cumulative_return, 2),
            "max_drawdown": round(max_drawdown, 2),
            "sharpe_ratio": round(sharpe, 2),
            "system_ready": ready
        }
