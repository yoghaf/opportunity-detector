
import sys
import os
import pandas as pd
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.settings import Config
from src.exchanges.gate_client import GateClient
from src.exchanges.okx_client import OKXClient
from src.exchanges.binance_client import BinanceClient
from src.strategies.opportunity_finder import OpportunityFinder
from src.utils.logger import setup_logger

logger = setup_logger("test_fees")

def test_fetch_fees():
    print("🚀 Initializing clients for Fee Test...")
    gate = GateClient()
    okx = OKXClient()
    binance = BinanceClient()
    
    finder = OpportunityFinder(gate, okx, binance)
    
    tokens = ['ETH', 'USDT', 'SOL', 'CELO'] # Test a mix of tokens
    
    print("\n🔍 Fetching Withdrawal Fees...")
    for token in tokens:
        print(f"\n🪙 Testing: {token}")
        try:
            fees = finder.get_token_wd_fees(token)
            
            gate_price = fees.get('token_price', 0.0)
            print(f"   Token Price (USDT): ${gate_price:,.4f}")
            
            # Print Fee + (USD)
            gate_fee = fees.get('gate_wd_fee', 0.0)
            gate_usd = fees.get('gate_wd_fee_usd', 0.0)
            print(f"   Gate: {gate_fee:.6f} (${gate_usd:.2f})")
            
            okx_fee = fees.get('okx_wd_fee', 0.0)
            okx_usd = fees.get('okx_wd_fee_usd', 0.0)
            print(f"   OKX:  {okx_fee:.6f} (${okx_usd:.2f})")
            
            bin_fee = fees.get('binance_wd_fee', 0.0)
            bin_usd = fees.get('binance_wd_fee_usd', 0.0)
            print(f"   Bin.: {bin_fee:.6f} (${bin_usd:.2f})")
            
            # Verify caching
            cached_fees = finder.get_token_wd_fees(token)
            if cached_fees == fees:
                print("   ✅ Cache Hit confirmed.")
            else:
                print("   ❌ Cache MISS.")
        except Exception as e:
            print(f"   ❌ Error fetching fees for {token}: {e}")

if __name__ == "__main__":
    test_fetch_fees()
