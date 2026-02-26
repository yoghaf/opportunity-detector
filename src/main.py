# src/main.py
import time
import sys
import os
import subprocess
import pandas as pd
from datetime import datetime

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Config
from src.exchanges.gate_client import GateClient
from src.exchanges.okx_client import OKXClient
from src.exchanges.binance_client import BinanceClient
from src.strategies.opportunity_finder import OpportunityFinder
from src.utils.logger import setup_logger
from src.utils.telegram_notifier import TelegramNotifier
from src.utils.watch_manager import WatchManager

logger = setup_logger(__name__)

sent_notifications = set()
streamlit_process = None

def launch_dashboard():
    """Launch Streamlit dashboard"""
    global streamlit_process
    print("\n🚀 Membuka Dashboard...")
    try:
        # Check if already running
        if streamlit_process and streamlit_process.poll() is None:
            print("⚠️  Dashboard sudah berjalan!")
            return

        # Run streamlit in a subprocess
        cmd = [sys.executable, "-m", "streamlit", "run", "src/dashboard.py"]
        streamlit_process = subprocess.Popen(cmd)
        print("✅ Dashboard dibuka di browser!")
    except Exception as e:
        print(f"❌ Gagal membuka dashboard: {e}")

def display_menu():
    print("\n" + "="*60)
    print("🤖 OPPORTUNITY DETECTOR - MAIN MENU")
    print("="*60)
    print("1. 📊 Tampilkan semua token APR tinggi")
    print("2. 🔍 Cari token spesifik")
    print("3. ⏰ Setup Watch & Notify (Telegram)")
    print("4. 📋 Manage Watch List")
    print("5. ⚙️  Update delay (interval refresh)")
    print("6. 🎚️  Set jumlah token yang ditampilkan")
    print("7. 🖥️  Buka Dashboard (Streamlit)")
    print("8. ✅ Exit")
    print("="*60)
    return input("Pilih opsi (1-8): ").strip()

def setup_watch_tokens(notifier, watch_manager, finder):
    """Setup watch tokens & mulai notifikasi"""
    if not notifier.enabled:
        print("❌ Telegram belum dikonfigurasi!")
        return
    
    watch_tokens = watch_manager.get_enabled_tokens()
    
    if not watch_tokens:
        print("⚠️  Belum ada token di-watch list!")
        print("📋 Pilih opsi 4 di menu untuk tambah token")
        return
    
    print(f"\n🔔 Watch tokens aktif: {', '.join(watch_tokens)}")
    print(f"⚠️  Bot akan check setiap {Config.UPDATE_INTERVAL} detik")
    print("💡 Tekan Ctrl+C untuk kembali ke menu")
    
    confirm = input("\nLanjutkan? (y/n): ").strip().lower()
    if confirm != 'y':
        return
    
    print("\n" + "="*60)
    print("🔔 WATCH MODE AKTIF")
    print("="*60)
    
    try:
        while True:
            check_and_notify(finder, notifier, watch_manager)
            time.sleep(Config.UPDATE_INTERVAL)
    except KeyboardInterrupt:
        print("\n🔄 Kembali ke menu...")

def manage_watch_list(watch_manager):
    """Menu untuk manage watch list"""
    while True:
        print("\n" + "="*60)
        print("🔔 WATCH LIST MANAGER")
        print("="*60)
        
        all_tokens = watch_manager.get_all_tokens()
        if all_tokens:
            print("Token yang di-watch:")
            for token, enabled in all_tokens.items():
                status = "✅ ON" if enabled else "❌ OFF"
                print(f"  {token:8} - {status}")
        else:
            print("Belum ada token di-watch list")
        
        print("\nOpsi:")
        print("1. ➕ Tambah token")
        print("2. ➖ Hapus token")
        print("3. 🔄 Toggle ON/OFF")
        print("4. 🔙 Kembali")
        print("="*60)
        
        choice = input("Pilih opsi (1-4): ").strip()
        
        if choice == "1":
            token = input("Masukkan token: ").strip().upper()
            if token:
                watch_manager.add_token(token, enabled=True)
                print(f"✅ Token {token} ditambahkan & diaktifkan")
            else:
                print("❌ Token tidak valid")
        elif choice == "2":
            token = input("Masukkan token: ").strip().upper()
            if token:
                if watch_manager.remove_token(token):
                    print(f"✅ Token {token} dihapus")
                else:
                    print(f"❌ Token {token} tidak ditemukan")
            else:
                print("❌ Token tidak valid")
        elif choice == "3":
            token = input("Masukkan token: ").strip().upper()
            if token:
                new_state = watch_manager.toggle_token(token)
                if new_state is not None:
                    status = "enabled" if new_state else "disabled"
                    print(f"✅ Token {token} sekarang {status}")
                else:
                    print(f"❌ Token {token} tidak ditemukan di watch list")
            else:
                print("❌ Token tidak valid")
        elif choice == "4":
            break
        else:
            print("❌ Pilihan tidak valid")

def check_and_notify(finder, notifier, watch_manager):
    """Cek token watch dan kirim notifikasi"""
    global sent_notifications
    
    enabled_tokens = watch_manager.get_enabled_tokens()
    
    if not enabled_tokens:
        return
    
    for token in enabled_tokens:
        df = finder.search_token(token)
        
        if not df.empty:
            row = df.iloc[0]
            interval = max(60, Config.UPDATE_INTERVAL)
            token_key = f"{token}_{int(time.time()) // interval}"
            
            if token_key not in sent_notifications:
                notifier.notify_opportunity(row.to_dict())
                sent_notifications.add(token_key)
                print(f"📱 Notifikasi terkirim: {token}")
            
            if len(sent_notifications) > 100:
                sent_notifications.clear()

def search_token_interactive(finder):
    """Cari token spesifik"""
    token = input("\nMasukkan kode token (contoh: ETH, BERA, BTC): ").strip().upper()
    if not token:
        print("❌ Token tidak boleh kosong!")
        return
    
    print(f"\n🔍 Mencari token: {token}...")
    df = finder.search_token(token)
    
    if not df.empty:
        print("\n" + "="*80)
        print(f"🔍 HASIL PENCARIAN: {token}")
        print("="*80)
        
        row = df.iloc[0]
        avail_loan = row.get('okx_avail_loan', row['okx_surplus_limit'])
        data_source = row.get('okx_avail_loan_source', 'interest-limits API (estimate)')
        
        print(f"Token: {row['currency']}")
        print(f"Gate APR: {row['gate_apr']:.2f}%")
        
        # Binance Data Display
        binance_earn = row.get('binance_earn_apr', 0)
        binance_loan = row.get('binance_loan_rate', 0)
        
        if binance_earn > 0:
            print(f"Binance Earn: {binance_earn:.2f}%")
            
        print(f"OKX APY: {row['okx_loan_rate']:.2f}%")
        
        if binance_loan > 0:
            print(f"Binance Loan: {binance_loan:.2f}%")
            
        print(f"Daily Rate: {row['okx_daily_rate']:.4f}%")
        print(f"Avail Loan: {avail_loan:,.2f} {row['currency']} [{data_source}]")
        print(f"Quota: {row['okx_used_quota']:,.2f} / {row['okx_total_quota']:,.2f}")
        print(f"Net APR: {row['net_apr']:.2f}%")
        print(f"Status: {row['status']}")
        print("="*80)
        
        save = input("Simpan hasil ke CSV? (y/n): ").strip().lower()
        if save == 'y':
            df.to_csv(Config.DATA_PATH, index=False)
            print(f"✅ Data tersimpan: {Config.DATA_PATH}")
    else:
        print(f"\n❌ Token {token} tidak ditemukan")

def display_high_apr(finder):
    """Tampilkan token APR tinggi"""
    print("\n⏳ Mengambil data, tunggu sebentar...")
    df = finder.find_opportunities()
    
    if not df.empty:
        display_limit = Config.DISPLAY_LIMIT
        
        print("\n" + "="*140)
        print(f"{'No':<3} {'Crypto':<8} {'Gate APR':>10} {'OKX Loan':>10} {'Bin Loan':>10} {'Best':>8} {'Avail Loan':>14} {'Net APR':>10} {'Status'}")
        print("="*140)
        
        for idx, row in df.head(display_limit).iterrows():
            status_emoji = "✅" if row['available'] else "❌"
            avail_loan = row.get('okx_avail_loan', row['okx_surplus_limit'])
            
            # Loan Rates Display
            okx_loan = row.get('okx_loan_rate', 0)
            binance_loan = row.get('binance_loan_rate', 0)
            okx_loan_display = f"{okx_loan:.2f}%"
            binance_loan_display = f"{binance_loan:.2f}%" if binance_loan > 0 else "-"
            
            # Best Loan Source
            best_source = row.get('best_loan_source', 'OKX')
            best_indicator = "🅱" if best_source == 'Binance' else "🆗"
            
            print(f"{idx+1:<3} {row['currency']:<8} {row['gate_apr']:>9.2f}% {okx_loan_display:>10} {binance_loan_display:>10} {best_indicator:>8} {avail_loan:>13,.2f} {row['net_apr']:>9.2f}% {status_emoji:>6}")
        
        print("="*140)
        print(f"Peluang ditemukan: {len(df)} token | 🅱 = Binance lebih murah | 🆗 = OKX lebih murah")
        print("="*140)
        
        df.to_csv(Config.DATA_PATH, index=False)
        print(f"✅ Data tersimpan otomatis: {Config.DATA_PATH}")
    else:
        print("\n❌ Tidak ada peluang sesuai kriteria")


def update_interval():
    """Update delay refresh"""
    try:
        new_interval = int(input("\nMasukkan interval baru (dalam detik, contoh: 300): ").strip())
        if new_interval < 10:
            print("❌ Interval minimal 10 detik!")
        else:
            Config.UPDATE_INTERVAL = new_interval
            print(f"✅ Interval diupdate menjadi: {new_interval} detik")
    except ValueError:
        print("❌ Input harus angka!")
def update_display_limit():
    """Update jumlah token yang ditampilkan di tabel"""
    try:
        new_limit = int(input("\nMasukkan jumlah token (contoh: 10, 50, 100): ").strip())
        if new_limit < 1:
            print("❌ Minimal 1 token!")
        elif new_limit > 500:
            print("❌ Maksimal 500 token (untuk performance)!")
        else:
            Config.DISPLAY_LIMIT = new_limit
            print(f"✅ Display limit diupdate menjadi: {new_limit} token")
    except ValueError:
        print("❌ Input harus angka!")

def main():
    gate_client = GateClient()
    okx_client = OKXClient()
    binance_client = BinanceClient()  # Will be disabled if no API keys
    finder = OpportunityFinder(gate_client, okx_client, binance_client)
    telegram = TelegramNotifier()
    watch_manager = WatchManager()
    
    if binance_client.enabled:
        logger.info("Binance integration: ENABLED")
    else:
        logger.info("Binance integration: DISABLED (no API keys)")
    
    logger.info("Opportunity Detector with Watch List Manager dimulai")
    
    try:
        while True:
            try:
                choice = display_menu()
                
                if choice == "1":
                    display_high_apr(finder)
                elif choice == "2":
                    search_token_interactive(finder)
                elif choice == "3":
                    setup_watch_tokens(telegram, watch_manager, finder)
                elif choice == "4":
                    manage_watch_list(watch_manager)
                elif choice == "5":
                    update_interval()
                elif choice == "6":
                    update_display_limit()
                elif choice == "7":
                    launch_dashboard()
                elif choice == "8":
                    print("\n👋 Bot dihentikan")
                    break
                else:
                    print("\n❌ Pilihan tidak valid")
                
            except KeyboardInterrupt:
                logger.info("Bot dihentikan via KeyboardInterrupt")
                break
            except Exception as e:
                logger.error(f"Error: {e}", exc_info=True)
                print("\n❌ Terjadi error, lihat log untuk detail")
                time.sleep(2)
    finally:
        # Clean up subprocess
        if streamlit_process and streamlit_process.poll() is None:
            print("Stopping Dashboard...")
            streamlit_process.terminate()
            try:
                streamlit_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                streamlit_process.kill()
            print("Dashboard stopped.")

if __name__ == "__main__":
    main()