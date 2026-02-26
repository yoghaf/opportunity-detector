# src/strategies/opportunity_finder.py
import pandas as pd
from datetime import datetime
from config.settings import Config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# OKX Allowlist - Only these tokens are confirmed borrowable for regular users
# Tokens NOT in this list will be excluded (they may be VIP-only)
OKX_BORROWABLE_TOKENS = {
    '1INCH', 'A', 'AAVE', 'ADA', 'AGLD', 'ALGO', 'ANIME', 'APE', 'API3', 'APT',
    'AR', 'ARB', 'ASTER', 'ATH', 'ATOM', 'AVAX', 'AVNT', 'AXS', 'BABY', 'BARD',
    'BAT', 'BCH', 'BERA', 'BLUR', 'BNB', 'BREV', 'CELO', 'CFX', 'CHZ', 'COMP',
    'CORE', 'CRO', 'CRV', 'CVX', 'DASH', 'DOGE', 'DOT', 'DYDX', 'EGLD', 'ENA',
    'ENS', 'ETC', 'ETH', 'ETHW', 'FIL', 'FLOKI', 'FLOW', 'FOGO', 'GALA', 'GMT',
    'GMX', 'GRT', 'HBAR', 'HUMA', 'HYPE', 'ICP', 'IMX', 'IOST', 'IOTA', 'IP',
    'JUP', 'KAITO', 'KITE', 'KSM', 'LAYER', 'LDO', 'LINEA', 'LINK', 'LIT', 'LPT',
    'LRC', 'LTC', 'LUNA', 'MAGIC', 'MANA', 'MASK', 'ME', 'MERL', 'MINA', 'MOVE',
    'NEAR', 'NEO', 'NIGHT', 'OKB', 'OM', 'ONDO', 'ONT', 'OP', 'ORDI', 'PEOPLE',
    'PEPE', 'POL', 'PUMP', 'QTUM', 'RENDER', 'RSR', 'SAND', 'SATS', 'SHIB', 'SNX',
    'SOL', 'STX', 'SUI', 'SUSHI', 'THETA', 'TIA', 'TON', 'TRB', 'TRUMP', 'TRX',
    'UMA', 'UNI', 'VIRTUAL', 'WLFI', 'XAUT', 'XLM', 'XPL', 'XRP', 'XTZ', 'YFI',
    'YGG', 'ZEC', 'ZIL', 'ZRX'
}

# Binance Allowlist - Only these tokens are confirmed borrowable for regular users
BINANCE_BORROWABLE_TOKENS = {
    'BTC', 'ETH', 'USDT', 'XRP', 'USDC', 'SOL', 'TRX', 'DOGE', 'BCH', 'ADA',
    'XLM', 'LINK', 'DAI', 'HBAR', 'LTC', 'AVAX', 'ZEC', 'SUI', 'SHIB', 'TON',
    'DOT', 'UNI', 'PAXG', 'WLD', 'TRUMP', 'TAO', 'AAVE', 'PEPE', 'NEAR', 'ICP',
    'ETC', 'ENA', 'POL', 'FIL', 'ALGO', 'ZRO', 'QNT', 'ATOM', 'RENDER', 'VET',
    'ARB', 'APT', 'CRV', 'ENS', 'VIRTUAL', 'BONK', 'JUP', 'SEI', 'TUSD', 'PENGU',
    'XTZ', 'CAKE', 'OP', 'STX', 'CHZ', 'FDUSD', 'FET', 'AXS', 'RAY', 'ETHFI',
    'INJ', 'IMX', 'BTTC', 'LDO', 'PENDLE', 'FLOKI', 'IOTA', 'NEO', 'TIA', 'JASMY',
    'STRK', 'PYTH', 'SAND', 'GRT', 'CFX', 'WIF', 'TWT', 'GALA', 'THETA', 'MANA',
    'LUNC', 'BAT', 'COMP', 'RUNE', 'A', 'SFP', '1INCH', 'AR', 'S', 'EGLD',
    'APE', 'ZK', 'JTO', 'W', 'ZEN', 'RSR', 'EDU', 'XVG', 'RVN', 'SNX',
    'DYDX', 'ZRX', 'ROSE', 'ZIL', 'VANA', 'CKB', 'SUPER', '1MBABYDOGE', 'MINA', 'KSM',
    'FLOW', 'TURBO', 'MOVE', 'ACH', 'SC', 'ARKM', 'HOT', 'LUNA', 'ID', 'ASTR',
    'KAVA', 'SUSHI', 'SPK', 'IOTX', 'LRC', 'ALT', 'GMT', 'OM', 'EURI', 'CELO',
    'MASK', 'ONT', 'MEME', 'POLYX', 'RIF', 'MANTA', 'ENJ', 'YGG', 'LISTA', 'ILV',
    'BAND', 'WOO', 'BB', 'NEIRO', 'COTI', 'STRAX', 'CYBER', 'AUCTION', 'TKO', 'IO',
    'AEVO', 'KNC', 'OSMO', 'CHR', 'FLUX', 'C98', 'SAGA', 'USUAL', 'USTC', 'SLP',
    '1000SATS', 'ARPA', 'MAGIC', 'AGLD', 'SXP', 'ACE', 'MAV', 'DOGS', 'DODO', 'ACT',
    'PIXEL', 'HMSTR', 'HIGH', 'MBOX', 'HOOK', 'RDNT'
}

pd.set_option('future.no_silent_downcasting', True)

class OpportunityFinder:
    def __init__(self, gate_client, okx_client, binance_client=None):
        self.gate_client = gate_client
        self.okx_client = okx_client
        self.binance_client = binance_client
        
        # Fee Cache
        self.fee_cache = {}
        self.last_fee_update = None
        self.FEE_UPDATE_INTERVAL = 3600 # 1 hour
    
    def get_gate_data(self):
        rates = self.gate_client.get_simple_earn_rates()
        if not rates:
            logger.warning("Gate API: No rates")
            return pd.DataFrame()
        
        data = []
        for rate in rates:
            currency = getattr(rate, 'currency', '')
            
            raw_real = float(getattr(rate, 'real_rate', 0)) if getattr(rate, 'real_rate', None) else 0.0
            raw_est = float(getattr(rate, 'est_rate', 0)) if getattr(rate, 'est_rate', None) else 0.0
            
            # Fallback to est_rate if real_rate is 0 for some reason, though it shouldn't be
            if raw_real <= 0:
                raw_real = raw_est
                
            apr = raw_real * 100
            est_apr = raw_est * 100
            
            if currency and apr > 0:
                data.append({'currency': currency, 'gate_apr': apr, 'gate_est_apr': est_apr})
        
        df = pd.DataFrame(data)
        logger.info(f"Gate: {len(df)} tokens with APR")
        return df
    
    def get_binance_earn_data(self):
        """Get Binance Simple Earn rates"""
        if not self.binance_client or not self.binance_client.enabled:
            return pd.DataFrame()
        
        rates = self.binance_client.get_simple_earn_rates()
        if not rates:
            logger.warning("Binance Earn API: No rates")
            return pd.DataFrame()
        
        df = pd.DataFrame(rates)
        logger.info(f"Binance Earn: {len(df)} tokens with APR")
        return df
    
    def get_binance_loan_data(self, assets=None):
        """Get Binance Crypto Loan (Flexible) rates"""
        if not self.binance_client or not self.binance_client.enabled:
            return pd.DataFrame()
        
        # Use Flexible Loan endpoint (Crypto Loan)
        # We fetch ALL available flexible loan rates
        rates = self.binance_client.get_flexible_loan_rates()
        
        if not rates:
            logger.warning("Binance Flexible Loan API: No rates")
            return pd.DataFrame()
        
        df = pd.DataFrame(rates)
        
        # Filter by allowlist if needed (currently using all available from API)
        # filtered_df = df[df['currency'].isin(BINANCE_BORROWABLE_TOKENS)]
        
        logger.info(f"Binance Flexible Loan: {len(df)} tokens with loan rates")
        return df
    
    def get_okx_data(self):
        """Get OKX loan data - FILTERED by allowlist for regular users"""
        logger.debug("Calling OKX API for loan limits...")
        
        data = self.okx_client.get_loan_limit()
        
        if not data:
            logger.warning("OKX API: No loan data")
            return pd.DataFrame()
        
        records = []
        skipped = 0
        for item in data:
            item_records = item.get('records', [])
            for record in item_records:
                currency = record.get('ccy', '')
                if not currency:
                    continue
                
                # FILTER: Only include tokens in allowlist
                if currency.upper() not in OKX_BORROWABLE_TOKENS:
                    skipped += 1
                    continue
                
                daily_rate = float(record.get('rate', 0))
                interest_rate_apy = daily_rate * 365 * 100
                
                surplus_limit = float(record.get('surplusLmt', 0))
                loan_quota = float(record.get('loanQuota', 0))
                used_limit = float(record.get('usedLmt', 0))
                
                is_available = surplus_limit > 0
                
                records.append({
                    'currency': currency,
                    'okx_loan_rate': interest_rate_apy,
                    'okx_daily_rate': daily_rate * 100,
                    'okx_total_quota': loan_quota,
                    'okx_used_quota': used_limit,
                    'okx_surplus_limit': surplus_limit,
                    'okx_avail_loan': surplus_limit,
                    'available': is_available,
                    'status': "✅ AVAILABLE" if is_available else "❌ NOT AVAILABLE"
                })
        
        df = pd.DataFrame(records)
        logger.info(f"OKX: {len(df)} tokens (skipped {skipped} VIP-only tokens)")
        return df
    
    def search_token(self, token_symbol):
        """Cari token spesifik dengan data yang AKURAT dari max-loan API + Binance Data"""
        logger.info(f"Mencari token: {token_symbol.upper()}")
        
        # 1. Fetch data from all sources
        gate_df = self.get_gate_data()
        okx_df = self.get_okx_data()
        
        # Binance Data (Optional)
        binance_earn_df = self.get_binance_earn_data()
        # For single token, we can just fetch all flexible rates and filter, 
        # because get_flexible_loan_rates(asset) might strictly require it to be valid
        binance_loan_df = self.get_binance_loan_data() 
        if not binance_loan_df.empty:
            binance_loan_df = binance_loan_df[binance_loan_df['currency'] == token_symbol.upper()]
        
        # 2. Check basics
        if gate_df.empty:
            logger.warning("Data Gate tidak tersedia")
            return pd.DataFrame()
            
        # 3. Filter specific token in Gate
        gate_token = gate_df[gate_df['currency'].str.upper() == token_symbol.upper()]
        
        if gate_token.empty:
            logger.warning(f"Token {token_symbol} tidak ditemukan di Gate")
            return pd.DataFrame()
            
        # 4. Filter OKX (Optional now)
        okx_token = pd.DataFrame()
        if not okx_df.empty:
            okx_token = okx_df[okx_df['currency'].str.upper() == token_symbol.upper()]
        
        # 5. Filter Binance Loan
        binance_loan_token = pd.DataFrame()
        if not binance_loan_df.empty:
            binance_loan_token = binance_loan_df
            
        if okx_token.empty and binance_loan_token.empty:
             logger.warning(f"Token {token_symbol} tidak tersedia di OKX Loan maupun Binance Loan")
             # We can still return Gate data if we want, but usually we want arb data
             # Let's return what we have but mark as no loan
             pass

        # 6. Merge Logic (Left Join on Gate)
        merged = gate_token.copy()
        
        # Add OKX data
        if not okx_token.empty:
            for col in okx_token.columns:
                if col != 'currency':
                    merged[col] = okx_token.iloc[0][col]
        else:
            merged['okx_loan_rate'] = 0.0
            merged['okx_avail_loan'] = 0.0
            merged['okx_used_quota'] = 0.0
            merged['okx_total_quota'] = 0.0
            merged['status'] = "❌ NOT ON OKX"
            
        # Add Binance Earn
        if not binance_earn_df.empty:
            binance_earn_token = binance_earn_df[binance_earn_df['currency'].str.upper() == token_symbol.upper()]
            if not binance_earn_token.empty:
                merged['binance_earn_apr'] = binance_earn_token.iloc[0]['binance_earn_apr']
            else:
                merged['binance_earn_apr'] = 0.0
        else:
            merged['binance_earn_apr'] = 0.0
            
        # Add Binance Loan
        if not binance_loan_token.empty:
            merged['binance_loan_rate'] = binance_loan_token.iloc[0]['binance_loan_rate']
            merged['binance_daily_rate'] = binance_loan_token.iloc[0]['binance_daily_rate']
        else:
            merged['binance_loan_rate'] = 0.0
            merged['binance_daily_rate'] = 0.0

        # 7. Fetch ACCURATE max loan from OKX if available
        if not okx_token.empty:
            actual_max_loan = self.okx_client.get_max_loan(token_symbol)
            if actual_max_loan is not None:
                merged['okx_avail_loan'] = actual_max_loan
                merged['okx_avail_loan_source'] = 'max-loan API (accurate)'
                logger.info(f"Actual max loan for {token_symbol}: {actual_max_loan}")
            else:
                merged['okx_avail_loan_source'] = 'interest-limits API (estimate)'
        else:
             merged['okx_avail_loan_source'] = 'N/A'
        
        # 8. Calculate Net APR
        # Use best loan source
        okx_rate = merged.get('okx_loan_rate', 0.0).iloc[0] if isinstance(merged, pd.DataFrame) else merged.get('okx_loan_rate', 0.0)
        bin_rate = merged.get('binance_loan_rate', 0.0).iloc[0] if isinstance(merged, pd.DataFrame) else merged.get('binance_loan_rate', 0.0)
        
        # Handle NaN
        okx_rate = 0.0 if pd.isna(okx_rate) else okx_rate
        bin_rate = 0.0 if pd.isna(bin_rate) else bin_rate
        
        best_rate = 0.0
        if okx_rate > 0 and bin_rate > 0:
            best_rate = min(okx_rate, bin_rate)
        elif okx_rate > 0:
            best_rate = okx_rate
        elif bin_rate > 0:
            best_rate = bin_rate
            
        merged['net_apr'] = merged['gate_apr'] - best_rate
        merged['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        return merged
    
    def get_token_price(self, token):
        """Get token price in USDT (with cache)"""
        now = datetime.now()
        
        # Check cache
        cache_key = f"{token}_price"
        if cache_key in self.fee_cache:
            cache_data = self.fee_cache[cache_key]
            # Refresh price every 5 minutes
            if (now - cache_data['timestamp']).total_seconds() < 300:
                return cache_data['price']
        
        # Helper: Local lookup from bulk cache (populated in find_opportunities)
        if hasattr(self, '_bulk_price_cache') and token in self._bulk_price_cache:
             price = self._bulk_price_cache[token]
             self.fee_cache[cache_key] = {'timestamp': now, 'price': price}
             return price

        # Fetch fresh price (fallback)
        
        # 0. Handle Stablecoins
        if token in ['USDT', 'USDC', 'DAI', 'FDUSD', 'TUSD']:
            self.fee_cache[cache_key] = {'timestamp': now, 'price': 1.0}
            return 1.0

        price = 0.0
        
        # 1. Try Gate
        try:
            if self.gate_client:
                price = self.gate_client.get_ticker_price(token)
        except Exception:
            pass
            
        # 2. Try OKX
        if price <= 0 and self.okx_client:
            try:
                price = self.okx_client.get_ticker_price(token)
            except Exception:
                pass
                
        # 3. Try Binance (needs implementation, but let's stick to OKX for now)
        
        if price <= 0:
             # logger.warning(f"Failed to fetch price for {token}")
             pass
        
        # Update cache
        self.fee_cache[cache_key] = {
            'timestamp': now,
            'price': price
        }
        return price

    def _prefetch_prices(self):
        """Fetch all prices at once to avoid N+1"""
        try:
             if self.gate_client:
                 logger.info("Prefetching Gate prices...")
                 self._bulk_price_cache = self.gate_client.get_all_tickers()
                 logger.info(f"Prefetched {len(self._bulk_price_cache)} prices from Gate")
        except Exception as e:
             logger.error(f"Prefetch error: {e}")
             self._bulk_price_cache = {}

    def get_token_wd_fees(self, token):
        """Get withdrawal fees for a token from all exchanges (with caching)"""
        now = datetime.now()
        
        # Check cache
        if token in self.fee_cache:
            cache_data = self.fee_cache[token]
            # Refresh if older than 1 hour
            if (now - cache_data['timestamp']).total_seconds() < 3600:
                return cache_data['fees']
        
        # Fetch fresh data
        # Check bulk cache first
        gate_fee_usd = None
        if hasattr(self, '_bulk_gate_fee_cache') and token in self._bulk_gate_fee_cache:
             gate_fee_usd = self._bulk_gate_fee_cache[token]
        else:
             # Fallback to single call
             gate_fee_usd = self.gate_client.get_withdrawal_fee(token) if self.gate_client else None
        
        # OKX/Binance return Token Amount (standard CEX behavior)
        okx_fee = self.okx_client.get_withdrawal_fee(token) if self.okx_client else 0.0
        binance_fee = self.binance_client.get_withdrawal_fee(token) if self.binance_client else 0.0
        
        # Get Price for USD calculation
        price = self.get_token_price(token)
        
        # --- LOGIC UPDATE: Strict USD Conversion & Sanity Checks ---
        
        # 1. Gate (Already USD or None)
        # If None, it means Non-Tradable (no valid chain)
        
        # 2. OKX (Coin Units -> USD)
        if okx_fee > 0 and price > 0:
            okx_wd_fee_usd = okx_fee * price
        else:
            okx_wd_fee_usd = None # Treat 0 or missing price as Missing Data (not free)

        # 3. Binance (Coin Units -> USD)
        if binance_fee > 0 and price > 0:
            binance_wd_fee_usd = binance_fee * price
        else:
            binance_wd_fee_usd = None
            
        # 4. Derived Gate Token Fee
        if gate_fee_usd is not None and price > 0:
            gate_wd_fee_token = gate_fee_usd / price
        else:
            gate_wd_fee_token = 0.0
        
        # 5. Sanity Logging
        if price > 0:
             # Only log if we have a valid price to make sense of the data
             gate_log = f"${gate_fee_usd:.2f}" if gate_fee_usd is not None else "N/A"
             logger.info(f"[WD DEBUG] {token} | Price: ${price:.4f} | Gate: {gate_log} | OKX: {okx_fee} (${(okx_wd_fee_usd or 0):.2f}) | Bin: {binance_fee} (${(binance_wd_fee_usd or 0):.2f})")
        
        fees = {
            'gate_wd_fee': gate_wd_fee_token, 
            'gate_wd_fee_usd': gate_fee_usd, # Can be None 
            'okx_wd_fee': okx_fee,
            'okx_wd_fee_usd': okx_wd_fee_usd, # Can be None
            'binance_wd_fee': binance_fee,
            'binance_wd_fee_usd': binance_wd_fee_usd, # Can be None
            'token_price': price,
            'valid': True # Default valid, filtered later if needed
        }
        
        # Update cache
        self.fee_cache[token] = {
            'timestamp': now,
            'fees': fees
        }
        
        return fees

    def find_opportunities(self):
        logger.info("Mencari peluang...")
        
        # Prefetch prices to avoid N+1 LATER
        # Ensure this is called before main loop
        self._prefetch_prices()
        
        # Fetch Gate Earn
        gate_df = self.get_gate_data()
        if gate_df.empty:
            logger.warning("Data Gate kosong")
            return pd.DataFrame()

        if self.gate_client:
             # Clean up old manual batch fetch to move it down
             pass 
        else:
             self._bulk_gate_fee_cache = {}

        # Fetch OKX Loan data
        okx_df = self.get_okx_data()
        
        logger.debug(f"Gate DF: {gate_df.shape}")
        logger.debug(f"OKX DF: {okx_df.shape}")
        
        # Fetch Binance Loan rates (Flexible)
        binance_loan_df = self.get_binance_loan_data()
        
        # ========================
        # MERGE LOGIC - INCLUSIVE
        # ========================
        # Base: Gate Earn (We need earn opportunity first)
        merged = gate_df.copy()
        
        # Join OKX (Left Join)
        if not okx_df.empty:
            merged = pd.merge(merged, okx_df, on='currency', how='left')
        else:
            merged['okx_loan_rate'] = 0.0
            merged['available'] = False
            
        # Join Binance (Left Join)
        if not binance_loan_df.empty:
            # binance_loan_df has 'currency', 'binance_loan_rate', 'binance_daily_rate'
            merged = pd.merge(merged, binance_loan_df[['currency', 'binance_loan_rate']], 
                            on='currency', how='left')
        else:
            merged['binance_loan_rate'] = 0.0
            
        # Fill NaN with 0
        merged['okx_loan_rate'] = merged['okx_loan_rate'].fillna(0.0)
        merged['binance_loan_rate'] = merged['binance_loan_rate'].fillna(0.0)
        
        # Explicit infer_objects to avoid FutureWarning
        # and then fillna(False)
        merged['available'] = merged['available'].fillna(False).infer_objects(copy=False) # OKX availability
        
        # ================================
        # FILTER: Must have AT LEAST ONE loan source
        # ================================
        # Keep if (OKX available) OR (Binance Rate > 0)
        valid_opportunities = merged[
            (merged['okx_loan_rate'] > 0) | (merged['binance_loan_rate'] > 0)
        ].copy()
        
        if valid_opportunities.empty:
             logger.warning("Tidak ada token yang memiliki opsi pinjaman (OKX/Binance)")
             return pd.DataFrame()
        
        # ================================
        # COMPARE OKX vs BINANCE LOAN RATE
        # Pick the CHEAPEST source for borrowing
        # ================================
        def get_best_loan(row):
            okx_rate = row['okx_loan_rate']
            binance_rate = row['binance_loan_rate']
            
            # Cases:
            # 1. Only OKX
            if okx_rate > 0 and binance_rate <= 0:
                return okx_rate, 'OKX'
            # 2. Only Binance
            if binance_rate > 0 and okx_rate <= 0:
                return binance_rate, 'Binance'
            # 3. Both available - pick cheapest
            if okx_rate > 0 and binance_rate > 0:
                if binance_rate < okx_rate:
                    return binance_rate, 'Binance'
                else:
                    return okx_rate, 'OKX'
            
            return 0.0, 'None'
        
        # Apply comparison
        valid_opportunities[['best_loan_rate', 'best_loan_source']] = valid_opportunities.apply(
            lambda row: pd.Series(get_best_loan(row)), axis=1
        )
        
        # Note regarding OKX Availability:
        # If best source is Binance, we consider it "Available" regardless of OKX status
        # If best source is OKX, we rely on OKX 'available' status
        def check_final_availability(row):
            if row['best_loan_source'] == 'Binance':
                return True # Assuming Binance Flexible is available if rate exists
            if row['best_loan_source'] == 'OKX':
                return row['available'] # From OKX surplus check
            return False

        valid_opportunities['available'] = valid_opportunities.apply(check_final_availability, axis=1)
        valid_opportunities['status'] = valid_opportunities['available'].apply(lambda x: "✅ AVAILABLE" if x else "❌ NOT AVAILABLE")
        
        # ================================
        # ENRICH: Add Withdrawal Fees
        # ================================
        
        # OPTIMIZATION: Batch Fetch Gate Fees for VALID opportunities only
        if self.gate_client and not valid_opportunities.empty:
            tokens = valid_opportunities['currency'].unique().tolist()
            logger.info(f"Batch fetching Gate fees for {len(tokens)} valid tokens...")
            # Update cache directly or use bulk cache
            self._bulk_gate_fee_cache = self.gate_client.get_batch_withdrawal_fees(tokens)
            
        def add_wd_fees(row):
            token = row['currency']
            fees = self.get_token_wd_fees(token)
            return pd.Series([
                fees['gate_wd_fee'], fees['gate_wd_fee_usd'],
                fees['okx_wd_fee'], fees['okx_wd_fee_usd'],
                fees['binance_wd_fee'], fees['binance_wd_fee_usd']
            ])
            
        valid_opportunities[['gate_wd_fee', 'gate_wd_fee_usd', 'okx_wd_fee', 'okx_wd_fee_usd', 'binance_wd_fee', 'binance_wd_fee_usd']] = valid_opportunities.apply(add_wd_fees, axis=1)
        
        # Hitung net APR using the BEST loan rate
        valid_opportunities['net_apr'] = valid_opportunities['gate_apr'] - valid_opportunities['best_loan_rate']
        
        # ================================
        # METRIC: Effective EV (Profitability after Fees)
        # ================================
        # Real EV = Net APR - Withdrawal Cost
        # effective_ev_percent = net_apr - (wd_fee_usd / 1000 * 100)
        DEFAULT_TRADE_SIZE = 1000.0
        
        def calc_ev(row):
            source = row['best_loan_source']
            net_apr = row['net_apr']
            
            # 1. Borrow/Bridge Fee (Source -> Gate)
            source_wd_fee = 0.0
            if source == 'OKX':
                val = row.get('okx_wd_fee_usd')
                if val is None or val <= 0:
                     return -999.0 # Missing Fee Data (Non-Tradable)
                source_wd_fee = float(val)
            elif source == 'Binance':
                val = row.get('binance_wd_fee_usd')
                if val is None or val <= 0:
                     return -999.0 # Missing Fee Data (Non-Tradable)
                source_wd_fee = float(val)
                
            # 2. Exit Fee (Gate -> Wallet)
            gate_val = row.get('gate_wd_fee_usd')
            # Fix Zero-Value Masking: If missing/None, return penalty
            if gate_val is None:
                return -999.0
            
            gate_wd_fee = float(gate_val)
            
            # Total Fee Impact
            total_fee = source_wd_fee + gate_wd_fee
            
            # Sanity Check: Fee > 50% of Position ($500)
            if total_fee > (DEFAULT_TRADE_SIZE * 0.5):
                 return -999.0 # Fee too high (Non-Tradable)
                
            # Impact in % terms
            fee_impact_pct = (total_fee / DEFAULT_TRADE_SIZE) * 100
            return net_apr - fee_impact_pct
            
        valid_opportunities['effective_ev'] = valid_opportunities.apply(calc_ev, axis=1)
        valid_opportunities['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        logger.info(f"Found {len(valid_opportunities)} opportunities (Gate + OKX/Binance)")
        
        # Sort by Effective EV instead of raw Net APR
        return valid_opportunities.sort_values('effective_ev', ascending=False)