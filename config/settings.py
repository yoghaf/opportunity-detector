# config/settings.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Gate.io API
    GATE_API_KEY = os.getenv('GATE_API_KEY')
    GATE_API_SECRET = os.getenv('GATE_API_SECRET')
    
    # OKX API
    OKX_API_KEY = os.getenv('OKX_API_KEY')
    OKX_API_SECRET = os.getenv('OKX_API_SECRET')
    OKX_PASSPHRASE = os.getenv('OKX_PASSPHRASE')
    
    # Telegram (untuk notifikasi)
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
    
    # Token yang di-watch (pisah dengan koma)
    WATCH_TOKENS = os.getenv('WATCH_TOKENS', '').split(',')
    
    # Settings
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL', '300'))  # detik
    DISPLAY_LIMIT = int(os.getenv('DISPLAY_LIMIT', '50'))
    MIN_NET_APR = float(os.getenv('MIN_NET_APR', '100'))  # minimal net APR
    MIN_OKX_SURPLUS = float(os.getenv('MIN_OKX_SURPLUS', '1000'))  # minimal surplus
    WATCH_LIST_PATH = 'data/watch_list.json'
    # File paths
    DATA_PATH = 'data/opportunities.csv'
    LOG_PATH = 'logs/bot.log'