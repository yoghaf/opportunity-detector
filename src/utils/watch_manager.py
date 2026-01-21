# src/utils/watch_manager.py
import json
import os
from datetime import datetime  # Penting: Diperlukan untuk add_token
from config.settings import Config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class WatchManager:
    def __init__(self):
        self.watch_file = Config.WATCH_LIST_PATH
        self.watch_data = self.load_watch_list()
    
    def load_watch_list(self):
        if os.path.exists(self.watch_file):
            try:
                with open(self.watch_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def save_watch_list(self):
        os.makedirs(os.path.dirname(self.watch_file), exist_ok=True)
        with open(self.watch_file, 'w') as f:
            json.dump(self.watch_data, f, indent=2)
        logger.info(f"Watch list saved: {len(self.watch_data)} tokens")
    
    def add_token(self, token, enabled=True):
        token = token.upper()
        self.watch_data[token] = {
            'enabled': enabled,
            'added_at': datetime.now().isoformat()
        }
        self.save_watch_list()
        logger.info(f"Token added: {token} (enabled: {enabled})")
    
    def remove_token(self, token):
        token = token.upper()
        if token in self.watch_data:
            del self.watch_data[token]
            self.save_watch_list()
            return True
        return False
    
    def toggle_token(self, token):
        token = token.upper()
        if token in self.watch_data:
            self.watch_data[token]['enabled'] = not self.watch_data[token]['enabled']
            self.save_watch_list()
            return self.watch_data[token]['enabled']
        return None
    
    def get_enabled_tokens(self):
        return [token for token, data in self.watch_data.items() if data.get('enabled', False)]
    
    # Alias untuk kompatibilitas dengan main.py
    def get_active_tokens(self):
        return self.get_enabled_tokens()
    
    def get_all_tokens(self):
        return {token: data.get('enabled', False) for token, data in self.watch_data.items()}
    
    def is_token_enabled(self, token):
        token = token.upper()
        return token in self.watch_data and self.watch_data[token].get('enabled', False)