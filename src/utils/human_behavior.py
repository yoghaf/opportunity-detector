import asyncio
import random
import time
import math
from playwright.async_api import Page, ElementHandle

async def human_delay(min_ms: int = 500, max_ms: int = 2000, gaussian: bool = True):
    """
    Sleeps for a random amount of time to simulate human processing time.
    """
    if gaussian:
        match_delay = (min_ms + max_ms) / 2
        sigma = (max_ms - min_ms) / 4
        delay = random.gauss(match_delay, sigma)
        delay = max(min_ms, min(delay, max_ms))
    else:
        delay = random.uniform(min_ms, max_ms)
    
    await asyncio.sleep(delay / 1000)

async def human_type(page: Page, selector: str, text: str, delay_min: int = 50, delay_max: int = 150):
    """
    Types text into a selector with variable speed and occasional pauses.
    """
    element = page.locator(selector).first
    await element.focus()
    
    for char in text:
        # Occasional detail/pause
        if random.random() < 0.05:
            await asyncio.sleep(random.uniform(0.1, 0.4))
            
        delay = random.uniform(delay_min, delay_max)
        await page.keyboard.type(char, delay=delay)

async def human_click(page: Page, element: ElementHandle | str, offset_range: int = 5):
    """
    Moves mouse to element with a natural curve and clicks with random offset.
    """
    if isinstance(element, str):
        locator = page.locator(element).first
        box = await locator.bounding_box()
    else:
        box = await element.bounding_box()
        
    if not box:
        return # Element not visible
        
    # Calculate target point with random offset
    target_x = box['x'] + box['width'] / 2 + random.uniform(-offset_range, offset_range)
    target_y = box['y'] + box['height'] / 2 + random.uniform(-offset_range, offset_range)
    
    # Move mouse safely
    await human_mouse_move(page, target_x, target_y)
    
    # Small pause before click
    await asyncio.sleep(random.uniform(0.05, 0.2))
    await page.mouse.click(target_x, target_y)

async def human_mouse_move(page: Page, x: float, y: float, steps: int = 10):
    """
    Moves mouse to x,y in a somewhat natural curve (simple approximation).
    """
    # Get current mouse position (Playwright doesn't expose this directly easily without tracking)
    # We'll just assume start is 0,0 or last known. 
    # For better realism, we can just use page.mouse.move with steps which playwright handles somewhat smoothly.
    # But adding some noise is good.
    
    # Playwright's own move with steps is already decent, let's just use that with some random control points if we wanted complex curves.
    # For now, variable steps is key.
    
    human_steps = steps + random.randint(-5, 5)
    human_steps = max(1, human_steps)
    
    await page.mouse.move(x, y, steps=human_steps)
