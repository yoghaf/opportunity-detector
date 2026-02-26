
"""
Alpha Validation Module - Quantitative Research
Tests the hypothesis: "Do EMA trend signals predict Net APR spikes?"
"""
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from src.prediction.db import DB_PATH

import json

def load_data(hours=24):
    """Load recent opportunity data from SQLite"""
    try:
        conn = sqlite3.connect(DB_PATH)
        # Select raw_payload which contains the JSON blob
        # Filter for data_type='opportunity' to get Net APR data
        query = f"""
            SELECT timestamp, currency, apr, raw_payload, data_type 
            FROM apr_history 
            WHERE timestamp >= datetime('now', '-{hours} hours')
            ORDER BY timestamp ASC
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        if df.empty:
            print("No data found in DB.")
            return pd.DataFrame()

        parsed_data = []
        for _, row in df.iterrows():
            try:
                # If we have direct columns, use them as defaults
                item = {
                    'timestamp': row['timestamp'],
                    'token': row['currency'],
                    'net_apr': row['apr'], # Default to 'apr' column
                    'gate_apr': row['apr']
                }
                
                # Parse JSON for more details (Net APR vs Gate APR)
                if row['raw_payload']:
                    data = json.loads(row['raw_payload'])
                    # If opportunity data, use specific fields
                    if row['data_type'] == 'opportunity':
                        item['token'] = data.get('currency', item['token'])
                        item['net_apr'] = float(data.get('net_apr', 0))
                        item['gate_apr'] = float(data.get('gate_apr', 0))
                        item['best_loan_rate'] = float(data.get('best_loan_rate', 0))
                    # If raw data, Net APR = Gate APR (no loan cost known)
                    elif row['data_type'] == 'raw':
                        # Raw data usually just Gate APR
                        pass
                
                # Only include if we have a valid token
                if item['token']:
                    parsed_data.append(item)
                    
            except (json.JSONDecodeError, TypeError):
                continue
                
        if not parsed_data:
            print("No valid parsed data.")
            return pd.DataFrame()
            
        clean_df = pd.DataFrame(parsed_data)
        clean_df['timestamp'] = pd.to_datetime(clean_df['timestamp'])
        
        # Filter: We really need Net APR > 0 or at least valid opportunity data for Alpha test
        # But for 'raw' data we might want to analyze Gate APR spikes too?
        # User asked for "Net APR prediction". So preferably 'opportunity' data.
        
        return clean_df

    except Exception as e:
        print(f"Error loading data: {e}")
        return pd.DataFrame()

def detect_spikes(df, token, threshold_ratio=2.0, min_apr=10.0, min_duration_minutes=2):
    """
    Identify significant APR spikes for a specific token.
    Rule: Net APR >= Baseline * threshold AND Net APR > min_apr
    """
    token_data = df[df['token'] == token].copy().sort_values('timestamp')
    if len(token_data) < 10:
        return []

    # Calculate Baseline (Rolling Median 60m to ignore short anomalies)
    token_data['baseline'] = token_data['net_apr'].rolling(window=120, min_periods=10, center=False).median()
    
    # Fill NaN baseline with initial mean
    token_data['baseline'] = token_data['baseline'].bfill()

    # Detect conditions
    token_data['is_spike'] = (
        (token_data['net_apr'] >= token_data['baseline'] * threshold_ratio) & 
        (token_data['net_apr'] > min_apr)
    )

    # Group consecutive spike events
    token_data['group'] = (token_data['is_spike'] != token_data['is_spike'].shift()).cumsum()
    
    spikes = []
    for gid, group in token_data[token_data['is_spike']].groupby('group'):
        start_time = group['timestamp'].iloc[0]
        end_time = group['timestamp'].iloc[-1]
        peak_apr = group['net_apr'].max()
        duration_min = (end_time - start_time).total_seconds() / 60
        
        if duration_min >= min_duration_minutes:
            spikes.append({
                'token': token,
                'start_time': start_time,
                'end_time': end_time,
                'peak_net_apr': peak_apr,
                'duration_minutes': duration_min,
                'baseline': group['baseline'].mean()
            })
            
    return spikes

def calculate_ema_signals(df, token, short_span=5, long_span=20):
    """
    Compute EMA Crossover Signals.
    Returns DataFrame with 'signal' column (1=UP, -1=DOWN, 0=FLAT)
    """
    data = df[df['token'] == token].copy().sort_values('timestamp')
    data['ema_short'] = data['net_apr'].ewm(span=short_span, adjust=False).mean()
    data['ema_large'] = data['net_apr'].ewm(span=long_span, adjust=False).mean()
    
    # Signal: Short > Long + Buffer? Keeping it simple for now
    data['signal'] = 0
    data.loc[data['ema_short'] > data['ema_large'], 'signal'] = 1 # UP
    data.loc[data['ema_short'] < data['ema_large'], 'signal'] = -1 # DOWN
    
    # Detect Crosses (Change in signal)
    data['signal_change'] = data['signal'].diff()
    
    return data

def analyze_lead_lag(df, token, spikes):
    """
    Check if Signal turned UP *before* the spike started.
    """
    if not spikes:
        return {'score': 0, 'details': []}
        
    signals = calculate_ema_signals(df, token)
    
    results = []
    valid_leads = 0
    
    for spike in spikes:
        spike_start = spike['start_time']
        
        # Lookback 30 minutes before spike
        lookback_window = spike_start - timedelta(minutes=30)
        
        # Find signals in this window
        window_data = signals[
            (signals['timestamp'] >= lookback_window) & 
            (signals['timestamp'] <= spike_start)
        ]
        
        # Find the LAST signal change to UP before spike
        up_signals = window_data[window_data['signal_change'] > 0] # Signal went 0->1 or -1->1
        
        if not up_signals.empty:
            last_signal_time = up_signals.iloc[-1]['timestamp']
            lead_time_sec = (spike_start - last_signal_time).total_seconds()
            
            # Valid Lead: Signal must be at least 1 min before spike, but not > 30 mins (stale)
            if lead_time_sec > 30: 
                valid_leads += 1
                results.append({
                    'spike_start': spike_start,
                    'signal_time': last_signal_time,
                    'lead_time_sec': lead_time_sec,
                    'valid': True
                })
            else:
                 results.append({'valid': False, 'reason': 'Signal too close/late'})
        else:
            results.append({'valid': False, 'reason': 'No UP signal in window'})
            
    return {
        'token': token,
        'total_spikes': len(spikes),
        'predicted_spikes': valid_leads,
        'success_rate': (valid_leads / len(spikes)) * 100 if spikes else 0,
        'details': results
    }

def simulate_sniper_ev(df, token, initial_capital=1000, trade_size=100):
    """
    Simulate Trades: Enter on Signal UP, Exit on Signal DOWN.
    """
    signals = calculate_ema_signals(df, token)
    
    in_position = False
    entry_price = 0 # In APR context, we gain (APR * time) / 365
    entry_time = None
    
    trades = []
    
    for idx, row in signals.iterrows():
        if row['signal_change'] > 0 and not in_position:
            # BUY SIGNAL
            in_position = True
            entry_time = row['timestamp']
            entry_apr = row['net_apr'] # Approx
            
        elif row['signal_change'] < 0 and in_position:
            # SELL SIGNAL
            in_position = False
            exit_time = row['timestamp']
            
            # Valid trade?
            duration_hours = (exit_time - entry_time).total_seconds() / 3600
            if duration_hours < 0.01: continue # Ignore sub-minute flicker
            
            # Simple Profit Calc: (Avg APR during trade * Duration)
            # We need avg APR between entry and exit
            trade_window = signals[
                (signals['timestamp'] >= entry_time) & 
                (signals['timestamp'] <= exit_time)
            ]
            avg_apr = trade_window['net_apr'].mean()
            
            # Profit % = (APR/100) * (Hours / 24 / 365) * Capital ?? 
            # Actually APR is annualized.
            # Profit Ratio = (AvgAPR / 100) * (DurationHours / 8760)
            profit_ratio = (avg_apr / 100.0) * (duration_hours / 8760.0)
            
            # Fees? (Assume 0.1% per trade cycle if lending logic involved? cost of borrow?)
            # Simplified: cost = 0.001 (0.1%)
            # cost = 0.0 # Ignore fees for pure Alpha test first
            
            trades.append({
                'entry_time': entry_time,
                'exit_time': exit_time,
                'duration_hours': duration_hours,
                'avg_apr': avg_apr,
                'profit_ratio': profit_ratio
            })
            
    # Aggregation
    if not trades:
        return {'ev_per_trade': 0, 'win_rate': 0, 'total_trades': 0}
        
    df_trades = pd.DataFrame(trades)
    return {
        'token': token,
        'total_trades': len(df_trades),
        'avg_duration_h': df_trades['duration_hours'].mean(),
        'avg_trade_apr': df_trades['avg_apr'].mean(),
        'total_profit_ratio': df_trades['profit_ratio'].sum(),
        'ev_per_trade': df_trades['profit_ratio'].mean()
    }

if __name__ == "__main__":
    print("🔬 Loading Data...")
    df = load_data(hours=24)
    if df.empty:
        print("❌ No data found. Run collector first.")
        exit()
        
    start_time = df['timestamp'].min()
    end_time = df['timestamp'].max()
    duration = (end_time - start_time).total_seconds() / 3600
    
    print(f"📅 Data Range: {start_time} to {end_time} ({duration:.2f} hours)")
    print(f"📊 Analyzing {len(df['token'].unique())} tokens ({len(df)} rows)...")
    
    tokens = df['token'].unique()
    
    # Sort tokens by max Net APR to prioritize interesting ones
    # Calculate max net apr per token
    token_max_apr = df.groupby('token')['net_apr'].max().sort_values(ascending=False)
    
    top_tokens = token_max_apr.head(5).index.tolist()
    
    for token in top_tokens: 
        print(f"\n🪙 Token: {token} (Max Net APR: {token_max_apr[token]:.2f}%)")
        spikes = detect_spikes(df, token)
        print(f"   ⚡ Spikes: {len(spikes)}")
        if spikes:
           for s in spikes:
               print(f"      - {s['start_time']} | Peak: {s['peak_net_apr']:.1f}% | Dur: {s['duration_minutes']:.1f}m")
               
           lead_stats = analyze_lead_lag(df, token, spikes)
           print(f"   🎯 Prediction Success: {lead_stats['success_rate']:.1f}%")
           
           ev = simulate_sniper_ev(df, token)
           print(f"   💰 EV/Trade: {ev['ev_per_trade']*100:.6f}% (Avg APR: {ev['avg_trade_apr']:.1f}%)")
