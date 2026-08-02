"""
Run this after login.py and recon_dashboard.py, once IRPSM_WORKS_URL is set
in .env. It opens the works listing page and dumps every select/input
(possible phase/filter controls) plus the tables it can see, so we can find
how to filter down to "PH 53" only.

Usage:
    python recon_works.py
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

WORKS_URL = os.environ.get("IRPSM_WORKS_URL")
STORAGE_STATE_PATH = "storage_state.json"
OUT_DIR = Path(__file__).parent / "recon_output"


def describe_controls(page):
    selects = page.eval_on_selector_all(
        "select",
        """els => els.map(e => ({
            name: e.name || null,
            id: e.id || null,
            options: Array.from(e.options).map(o => ({value: o.value, text: o.text.trim()})),
        }))""",
    )
    text_inputs = page.eval_on_selector_all(
        "input[type=text], input:not([type])",
        """els => els.map(e => ({
            name: e.name || null,
            id: e.id || null,
            placeholder: e.placeholder || null,
        }))""",
    )
    buttons = page.eval_on_selector_all(
        "button, input[type=submit], input[type=button]",
        """els => els.map(e => ({
            text: (e.innerText || e.value || '').trim(),
            id: e.id || null,
            name: e.name || null,
        }))""",
    )
    tables = page.eval_on_selector_all(
        "table",
        """els => els.map((e, i) => ({
            index: i,
            id: e.id || null,
            className: e.className || null,
            rowCount: e.querySelectorAll('tr').length,
        }))""",
    )
    return {"selects": selects, "text_inputs": text_inputs, "buttons": buttons, "tables": tables}


def main():
    if not WORKS_URL:
        print("IRPSM_WORKS_URL is not set in .env — run recon_dashboard.py first.")
        return
    if not Path(STORAGE_STATE_PATH).exists():
        print(f"{STORAGE_STATE_PATH} not found — run `python login.py` first.")
        return

    OUT_DIR.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=STORAGE_STATE_PATH)
        page = context.new_page()
        page.goto(WORKS_URL, wait_until="networkidle")

        info = describe_controls(page)
        (OUT_DIR / "works_controls.json").write_text(json.dumps(info, indent=2))
        page.screenshot(path=str(OUT_DIR / "works_page.png"), full_page=True)

        print(json.dumps(info, indent=2))
        print(f"\nSaved to {OUT_DIR}/works_controls.json and works_page.png")
        print("Look for a select/input related to Phase, and check its 'options' for")
        print("something like 'PH 53' or 'Phase 53'. Set in .env:")
        print("  IRPSM_FILTER_SELECTOR   (CSS selector for the control)")
        print("  IRPSM_FILTER_TYPE       (select or text)")
        print("  IRPSM_FILTER_VALUE      (e.g. 'PH 53' — match the option text/value exactly)")
        print("  IRPSM_FILTER_SUBMIT_SELECTOR  (if a separate Search/Go button applies it)")
        input("Press Enter to close the browser...")
        browser.close()


if __name__ == "__main__":
    main()
