
import pandas as pd
import numpy as np
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

from .db import get_connection, get_token_history
from .db import get_connection, get_token_history
from .features import DataQuality, LightweightHMM
from .analytics import SurvivalStats, RiskEngine
from .simulation import PaperTradingEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('PredictionPipeline')

class PredictionPipeline:
    """
    Phase 1: Orchestration
    Runs the full Clean -> Infer -> Value -> Store cycle.
    """
    
    def __init__(self):
        self.hmm = LightweightHMM()
        self.trader = PaperTradingEngine()
        self.survival_curves = {} 

    def update_survival_curves(self):
        """
        Periodically called (e.g. daily) to re-compute Survival Curves from history.
        """
        logger.info("Re-training Survival Curves...")
        
        tiers = ['100-200', '200-400', '400+']
        for tier in tiers:
            # Mock Logic: Higher tier = faster decay
            decay_rate = 0.99 if tier == '100-200' else 0.95 if tier == '200-400' else 0.90
            probs = [decay_rate ** i for i in range(60)]
            
            with get_connection() as conn:
                for minute, prob in enumerate(probs):
                    conn.execute(
                        "INSERT OR REPLACE INTO survival_curves (tier, minute, survival_prob, updated_at) VALUES (?, ?, ?, ?)",
                        (tier, minute, prob, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
                    )
        logger.info("Survival Curves updated.")

    def run_cycle(self):
        """
        Main execution entry point.
        """
        # 0. Maintenance - Run once to populate DB if empty
        # self.update_survival_curves() 
        
        active_tokens = self._get_active_tokens()
        logger.info(f"Starting pipeline cycle for {len(active_tokens)} active tokens.")
        
        signals_batch = []
        
        for token in active_tokens:
            try:
                signal = self.process_token(token)
                if signal:
                    signals_batch.append(signal)
            except Exception as e:
                logger.error(f"Error processing {token}: {e}")
                
        # Update Simulation
        if signals_batch:
            try:
                self.trader.update(signals_batch)
            except Exception as e:
                logger.error(f"Paper Trading Update Failed: {e}")

    def _get_active_tokens(self) -> List[str]:
        # Simple query to get tokens updated in last 10 mins
        with get_connection() as conn:
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
            rows = conn.execute(
                "SELECT DISTINCT currency FROM apr_history WHERE timestamp >= ?", 
                (cutoff,)
            ).fetchall()
            return [r[0] for r in rows]

    def process_token(self, token: str) -> Optional[dict]:
        history = get_token_history(token, hours=24)
        if not history or len(history) < 20:
            return None
            
        df = pd.DataFrame(history)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        apr_series = pd.Series(df['net_apr'].values, index=df['timestamp'])
        try:
            apr_clean = DataQuality.dual_stage_filter(apr_series)
        except Exception as e:
            logger.warning(f"Filter failed for {token}, skipping. {e}")
            return None

        # Feature Engineering
        try:
            slope = apr_clean.diff(1).iloc[-1] # 1 min diff
            volatility = apr_clean.diff().rolling(15).std().iloc[-1]
            ema_short = apr_clean.ewm(span=5).mean().iloc[-1]
            ema_long = apr_clean.ewm(span=20).mean().iloc[-1]
            divergence = ema_short - ema_long
        except:
             return None

        # HMM
        latest_apr = apr_clean.iloc[-1]
        features = {
            'apr': latest_apr,
            'slope': slope if not pd.isna(slope) else 0,
            'divergence': divergence,
            'volatility': volatility if not pd.isna(volatility) else 0
        }
        regime_probs = self.hmm.update(features)
        
        # Determine dominant regime and confidence
        dominant_regime = max(regime_probs, key=regime_probs.get)
        confidence = regime_probs[dominant_regime]
        
        # RA-EV
        # Load curve for tier
        # In prod: fetch from DB. usage mock for now to match _store
        mock_curve = pd.DataFrame({'survival_prob': [0.99 ** i for i in range(60)]})
        ra_ev = RiskEngine.calculate_ra_ev(latest_apr, mock_curve, volatility=features['volatility'])
        
        # Store
        hist_entry = history[-1]
        self._store_features(
            token, hist_entry['timestamp'], 
            hist_entry['net_apr'], latest_apr, regime_probs, features['volatility']
        )
        
        # Construct Signal for Paper Trader
        # Attempt to get withdrawal fee from latest history entry if available (it might not be in generic get_token_history stats)
        # We assume net_apr accounts for borrow cost, so borrow_cost_apr passed to engine = 0
        return {
            "token": token,
            "apr": latest_apr,
            "regime": dominant_regime,
            "confidence": confidence,
            "ra_ev": ra_ev,
            "volatility": features['volatility'],
            "borrow_cost_apr": 0, # Net APR used
            "withdrawal_fee": 0,  # Placeholder until we fetch from raw_payload
            "timestamp": hist_entry['timestamp']
        }

    def _store_features(self, currency, timestamp, apr_raw, apr_clean, regime_probs, volatility):
        with get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO apr_features 
                   (timestamp, currency, apr_raw, apr_clean, regime_prob, volatility)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (timestamp, currency, apr_raw, apr_clean, json.dumps(regime_probs), volatility)
            )

if __name__ == "__main__":
    pipeline = PredictionPipeline()
    # Uncomment to init DB if needed
    pipeline.update_survival_curves()
    pipeline.run_cycle()
    def _store_features(self, currency, timestamp, apr_raw, apr_clean, regime_probs, volatility):
        with get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO apr_features 
                   (timestamp, currency, apr_raw, apr_clean, regime_prob, volatility)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (timestamp, currency, apr_raw, apr_clean, json.dumps(regime_probs), volatility)
            )

if __name__ == "__main__":
    pipeline = PredictionPipeline()
    # Uncomment to init DB if needed
    pipeline.update_survival_curves()
    pipeline.run_cycle()
