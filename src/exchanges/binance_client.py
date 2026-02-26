# src/exchanges/binance_client.py
import requests
import hmac
import hashlib
import time
from datetime import datetime
from config.settings import Config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class BinanceClient:
    """Binance API client for Simple Earn and Margin Loan data"""
    
    MAX_RETRIES = 3
    RETRY_DELAY = 2
    
    def __init__(self):
        self.api_key = Config.BINANCE_API_KEY
        self.secret_key = Config.BINANCE_API_SECRET
        self.base_url = "https://api.binance.com"
        self.session = requests.Session()
        
        # Anti-Detection / Proxy
        if Config.PROXY_URL:
            self.session.proxies.update({
                'http': Config.PROXY_URL,
                'https': Config.PROXY_URL
            })
            logger.info(f"Binance Client using Proxy: {Config.PROXY_URL}")
        
        if not self.api_key or not self.secret_key:
            logger.warning("Binance API keys not configured - Binance data will be unavailable")
            self.enabled = False
        else:
            self.enabled = True
    
    def _generate_signature(self, query_string):
        """Generate HMAC SHA256 signature"""
        return hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _make_request(self, endpoint, params=None):
        """Make signed API request with retry logic"""
        if not self.enabled:
            return []
        
        for attempt in range(self.MAX_RETRIES):
            try:
                timestamp = int(time.time() * 1000)
                
                if params is None:
                    params = {}
                params['timestamp'] = timestamp
                
                # Build query string
                query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
                signature = self._generate_signature(query_string)
                query_string += f"&signature={signature}"
                
                headers = {
                    "X-MBX-APIKEY": self.api_key
                }
                
                full_url = f"{self.base_url}{endpoint}?{query_string}"
                
                logger.debug(f"Binance Request: {endpoint} (attempt {attempt + 1})")
                response = self.session.get(full_url, headers=headers, timeout=15)
                
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"Binance API Error: {response.status_code} - {response.text}")
                    return []
                    
            except (requests.exceptions.ConnectionError, ConnectionResetError) as e:
                logger.warning(f"Binance connection error (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}")
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                    continue
                return []
            except Exception as e:
                logger.error(f"Binance Request Error: {e}")
                return []
        return []
    
    def get_simple_earn_rates(self):
        """Get Simple Earn flexible product rates
        
        Returns list of dicts with:
        - asset: token symbol
        - latestAnnualPercentageRate: current APR
        """
        if not self.enabled:
            return []
        
        all_products = []
        current = 1
        size = 100
        
        while True:
            params = {
                "current": current,
                "size": size
            }
            
            data = self._make_request("/sapi/v1/simple-earn/flexible/list", params)
            
            if not data or 'rows' not in data:
                break
            
            rows = data.get('rows', [])
            if not rows:
                break
            
            for product in rows:
                asset = product.get('asset', '')
                apr_str = product.get('latestAnnualPercentageRate', '0')
                
                try:
                    apr = float(apr_str) * 100  # Convert to percentage
                except:
                    apr = 0.0
                
                if asset and apr > 0:
                    all_products.append({
                        'currency': asset,
                        'binance_earn_apr': apr
                    })
            
            # Check if there are more pages
            total = data.get('total', 0)
            if current * size >= total:
                break
            current += 1
        
        logger.info(f"Binance Earn: {len(all_products)} tokens with APR")
        return all_products
    
    def get_flexible_loan_rates(self, loanCoin=None):
        """Get Binance Crypto Loan (Flexible Loan) interest rates
        
        Uses /sapi/v2/loan/flexible/loanable/data endpoint
        This is the CORRECT endpoint for Finance -> Crypto Loan rates!
        
        Args:
            loanCoin: Optional specific coin to query
        
        Returns list of dicts with:
        - loanCoin: token symbol
        - flexibleInterestRate: current interest rate (daily)
        """
        if not self.enabled:
            return []
        
        params = {}
        if loanCoin:
            params['loanCoin'] = loanCoin
        
        data = self._make_request("/sapi/v2/loan/flexible/loanable/data", params)
        
        if not data or 'rows' not in data:
            logger.warning("Binance Flexible Loan API: No data returned")
            return []
        
        rates = []
        for item in data.get('rows', []):
            coin = item.get('loanCoin', '')
            # flexibleInterestRate is daily rate already in percentage (e.g., 0.168 = 0.168%)
            daily_rate_str = item.get('flexibleInterestRate', '0')
            
            try:
                daily_rate = float(daily_rate_str)
                # flexibleInterestRate is already percentage, just multiply by 365
                # e.g., 0.168 * 365 = 61.32% annual
                annual_rate = daily_rate * 365
            except:
                annual_rate = 0.0
            
            if coin and annual_rate > 0:
                rates.append({
                    'currency': coin,
                    'binance_loan_rate': annual_rate,
                    'binance_daily_rate': daily_rate  # already percentage
                })
        
        logger.info(f"Binance Flexible Loan: {len(rates)} tokens with loan rates")
        return rates
    
    def get_margin_loan_rates(self, assets=None):
        """Get margin borrow interest rates (DEPRECATED - use get_flexible_loan_rates instead)
        
        Args:
            assets: List of asset symbols to query, or None for common ones
        
        Returns list of dicts with:
        - asset: token symbol
        - nextHourlyInterestRate: hourly rate
        """
        if not self.enabled:
            return []
        
        if assets is None:
            # Query common assets
            assets = ['BTC', 'ETH', 'USDT', 'BNB', 'SOL', 'XRP', 'ADA', 'DOGE', 'MATIC', 'DOT']
        
        params = {
            "assets": ','.join(assets),
            "isIsolated": "FALSE"
        }
        
        data = self._make_request("/sapi/v1/margin/next-hourly-interest-rate", params)
        
        if not data:
            return []
        
        rates = []
        for item in data:
            asset = item.get('asset', '')
            hourly_rate_str = item.get('nextHourlyInterestRate', '0')
            
            try:
                hourly_rate = float(hourly_rate_str)
                # Convert hourly to annual: hourly * 24 * 365 * 100
                annual_rate = hourly_rate * 24 * 365 * 100
            except:
                annual_rate = 0.0
            
            if asset:
                rates.append({
                    'currency': asset,
                    'binance_loan_rate': annual_rate,
                    'binance_hourly_rate': hourly_rate * 100  # as percentage
                })
        
        logger.info(f"Binance Margin: {len(rates)} tokens with loan rates")
        return rates
    
    def get_margin_loan_rates_batch(self, assets):
        """Get margin borrow interest rates for a batch of assets
        
        Splits into chunks to avoid URL length limits (Binance limit ~20 assets)
        
        Args:
            assets: List of asset symbols to query
        
        Returns list of dicts with:
        - currency: token symbol
        - binance_loan_rate: annual rate as percentage
        """
        if not self.enabled or not assets:
            return []
        
        BATCH_SIZE = 20
        all_rates = []
        
        # Split into chunks
        for i in range(0, len(assets), BATCH_SIZE):
            batch = assets[i:i + BATCH_SIZE]
            rates = self.get_margin_loan_rates(batch)
            all_rates.extend(rates)
        
        
        logger.info(f"Binance Margin Batch: {len(all_rates)} tokens processed from {len(assets)} requested")
        return all_rates

    def get_withdrawal_fee(self, currency):
        """Get withdrawal fee for a specific currency (default chain)"""
        if not self.enabled:
            return 0.0

        # Check in-memory cache first
        now = time.time()
        if hasattr(self, '_wd_fee_cache') and self._wd_fee_cache and (now - getattr(self, '_wd_fee_cache_time', 0) < 3600):
            return self._wd_fee_cache.get(currency.upper(), 0.0)

        # ----------------------------------------
        # Optimization: Fetch ALL configs once
        # ----------------------------------------
        # /sapi/v1/capital/config/getall returns ALL coins
        try:
            logger.info("Fetching Binance Withdrawal Fees (Global Config)...")
            data = self._make_request("/sapi/v1/capital/config/getall")
            
            if not data:
                return 0.0
            
            # Build cache
            new_cache = {}
            for item in data:
                coin = item.get('coin')
                network_list = item.get('networkList', [])
                if not network_list:
                    new_cache[coin] = 0.0
                    continue
                
                # Find minimum withdrawal fee among enabled networks
                fees = []
                for net in network_list:
                    if net.get('withdrawEnable') is True:
                        fees.append(float(net.get('withdrawFee')))
                
                if fees:
                    new_cache[coin] = min(fees)
                else:
                    new_cache[coin] = 0.0
            
            self._wd_fee_cache = new_cache
            self._wd_fee_cache_time = now
            logger.info(f"Cached withdrawal fees for {len(new_cache)} tokens")
            
            return self._wd_fee_cache.get(currency.upper(), 0.0)
            
        except Exception as e:
            logger.error(f"Binance WD Fee Error ({currency}): {e}")
            return 0.0
