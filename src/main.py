# src/main.py
import time
import pandas as pd
from datetime import datetime
from config.settings import Config
from src.exchanges.gate_client import GateClient
from src.exchanges.okx_client import OKXClient
from src.strategies.opportunity_finder import OpportunityFinder
from src.utils.logger import setup_logger
from src.utils.telegram_notifier import TelegramNotifier
from src.utils.watch_manager import WatchManager

logger = setup_logger(__name__)

# Global variables
sent_notifications = set()  # Track notifikasi yang sudah dikirim

def manage_watch_list(watch_manager):
    """Menu untuk manage watch list"""
    # Menggunakan instance watch_manager yang dipassing dari main
    
    while True:
        print("\n" + "="*60)
        print("🔔 WATCH LIST MANAGER")
        print("="*60)
        
        # Tampilkan semua token
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
        print("3. 🔄 Toggle enable/disable")
        print("4. 🔙 Kembali ke menu utama")
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

def display_menu():
    """Tampilkan menu interaktif"""
    print("\n" + "="*60)
    print("🤖 OPPORTUNITY DETECTOR - MAIN MENU")
    print("="*60)
    print("1. 📊 Tampilkan semua token APR tinggi")
    print("2. 🔍 Cari token spesifik")
    print("3. ⏰ Setup Watch & Notify (Telegram)")
    print("4. 📋 Manage Watch List")
    print("5. ⚙️  Update delay (interval refresh)")
    print("6. ✅ Exit")
    print("="*60)
    return input("Pilih opsi (1-6): ").strip()

def setup_watch_tokens(notifier, watch_manager, finder):
    """Setup token yang mau di-monitor via Telegram"""
    
    print("\n" + "="*60)
    print("🔔 SETUP WATCH & NOTIFY")
    print("="*60)
    
    if not notifier.enabled:
        print("❌ Telegram belum dikonfigurasi!")
        print("Silakan tambahkan TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID di .env")
        return
    
    print("Mode ini akan memverifikasi token baru dan menambahkannya ke Watch List.")
    
    # Input token
    tokens_input = input("\nMasukkan token baru (pisah koma, contoh: BERA,ETH): ").strip().upper()
    
    if not tokens_input:
        print("❌ Tidak ada token dimasukkan!")
        return
    
    # Parse token
    input_tokens = [t.strip() for t in tokens_input.split(',') if t.strip()]
    
    # Verifikasi token
    print(f"\n⏳ Memverifikasi {len(input_tokens)} token...")
    
    gate_df = finder.get_gate_data()
    okx_df = finder.get_okx_data()
    
    valid_count = 0
    for token in input_tokens:
        gate_exists = token in gate_df['currency'].str.upper().values
        okx_exists = token in okx_df['currency'].str.upper().values
        
        if gate_exists and okx_exists:
            watch_manager.add_token(token, enabled=True)
            print(f"✅ {token} - Valid & Ditambahkan ke Watch List")
            valid_count += 1
        else:
            print(f"❌ {token} - Tidak ditemukan (Gate: {gate_exists}, OKX: {okx_exists})")
    
    active_tokens = watch_manager.get_active_tokens()
    
    if active_tokens:
        print(f"\n📝 Total Token Aktif: {len(active_tokens)}")
        print(f"List: {', '.join(active_tokens)}")
        print("⚠️  Bot akan check & kirim notifikasi setiap 5 menit")
        
        # Konfirmasi Loop
        confirm = input("\nMulai monitoring sekarang? (y/n): ").strip().lower()
        if confirm == 'y':
            print("✅ Monitoring dimulai... Tekan Ctrl+C untuk berhenti.")
            try:
                while True:
                    check_and_notify(finder, notifier, watch_manager)
                    time.sleep(Config.UPDATE_INTERVAL)
            except KeyboardInterrupt:
                print("\n🛑 Monitoring dihentikan, kembali ke menu.")
        else:
            print("❌ Monitoring dibatalkan")
    else:
        print("❌ Tidak ada token aktif di Watch List.")

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
        print(f"Token: {row['currency']}")
        print(f"Gate APR: {row['gate_apr']:.2f}%")
        print(f"OKX APY: {row['okx_loan_rate']:.2f}%")
        print(f"Daily Rate: {row['okx_daily_rate']:.4f}%")
        print(f"Surplus Limit: {row['okx_surplus_limit']:,.2f} {row['currency']}")
        print(f"Used/Total: {row['okx_used_quota']:,.2f} / {row['okx_total_quota']:,.2f}")
        print(f"Net APR: {row['net_apr']:.2f}%")
        print(f"Status: {row['status']}")
        print("="*80)
        
        # Simpan?
        save = input("Simpan hasil ke CSV? (y/n): ").strip().lower()
        if save == 'y':
            df.to_csv(Config.DATA_PATH, index=False)
            print(f"✅ Data tersimpan: {Config.DATA_PATH}")
    else:
        print(f"\n❌ Token {token} tidak ditemukan atau tidak memenuhi syarat")

def display_high_apr(finder):
    """Tampilkan token APR tinggi"""
    print("\n⏳ Mengambil data, tunggu sebentar...")
    df = finder.find_opportunities()
    
    if not df.empty:
        display_limit = Config.DISPLAY_LIMIT
        
        print("\n" + "="*130)
        print(f"{'No':<3} {'Crypto':<8} {'Gate APR':>10} {'OKX APY':>10} {'Daily Rate':>12} {'Surplus':>12} {'Used/Total':>20} {'Net APR':>10} {'Status'}")
        print("="*130)
        
        for idx, row in df.head(display_limit).iterrows():
            used_total = f"{row['okx_used_quota']:,.2f} / {row['okx_total_quota']:,.2f}"
            rate_display = f"{row['okx_daily_rate']:.4f}%"
            status_emoji = "✅" if row['available'] else "❌"
            
            print(f"{idx+1:<3} {row['currency']:<8} {row['gate_apr']:>9.2f}% {row['okx_loan_rate']:>9.2f}% {rate_display:>11} {row['okx_surplus_limit']:>11.2f} {used_total:>19} {row['net_apr']:>9.2f}% {status_emoji:>6}")
        
        print("="*130)
        print(f"Peluang ditemukan: {len(df)} token")
        print("="*130)
        
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

def check_and_notify(finder, notifier, watch_manager):
    """Cek token watch dan kirim notifikasi"""
    global sent_notifications
    
    # Ambil token yang aktif dari WatchManager
    active_tokens = watch_manager.get_active_tokens()
    
    if not active_tokens:
        return
    
    for token in active_tokens:
        df = finder.search_token(token)
        
        if not df.empty:
            row = df.iloc[0]
            # Key unik: token + timestamp per 5 menit agar tidak spam
            token_key = f"{token}_{int(time.time()) // 300}"
            
            if token_key not in sent_notifications:
                # Pastikan row dikonversi ke dict dengan benar untuk notifier
                notifier.notify_opportunity(row.to_dict())
                sent_notifications.add(token_key)
                print(f"📱 Notifikasi terkirim: {token}")
            
            # Cleanup memori jika set terlalu besar
            if len(sent_notifications) > 500:
                sent_notifications.clear()

def main():
    """Main loop dengan watch list manager"""
    gate_client = GateClient()
    okx_client = OKXClient()
    finder = OpportunityFinder(gate_client, okx_client)
    telegram = TelegramNotifier()
    watch_manager = WatchManager()
    
    logger.info("Opportunity Detector with Watch List Manager dimulai")
    
    while True:
        try:
            choice = display_menu()
            
            if choice == "1":
                display_high_apr(finder)
            elif choice == "2":
                search_token_interactive(finder)
            elif choice == "3":
                # Fix: Passing semua argumen yang diperlukan
                setup_watch_tokens(telegram, watch_manager, finder)
            elif choice == "4":
                # Fix: Passing watch_manager yang sudah diinisialisasi
                manage_watch_list(watch_manager)
            elif choice == "5":
                update_interval()
            elif choice == "6":
                print("\n👋 Bot dihentikan")
                break
            else:
                print("\n❌ Pilihan tidak valid")
            
        except KeyboardInterrupt:
            logger.info("Bot dihentikan")
            break
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            print("\n❌ Terjadi error, lihat log untuk detail")
            time.sleep(2)

if __name__ == "__main__":
    main()