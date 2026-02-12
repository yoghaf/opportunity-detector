
import sys
import os
import requests
from config.settings import Config
from src.exchanges.okx_client import OKXClient
from src.exchanges.binance_client import BinanceClient
from src.utils.logger import setup_logger

logger = setup_logger('debug_proxy')

def main():
    print("--- Proxy Verification ---")
    
    # 1. Manual Request to check current IP/Proxy
    print("\n1. Direct Request (No Client)")
    try:
        ip = requests.get("https://api.ipify.org", timeout=5).text
        print(f"Direct connection IP: {ip}")
    except Exception as e:
        print(f"Direct connection failed: {e}")
        
    print(f"\nConfigured PROXY_URL: {Config.PROXY_URL if Config.PROXY_URL else 'NONE'}")
    
    # 2. OKX Client
    print("\n2. OKX Client Test")
    try:
        okx = OKXClient()
        print(f"OKX Session Proxies: {okx.session.proxies}")
        # Check connection
        connected, msg = okx.check_connection()
        print(f"OKX Connection Status: {connected} ({msg})")
        # Check public quota (doesn't need auth, good for connectivity test)
        # quota = okx.get_public_loan_quota()
        # print(f"OKX Public Quota result count: {len(quota) if quota else 0}")
    except Exception as e:
        print(f"OKX Client Init Failed: {e}")

    # 3. Binance Client
    print("\n3. Binance Client Test")
    try:
        binance = BinanceClient()
        print(f"Binance Session Proxies: {binance.session.proxies}")
        # Simple Earn Rates (public endpoint)
        rates = binance.get_simple_earn_rates()
        print(f"Binance Earn Rates result count: {len(rates) if rates else 0}")
    except Exception as e:
        print(f"Binance Client Init Failed: {e}")

if __name__ == "__main__":
    main()
