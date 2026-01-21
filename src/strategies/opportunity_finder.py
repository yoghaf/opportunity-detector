# src/strategies/opportunity_finder.py
import pandas as pd
from datetime import datetime
from config.settings import Config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class OpportunityFinder:
    def __init__(self, gate_client, okx_client):
        self.gate_client = gate_client
        self.okx_client = okx_client
    
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
    
    def get_okx_data(self):
        logger.debug("Calling OKX API...")
        loan_data = self.okx_client.get_loan_limit()
        
        if not loan_data:
            logger.warning("OKX API: No loan data")
            return pd.DataFrame()
        
        records = []
        for item in loan_data:
            if isinstance(item, dict):
                if 'ccy' in item:
                    records.append(item)
                elif 'records' in item:
                    records.extend(item['records'])
        
        logger.debug(f"Extracted {len(records)} records")
        
        if not records:
            logger.warning("OKX: No valid records")
            return pd.DataFrame()
        
        data = []
        for record in records:
            currency = record.get('ccy', '')
            if not currency:
                continue
            
            daily_rate = float(record.get('rate', 0))
            interest_rate_apy = daily_rate * 365 * 100
            surplus_limit = float(record.get('surplusLmt', 0))
            total_quota = float(record.get('loanQuota', 0))
            used_quota = float(record.get('usedLmt', 0))
            is_available = surplus_limit > 0
            
            # FIX: Tambahkan 'status' di sini
            data.append({
                'currency': currency,
                'okx_loan_rate': interest_rate_apy,
                'okx_daily_rate': daily_rate * 100,
                'okx_total_quota': total_quota,
                'okx_used_quota': used_quota,
                'okx_surplus_limit': surplus_limit,
                'available': is_available,
                'status': "✅ AVAILABLE" if is_available else "❌ NOT AVAILABLE"  # TAMBAHKAN INI
            })
        
        df = pd.DataFrame(data)
        logger.info(f"OKX: {len(df)} tokens with loan data")
        return df
    
    def search_token(self, token_symbol):
        """Cari token spesifik"""
        logger.info(f"Mencari token: {token_symbol.upper()}")
        
        gate_df = self.get_gate_data()
        okx_df = self.get_okx_data()
        
        if gate_df.empty or okx_df.empty:
            logger.warning("Data tidak lengkap")
            return pd.DataFrame()
        
        # Filter token spesifik
        gate_token = gate_df[gate_df['currency'].str.upper() == token_symbol.upper()]
        okx_token = okx_df[okx_df['currency'].str.upper() == token_symbol.upper()]
        
        if gate_token.empty:
            logger.warning(f"Token {token_symbol} tidak ditemukan di Gate")
            return pd.DataFrame()
        
        if okx_token.empty:
            logger.warning(f"Token {token_symbol} tidak tersedia di OKX Loan")
            return pd.DataFrame()
        
        # Merge
        merged = pd.merge(gate_token, okx_token, on='currency', how='inner')
        
        if merged.empty:
            logger.warning("Tidak ada data yang cocok")
            return pd.DataFrame()
        
        # FIX: Kolom 'status' sudah ada dari okx_token, jadi tidak perlu di-set lagi
        merged['net_apr'] = merged['gate_apr'] - merged['okx_loan_rate']
        merged['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        return merged
    
    def find_opportunities(self):
        logger.info("Mencari peluang...")
        
        gate_df = self.get_gate_data()
        okx_df = self.get_okx_data()
        
        logger.debug(f"Gate DF: {gate_df.shape}")
        logger.debug(f"OKX DF: {okx_df.shape}")
        
        if gate_df.empty or okx_df.empty:
            logger.warning("Data tidak lengkap")
            return pd.DataFrame()
        
        # Merge
        merged = pd.merge(gate_df, okx_df, on='currency', how='inner')
        logger.info(f"Merged: {len(merged)} common tokens")
        
        if merged.empty:
            logger.warning("Tidak ada currency yang sama")
            return pd.DataFrame()
        
        # Hitung net APR
        merged['net_apr'] = merged['gate_apr'] - merged['okx_loan_rate']
        merged['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Filter
        opportunities = merged[
            (merged['available'] == True) &
            (merged['okx_surplus_limit'] >= Config.MIN_OKX_SURPLUS) &
            (merged['net_apr'] >= Config.MIN_NET_APR)
        ].copy()
        
        logger.info(f"Found {len(opportunities)} opportunities")
        return opportunities.sort_values('net_apr', ascending=False)