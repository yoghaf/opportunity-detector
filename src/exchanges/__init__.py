# src/exchanges/okx_client.py (tambah di __init__)
def __init__(self):
    missing = []
    if not Config.OKX_API_KEY:
        missing.append("OKX_API_KEY")
    if not Config.OKX_API_SECRET:
        missing.append("OKX_API_SECRET")
    if not Config.OKX_PASSPHRASE:
        missing.append("OKX_PASSPHRASE")
    
    if missing:
        raise ValueError(f"OKX API keys tidak lengkap: {', '.join(missing)}")
    
    self.api_key = Config.OKX_API_KEY
    self.secret_key = Config.OKX_API_SECRET
    self.passphrase = Config.OKX_PASSPHRASE
    self.base_url = "https://www.okx.com"
    
    logger.debug(f"OKX Client initialized with key: {self.api_key[:10]}...")