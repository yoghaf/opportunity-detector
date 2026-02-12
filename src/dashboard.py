import streamlit as st
import pandas as pd
import time
import sys
import os
import subprocess

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Config
from src.exchanges.gate_client import GateClient
from src.exchanges.okx_client import OKXClient
from src.exchanges.binance_client import BinanceClient
from src.strategies.opportunity_finder import OpportunityFinder

# Page config
st.set_page_config(
    page_title="Crypto Opportunity Dashboard",
    page_icon="💸",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize clients (cached)
@st.cache_resource
def init_clients():
    gate = GateClient()
    okx = OKXClient()
    binance = BinanceClient()
    finder = OpportunityFinder(gate, okx, binance)
    return finder, okx

# Initialize Sniper (Global/Session State)
if 'sniper' not in st.session_state:
    from src.strategies.sniper import SniperBot
    # We need okx client for sniper
    _, okx_client = init_clients()
    st.session_state.sniper = SniperBot(okx_client)

# Fetch fresh data from APIs
@st.cache_data(ttl=60)  # Cache for 60 seconds
def fetch_live_data(_finder):
    """Fetch real-time data from all exchanges"""
    try:
        df = _finder.find_opportunities()
        return df, time.time()
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return pd.DataFrame(), time.time()

# Title
st.title("💸 Crypto Opportunity Dashboard")
st.caption("🔄 Real-time data • Auto-refresh every 60 seconds")

# Initialize
finder, okx = init_clients()
sniper = st.session_state.sniper

# Sidebar
with st.sidebar:
    st.header("⚙️ Settings")
    
    if st.button("🔄 Force Refresh Now"):
        st.cache_data.clear()
        st.rerun()
    
    st.markdown("---")
    st.markdown("### 🏦 Loan Source Filter")
    loan_source = st.radio(
        "Show opportunities from:",
        ["📊 All (Best Rate)", "🆗 OKX Only", "🅱️ Binance Only"],
        index=0
    )
    
    st.markdown("---")
    st.markdown("### 📊 APR Filter")
    min_apr = st.slider("Min Net APR (%)", -100, 500, 0)
    
    # Sniper Status in Sidebar
    if sniper.running:
        st.markdown("---")
        st.info(f"🔫 Sniper Running:\n\nTarget: **{st.session_state.get('sniper_target', 'Unknown')}**\n\nStatus: {sniper.status_msg}")

# Fetch live data
with st.spinner("📡 Fetching live data..."):
    df, fetch_time = fetch_live_data(finder)
    
fetch_time_str = time.strftime('%H:%M:%S', time.localtime(fetch_time))
st.caption(f"Last updated: **{fetch_time_str}**")

# TABS LAYOUT
tab1, tab2, tab3, tab4 = st.tabs(["📊 Opportunities", "🔫 OKX Sniper Bot", "💼 My Loans", "🌐 Browser Actions"])

# TAB 1: OPPORTUNITIES
with tab1:
    if not df.empty:
        filtered_df = df.copy()
        
        # Apply loan source filter
        if "OKX Only" in loan_source:
            filtered_df = filtered_df[filtered_df['okx_loan_rate'] > 0].copy()
            filtered_df['net_apr'] = filtered_df['gate_apr'] - filtered_df['okx_loan_rate']
            filtered_df['best_loan_source'] = 'OKX'
            source_label = "🆗 OKX Only"
        elif "Binance Only" in loan_source:
            filtered_df = filtered_df[filtered_df['binance_loan_rate'] > 0].copy()
            filtered_df['net_apr'] = filtered_df['gate_apr'] - filtered_df['binance_loan_rate']
            filtered_df['best_loan_source'] = 'Binance'
            source_label = "🅱️ Binance Only"
        else:
            source_label = "📊 All"
        
        # Apply min APR filter
        filtered_df = filtered_df[filtered_df['net_apr'] >= min_apr].copy()
        filtered_df = filtered_df.sort_values('net_apr', ascending=False).reset_index(drop=True)
        
        # KPIs
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Total Opportunities", len(filtered_df))
        with col2:
            st.metric("Top APR", f"{filtered_df['net_apr'].max():.1f}%" if not filtered_df.empty else "0%")
        with col3:
            st.metric("Avg APR", f"{filtered_df['net_apr'].mean():.1f}%" if not filtered_df.empty else "0%")
            
        st.markdown(f"### {source_label}")
        
        # Prepare display - DYNAMIC columns based on filter
        display_df = filtered_df.copy()
        
        if "OKX Only" in loan_source:
            cols = ['currency', 'gate_apr', 'okx_loan_rate', 'net_apr', 'okx_avail_loan']
            col_names = {'currency': 'Symbol', 'gate_apr': 'Gate Earn %', 'okx_loan_rate': 'Loan Rate %', 'net_apr': 'Net APR %', 'okx_avail_loan': 'Max Loan'}
            col_config = {
                "Gate Earn %": st.column_config.NumberColumn(format="%.2f"),
                "Loan Rate %": st.column_config.NumberColumn(format="%.2f"),
                "Net APR %": st.column_config.NumberColumn(format="%.2f"),
                "Max Loan": st.column_config.NumberColumn(format="%.0f"),
            }
        elif "Binance Only" in loan_source:
            cols = ['currency', 'gate_apr', 'binance_loan_rate', 'net_apr']
            col_names = {'currency': 'Symbol', 'gate_apr': 'Gate Earn %', 'binance_loan_rate': 'Loan Rate %', 'net_apr': 'Net APR %'}
            col_config = {
                "Gate Earn %": st.column_config.NumberColumn(format="%.2f"),
                "Loan Rate %": st.column_config.NumberColumn(format="%.2f"),
                "Net APR %": st.column_config.NumberColumn(format="%.2f"),
            }
        else:
            cols = ['currency', 'gate_apr', 'okx_loan_rate', 'binance_loan_rate', 'net_apr', 'best_loan_source', 'okx_avail_loan']
            col_names = {'currency': 'Symbol', 'gate_apr': 'Gate Earn %', 'okx_loan_rate': 'OKX Loan %', 'binance_loan_rate': 'Bin Loan %', 'net_apr': 'Net APR %', 'best_loan_source': 'Best Source', 'okx_avail_loan': 'Max Loan'}
            col_config = {
                "Gate Earn %": st.column_config.NumberColumn(format="%.2f"),
                "OKX Loan %": st.column_config.NumberColumn(format="%.2f"),
                "Bin Loan %": st.column_config.NumberColumn(format="%.2f"),
                "Net APR %": st.column_config.NumberColumn(format="%.2f"),
                "Max Loan": st.column_config.NumberColumn(format="%.0f"),
            }
        
        cols = [c for c in cols if c in display_df.columns]
        display_df = display_df[cols].rename(columns=col_names)
        
        st.dataframe(display_df, width='stretch', hide_index=False, height=600, column_config=col_config)
    else:
        st.warning("⚠️ No data available.")

# TAB 2: SNIPER BOT
with tab2:
    st.header("🔫 OKX Sniper Bot")
    st.markdown("Automate borrowing from OKX when inventory becomes available.")
    
    col_input, col_status = st.columns([1, 1])
    
    with col_input:
        # Check Browser Session Status
        import os
        from datetime import datetime
        session_file = 'okx_session.json'
        is_logged_in = os.path.exists(session_file)
        
        if is_logged_in:
             mod_time = os.path.getmtime(session_file)
             last_login = datetime.fromtimestamp(mod_time).strftime('%Y-%m-%d %H:%M')
             st.success(f"✅ Browser Session Active (Login: {last_login})")
        else:
             st.error("❌ No Browser Session Found! Please Login first.")
             
        # Token Selection (Dropdown)
        available_tokens = sorted(df['currency'].unique().tolist()) if not df.empty else []
        default_idx = available_tokens.index('ANIME') if 'ANIME' in available_tokens else 0
        
        target_token = st.selectbox("Target Token", options=available_tokens, index=default_idx)
        st.session_state['sniper_target'] = target_token
        
        max_amount = st.number_input(
            "Max Borrow Cap (Optional)", 
            min_value=0.0, 
            value=0.0, 
            step=10.0,
            help="Set to 0 for unlimited. The bot will stop borrowing only when the Max LTV is reached."
        )
        max_ltv = st.number_input("Max Safe Account LTV (%)", min_value=1.0, max_value=99.0, value=70.0, step=5.0)
        
        
        # New Option: Browser Automation & Sniper Mode
        use_browser = st.checkbox(
            "Use Browser Automation (Flexible Loan)", 
            value=False,
            help="If checked, uses the saved Chrome session to borrow via UI instead of API. Required if API is restricted."
        )
        
        sniper_mode = st.checkbox(
            "🔫 Sniper Mode (Wait for Stock)", 
            value=False, 
            help="Enable if stock is empty. Will loop refresh every 3-5s for 30 mins."
        )
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("▶️ START SNIPER", type="primary", use_container_width=True):
                if not sniper.running:
                    success = sniper.start(target_token, max_ltv, max_amount, use_browser=use_browser, sniper_mode=sniper_mode)
                    if success:
                        st.success(f"Started sniping {target_token}!")
                        st.rerun()
                    else:
                        st.error(f"Failed to start: {sniper.status_msg}")
                else:
                    st.warning("Sniper is already running!")
        
        with col_btn2:
            if st.button("⏹️ STOP SNIPER", type="secondary", use_container_width=True):
                if sniper.running:
                    sniper.stop()
                    st.info("Sniper stopped.")
                    st.rerun()
    
    with col_status:
        st.markdown("### Status")
        if sniper.running:
            st.success("🟢 RUNNING")
            st.code(sniper.status_msg)
            st.markdown("Logs:")
            for log in sniper.borrow_history[-5:]:
                st.text(log)
        else:
            st.info("⚪ IDLE")
            st.write("Ready to start.")

# TAB 3: MY LOANS
with tab3:
    st.header("💼 My Current Loans (OKX)")
    
    if st.button("🔄 Refresh My Loans"):
        st.rerun()
        
    try:
        # 1. Get AccountConfig
        config = okx.get_account_config()
        acct_lv = config.get('acctLv', 'Unknown') if config else 'Unknown'
        mode_map = {'1': 'Simple', '2': 'Single Currency Margin', '3': 'Multi-currency Margin', '4': 'Portfolio Margin'}
        mode_name = mode_map.get(acct_lv, f"Unknown ({acct_lv})")
        
        st.info(f"ℹ️ Account Mode: **{mode_name}**")
        
        if acct_lv == '1':
            st.warning("⚠️ You are in **Simple Mode**. The 'Sniper Bot' (Auto-Borrow) requires **Single Currency Margin** or higher to function for Margin Loans.")
        
        # 2. Fetch Loans
        all_loans = []
        
        # Margin Loans
        balance_data = okx.get_account_balance_details()
        if balance_data and 'loans' in balance_data:
            for l in balance_data['loans']:
                l['type'] = 'Margin Loan'
                all_loans.append(l)
                
        # Flexible Loans
        flex_loans = okx.get_flexible_loans()
        if flex_loans:
            all_loans.extend(flex_loans)
            
        if all_loans:
            loans_df = pd.DataFrame(all_loans)
            st.metric("Total Active Loans", len(all_loans))
            
            st.dataframe(
                loans_df,
                column_config={
                    "currency": "Token",
                    "type": "Loan Type",
                    "amount": st.column_config.NumberColumn("Borrowed Amount", format="%.8f"),
                    "liab_usd": st.column_config.NumberColumn("Liability (USD)", format="$%.2f"),
                    "eq": "Collateral (Approx)"
                },
                width='stretch'
            )
        else:
            st.info("✅ No active loans found.")

    except Exception as e:
        st.error(f"Error fetching loans: {e}")

# TAB 4: BROWSER AUTOMATION (NEW)
with tab4:
    st.header("🌐 OKX Browser Automation (Playwright)")
    st.markdown("""
    Use a real browser to manipulate OKX account securely.
    - **Login**: Opens visible browser to scan QR Code.
    - **Borrow**: Runs headless browser to execute Flexible Loan.
    """)
    
    col_login, col_borrow = st.columns([1, 1])
    
    with col_login:
        st.subheader("1. Login / Capture Session")
        st.info("Required first! Session saved to `okx_session.json`.")
        if st.button("📱 Launch QR Login (Visible Browser)", use_container_width=True):
            try:
                # Run as subprocess to avoid blocking Streamlit
                # Use cmd /k on Windows to keep window open if it crashes immediately
                if sys.platform == "win32":
                    cmd_str = f'start cmd /k "{sys.executable} -m src.exchanges.okx_browser login"'
                    subprocess.Popen(cmd_str, shell=True)
                else:
                    cmd = [sys.executable, "-m", "src.exchanges.okx_browser", "login"]
                    subprocess.Popen(cmd)
                    
                st.success("Browser launched! Check the new window and scan QR.")
            except Exception as e:
                st.error(f"Failed to launch: {e}")

        st.divider()
        st.caption("Option 2: Bypass Verification")
        if st.button("💻 Login via System Chrome (Main Profile)", use_container_width=True):
            st.warning("⚠️ CRITICAL: CLOSE ALL CHROME WINDOWS FIRST!")
            try:
                # Run with --use-system-chrome
                if sys.platform == "win32":
                    cmd_str = f'start cmd /k "{sys.executable} -m src.exchanges.okx_browser login --use-system-chrome"'
                    subprocess.Popen(cmd_str, shell=True)
                else:
                    cmd = [sys.executable, "-m", "src.exchanges.okx_browser", "login", "--use-system-chrome"]
                    subprocess.Popen(cmd)
                st.success("Launching System Chrome... If it fails, close Chrome and try again.")
            except Exception as e:
                st.error(f"Failed: {e}")
                
    with col_borrow:
        st.subheader("2. Manual Borrow Execution")
        st.warning("Runs in background (Headless). Check Telegram for results.")
        
        b_token = st.selectbox("Borrow Token", options=["ETH", "BTC", "USDT", "USDC"], index=0)
        b_amount = st.text_input("Amount (or 'max')", value="0.001")
        
        if st.button("💸 Execute Borrow Now", type="primary", use_container_width=True):
            if not b_amount:
                st.error("Please enter amount")
            else:
                try:
                    cmd = [sys.executable, "-m", "src.exchanges.okx_browser", "borrow", b_token, b_amount]
                    if sys.platform == "win32":
                         subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
                    else:
                         subprocess.Popen(cmd)
                    
                    st.success(f"Execution started for {b_amount} {b_token}...")
                    st.toast("Borrow process running in background")
                except Exception as e:
                    st.error(f"Failed to execute: {e}")
    
    st.markdown("---")
    st.subheader("📝 Live Logs (Real-time)")
    
    # Auto-refresh checkbox (runs locally in this script execution context)
    auto_refresh_logs = st.checkbox("🔄 Auto-refresh Logs (Every 2s)", value=True)
    
    log_container = st.empty()
    
    def get_browser_logs():
        log_path = 'logs/bot.log'
        if not os.path.exists(log_path):
            return "No log file found."
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                # Filter for okx_browser logs or specific keywords
                filtered = [line for line in lines if 'okx_browser' in line or 'Sniper' in line]
                return "".join(filtered[-50:]) # Last 50 lines
        except Exception as e:
            return f"Error reading logs: {e}"

    # Display logs
    logs = get_browser_logs()
    log_container.code(logs, language='text')
    
    # Show screenshot if exists (result of last borrow)
    st.markdown("#### Latest Screenshot")
    if os.path.exists("borrow_result.png"):
        st.image("borrow_result.png", caption="Last Borrow Result", use_column_width=True)
    elif os.path.exists("borrow_error_exception.png"):
        st.image("borrow_error_exception.png", caption="Last Error Screenshot", use_column_width=True)
    elif os.path.exists("screenshots/borrow_success.png"): # Check new folder structure
        st.image("screenshots/borrow_success.png", caption="Last Success", use_column_width=True)
        
    if auto_refresh_logs:
        import time
        time.sleep(2)
        st.rerun()



# Auto-refresh every 60 seconds
time.sleep(60)
st.rerun()
