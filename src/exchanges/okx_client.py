# src/exchanges/okx_client.py
import requests
import hmac
import hashlib
import base64
import json
import time
import random
from datetime import datetime
from urllib.parse import urlencode
from config.settings import Config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class OKXClient:
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds
    
    def __init__(self):
        if not all([Config.OKX_API_KEY, Config.OKX_API_SECRET, Config.OKX_PASSPHRASE]):
            raise ValueError("OKX API keys tidak lengkap! Periksa .env file")
        
        self.api_key = Config.OKX_API_KEY
        self.secret_key = Config.OKX_API_SECRET
        self.passphrase = Config.OKX_PASSPHRASE
        self.base_url = "https://www.okx.com"
        self.session = requests.Session()  # Use session for connection reuse
        
        # Anti-Detection / Proxy
        if Config.PROXY_URL:
            self.session.proxies.update({
                'http': Config.PROXY_URL,
                'https': Config.PROXY_URL
            })
            logger.info(f"OKX Client using Proxy: {Config.PROXY_URL}")
    
    def _generate_signature(self, timestamp, method, request_path, body=''):
        message = str(timestamp) + str(method) + str(request_path) + str(body)
        logger.debug(f"Message to sign: {message}")
        
        mac = hmac.new(
            self.secret_key.encode('utf-8'),
            message.encode('utf-8'),
            digestmod=hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode('utf-8')
    
    def _make_request(self, method, base_path, params=None):
        """Make API request with retry logic"""
        for attempt in range(self.MAX_RETRIES):
            try:
                timestamp = datetime.utcnow().isoformat()[:-3] + 'Z'
                
                # Handle GET vs POST for Params & Signature
                request_path = base_path
                body = ""
                
                if method.upper() == "GET" and params is not None:
                    # For GET, params go into query string
                    # Sort params for signature consistency if needed, though requests.get usually handles dicts
                    # OKX requires sorted params for query string signature?
                    # "The query string ... must be sorted" -> standard is often sorted by key
                    query_parts = []
                    for k, v in sorted(params.items()):
                        query_parts.append(f"{k}={v}")
                    query_string = "&".join(query_parts)
                    request_path = f"{base_path}?{query_string}"
                    
                if method.upper() == "POST" and params:
                     # For POST, params go into JSON Body
                     body = json.dumps(params)
                
                # Jitter / Random Delay for POST (Borrow/Action) to mimic human
                if method.upper() == "POST":
                    delay = random.uniform(2.0, 5.0)
                    logger.info(f"⏳ Waiting {delay:.2f}s before execution (Anti-Detect)...")
                    time.sleep(delay)

                # Generate Signature
                sign = self._generate_signature(timestamp, method, request_path, body)
                
                # Rotate User-Agent
                user_agents = [
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"
                ]
                
                headers = {
                    "OK-ACCESS-KEY": self.api_key,
                    "OK-ACCESS-SIGN": sign,
                    "OK-ACCESS-TIMESTAMP": timestamp,
                    "OK-ACCESS-PASSPHRASE": self.passphrase,
                    "Content-Type": "application/json",
                    "User-Agent": random.choice(user_agents)
                }
                
                full_url = self.base_url + request_path
                
                logger.debug(f"Request: {method} {full_url} (attempt {attempt + 1})")
                
                if method.upper() == "GET":
                    response = self.session.request(method, full_url, headers=headers, timeout=15)
                else:
                    response = self.session.request(method, full_url, headers=headers, data=body, timeout=15)
                
                result = response.json()
                
                if result.get('code') == '0':
                    return result.get('data', [])
                else:
                    logger.error(f"OKX API Error: {result.get('msg')} (code: {result.get('code')})")
                    return []
                    
            except requests.exceptions.SSLError as e:
                logger.error(f"SSL Error (Internet Positif?): {e}")
                logger.error("👉 Please ENABLE your VPN/DNS. This error usually means your ISP is blocking the connection.")
                return []
            except (requests.exceptions.ConnectionError, ConnectionResetError) as e:
                logger.warning(f"Connection error (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}")
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY * (attempt + 1))  # Exponential backoff
                    continue
                logger.error(f"Max retries reached: {e}")
                return []
            except Exception as e:
                logger.error(f"OKX Request Error: {e}")
                return []
        return []
    
    def get_loan_limit(self):
        """Get loan interest and limit via REST API with retry"""
        params = {
            "type": "2",  # 2 = borrow interest
            "mgnMode": "cross"
        }
        
        data = self._make_request("GET", "/api/v5/account/interest-limits", params)
        if data:
            logger.info(f"OKX API success: {len(data)} records")
        return data
    
    def get_max_loan(self, currency):
        """Get ACTUAL max loan amount for a specific currency via /api/v5/account/max-loan
        
        This returns the real borrowable amount based on:
        - Your collateral value
        - Current pool liquidity
        - System limits
        """
        # instId format: CCY-USDT (e.g., ZRX-USDT, ETH-USDT)
        inst_id = f"{currency.upper()}-USDT"
        
        params = {
            "instId": inst_id,
            "mgnMode": "cross",
            "mgnCcy": "USDT" 
        }
        
        data = self._make_request("GET", "/api/v5/account/max-loan", params)
        
        if not data:
            logger.warning(f"No max-loan data for {currency}")
            return None
        
        # Find the maxLoan for the currency we want
        for item in data:
            if item.get('ccy', '').upper() == currency.upper():
                max_loan = float(item.get('maxLoan', 0))
                logger.info(f"Max loan for {currency}: {max_loan}")
                return max_loan
        
    
        # If currency found in response but with different ccy field
        if data:
            max_loan = float(data[0].get('maxLoan', 0))
            logger.info(f"Max loan for {currency}: {max_loan}")
            return max_loan
        
        return 0.0

    def get_flexible_max_loan(self, currency, collateral_currency="USDT"):
        """Get Max Loan for Flexible Loan (Simple Mode) via /api/v5/finance/flexible-loan/max-loan"""
        params = {
            "borrowCcy": currency.upper(),
            "supCollateralCcy": collateral_currency.upper(),
            "energy": "0"
        }
        
        # This endpoint uses POST!
        data = self._make_request("POST", "/api/v5/finance/flexible-loan/max-loan", params)
        
        if data and len(data) > 0:
            max_loan = self._safe_float(data[0].get('maxLoan'))
            logger.info(f"Flexible Max Loan for {currency}: {max_loan}")
            return max_loan
            
        return 0.0
    
    def set_leverage(self, currency, leverage, mgn_mode="cross"):
        """Set leverage for an instrument (needed to activate borrowing in some modes)
        
        Args:
            currency (str): Token symbol (e.g. ETH)
            leverage (str): Leverage multiplier (e.g. "3", "5")
            mgn_mode (str): Margin mode ("cross" or "isolated")
        """
        inst_id = f"{currency.upper()}-USDT"
        params = {
            "instId": inst_id,
            "lever": str(leverage),
            "mgnMode": mgn_mode
        }
        
        logger.info(f"Setting leverage to {leverage}x for {inst_id} ({mgn_mode})...")
        return self._make_request("POST", "/api/v5/account/set-leverage", params)

    def borrow_money(self, currency, amount):
        """Borrow tokens manually via /api/v5/account/spot-manual-borrow-repay
        
        Args:
            currency (str): Token symbol (e.g., 'USDT')
            amount (float): Amount to borrow
            
        Returns:
            dict: API response or None
        """
        params = {
            "ccy": currency.upper(),
            "side": "borrow",
            "amt": str(amount)
        }
        
        logger.info(f"Attempting to borrow {amount} {currency} on OKX...")
        data = self._make_request("POST", "/api/v5/account/spot-manual-borrow-repay", params)
        
        if data:
            logger.info(f"✅ Borrow success: {amount} {currency}")
            return data
        return None

    def get_account_risk(self):
        """Get account risk metrics (Margin Ratio / LTV)
        
        Uses /api/v5/account/account-position-risk
        
        Returns:
            dict: {
                'mgnRatio': float (Margin Ratio in %),
                'adjEq': float (Adjusted Equity in USD),
                'totalLiab': float (Total Liabilities in USD)
            } or None
        """
        # Note: endpoint might differ based on account mode (portfolio vs standard)
        # Trying account-position-risk first, if not available fall back to balance
        
        data = self._make_request("GET", "/api/v5/account/account-position-risk")
        
        if data and len(data) > 0:
            # OKX returns mgnRatio. 
            # If mgnRatio is high (e.g. > 10,000%), risk is low.
            # If mgnRatio is low (e.g. < 110%), risk is HIGH (liquidation risk).
            # LTV = 1 / mgnRatio (roughly) ??? 
            # Actually OKX uses Margin Ratio = Equity / Maintenance Margin.
            # Let's use simple leverage = Total Liab / Equity
            
            # Let's get balance details instead for simpler LTV calc
            # GET /api/v5/account/balance
            return data[0]
            
        return None

    def _safe_float(self, value):
        """Safely convert value to float, handling empty strings and None"""
        if value is None or value == '':
            return 0.0
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0

    def get_account_balance_details(self):
        """Get detailed account balance for LTV calculation and loan list"""
        data = self._make_request("GET", "/api/v5/account/balance")
        
        if data and len(data) > 0:
            details = data[0].get('details', [])
            total_eq = self._safe_float(data[0].get('totalEq'))
            mgn_ratio = self._safe_float(data[0].get('mgnRatio'))
            
            # Extract loans (liabilities)
            loans = []
            for d in details:
                liab = self._safe_float(d.get('liab'))
                if liab < 0: 
                    liab = abs(liab)
                
                # Check liability
                if liab > 0:
                    loans.append({
                        'currency': d.get('ccy'),
                        'amount': liab,
                        'eq': self._safe_float(d.get('eq')), 
                        'liab_usd': self._safe_float(d.get('liabEq')) # Use liabEq (USD value) instead of uTime
                    })
            
            return {
                'total_eq': total_eq,
                'mgn_ratio': mgn_ratio,
                'loans': loans,
                'raw': data[0]
            }
        return None

    def get_flexible_loans(self):
        """Get Flexible Loan (Earn) info for Simple Mode users"""
        data = self._make_request("GET", "/api/v5/finance/flexible-loan/loan-info")
        
        loans = []
        if data:
            for item in data:
                # item contains collateralData, loanData, etc.
                loan_data = item.get('loanData', [])
                for loan in loan_data:
                    amt = self._safe_float(loan.get('amt'))
                    if amt > 0:
                        loans.append({
                            'currency': loan.get('ccy'),
                            'amount': amt,
                            'type': 'Flexible Loan',
                            'liab_usd': self._safe_float(item.get('loanNotionalUsd')), # Approx, per position
                            'eq': self._safe_float(item.get('collateralNotionalUsd')) # Approx
                        })
        return loans

    def get_account_config(self):
        """Get Account Configuration (e.g. Account Level)"""
        data = self._make_request("GET", "/api/v5/account/config")
        if data:
            return data[0]
        return None

    
    def get_public_loan_quota(self):
        """Get loan quota and interest rate from PUBLIC API
        
        This endpoint returns ONLY tokens available for regular users!
        Uses /api/v5/public/interest-rate-loan-quota which returns:
        - basic[]: tokens available for regular margin trading (what we need!)
        - vip[]: VIP level info
        - regular[]: Regular user level info
        
        NO AUTHENTICATION REQUIRED - Public API
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                url = f"{self.base_url}/api/v5/public/interest-rate-loan-quota"
                
                logger.debug(f"Public API Request: {url} (attempt {attempt + 1})")
                response = self.session.get(url, timeout=15)
                
                result = response.json()
                
                if result.get('code') == '0':
                    data = result.get('data', [])
                    if data and 'basic' in data[0]:
                        basic_tokens = data[0]['basic']
                        logger.info(f"OKX Public API: {len(basic_tokens)} tokens for regular users")
                        return basic_tokens
                    return []
                else:
                    logger.error(f"OKX Public API Error: {result.get('msg')} (code: {result.get('code')})")
                    logger.error(f"Response Body: {response.text}") # Added this line
                    return []
                    
            except (requests.exceptions.ConnectionError, ConnectionResetError) as e:
                logger.warning(f"Connection error (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}")
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                    continue
                logger.error(f"Max retries reached: {e}")
                return []
            except Exception as e:
                logger.error(f"OKX Public API Request Error: {e}")
                return []
        return []

    def check_connection(self):
        """Check connection to OKX Public API to verify IP/Network status"""
        try:
            url = f"{self.base_url}/api/v5/public/time"
            response = self.session.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == '0':
                    logger.info("✅ OKX Public API Connection: OK")
                    return True, "Connected"
            return False, f"HTTP {response.status_code}: {response.text}"
        except requests.exceptions.SSLError as e:
            msg = "⛔ SSL Error: Certificate Verify Failed. Likely ISP Block (Internet Positif). Please TURN ON your VPN."
            logger.error(msg)
            return False, msg
        except Exception as e:
            return False, str(e)

    def _get_external_ip(self):
        """Get external IP for debugging"""
        try:
            return self.session.get("https://api.ipify.org", timeout=3).text
        except:
            return "Unknown"

    def borrow_flexible(self, currency, amount, collateral_currency="USDT", collateral_amount="0"):
        """Borrow tokens via Spot Manual Borrow (works for Simple Mode Flexible Loan)
        
        Args:
            currency (str): Token symbol to borrow (e.g., 'ETH')
            amount (float): Amount to borrow
            collateral_currency (str): (Ignored) Kept for signature compatibility
            collateral_amount (str): Amount of collateral to add (default '0')
            
        Returns:
            dict: API response or None
        """
        # Endpoint: POST /api/v5/account/spot-manual-borrow-repay
        # This endpoint is used for manual borrowing in Margin/Simple mode.
        
        params = {
            "ccy": currency.upper(),
            "side": "borrow",
            "amt": str(amount)
        }
        
        max_retries = 3
        
        for attempt in range(max_retries):
            logger.info(f"Attempting to borrow {amount} {currency} via Manual Borrow (attempt {attempt+1})...")
            
            # 1. Check Public Connection first if retrying
            if attempt > 0:
                is_connected, msg = self.check_connection()
                if not is_connected:
                    logger.warning(f"Connection lost before borrow retry: {msg}")
                    time.sleep(2)
                    continue

            # 2. Execute POST Request
            # Note: _make_request handles the POST JSON body construction
            data = self._make_request("POST", "/api/v5/account/spot-manual-borrow-repay", params)
            
            if data:
                 logger.info(f"Borrow Success! Result: {data}")
                 return data
            
            # If we are here, result was None or empty list (error logged in _make_request)
            time.sleep(1) # Wait before retry
            
        return None

    def get_ticker_price(self, symbol):
        """Get current market price for a symbol (e.g. ETH) against USDT"""
        # Symbol format: ETH-USDT-SWAP or ETH-USDT spot?
        # Flexible Loan usually references Index Price or Mark Price.
        # Let's use Mark Price for simplicity: /api/v5/public/mark-price
        
        inst_id = f"{symbol.upper()}-USDT"
        
        try:
            data = self._make_request("GET", "/api/v5/market/ticker", {"instId": inst_id})
            if data and len(data) > 0:
                price = self._safe_float(data[0].get('last'))
                return price
        except Exception as e:
            logger.error(f"Error fetching price for {symbol}: {e}")
            
        return 0.0

    def get_withdrawal_fee(self, currency):
        """Get withdrawal fee for a specific currency (default chain)"""
        try:
            # Check Cache
            now = time.time()
            if hasattr(self, '_wd_fee_cache') and self._wd_fee_cache and (now - getattr(self, '_wd_fee_cache_time', 0) < 3600):
                return self._wd_fee_cache.get(currency.upper(), 0.0)
                
            # Fetch ALL currencies
            # /api/v5/asset/currencies without ccy param returns all
            logger.info("Fetching OKX Withdrawal Fees (All Currencies)...")
            data = self._make_request("GET", "/api/v5/asset/currencies")
            
            if not data:
                return 0.0
            
            # Build cache
            new_cache = {}
            # Data is a list of currency objects
            # Each object has 'ccy', 'chain', 'minFee', 'maxFee'
            # Note: One currency can have multiple chains (multiple entries in data list)
            
            # Group by currency to find min fee
            temp_fees = {} 
            
            for item in data:
                ccy = item.get('ccy')
                can_wd = item.get('canWd')
                if can_wd == True or str(can_wd).lower() == 'true':
                    fee = float(item.get('minFee', 0))
                    if ccy not in temp_fees:
                        temp_fees[ccy] = []
                    temp_fees[ccy].append(fee)
            
            for ccy, fees in temp_fees.items():
                if fees:
                    new_cache[ccy] = min(fees)
                else:
                    new_cache[ccy] = 0.0
            
            self._wd_fee_cache = new_cache
            self._wd_fee_cache_time = now
            logger.info(f"Cached withdrawal fees for {len(new_cache)} tokens")
            
            return self._wd_fee_cache.get(currency.upper(), 0.0)
            
        except Exception as e:
            logger.error(f"OKX WD Fee Error ({currency}): {e}")
            return 0.0

