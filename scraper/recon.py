"""
Recon tool: run this FIRST, before writing any real selectors.

It opens the IRPSM login page in a real (visible) browser, waits for you to
look at it, and dumps every <input>, <button> and <form> on the page to
recon_output/login_fields.json plus a screenshot. Send that JSON back to
whoever is helping you configure .env, or fill in the selectors yourself
by matching field "name"/"id" values to the .env.example placeholders.

Usage:
    python recon.py
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

BASE_URL = os.environ.get("IRPSM_BASE_URL", "https://ircep.gov.in/IRPSM/LoginController")
OUT_DIR = Path(__file__).parent / "recon_output"


def describe_elements(page):
    fields = page.eval_on_selector_all(
        "input, select, textarea",
        """els => els.map(e => ({
            tag: e.tagName.toLowerCase(),
            type: e.type || null,
            name: e.name || null,
            id: e.id || null,
            placeholder: e.placeholder || null,
        }))""",
    )
    buttons = page.eval_on_selector_all(
        "button, input[type=submit], input[type=button]",
        """els => els.map(e => ({
            tag: e.tagName.toLowerCase(),
            text: (e.innerText || e.value || '').trim(),
            id: e.id || null,
            name: e.name || null,
        }))""",
    )
    forms = page.eval_on_selector_all(
        "form",
        """els => els.map(e => ({
            id: e.id || null,
            action: e.action || null,
            method: e.method || null,
        }))""",
    )
    return {"fields": fields, "buttons": buttons, "forms": forms}


def main():
    OUT_DIR.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        print(f"Opening {BASE_URL} ...")
        page.goto(BASE_URL, wait_until="networkidle")

        info = describe_elements(page)
        (OUT_DIR / "login_fields.json").write_text(json.dumps(info, indent=2))
        page.screenshot(path=str(OUT_DIR / "login_page.png"), full_page=True)

        print(json.dumps(info, indent=2))
        print(f"\nSaved details to {OUT_DIR}/login_fields.json and login_page.png")
        print("Match the 'name' or 'id' values above to the *_SELECTOR entries in .env")
        print("(use CSS like '#fieldId' or '[name=\"fieldName\"]').")
        input("Press Enter to close the browser...")
        browser.close()


if __name__ == "__main__":
    main()
