"""
Run this AFTER login.py has succeeded once (storage_state.json exists).
It reopens the dashboard using the saved session and lists every link/menu
item so you can find the URL of the "works" listing page.

Usage:
    python recon_dashboard.py
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

BASE_URL = os.environ["IRPSM_BASE_URL"]
STORAGE_STATE_PATH = "storage_state.json"
OUT_DIR = Path(__file__).parent / "recon_output"


def main():
    if not Path(STORAGE_STATE_PATH).exists():
        print(f"{STORAGE_STATE_PATH} not found — run `python login.py` first.")
        return

    OUT_DIR.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=STORAGE_STATE_PATH)
        page = context.new_page()
        page.goto(BASE_URL, wait_until="networkidle")

        links = page.eval_on_selector_all(
            "a[href]",
            """els => els.map(e => ({text: e.innerText.trim(), href: e.href}))
                        .filter(l => l.text)""",
        )
        (OUT_DIR / "dashboard_links.json").write_text(json.dumps(links, indent=2))
        page.screenshot(path=str(OUT_DIR / "dashboard.png"), full_page=True)

        print(json.dumps(links, indent=2))
        print(f"\nSaved to {OUT_DIR}/dashboard_links.json")
        print("Find the link whose text mentions 'Works' and set IRPSM_WORKS_URL in .env")
        input("Press Enter to close the browser...")
        browser.close()


if __name__ == "__main__":
    main()
