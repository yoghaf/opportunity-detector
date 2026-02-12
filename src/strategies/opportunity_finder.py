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
    
    def get_gate_data(self):
        rates = self.gate_client.get_simple_earn_rates()
        if not rates:
            logger.warning("Gate API: No rates")
            return pd.DataFrame()
        
        data = []
        for rate in rates:
            currency = getattr(rate, 'currency', '')
            raw_rate = float(getattr(rate, 'est_rate', 0)) if getattr(rate, 'est_rate') else 0.0
            apr = raw_rate * 100
            
            if currency and apr > 0:
                data.append({'currency': currency, 'gate_apr': apr})
        
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
    
    def find_opportunities(self):
        logger.info("Mencari peluang...")
        
        # Fetch Gate Earn
        gate_df = self.get_gate_data()
        if gate_df.empty:
            logger.warning("Data Gate kosong")
            return pd.DataFrame()

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
        
        # Hitung net APR using the BEST loan rate
        valid_opportunities['net_apr'] = valid_opportunities['gate_apr'] - valid_opportunities['best_loan_rate']
        valid_opportunities['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        logger.info(f"Found {len(valid_opportunities)} opportunities (Gate + OKX/Binance)")
        
        return valid_opportunities.sort_values('net_apr', ascending=False)