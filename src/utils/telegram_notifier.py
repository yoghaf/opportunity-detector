# src/utils/telegram_notifier.py
import asyncio
from datetime import datetime
from telegram import Bot
from config.settings import Config
from src.utils.logger import setup_logger
from src.utils.watch_manager import WatchManager

logger = setup_logger(__name__)

class TelegramNotifier:
    def __init__(self):
        self.bot = Bot(token=Config.TELEGRAM_BOT_TOKEN)
        self.chat_id = Config.TELEGRAM_CHAT_ID
        self.enabled = bool(self.bot.token and self.chat_id)
        self.watch_manager = WatchManager()
        
        if not self.enabled:
            logger.warning("Telegram not configured. Notifications disabled.")
    
    async def send_message_async(self, message):
        if not self.enabled:
            return
        
        try:
            message = message.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`')
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
            logger.info(f"Telegram sent: {message[:50]}...")
        except Exception as e:
            logger.error(f"Telegram error: {e}")
    
    def send_message(self, message):
        try:
            asyncio.run(self.send_message_async(message))
        except Exception as e:
            logger.error(f"Telegram sync error: {e}")
    
    def notify_opportunity(self, token_data):
        """Kirim notifikasi jika token ada di watch list & enabled"""
        if not token_data or not self.enabled:
            return
        
        currency = token_data.get('currency', '')
        
        # Cek apakah token di-watch & enabled
        if not self.watch_manager.is_token_enabled(currency):
            logger.debug(f"Token {currency} tidak di-watch atau disabled, skip notif")
            return
        
        # Format & kirim notifikasi
        net_apr = token_data.get('net_apr', 0)
        gate_apr = token_data.get('gate_apr', 0)
        okx_apy = token_data.get('okx_loan_rate', 0)
        surplus = token_data.get('okx_surplus_limit', 0)
        
        emoji = "🚀" if net_apr > 200 else "💰" if net_apr > 100 else "📈"
        
        message = (
            f"*{emoji} OPPORTUNITY ALERT: {currency}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Net APR:* `{net_apr:.2f}%`\n"
            f"📊 *Gate APR:* `{gate_apr:.2f}%`\n"
            f"🏦 *OKX APY:* `{okx_apy:.2f}%`\n"
            f"💎 *Surplus:* `{surplus:,.2f} {currency}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ *Time:* `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        )
        
        self.send_message(message)