import asyncio
import os
import sys
from playwright.async_api import async_playwright

# Add root to path
sys.path.append(os.path.join(os.getcwd()))

SESSION_FILE = 'okx_session.json'

async def verify():
    print(f"Checking session file: {SESSION_FILE}")
    if not os.path.exists(SESSION_FILE):
        print("❌ Session file not found!")
        return

    async with async_playwright() as p:
        # Launch Headless
        browser = await p.chromium.launch(headless=True)
        
        try:
            # Load Session
            context = await browser.new_context(storage_state=SESSION_FILE)
            page = await context.new_page()
            
            # Stealth (Minimal)
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            url = "https://www.okx.com/id/loan"
            print(f"Navigating to {url}...")
            await page.goto(url, timeout=60000)
            await page.wait_for_timeout(5000) # Wait for load
            
            # Take Screenshot
            screenshot_path = "session_status.png"
            await page.screenshot(path=screenshot_path)
            print(f"📸 Screenshot saved to {screenshot_path}")
            
            # Check Login Status
            # Look for common login elements or logged-in elements
            content = await page.content()
            
            # Indicators
            is_login_btn_visible = await page.locator('a[href*="/login"], button:has-text("Masuk"), button:has-text("Log in")').first.is_visible()
            is_assets_visible = await page.locator('text="Aset saya"', has_text="Aset").or_(page.locator('text="My assets"')).is_visible()
            
            if is_assets_visible:
                print("✅ Session ACTIVE (Found 'Aset saya'/'My assets')")
            elif is_login_btn_visible:
                print("❌ Session EXPIRED or INVALID (Found Login button)")
            else:
                print("⚠️ State UNCERTAIN. Check screenshot.")
                
        except Exception as e:
            print(f"❌ Error during verification: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(verify())
