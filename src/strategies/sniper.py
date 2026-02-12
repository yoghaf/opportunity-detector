import time
import threading
from datetime import datetime
from src.utils.logger import setup_logger
import subprocess
import sys
import os

logger = setup_logger(__name__)

from typing import Optional

class SniperBot:
    def __init__(self, okx_client):
        self.okx_client = okx_client
        self.running = False
        self.target_currency: Optional[str] = None
        self.max_ltv = 70.0  # Default safe LTV %
        self.max_amount = 0.0  # Max amount to borrow
        self.thread: Optional[threading.Thread] = None
        self.browser_process: Optional[subprocess.Popen] = None
        self.status_msg = "Idle"
        self.last_ltv = 0.0
        self.borrow_history = []
        self.mode = 'Unknown' # '1' = Simple, '2' = Single Ccy Margin, etc.
        self.use_browser = False
        self.sniper_mode = False

    def start(self, currency, max_ltv, max_amount, use_browser=False, sniper_mode=False):
        if self.running:
            logger.warning("Sniper already running!")
            return False
            
        # Check connection first
        is_connected, msg = self.okx_client.check_connection()
        if not is_connected:
            logger.error(f"Cannot start Sniper: OKX Connection Failed ({msg})")
            self.status_msg = f"⚠️ Connection Failed: {msg}"
            return False
        
        self.target_currency = str(currency).upper()
        self.max_ltv = float(max_ltv)
        self.max_amount = float(max_amount)

        self.use_browser = bool(use_browser)
        self.sniper_mode = bool(sniper_mode)
        self.running = True
        
        mode_str = " (Browser)" if self.use_browser else " (API)"
        if self.sniper_mode:
            mode_str += " [SNIPER MODE 🔫]"
        self.status_msg = f"🔫 Sniping {self.target_currency} (Max LTV: {self.max_ltv}%){mode_str}"
        
        # Detect Mode
        config = self.okx_client.get_account_config()
        if config:
            self.mode = config.get('acctLv', 'Unknown')
            logger.info(f"Sniper detected Account Mode: {self.mode}")
        
        self.thread = threading.Thread(target=self._run_loop)
        self.thread.daemon = True
        self.thread.start()
        logger.info(f"Sniper started for {self.target_currency}")
        return True

    def stop(self):
        self.running = False
        self.status_msg = "Stopping..."
        
        # Kill browser process if active
        if hasattr(self, 'browser_process') and self.browser_process:
            try:
                self.browser_process.terminate()
                self.browser_process.wait(timeout=5)
                logger.info("Browser process terminated.")
            except Exception as e:
                logger.error(f"Error killing browser process: {e}")
            self.browser_process = None

        if self.thread:
            self.thread.join(timeout=2)
        
        self.status_msg = "Stopped"
        logger.info("Sniper stopped")

    def _get_current_ltv(self):
        try:
            risk = self.okx_client.get_account_risk()
            if risk:
                # OKX returns mgnRatio (Margin Ratio) = Equity / Maint Margin
                # This is NOT LTV.
                # Let's try to get simple LTV from balance if available
                # If not, we can estimate risk by mgnRatio.
                # Safe mgnRatio > 300% usually. 
                # Liquidation at mgnRatio = 100%.
                
                # Let's use totalEq and totalLiab if available
                details = risk.get('details', []) # ?
                
                # Fallback to simple balance check if possible
                balance = self.okx_client.get_account_balance_details()
                if balance:
                    total_eq = float(balance.get('totalEq', 0)) # USD value
                    # OKX doesn't give totalLiab directly in some modes.
                    # We might need to trust the user or Implement strict mgnRatio check.
                    
                    mgn_ratio = float(balance.get('mgnRatio', 0) or 0)
                    if mgn_ratio == 0:
                        return 0.0 # No risk? or Error?
                        
                    # MgnRatio 1000% = Very Safe
                    # MgnRatio 100% = Dead
                    # We can map User's "Max LTV" to MgnRatio?
                    # LTV 70% ~= MgnRatio 143% (1/0.7)
                    # LTV 50% ~= MgnRatio 200% (1/0.5)
                    
                    return mgn_ratio
            return 0.0
        except Exception as e:
            logger.error(f"Error checking LTV: {e}")
            return 0.0

    def _run_loop(self):
        while self.running:
            if not self.target_currency:
                logger.error("Target currency not set. Stopping sniper.")
                self.running = False
                break
                
            try:
                # --- 1. HANDLE BROWSER SNIPER MODE (LOOP IN BROWSER) ---
                if self.use_browser and self.sniper_mode:
                    logger.info(f"🔫 Launching Browser Sniper Mode for {self.target_currency} (Target LTV: {self.max_ltv}%)")
                    
                    cmd = [
                        sys.executable, "-m", "src.exchanges.okx_browser", "borrow",
                        str(self.target_currency), "MAX", 
                        "--sniper", 
                        "--target-ltv", str(self.max_ltv)
                    ]
                    

                    try:
                        # Use Popen to stream output
                        # bufsize=1 means line buffered
                        env = os.environ.copy()
                        env["PYTHONIOENCODING"] = "utf-8"
                        
                        self.browser_process = subprocess.Popen(
                            cmd, 
                            stdout=subprocess.PIPE, 
                            stderr=subprocess.STDOUT, 
                            text=True,
                            bufsize=1,
                            encoding='utf-8', # Force utf-8 for emojis
                            env=env
                        )
                        
                        # Read logs in real-time
                        while self.running and self.browser_process and self.browser_process.poll() is None:
                            line = self.browser_process.stdout.readline()
                            if line:
                                clean_line = line.strip()
                                if clean_line:
                                    logger.info(f"[BROWSER] {clean_line}")
                                    self.borrow_history.append(f"{datetime.now().strftime('%H:%M:%S')} - {clean_line}")
                                    # Update status for UI
                                    if "Step" in clean_line or "LTV" in clean_line:
                                         self.status_msg = f"🔫 {clean_line}"
                            time.sleep(0.1)
                        
                        # Process finished
                        return_code = -1
                        if self.browser_process:
                            return_code = self.browser_process.poll()
                            
                        if return_code == 0:
                            msg = f"✅ Browser Sniper Finished Success for {self.target_currency}!"
                            logger.info(msg)
                            self.borrow_history.append(f"{datetime.now().strftime('%H:%M:%S')} - {msg}")
                            time.sleep(30)
                        else:
                             # Should have been captured in loop, but verify
                             logger.warning(f"⚠️ Browser Sniper exited with code {return_code}")
                             time.sleep(10)

                    except Exception as e:
                        logger.error(f"❌ Failed to launch/monitor browser sniper: {e}")
                        time.sleep(10)
                    finally:
                        self.browser_process = None
                        
                    continue # Bypass Python logic

                # --- 2. BROWSER SANTAI: ONE-SHOT (No Python LTV calc) ---
                if self.use_browser and not self.sniper_mode:
                    logger.info(f"🖥️ Santai One-Shot for {self.target_currency} (Target LTV: {self.max_ltv}%)")
                    self.status_msg = f"🖥️ Santai: borrowing {self.target_currency} to LTV {self.max_ltv}%..."
                    
                    cmd = [
                        sys.executable, "-m", "src.exchanges.okx_browser", "borrow",
                        str(self.target_currency), "MAX",
                        "--target-ltv", str(self.max_ltv)
                    ]
                    
                    try:
                        env = os.environ.copy()
                        env["PYTHONIOENCODING"] = "utf-8"
                        
                        result = subprocess.run(
                            cmd, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=180, env=env
                        )
                        
                        # Log all output
                        for line in (result.stdout or '').strip().splitlines():
                            if line.strip():
                                logger.info(f"[BROWSER] {line}")
                                self.borrow_history.append(f"{datetime.now().strftime('%H:%M:%S')} - {line.strip()}")
                        for line in (result.stderr or '').strip().splitlines():
                            if line.strip():
                                logger.warning(f"[BROWSER ERR] {line}")
                        
                        if result.returncode == 0:
                            self.status_msg = f"✅ Santai Done: {self.target_currency}"
                            self.borrow_history.append(f"{datetime.now().strftime('%H:%M:%S')} - ✅ Santai completed successfully")
                        else:
                            self.status_msg = f"⚠️ Browser Failed (exit {result.returncode})"
                            
                    except subprocess.TimeoutExpired:
                        logger.error("❌ Browser Timeout (180s)!")
                        self.status_msg = "⚠️ Browser Timeout"
                    except Exception as e:
                        logger.error(f"❌ Santai error: {e}")
                        self.status_msg = f"⚠️ Error: {e}"
                    
                    # ONE-SHOT: stop immediately after single execution
                    self.running = False
                    logger.info("🛑 Santai One-Shot complete. Stopping bot.")
                    break
                
                # --- 3. API MODE (use_browser=False) ---
                # Simple API borrow loop — kept for non-browser usage
                flex_loans = self.okx_client.get_flexible_loans()
                total_collateral_usd = 0.0
                total_loan_usd = 0.0
                
                if flex_loans:
                    for l in flex_loans:
                        total_collateral_usd += float(l.get('eq', 0))
                        total_loan_usd += float(l.get('liab_usd', 0))

                current_ltv = (total_loan_usd / total_collateral_usd * 100) if total_collateral_usd > 0 else 0.0
                logger.info(f"API LTV Check: {current_ltv:.2f}% | Target {self.max_ltv:.2f}%")

                if current_ltv >= self.max_ltv:
                    self.status_msg = f"✅ LTV at target ({current_ltv:.1f}%)"
                elif total_collateral_usd == 0:
                    self.status_msg = "⚠️ No Collateral Found"
                else:
                    max_available = self.okx_client.get_flexible_max_loan(self.target_currency)
                    if max_available > 0:
                        price = 1.0 if self.target_currency in ['USDT', 'USDC', 'FDUSD'] else self.okx_client.get_ticker_price(self.target_currency)
                        if price > 0:
                            target_loan_usd = total_collateral_usd * (self.max_ltv / 100.0)
                            room_usd = target_loan_usd - total_loan_usd
                            actual_borrow = min((room_usd * 0.98) / price, max_available)
                            
                            if actual_borrow > 0:
                                result = self.okx_client.borrow_flexible(
                                    currency=self.target_currency, amount=actual_borrow
                                )
                                if result:
                                    msg = f"✅ API Borrowed {actual_borrow:.4f} {self.target_currency}"
                                    logger.info(msg)
                                    self.status_msg = msg
                                    self.borrow_history.append(f"{datetime.now().strftime('%H:%M:%S')} - {msg}")
                                else:
                                    self.status_msg = "⚠️ API Borrow failed"
                    else:
                        logger.info(f"⏳ No {self.target_currency} available. Waiting...")

                time.sleep(5)
                
            except Exception as e:
                logger.error(f"Sniper loop error: {e}")
                time.sleep(5)