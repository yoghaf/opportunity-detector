import asyncio
import argparse
import sys

# Windows Unicode fix for stdout
if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

import os
import random
import time
import re
import traceback
from typing import Optional, Tuple, List, Union
from playwright.async_api import async_playwright, Page, ElementHandle, TimeoutError as PlaywrightTimeoutError, expect
from datetime import datetime

# Add root to path
sys.path.append(os.path.join(os.getcwd()))

from config.settings import Config
from src.utils.logger import setup_logger
from src.utils.telegram_notifier import TelegramNotifier
from src.utils.human_behavior import human_delay, human_type, human_click, human_mouse_move
from src.exchanges.token_data import TokenConfig

logger = setup_logger('okx_browser')
notifier = TelegramNotifier()

SESSION_FILE = 'okx_session.json'
PROFILE_DIR = os.path.join(os.getcwd(), 'okx_profile')

# --- DATA STRUCTURES ---

class Selectors:
    # Prioritaskan CSS Classes OKX (.okui-...)
    BORROW_MORE_BTN = [
        '.okui-btn-secondary:has-text("Pinjam lebih banyak")',
        'button:has-text("Pinjam lebih banyak")',
        '[data-testid="borrow-more-btn"]',
        '.okui-btn:has-text("Borrow more")',
        'button:has-text("Borrow more")'
    ]
    # Fallback jika tombol spesifik tidak ketemu, cari tombol "Pinjam" umum di baris
    BORROW_BTN_GENERIC = [
        '.okui-btn-secondary:has-text("Pinjam")',
        'button:has-text("Pinjam")',
        '.okui-btn-secondary:has-text("Borrow")',
         'button:has-text("Borrow")'
    ]
    
    DROPDOWN = [
        '[data-testid="token-selector"]',
        '.okui-select-trigger', # Most common trigger
        '.okui-input-box-append .okui-select-trigger', # Inside input group
        '.okui-input-box-append', # Click the append area itself
        '.okui-select-value', # Click the value text
        'div[class*="select-trigger"]', # Generic fallback
        '.okui-dialog-content span:has-text("USDC")', # Click default currency text
        '.okui-dialog-content span:has-text("USDT")',
        '.okui-dialog-content .okui-icon-arrow-down', # Click arrow icon
        '[role="combobox"]', # Generic combobox role
    ]
    
    SEARCH_INPUT = [
        '.okui-select-dropdown-search-input',  # Container
        '.okui-select-dropdown-search-input input',  # Input inside
        '.okui-select-dropdown input[type="text"]',
        '.okui-select-dropdown input',
        '.okui-dropdown-menu input',
        'input[placeholder="Cari"]',
        'input[placeholder*="Cari"]',
        'input[placeholder="Search"]',
        'input[placeholder*="Search"]',
        '.okui-dialog-content input[type="text"]',
        '.okui-dialog input',
        'input[type="text"]',  # Fallback
    ]
    
    TOKEN_ITEM = [
        '.okui-select-item',  # Generic item
        '[data-testid="token-item"]',  # Specific testid
        '.okui-dropdown-menu-item',  # Alternative class
    ]
    
    MAX_BTN = [
        '.okui-input-box-append .okui-btn', # Class spesifik tombol di dalam input box
        'button:has-text("Maks")', 
        'button:has-text("Max")',
        '[data-testid="max-btn"]'
    ]
    
    # Tombol Review biasanya Primary (Hitam/Solid)
    REVIEW_BTN = [
        'button.okui-btn-primary:has-text("Tinjau loan")',
        'button:has-text("Tinjau loan")', 
        'button:has-text("Review")',
        '[data-testid="review-btn"]'
    ]
    
    CONFIRM_BTN = [
        'button.okui-btn-primary:has-text("Konfirmasi")',
        'button:has-text("Konfirmasi")', 
        'button:has-text("Confirm")',
        '[data-testid="confirm-btn"]'
    ]
    
    CHECKBOX = [
        'input[type="checkbox"]', 
        '.okui-checkbox-input', 
        '[data-testid="agreement-checkbox"]'
    ]
    
    AMOUNT_INPUT = [
        'input[placeholder*="Masukkan jumlah"]',
        'input[placeholder*="Enter amount"]',
        '.okui-input-input' # Class generic input OKX
    ]
    
    MODAL_CONTENT = '.okui-dialog-content' # Class modal dialog OKX

# --- UTILS ---

async def apply_stealth(page: Page):
    """Applies stealth scripts and basic randomization."""
    # Patch Webdriver
    await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
    """)
    # Patch Languages (Consistent with User Agent)
    await page.add_init_script("""
        Object.defineProperty(navigator, 'languages', {
            get: () => ['id-ID', 'id', 'en-US', 'en']
        });
    """)
    # Patch Plugins
    await page.add_init_script("""
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
    """)

async def find_element(page: Page, selectors: List[str], timeout: int = 3000) -> Optional[ElementHandle]:
    """Tries to find an element using a list of potential selectors."""
    for selector in selectors:
        try:
            # Use specific timeout for check
            el = page.locator(selector).first
            if await el.count() > 0 and await el.is_visible(timeout=timeout):
                return el
        except:
            continue
    return None

async def take_screenshot(page: Page, name: str):
    """Saves screenshot to screenshots folder with timestamp."""
    if not os.path.exists("screenshots"):
        os.makedirs("screenshots")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"screenshots/{name}_{timestamp}.png"
    try:
        await page.screenshot(path=filename)
        logger.info(f"📸 Screenshot saved: {filename}")
    except Exception as e:
        logger.error(f"Failed to take screenshot: {e}")

def parse_ltv_text(text: str) -> Tuple[float, str]:
    """Parses LTV value and status from text."""
    match = re.search(r'(\d+[,.]?\d*)%\s*([A-Za-z]+)', text)
    if match:
        val = float(match.group(1).replace(',', '.'))
        status = match.group(2)
        return val, status
    
    match_simple = re.search(r'(\d+[,.]?\d*)%', text)
    if match_simple:
        val = float(match_simple.group(1).replace(',', '.'))
        return val, "Unknown"
        
    return 0.0, "Unknown"

def parse_stock_text(text: str) -> Tuple[float, float]:
    """Parses available stock from text. Handles multiple formats."""
    if not text:
        return 0.0, 0.0
    
    # Try format: "123.45 / 1,000.00" or "123,45 / 1.000,00"
    match = re.search(r'([\d,.]+)\s*/\s*([\d,.]+)', text)
    if match:
        raw_avail = match.group(1).strip()
        raw_limit = match.group(2).strip()
        avail = _parse_number(raw_avail)
        limit = _parse_number(raw_limit)
        return avail, limit
    
    # Try standalone number after "meminjam"
    match2 = re.search(r'meminjam\s*:?\s*([\d,.]+)', text, re.IGNORECASE)
    if match2:
        return _parse_number(match2.group(1)), 0.0

    # Try any number in the text
    nums = re.findall(r'[\d,.]+', text)
    if nums:
        return _parse_number(nums[0]), (_parse_number(nums[1]) if len(nums) > 1 else 0.0)
    
    return 0.0, 0.0


def _parse_number(s: str) -> float:
    """Parse a number string that may use . or , as decimal/thousands separator."""
    s = s.strip()
    if not s:
        return 0.0
    # If both . and , exist, the last one is the decimal separator
    if ',' in s and '.' in s:
        if s.rfind(',') > s.rfind('.'):
            # Comma is decimal: 1.000,50
            s = s.replace('.', '').replace(',', '.')
        else:
            # Dot is decimal: 1,000.50
            s = s.replace(',', '')
    elif ',' in s:
        # Could be decimal (0,50) or thousands (1,000)
        parts = s.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(',', '.')  # decimal
        else:
            s = s.replace(',', '')  # thousands
    try:
        return float(s)
    except ValueError:
        return 0.0

# --- MAIN FUNCTIONS ---

BROWSER_ARGS = [
    '--disable-blink-features=AutomationControlled',
    '--no-sandbox',
    '--disable-infobars',
    '--mute-audio',
]
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"


async def get_persistent_context(playwright, headless: bool = True):
    """Creates a persistent browser context that reuses the same profile directory."""
    os.makedirs(PROFILE_DIR, exist_ok=True)
    
    vp_width = 1280 + random.randint(0, 80)
    vp_height = 720 + random.randint(0, 80)
    
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=PROFILE_DIR,
        headless=headless,
        args=BROWSER_ARGS,
        viewport={'width': vp_width, 'height': vp_height},
        user_agent=DEFAULT_UA,
        locale='id-ID',
        timezone_id='Asia/Jakarta',
    )
    
    page = context.pages[0] if context.pages else await context.new_page()
    await apply_stealth(page)
    return context, page


async def check_session_health(page: Page) -> bool:
    """Returns True if session is valid (user is logged in on loan page)."""
    try:
        await page.goto("https://www.okx.com/id/loan/multi", timeout=45000)
        await page.wait_for_load_state("domcontentloaded")
    except:
        try:
            await page.reload(timeout=30000)
        except:
            return False

    # Check redirect to login
    if "/login" in page.url:
        logger.warning("   Session redirected to login page.")
        return False
    
    # Check for login button presence (means NOT logged in)
    try:
        login_btn = page.locator('a[href*="/login"], button:has-text("Masuk"), button:has-text("Log in")').first
        if await login_btn.is_visible(timeout=3000):
            logger.warning("   Login button visible — session expired.")
            return False
    except:
        pass
    
    # Positive check: look for private data elements
    try:
        await expect(
            page.locator("text=/Batas pinjaman|Borrow limit|Pinjam lebih banyak|Borrow more/").first
        ).to_be_visible(timeout=10000)
        return True
    except:
        logger.warning("   Private loan elements not found.")
        return False


async def login_mode():
    """Login Mode with Persistent Context."""
    logger.info("🚀 Starting OKX Browser Login Mode (Persistent Profile)...")
    print("\n=== OKX BROWSER LOGIN (PERSISTENT) ===")
    print("1. Browser akan terbuka")
    print("2. Silakan SCAN QR CODE dari Aplikasi OKX di HP Anda")
    print("3. Tunggu sampai login berhasil dan halaman redirect ke Dashboard")
    
    async with async_playwright() as p:
        context, page = await get_persistent_context(p, headless=False)
        
        try:
            # Check if already logged in
            logger.info("   Checking existing session...")
            is_healthy = await check_session_health(page)
            
            if is_healthy:
                logger.info("   ✅ Already logged in! Session is active.")
                print("✅ Session masih aktif, tidak perlu login ulang.")
                # Backup storage state
                await context.storage_state(path=SESSION_FILE)
                return
            
            # Not logged in — navigate to login page
            logger.info("   Session expired or first run. Opening login page...")
            await page.goto("https://www.okx.com/account/login", timeout=60000)
            
            logger.info("   👉 Please login manually (Scan QR or Enter Creds).")
            logger.info("   Waiting up to 5 minutes for login...")
            
            start_time = time.time()
            logged_in = False
            
            while time.time() - start_time < 300:
                url = page.url
                if "/dashboard" in url or "/assets" in url or "/account" in url:
                    if "/login" not in url:
                        logged_in = True
                        break
                
                try:
                    if await page.get_by_text("Aset saya", exact=False).is_visible() or \
                       await page.get_by_text("My assets", exact=False).is_visible():
                        logged_in = True
                        break
                except:
                    pass
                
                await asyncio.sleep(1)
            
            if logged_in:
                logger.info("   ✅ Login Detected!")
                await context.storage_state(path=SESSION_FILE)
                logger.info(f"   💾 Backup session saved to {SESSION_FILE}")
                print(f"✅ Login berhasil! Profile tersimpan di {PROFILE_DIR}")
                await human_delay(2000, 3000)
            else:
                logger.warning("   ⚠️ Login timeout (5 min).")
                print("❌ Login timeout.")
                
        except Exception as e:
            logger.error(f"Login error: {e}")
        finally:
            await context.close()


async def browser_borrow_santai(page: Page, currency: str, amount: str, target_ltv: float = 70.0) -> bool:
    """One-Shot Borrow flow — reads LTV from UI, borrows to target, stops."""
    logger.info(f"🚀 Borrow Mode SANTAI: {currency} (Target LTV: {target_ltv}%)")
    
    await human_delay(2000, 3000)

    # === STEP 0: Read current LTV from UI ===
    logger.info("Step 0: Reading current LTV from page...")
    body_text = await page.locator("body").text_content()
    current_ltv, ltv_status = parse_ltv_text(body_text)
    logger.info(f"📊 Current LTV: {current_ltv}% | Target: {target_ltv}% | Status: {ltv_status}")
    await take_screenshot(page, "step0_ltv_read")
    
    if current_ltv >= target_ltv:
        logger.info(f"✅ LTV already at target ({current_ltv}% ≥ {target_ltv}%). No borrow needed.")
        return True

    # === STEP 1: Click "Pinjam lebih banyak" ===
    logger.info("Step 1: Opening borrow dialog...")
    btn = None
    for text in ["Pinjam lebih banyak", "Borrow more"]:
        try:
            loc = page.get_by_text(text, exact=True).first
            if await loc.is_visible(timeout=3000):
                btn = loc
                break
        except:
            continue
    
    if not btn:
        logger.error("❌ 'Pinjam lebih banyak' not found!")
        await take_screenshot(page, "error_no_pinjam_btn")
        return False
    
    await btn.click()
    await human_delay(2000, 3000)
    await take_screenshot(page, "step1_dialog_opened")

    # === STEP 2: Click token dropdown (the "USDC ∨" area) ===
    logger.info(f"Step 2: Opening token dropdown...")
    
    # Find "Maks." button as anchor, dropdown is to its left
    maks_el = None
    for text in ["Maks.", "Max"]:
        try:
            loc = page.get_by_text(text, exact=True).first
            if await loc.is_visible(timeout=3000):
                maks_el = loc
                break
        except:
            continue
    
    if not maks_el:
        logger.error("❌ Cannot find 'Maks.' button!")
        await take_screenshot(page, "error_no_maks")
        return False
    
    box = await maks_el.bounding_box()
    if not box:
        logger.error("❌ Cannot get Maks. position!")
        return False
    
    # Click 80px left of "Maks." = hits "USDC ∨" dropdown
    await page.mouse.click(box['x'] - 80, box['y'] + box['height'] / 2)
    await human_delay(1500, 2500)
    await take_screenshot(page, "step2_dropdown_opened")

    # === STEP 3: Type token in search (ONLY use dropdown search input) ===
    logger.info(f"Step 3: Searching for {currency}...")
    
    # The dropdown popup has a search input with 🔍 icon
    # CRITICAL: Only match search inputs that are VISIBLE and inside dropdown popup
    # DO NOT match "Tambahkan kolateral" input!
    search_input = None
    
    # Method A: Find input inside dropdown/popup container
    for container_sel in ['.okui-select-dropdown', '.okui-popup', '[role="listbox"]']:
        try:
            container = page.locator(container_sel).first
            if await container.is_visible(timeout=2000):
                inp = container.locator('input').first
                if await inp.is_visible(timeout=1000):
                    search_input = inp
                    logger.info(f"   Found search input in {container_sel}")
                    break
        except:
            continue
    
    # Method B: Find by placeholder but verify it's NOT the kolateral input
    if not search_input:
        all_inputs = page.locator('input[type="search"], input[placeholder*="Cari"], input[placeholder*="Search"]')
        for i in range(await all_inputs.count()):
            inp = all_inputs.nth(i)
            try:
                if await inp.is_visible(timeout=1000):
                    # Verify this input is ABOVE the "Kolateral" section (y < kolateral y)
                    inp_box = await inp.bounding_box()
                    if inp_box and inp_box['y'] < box['y'] + 200:  # Should be near the input row area
                        search_input = inp
                        logger.info(f"   Found search input by placeholder (y={inp_box['y']:.0f})")
                        break
            except:
                continue
    
    if search_input:
        await search_input.click(force=True)
        await search_input.fill(currency)
        await human_delay(1500, 2500)
        logger.info(f"   Typed '{currency}' in search")
    else:
        logger.warning("   ⚠️ No search input found, looking in visible list...")
    
    await take_screenshot(page, "step3_after_search")

    # === STEP 4: Click token in dropdown list ===
    logger.info(f"Step 4: Clicking token {currency}...")
    token_clicked = False
    
    # get_by_text matches search input too! Must skip it.
    # Strategy: find all text matches, click the one that's NOT the search input
    try:
        matches = page.get_by_text(currency, exact=True)
        count = await matches.count()
        logger.info(f"   Found {count} elements with text '{currency}'")
        
        for i in range(count):
            el = matches.nth(i)
            if await el.is_visible(timeout=1000):
                tag = await el.evaluate("el => el.tagName")
                # Skip INPUT elements (that's the search box)
                if tag.upper() == "INPUT":
                    logger.info(f"   [{i}] Skipping INPUT element")
                    continue
                logger.info(f"   [{i}] Clicking {tag} element")
                await el.click()
                token_clicked = True
                logger.info(f"   ✅ Clicked {currency}")
                break
    except Exception as e:
        logger.warning(f"   get_by_text failed: {e}")
    
    if not token_clicked:
        logger.error(f"❌ Token {currency} not found in dropdown!")
        await take_screenshot(page, f"error_token_not_found_{currency}")
        return False
    
    await human_delay(2000, 3000)
    
    # Verify we're still on "Pinjam" dialog (not Transfer!)
    try:
        if await page.get_by_text("Transfer", exact=True).first.is_visible(timeout=1000):
            logger.error("❌ Accidentally opened Transfer dialog! Aborting.")
            await page.keyboard.press("Escape")
            return False
    except:
        pass  # Good - no Transfer dialog
    
    await take_screenshot(page, "step4_token_selected")

    # === STEP 5: Input amount ===
    logger.info(f"Step 5: Inputting amount {amount}...")
    
    is_max = isinstance(amount, str) and amount.lower() == 'max'
    
    # Helper: find Maks. button
    async def find_maks_btn():
        for text in ["Maks.", "Max"]:
            try:
                loc = page.get_by_text(text, exact=True).first
                if await loc.is_visible(timeout=2000):
                    return loc
            except:
                continue
        return None
    
    if is_max:
        maks_btn = await find_maks_btn()
        if maks_btn:
            await maks_btn.click()
            logger.info("   Clicked Maks.")
        else:
            logger.error("❌ Maks. button not found!")
            return False
    else:
        # Type specific amount — truncate to 4 decimals (OKX precision limit)
        amount_input = None
        for sel in ['input[placeholder*="Masukkan jumlah"]', 'input[placeholder*="Enter amount"]']:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible(timeout=3000):
                    amount_input = loc
                    break
            except:
                continue
        
        if amount_input:
            # Truncate (floor) to 4 decimal places to avoid "exceeds quota" error
            import math
            amt_float = float(amount)
            amt_truncated = math.floor(amt_float * 10000) / 10000
            val = f"{amt_truncated:.4f}".replace(".", ",")
            
            await amount_input.click(force=True, click_count=3)
            await human_delay(200, 400)
            await amount_input.type(val, delay=50)
            logger.info(f"   Typed amount: {val} (truncated from {amount})")
            
            await human_delay(2000, 3000)
            
            # Check for error message — if exceeds, fallback to Maks.
            try:
                error_el = page.locator('text=/melampaui|exceeds|melebihi/i').first
                if await error_el.is_visible(timeout=1500):
                    logger.warning("   ⚠️ Amount exceeds quota! Falling back to Maks...")
                    maks_btn = await find_maks_btn()
                    if maks_btn:
                        await maks_btn.click()
                        logger.info("   ✅ Clicked Maks. as fallback")
                    else:
                        logger.error("❌ Cannot find Maks. button for fallback!")
                        return False
            except:
                pass  # No error — amount is fine
        else:
            logger.error("❌ Amount input not found!")
            await take_screenshot(page, "error_no_amount_input")
            return False
    
    await human_delay(2000, 3000)
    await take_screenshot(page, "step5_amount_entered")

    # === STEP 6: Click "Tinjau loan" (Review) ===
    logger.info("Step 6: Clicking Review...")
    review_btn = None
    for text in ["Tinjau loan", "Review"]:
        try:
            loc = page.get_by_role("button", name=text, exact=True).first
            if await loc.is_visible(timeout=3000):
                review_btn = loc
                break
        except:
            continue
    
    if not review_btn:
        # Broader search
        for text in ["Tinjau", "Review"]:
            try:
                loc = page.get_by_text(text, exact=False).first
                if await loc.is_visible(timeout=2000):
                    review_btn = loc
                    break
            except:
                continue
    
    if not review_btn:
        logger.error("❌ Review button not found!")
        await take_screenshot(page, "error_no_review_btn")
        return False
    
    try:
        if await review_btn.is_disabled():
            logger.warning("   ⚠️ Review button disabled, waiting 5s...")
            await human_delay(5000, 6000)
            if await review_btn.is_disabled():
                logger.error("❌ Review still disabled!")
                await take_screenshot(page, "error_review_disabled")
                return False
    except:
        pass
    
    await review_btn.click()
    await human_delay(2000, 3000)

    # === STEP 7: Checkbox + Confirm ===
    logger.info("Step 7: Confirming loan...")
    
    # Check agreement checkbox if exists
    try:
        checkbox = page.locator("input[type='checkbox']").last
        if await checkbox.is_visible(timeout=2000):
            if not await checkbox.is_checked():
                await checkbox.check()
                logger.info("   ✅ Checked agreement")
    except:
        pass
    
    await human_delay(500, 1000)
    
    # Click Confirm
    confirm_btn = None
    for text in ["Konfirmasi", "Confirm"]:
        try:
            loc = page.get_by_role("button", name=text, exact=True).first
            if await loc.is_visible(timeout=3000):
                confirm_btn = loc
                break
        except:
            continue
    
    if confirm_btn and await confirm_btn.is_enabled():
        await confirm_btn.click()
        logger.info("   Clicked Konfirmasi")
        
        # Wait for success
        try:
            success = page.get_by_text("Loan disetujui", exact=False).or_(
                      page.get_by_text("Borrow successful", exact=False))
            await success.first.wait_for(state="visible", timeout=10000)
            logger.info("✅ SUCCESS: Loan Approved!")
            
            # Click OK to close
            try:
                ok_btn = page.get_by_role("button", name="OK").or_(
                         page.get_by_text("Selesai", exact=True))
                if await ok_btn.first.is_visible(timeout=3000):
                    await ok_btn.first.click()
            except:
                pass
            
            return True
        except:
            logger.warning("⚠️ Success message not found, assuming success.")
            return True
    else:
        logger.error("❌ Confirm button not found or disabled!")
        await take_screenshot(page, "error_confirm_failed")
        return False


async def browser_borrow_sniper(page: Page, token: str, target_ltv: float = 50.0, max_duration_minutes: int = 60) -> bool:
    """Sniper Mode — re-selects token each cycle to force fresh liquidity from OKX backend."""
    logger.info(f"🔫 Start SNIPER LTV TARGET: {target_ltv}% for {token}")
    
    start_time = time.time()
    cycle_count = 0
    last_page_reload = time.time()
    STALE_RELOAD_SECONDS = 300  # Reload page after 5 min of zero liquidity
    
    while True:
        elapsed_min = (time.time() - start_time) / 60
        if elapsed_min > max_duration_minutes:
            logger.info("🛑 Sniper max duration reached.")
            return True

        try:
            # === PHASE 1: Navigate & Read LTV ===
            await page.goto("https://www.okx.com/id/loan/multi", timeout=30000)
            await human_delay(3000, 5000)
        except:
            await human_delay(2000, 3000)
            continue

        body_text = await page.locator("body").text_content()
        current_ltv, ltv_status = parse_ltv_text(body_text)
        logger.info(f"📊 LTV: {current_ltv}% | Target: {target_ltv}% | Status: {ltv_status}")

        if current_ltv >= target_ltv:
            logger.info(f"✅ LTV at target ({current_ltv}% ≥ {target_ltv}%). Done.")
            return True

        # === PHASE 2: Open Borrow Modal ===
        btn = None
        for text in ["Pinjam lebih banyak", "Borrow more"]:
            try:
                loc = page.get_by_text(text, exact=True).first
                if await loc.is_visible(timeout=3000):
                    btn = loc
                    break
            except:
                continue
        
        if not btn:
            logger.warning("❌ 'Pinjam lebih banyak' not found. Retrying...")
            await human_delay(3000, 5000)
            continue
        
        await btn.click()
        await human_delay(2000, 3000)

        # === PHASE 3: Find Maks. anchor (used for dropdown positioning) ===
        maks_el = None
        for text in ["Maks.", "Max"]:
            try:
                loc = page.get_by_text(text, exact=True).first
                if await loc.is_visible(timeout=3000):
                    maks_el = loc
                    break
            except:
                continue
        
        if not maks_el:
            logger.warning("❌ 'Maks.' not found in modal. Retrying...")
            await page.keyboard.press("Escape")
            await human_delay(2000, 3000)
            continue

        maks_box = await maks_el.bounding_box()
        if not maks_box:
            logger.warning("❌ Cannot get Maks. position. Retrying...")
            await page.keyboard.press("Escape")
            continue

        # === PHASE 4: TOKEN RE-SELECTION REFRESH LOOP ===
        # This is the core sniper innovation: re-select token each cycle
        # to force OKX backend to return fresh liquidity data.
        logger.info(f"🔫 Entering sniper refresh loop for {token}...")
        refresh_start = time.time()
        
        while True:
            cycle_count += 1
            elapsed_refresh = time.time() - refresh_start
            
            # Stale page check: reload after 5 min of no liquidity
            if elapsed_refresh > STALE_RELOAD_SECONDS:
                logger.info("🔄 Stale page detected. Reloading...")
                last_page_reload = time.time()
                break  # Break inner loop → outer loop reloads page
            
            # Overall timeout check
            if (time.time() - start_time) / 60 > max_duration_minutes:
                logger.info("🛑 Sniper max duration reached.")
                return True

            # --- STEP A: Open dropdown (click 80px left of Maks.) ---
            try:
                # Re-read Maks. position (may shift after token change)
                maks_box = await maks_el.bounding_box()
                if not maks_box:
                    logger.warning("   Maks. position lost. Breaking to reload...")
                    break
                
                await page.mouse.click(maks_box['x'] - 80, maks_box['y'] + maks_box['height'] / 2)
                await human_delay(600, 1000)
            except Exception as e:
                logger.warning(f"   ⚠️ Dropdown click failed: {e}")
                break  # Break to outer loop for page reload

            # --- STEP B: Find & type in search input ---
            search_input = None
            for container_sel in ['.okui-select-dropdown', '.okui-popup', '[role="listbox"]']:
                try:
                    container = page.locator(container_sel).first
                    if await container.is_visible(timeout=1500):
                        inp = container.locator('input').first
                        if await inp.is_visible(timeout=800):
                            search_input = inp
                            break
                except:
                    continue
            
            if not search_input:
                # Fallback: find by placeholder
                for sel in ['input[placeholder*="Cari"]', 'input[placeholder*="Search"]', 'input[type="search"]']:
                    try:
                        loc = page.locator(sel).first
                        if await loc.is_visible(timeout=800):
                            search_input = loc
                            break
                    except:
                        continue
            
            if search_input:
                try:
                    await search_input.click(force=True)
                    await search_input.fill(token)
                    await human_delay(500, 800)
                except Exception as e:
                    logger.warning(f"   ⚠️ Search input failed: {e}")
                    # Try pressing Escape to close broken dropdown
                    await page.keyboard.press("Escape")
                    await human_delay(600, 1000)
                    continue

            # --- STEP C: Click token from dropdown results ---
            token_clicked = False
            try:
                matches = page.get_by_text(token, exact=True)
                count = await matches.count()
                
                for i in range(count):
                    el = matches.nth(i)
                    try:
                        if await el.is_visible(timeout=800):
                            tag = await el.evaluate("el => el.tagName")
                            if tag.upper() == "INPUT":
                                continue  # Skip search input
                            await el.click()
                            token_clicked = True
                            break
                    except:
                        continue
            except:
                pass
            
            if not token_clicked:
                if cycle_count % 10 == 0:
                    logger.warning(f"   ⚠️ Token {token} not found in dropdown (cycle {cycle_count})")
                # Close dropdown and retry
                await page.keyboard.press("Escape")
                await human_delay(600, 1000)
                continue

            # --- STEP D: Wait for rate calc banner to clear ---
            await human_delay(800, 1200)
            try:
                calc_banner = page.locator('text=/Kami Sedang Menghitung|We are calculating/').first
                if await calc_banner.is_visible(timeout=500):
                    await calc_banner.wait_for(state='hidden', timeout=8000)
            except:
                pass

            # --- STEP E: Read liquidity ("Anda dapat meminjam") ---
            liquidity = 0.0
            for pattern in [
                "text=/Anda dapat meminjam/",
                "text=/You can borrow/",
                "text=/dapat meminjam/",
            ]:
                try:
                    stock_el = page.locator(pattern).first
                    if await stock_el.is_visible(timeout=1500):
                        # Climb DOM to find parent with numbers
                        full_text = await stock_el.text_content()
                        current_el = stock_el
                        for level in range(1, 5):
                            current_el = current_el.locator('xpath=..')
                            parent_txt = await current_el.text_content()
                            if parent_txt and '/' in parent_txt and re.search(r'[\d]', parent_txt):
                                full_text = parent_txt
                                break
                        
                        liquidity, _ = parse_stock_text(full_text)
                        break
                except:
                    continue

            # --- STEP F: Decision ---
            if cycle_count % 5 == 0 or liquidity > 0:
                logger.info(f"   🔫 Cycle {cycle_count} | Liquidity: {liquidity} | Elapsed: {elapsed_refresh:.0f}s")

            if liquidity > 0:
                logger.info(f"   🚀 LIQUIDITY FOUND: {liquidity} {token}! Proceeding to borrow...")
                await take_screenshot(page, f"sniper_liquidity_found_{token}")
                
                # === BORROW EXECUTION ===
                # Click Maks. to fill max amount
                try:
                    maks_btn = None
                    for text in ["Maks.", "Max"]:
                        try:
                            loc = page.get_by_text(text, exact=True).first
                            if await loc.is_visible(timeout=2000):
                                maks_btn = loc
                                break
                        except:
                            continue
                    if maks_btn:
                        await maks_btn.click()
                        logger.info("   Clicked Maks.")
                    await human_delay(1500, 2500)
                except Exception as e:
                    logger.warning(f"   ⚠️ Maks. click error: {e}")
                
                # Click Review
                review_btn = None
                for text in ["Tinjau loan", "Review"]:
                    try:
                        loc = page.get_by_role("button", name=text, exact=True).first
                        if await loc.is_visible(timeout=3000):
                            review_btn = loc
                            break
                    except:
                        continue
                
                if not review_btn:
                    for text in ["Tinjau", "Review"]:
                        try:
                            loc = page.get_by_text(text, exact=False).first
                            if await loc.is_visible(timeout=2000):
                                review_btn = loc
                                break
                        except:
                            continue
                
                if review_btn:
                    try:
                        if await review_btn.is_disabled():
                            logger.warning("   ⚠️ Review button disabled, waiting...")
                            await human_delay(3000, 5000)
                    except:
                        pass
                    
                    await review_btn.click()
                    await human_delay(1500, 2500)
                    await take_screenshot(page, "sniper_after_review")
                    
                    # Checkbox
                    try:
                        checkbox = page.locator("input[type='checkbox']").last
                        if await checkbox.is_visible(timeout=2000):
                            if not await checkbox.is_checked():
                                await checkbox.check()
                                logger.info("   ✅ Checked agreement")
                    except:
                        pass
                    
                    await human_delay(500, 1000)
                    
                    # Confirm
                    confirm_btn = None
                    for text in ["Konfirmasi", "Confirm"]:
                        try:
                            loc = page.get_by_role("button", name=text, exact=True).first
                            if await loc.is_visible(timeout=3000):
                                confirm_btn = loc
                                break
                        except:
                            continue
                    
                    if confirm_btn and await confirm_btn.is_enabled():
                        await confirm_btn.click()
                        logger.info("   Clicked Konfirmasi")
                        
                        # Wait for success
                        try:
                            success = page.get_by_text("Loan disetujui", exact=False).or_(
                                      page.get_by_text("Borrow successful", exact=False))
                            await success.first.wait_for(state="visible", timeout=10000)
                            logger.info("✅ SNIPER SUCCESS: Loan Approved!")
                            await take_screenshot(page, "sniper_borrow_success")
                            
                            # Click OK to close
                            try:
                                ok_btn = page.get_by_role("button", name="OK").or_(
                                         page.get_by_text("Selesai", exact=True))
                                if await ok_btn.first.is_visible(timeout=3000):
                                    await ok_btn.first.click()
                            except:
                                pass
                            
                            # Wait before next LTV check
                            await human_delay(5000, 8000)
                            break  # Break inner loop → outer loop re-checks LTV
                        except:
                            logger.warning("⚠️ Success message not found, assuming success.")
                            await human_delay(5000, 8000)
                            break
                    else:
                        logger.warning("   ❌ Confirm button not available.")
                        await take_screenshot(page, "sniper_confirm_failed")
                        break  # Break to outer loop
                else:
                    logger.warning("   ❌ Review button not found.")
                    await take_screenshot(page, "sniper_review_missing")
                    break  # Break to outer loop
            else:
                # No liquidity — wait human-like delay then re-select
                await human_delay(600, 1200)
        
        logger.info("⏳ Waiting loop...")
        await human_delay(3000, 5000)

    return False


async def borrow_mode(currency: str, amount: str, mode: str = "santai", target_ltv: float = 50.0):
    """Entry point for borrow — opens persistent context, checks session, dispatches strategy."""
    logger.info(f"🚀 Launching Browser Borrow ({mode.upper()}) for {currency}...")
    
    async with async_playwright() as p:
        context, page = await get_persistent_context(p, headless=True)
        
        try:
            # Health Check
            logger.info("   Checking session health...")
            is_healthy = await check_session_health(page)
            
            if not is_healthy:
                logger.error("❌ Session expired! Please run 'login' mode first.")
                await take_screenshot(page, "error_session_expired")
                return False
            
            logger.info("   ✅ Session active. Proceeding...")
            
            if mode == "sniper":
                return await browser_borrow_sniper(page, currency, target_ltv)
            else:
                return await browser_borrow_santai(page, currency, amount, target_ltv)
                
        except Exception as e:
            logger.error(f"❌ Browser Borrow Error: {e}")
            traceback.print_exc()
            try:
                await take_screenshot(page, "error_main_borrow")
            except:
                pass
            return False
        finally:
            await context.close()


async def check_mode():
    """Checks session validity and captures evidence."""
    logger.info("🕵️ Starting Session Check...")
    
    async with async_playwright() as p:
        context, page = await get_persistent_context(p, headless=False) # Headless False so user can see
        
        try:
            logger.info("   Navigating to Assets Overview...")
            await page.goto("https://www.okx.com/id/balance/overview", timeout=60000)
            await human_delay(3000, 5000)
            
            # Check for specific logged-in elements
            if "/login" in page.url:
                logger.error("❌ Redirected to Login page. Session is EXPIRED/INVALID.")
                print("\n❌ Akun BELUM login atau sesi habis.")
                return

            # Try to find user identifier (often in header or settings)
            try:
                # Open user menu to see email/id
                user_menu = page.locator('.okui-header-user-menu-btn').first
                if await user_menu.is_visible():
                     await user_menu.hover()
                     await human_delay(1000, 2000)
                     
                user_info_el = page.locator('.user-info-email, .header-user-email, [class*="userInfo"]').first
                if await user_info_el.is_visible():
                     info = await user_info_el.text_content()
                     logger.info(f"   👤 Logged in as: {info}")
                     print(f"\n✅ Akun TERDETEKSI: {info}")
                else:
                     logger.info("   ✅ Logged in (Asset page accessible).")
                     print("\n✅ Akun TERDETEKSI (Halaman Aset terbuka).")
            except:
                logger.info("   ✅ Logged in (Asset page accessible).")
                print("\n✅ Akun TERDETEKSI (Halaman Aset terbuka).")

            await take_screenshot(page, "session_check_evidence")
            print(f"📸 Screenshot saved to screenshots/session_check_evidence.png")
            
            await human_delay(5000, 7000) # Let user see
            
        except Exception as e:
            logger.error(f"Check failed: {e}")
            print(f"❌ Error saat checking: {e}")
        finally:
            await context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["login", "borrow", "check"])
    parser.add_argument("currency", nargs="?")
    parser.add_argument("amount", nargs="?")
    parser.add_argument("--use-system-chrome", action="store_true")
    parser.add_argument("--sniper", action="store_true")
    parser.add_argument("--target-ltv", type=float, default=50.0)
    args = parser.parse_args()
    
    try:
        if args.mode == "login":
            asyncio.run(login_mode())
        elif args.mode == "check":
            asyncio.run(check_mode())
        elif args.mode == "borrow":
            success = asyncio.run(borrow_mode(args.currency, args.amount, "sniper" if args.sniper else "santai", args.target_ltv))
            sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)