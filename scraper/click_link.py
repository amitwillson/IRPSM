"""
Some dashboard menu items navigate via JavaScript (href="#"), so the real
URL only appears after actually clicking. This reuses the saved session,
opens the dashboard, clicks the first link/element whose visible text
contains the given text, and reports the resulting URL (handling a popup
window or a new tab too, if the click opens one).

Usage:
    python click_link.py "Sanctioned Works"
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
import os

load_dotenv()

BASE_URL = os.environ["IRPSM_BASE_URL"]
STORAGE_STATE_PATH = "storage_state.json"
OUT_DIR = Path(__file__).parent / "recon_output"


def main():
    if len(sys.argv) < 2:
        print('Usage: python click_link.py "link text"')
        return
    target_text = sys.argv[1]

    if not Path(STORAGE_STATE_PATH).exists():
        print(f"{STORAGE_STATE_PATH} not found — run `python login.py` first.")
        return

    OUT_DIR.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=STORAGE_STATE_PATH)
        page = context.new_page()
        page.goto(BASE_URL, wait_until="networkidle")

        locator = page.get_by_text(target_text, exact=False).first

        try:
            with context.expect_page(timeout=5000) as new_page_info:
                locator.click()
            new_page = new_page_info.value
            new_page.wait_for_load_state("networkidle")
            target_page = new_page
            print("A new tab/window opened.")
        except Exception:
            page.wait_for_load_state("networkidle")
            target_page = page
            print("Navigated in the same window.")

        print("Resulting URL:", target_page.url)
        safe_name = "".join(c if c.isalnum() else "_" for c in target_text)
        target_page.screenshot(path=str(OUT_DIR / f"click_{safe_name}.png"), full_page=True)
        print(f"Screenshot saved to recon_output/click_{safe_name}.png")

        input("Press Enter to close the browser...")
        browser.close()


if __name__ == "__main__":
    main()
