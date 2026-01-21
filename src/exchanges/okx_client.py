# src/exchanges/okx_client.py
import requests
import hmac
import hashlib
import base64
import time
from datetime import datetime
from urllib.parse import urlencode
from config.settings import Config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class OKXClient:
    def __init__(self):
        if not all([Config.OKX_API_KEY, Config.OKX_API_SECRET, Config.OKX_PASSPHRASE]):
            raise ValueError("OKX API keys tidak lengkap! Periksa .env file")
        
        self.api_key = Config.OKX_API_KEY
        self.secret_key = Config.OKX_API_SECRET
        self.passphrase = Config.OKX_PASSPHRASE
        self.base_url = "https://www.okx.com"
    
    def _generate_signature(self, timestamp, method, request_path, body=''):
        message = str(timestamp) + str(method) + str(request_path) + str(body)
        logger.debug(f"Message to sign: {message}")
        
        mac = hmac.new(
            self.secret_key.encode('utf-8'),
            message.encode('utf-8'),
            digestmod=hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode('utf-8')
    
    def get_loan_limit(self):
        """Get loan interest and limit via REST API"""
        try:
            timestamp = datetime.utcnow().isoformat()[:-3] + 'Z'
            method = "GET"
            base_path = "/api/v5/account/interest-limits"
            
            # FIX: Parameter yang benar untuk borrowing info
            params = {
                "type": "2",  # 2 = borrow interest
                "mgnMode": "cross"
            }
            
            query_parts = []
            for k, v in sorted(params.items()):
                query_parts.append(f"{k}={v}")
            query_string = "&".join(query_parts)
            
            request_path_for_sign = f"{base_path}?{query_string}"
            sign = self._generate_signature(timestamp, method, request_path_for_sign, "")
            
            headers = {
                "OK-ACCESS-KEY": self.api_key,
                "OK-ACCESS-SIGN": sign,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": self.passphrase,
                "Content-Type": "application/json"
            }
            
            full_url = self.base_url + request_path_for_sign
            
            logger.debug(f"Request URL: {full_url}")
            response = requests.get(full_url, headers=headers, timeout=10)
            
            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response text: {response.text[:500]}")
            
            result = response.json()
            
            if result.get('code') == '0':
                data = result.get('data', [])
                logger.info(f"OKX API success: {len(data)} records")
                return data
            else:
                logger.error(f"OKX API Error: {result.get('msg')} (code: {result.get('code')})")
                return []
        except Exception as e:
            logger.error(f"OKX Request Error: {e}")
            return []