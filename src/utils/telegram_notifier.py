# src/utils/telegram_notifier.py
import asyncio
from datetime import datetime
from telegram import Bot
from config.settings import Config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class TelegramNotifier:
    def __init__(self):
        self.bot = Bot(token=Config.TELEGRAM_BOT_TOKEN)
        self.chat_id = Config.TELEGRAM_CHAT_ID
        self.enabled = bool(self.bot.token and self.chat_id)
        
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
            
    async def send_photo_async(self, photo_path, caption=None):
        if not self.enabled:
            return
            
        try:
            caption = caption or ""
            # Escape markdown special chars in caption if needed, 
            # but let's keep it simple or strictly plain text for now to avoid errors
            
            with open(photo_path, 'rb') as photo:
                await self.bot.send_photo(
                    chat_id=self.chat_id,
                    photo=photo,
                    caption=caption
                )
            logger.info(f"Telegram photo sent: {photo_path}")
        except Exception as e:
            logger.error(f"Telegram photo error: {e}")
            
    def send_photo(self, photo_path, caption=None):
        try:
            asyncio.run(self.send_photo_async(photo_path, caption))
        except Exception as e:
            logger.error(f"Telegram photo sync error: {e}")
    
    def notify_opportunity(self, token_data):
        """Kirim notifikasi - tidak perlu cek watch list lagi (sudah difilter)"""
        if not token_data or not self.enabled:
            return
        
        currency = token_data.get('currency', '')
        net_apr = token_data.get('net_apr', 0)
        gate_apr = token_data.get('gate_apr', 0)
        okx_apy = token_data.get('okx_loan_rate', 0)
        surplus = token_data.get('okx_surplus_limit', 0)
        
        emoji = "🚀" if net_apr > 200 else "💰" if net_apr > 100 else "📈"
        
        # Deep Links (Anti-Detection / Manual Execution)
        # OKX Loan: https://www.okx.com/loan
        # Binance Loan: https://www.binance.com/en/loan
        # Gate Earn: https://www.gate.io/hodl
        
        deep_links = ""
        if okx_apy > 0:
            deep_links += f"[👉 OKX Loan ({currency})](https://www.okx.com/loan) | "
        
        binance_rate = token_data.get('binance_loan_rate', 0)
        if binance_rate > 0:
            deep_links += f"[👉 Binance Loan ({currency})](https://www.binance.com/en/loan) | "
            
        deep_links += f"[👉 Gate Earn](https://www.gate.io/hodl)"

        message = (
            f"*{emoji} OPPORTUNITY ALERT: {currency}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Net APR:* `{net_apr:.2f}%`\n"
            f"📊 *Gate APR:* `{gate_apr:.2f}%`\n"
            f"🏦 *OKX APY:* `{okx_apy:.2f}%`\n"
            f"💎 *Surplus:* `{surplus:,.2f} {currency}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 *Manual Action (Anti-Detect):*\n"
            f"{deep_links}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ *Time:* `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        )
        
        self.send_message(message)
        print(f"📱 Notifikasi terkirim ke Telegram: {currency}")