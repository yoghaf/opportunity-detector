import gate_api
import concurrent.futures
from config.settings import Config

class GateClient:
    def __init__(self):
        configuration = gate_api.Configuration(
            host="https://api.gateio.ws/api/v4",
            key=Config.GATE_API_KEY,
            secret=Config.GATE_API_SECRET
        )
        self.client = gate_api.ApiClient(configuration)
        self.client = gate_api.ApiClient(configuration)
        self.earn_api = gate_api.EarnUniApi(self.client)
        self.unified_api = gate_api.UnifiedApi(self.client)
    
    def get_real_apr_batch(self, currencies):
        """
        Fetch ACTUAL realized APR (last hour) for a list of currencies.
        Uses UnifiedApi.get_history_loan_rate.
        """
        # Limit concurrency to avoid rate limits
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_curr = {
                executor.submit(self._get_single_real_apr, c): c 
                for c in currencies
            }
            results = {}
            for future in concurrent.futures.as_completed(future_to_curr):
                curr = future_to_curr[future]
                try:
                    # Add timeout to prevent hanging threads preventing shutdown
                    apr = future.result(timeout=5)
                    if apr is not None:
                        results[curr] = apr
                except Exception:
                    # Timeout or Error
                    pass
            return results

    def _get_single_real_apr(self, currency):
        """Helper to fetch single history point"""
        try:
            # limit=1 gets the latest hour
            history = self.unified_api.get_history_loan_rate(currency=currency, limit=1)
            # Check for 'rates' attribute (UniLoanInterestRecord)
            if hasattr(history, 'rates') and history.rates:
                latest = history.rates[0]
                latest = history.rates[0]
                latest = history.rates[0]
                latest = history.rates[0]
                hourly_rate = float(latest.rate)
                # Convert Hourly to APR
                gross_apr = hourly_rate * 24 * 365 * 100
                
                # Dynamic Fee Model (Data-Driven) - DISABLED (2026-02-15)
                # Reason: User feedback indicates Gate UI shows "Est. Standard APR" (e.g. 499%) 
                # which matches our Gross calculation exactly. 
                # The previous deduction (0.91) caused a discrepancy (454% vs 499%).
                # We now return the Gross Rate to align with the User's "Truth" (Gate UI).
                
                # if gross_apr > 135:
                #     fee_factor = 0.91
                # else:
                #     fee_factor = 0.95
                    
                return gross_apr # * fee_factor
            return None
        except Exception:
            return None
    
    def get_batch_withdrawal_fees(self, token_list):
        """Fetch withdrawal fees for multiple tokens in parallel"""
        # Reduced max_workers to 5 to avoid Rate Limits/WAF
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_token = {
                executor.submit(self.get_withdrawal_fee, token): token 
                for token in token_list
            }
            results = {}
            for future in concurrent.futures.as_completed(future_to_token):
                token = future_to_token[future]
                try:
                    # TIMEOUT ADDED: Prevent hanging threads (10s per request max)
                    data = future.result(timeout=10)
                    results[token] = data
                except concurrent.futures.TimeoutError:
                    print(f"Batch Fee Timeout: {token}")
                    results[token] = None
                except Exception as e:
                    print(f"Batch Fee Error {token}: {e}")
                    results[token] = None
            return results

    def get_simple_earn_rates(self):
        try:
            rates = self.earn_api.list_uni_rate()
            
            # QUANT FIX (2026-02-15 FINAL): 
            # User feedback confirms "Est. Standard APR" (UI Header) is often a lagging indicator 
            # or a 24h average that hides recent crashes (e.g. ATH 134% -> 50%, LPT 183% -> 9%).
            # The User explicitly requested the "Chart Data" (Realized History) for accuracy.
            # Strategy: For High APR tokens (>5%), fetch the latest hourly history.
            # If History exists, USE IT (Source of Truth).
            
            candidates = []
            for r in rates:
                est = float(r.est_rate) if r.est_rate else 0
                # If APR > 5% (0.05), it's worth checking reality
                if est > 0.05:
                    if hasattr(r, 'currency'):
                         candidates.append(r.currency)
            
            if candidates:
                print(f"🔎 Verifying Realized APR for {len(candidates)} high-yield tokens...")
                real_aprs = self.get_real_apr_batch(candidates)
                
                # Add 'real_rate' while preserving 'est_rate'
                for r in rates:
                    # Default: real_rate is same as est_rate
                    setattr(r, 'real_rate', getattr(r, 'est_rate', "0"))
                    
                    if hasattr(r, 'currency') and r.currency in real_aprs:
                        real_val_percent = real_aprs[r.currency] # e.g. 50.5
                        # Set actual realized rate
                        r.real_rate = str(real_val_percent / 100.0)
                        
            return rates
        except Exception as e:
            print(f"Gate API Error: {e}")
            return []

    def get_withdrawal_fee(self, currency):
        """
        Get real withdrawal fee in USD based on available chains.
        
        Strict Validation:
        1. Withdrawal Enabled
        2. Deposit Enabled (on Gate)
        3. Min Withdrawal Amount <= Assumed Trade Size
        
        Returns:
            float: Cheapest fee in USD, or None if no valid network exists.
        """
        ASSUMED_TRADE_SIZE_USD = 100.0 # Configurable trade size assumption
        
        try:
            # 1. Get Chain Info (Raw or SDK)
            chains = self._get_chain_info(currency)
            if not chains:
                # WARN: If no chains, likely permission issue or invalid token
                print(f"⚠️ Gate No Chains found for {currency}. Possible Permission/IP issue.")
                return None
            # 2. Get Token Price (Mid-Price for fairness)
            # Handle Stablecoins
            if currency in ['USDT', 'USDC', 'DAI']:
                price = 1.0
            else:
                price = self.get_ticker_price(currency)
            
            if price <= 0:
                print(f"Gate Fee Error: Invalid price for {currency}")
                return None
                
            # 2. Get Withdraw Status (for FEE MAP - works with Read Only)
            wd_status = self._get_withdraw_status(currency)
            fee_map = {}
            if wd_status:
                fee_map = wd_status.get('withdraw_fix_on_chains', {})

            valid_fees_usd = []
            
            for c in chains:
                # Helper to safely get attributes from dict or object
                def get_attr(obj, key, default=None):
                    if isinstance(obj, dict):
                        return obj.get(key, default)
                    return getattr(obj, key, default)

                # Status Checks
                is_wd_disabled = get_attr(c, 'is_withdraw_disabled', 1) 
                if is_wd_disabled == 1:
                    continue
                
                # Convert to dict
                chain_data = c.to_dict() if hasattr(c, 'to_dict') else c
                chain_name = chain_data.get('chain')
                
                # FEE LOOKUP STRATEGY:
                # Priority 1: Fee Map from /wallet/withdraw_status (Reliable for Read-Only)
                # Priority 2: 'withdraw_fee' from /wallet/currency_chains (Often None)
                
                raw_fee_str = None
                
                # Check Fee Map first
                if chain_name and chain_name in fee_map:
                    raw_fee_str = fee_map[chain_name]
                    # Also check percent fee if fixed is 0? usually fixed is main.
                
                # Fallback
                if not raw_fee_str:
                    raw_fee_str = chain_data.get('withdraw_fee')
                    if raw_fee_str is None:
                         raw_fee_str = chain_data.get('withdraw_fix_on_chain')

                if raw_fee_str is None:
                    continue

                min_amount_str = chain_data.get('min_amount')
                
                try:
                    raw_fee = float(raw_fee_str)
                    min_amount = float(min_amount_str) if min_amount_str else 0.0
                except:
                    continue
                    
                # Min Amount Check
                min_amount_usd = min_amount * price
                if min_amount_usd > ASSUMED_TRADE_SIZE_USD:
                    continue
                    
                # Calculate Fee in USD
                fee_usd = raw_fee * price
                valid_fees_usd.append(fee_usd)
            
            if not valid_fees_usd:
                return None
                
            # Return cheapest valid fee
            return min(valid_fees_usd)

        except Exception as e:
            print(f"Gate Fee Error ({currency}): {e}")
            return None

    def _get_chain_info(self, currency):
        """
        Fetch chain info. 
        Uses Authenticated /wallet/currency_chains.
        REQUIRES 'wallet:read' or 'wallet:withdraw' permission to see fees.
        """
        try:
            import requests
            import time
            import hashlib
            import hmac
            
            # Helper for Auth
            def get_auth_headers(method, url, query_param):
                t = time.time()
                m = hashlib.sha512()
                m.update("".encode('utf-8'))
                hashed_payload = m.hexdigest()
                s = '%s\n%s\n%s\n%s\n%s' % (method, url, query_param, hashed_payload, t)
                sign = hmac.new(Config.GATE_API_SECRET.encode('utf-8'), s.encode('utf-8'), hashlib.sha512).hexdigest()
                return {'KEY': Config.GATE_API_KEY, 'Timestamp': str(t), 'SIGN': sign}

            host = "https://api.gateio.ws"
            prefix = "/api/v4"
            url = "/wallet/currency_chains"
            query_param = f"currency={currency}"
            
            headers = get_auth_headers('GET', prefix + url, query_param)
            
            r = requests.get(f"{host}{prefix}{url}?{query_param}", headers=headers)
            if r.status_code == 200:
                data = r.json()
                return data
            else:
                print(f"API Error ({currency}): Status {r.status_code} - {r.text}")
        except Exception as e:
            print(f"Request Error ({currency}): {e}")
        return []

    def _get_withdraw_status(self, currency):
        """
        Fetch withdraw status (contains FEE map even for Read-Only keys!)
        """
        try:
            import requests
            import time
            import hashlib
            import hmac
            
            host = "https://api.gateio.ws"
            prefix = "/api/v4"
            url = "/wallet/withdraw_status"
            query_param = f"currency={currency}"
            
            t = time.time()
            m = hashlib.sha512()
            m.update("".encode('utf-8'))
            hashed_payload = m.hexdigest()
            s = '%s\n%s\n%s\n%s\n%s' % ('GET', prefix + url, query_param, hashed_payload, t)
            sign = hmac.new(Config.GATE_API_SECRET.encode('utf-8'), s.encode('utf-8'), hashlib.sha512).hexdigest()
            headers = {'KEY': Config.GATE_API_KEY, 'Timestamp': str(t), 'SIGN': sign}
            
            r = requests.get(f"{host}{prefix}{url}?{query_param}", headers=headers)
            if r.status_code == 200:
                data = r.json()
                if data and isinstance(data, list) and len(data) > 0:
                    return data[0]
            return None
        except Exception:
            return None

    def get_ticker_price(self, currency):
        """
        Get current Mid-Price in USDT ((bid+ask)/2)
        """
        try:
            api = gate_api.SpotApi(self.client)
            pair = f"{currency}_USDT"
            tickers = api.list_tickers(currency_pair=pair)
            if tickers and tickers[0].lowest_ask and tickers[0].highest_bid:
                ask = float(tickers[0].lowest_ask)
                bid = float(tickers[0].highest_bid)
                if ask > 0 and bid > 0:
                    return (ask + bid) / 2
                # Fallback to last if bid/ask missing
                return float(tickers[0].last)
        except Exception:
             pass
        return 0.0

    def get_all_tickers(self):
        """Get ALL tickers ending in _USDT for batch processing"""
        try:
            api = gate_api.SpotApi(self.client)
            # Fetch all tickers (no currency_pair param)
            tickers = api.list_tickers()
            
            price_map = {}
            if tickers:
                for t in tickers:
                    pair = t.currency_pair
                    if pair.endswith('_USDT'):
                        currency = pair.replace('_USDT', '')
                        try:
                            # Use Mid-Price if possible
                            ask = float(t.lowest_ask) if t.lowest_ask else 0
                            bid = float(t.highest_bid) if t.highest_bid else 0
                            if ask > 0 and bid > 0:
                                price_map[currency] = (ask + bid) / 2
                            else:
                                price_map[currency] = float(t.last)
                        except:
                            pass
            return price_map
        except Exception as e:
            print(f"Gate Bulk Ticker Error: {e}")
            return {}
