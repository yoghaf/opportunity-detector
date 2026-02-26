
import os
import sys
import gate_api
from config.settings import Config

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def prove_dynamic_data():
    print("🔌 Connecting to Gate.io API (Live)...")
    configuration = gate_api.Configuration(
        host="https://api.gateio.ws/api/v4",
        key=Config.GATE_API_KEY,
        secret=Config.GATE_API_SECRET
    )
    api_client = gate_api.ApiClient(configuration)
    earn_api = gate_api.EarnUniApi(api_client)
    unified_api = gate_api.UnifiedApi(api_client)

    print("📡 Fetching ALL active Simple Earn rates...")
    rates = earn_api.list_uni_rate()
    print(f"✅ Received {len(rates)} tokens from API.")
    
    # Filter for high rates to show it's dynamic
    high_yield = []
    
    print("\n🔍 Verifying Top 5 Opportunities (Live Data):")
    print(f"{'Token':<10} | {'Est. Rate (API)':<20} | {'Realized APR (History)':<25}")
    print("-" * 65)

    # Sort by estimated rate first to pick candidates
    # API returns string floats
    sorted_rates = sorted(rates, key=lambda x: float(x.est_rate) if x.est_rate else 0, reverse=True)
    
    count = 0
    for r in sorted_rates[:5]: # Check top 5
        token = r.currency
        est = float(r.est_rate)
        
        # Verify with History (Source of Truth)
        try:
            history = unified_api.get_history_loan_rate(currency=token, limit=1)
            if hasattr(history, 'rates') and history.rates:
                latest = history.rates[0]
                hourly = float(latest.rate)
                real_apr = hourly * 24 * 365 * 100
                
                print(f"{token:<10} | {est:<20.4f} | {real_apr:<25.2f}%")
            else:
                print(f"{token:<10} | {est:<20.4f} | {'No History Data':<25}")
        except Exception as e:
            print(f"{token:<10} | {est:<20.4f} | Error: {e}")
            
if __name__ == "__main__":
    prove_dynamic_data()
