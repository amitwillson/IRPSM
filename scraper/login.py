"""
Shared login helper. Logs in with ID + password, then pauses so you can
type the OTP sent to your phone/email. Saves the authenticated session to
storage_state.json so other scripts can reuse it without logging in again.
"""
import os
import sys

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

BASE_URL = os.environ["IRPSM_BASE_URL"]
USER_ID = os.environ["IRPSM_USER_ID"]
PASSWORD = os.environ["IRPSM_PASSWORD"]

USERID_SELECTOR = os.environ.get("IRPSM_USERID_SELECTOR")
PASSWORD_SELECTOR = os.environ.get("IRPSM_PASSWORD_SELECTOR")
LOGIN_BUTTON_SELECTOR = os.environ.get("IRPSM_LOGIN_BUTTON_SELECTOR")
OTP_SELECTOR = os.environ.get("IRPSM_OTP_SELECTOR")
OTP_SUBMIT_SELECTOR = os.environ.get("IRPSM_OTP_SUBMIT_SELECTOR")

STORAGE_STATE_PATH = "storage_state.json"

REQUIRED = {
    "IRPSM_USERID_SELECTOR": USERID_SELECTOR,
    "IRPSM_PASSWORD_SELECTOR": PASSWORD_SELECTOR,
    "IRPSM_LOGIN_BUTTON_SELECTOR": LOGIN_BUTTON_SELECTOR,
}


def require_selectors():
    missing = [k for k, v in REQUIRED.items() if not v]
    if missing:
        print("Missing selectors in .env: " + ", ".join(missing))
        print("Run `python recon.py` first and fill these in from recon_output/login_fields.json")
        sys.exit(1)


def login_and_save_session(headless=False):
    require_selectors()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="networkidle")

        page.fill(USERID_SELECTOR, USER_ID)
        page.fill(PASSWORD_SELECTOR, PASSWORD)
        page.click(LOGIN_BUTTON_SELECTOR)
        page.wait_for_load_state("networkidle")

        if OTP_SELECTOR:
            print("\nAn OTP should have been sent to you. Check your phone/email.")
            otp = input("Enter the OTP: ").strip()
            # type() simulates real keystrokes (fill() doesn't fire key
            # events), which some OTP fields need for their JS validation.
            page.type(OTP_SELECTOR, otp, delay=50)
            if OTP_SUBMIT_SELECTOR:
                page.click(OTP_SUBMIT_SELECTOR)
            else:
                page.press(OTP_SELECTOR, "Enter")
            page.wait_for_load_state("networkidle")
        else:
            print("\nNo OTP selector configured — if the site is now showing an OTP")
            print("screen, run recon.py again pointed at this stage to find the field,")
            print("or fill IRPSM_OTP_SELECTOR in .env and re-run.")
            input("Press Enter once you're past login (or to abort otherwise)...")

        page.context.storage_state(path=STORAGE_STATE_PATH)
        print(f"Session saved to {STORAGE_STATE_PATH}")
        return browser, page


if __name__ == "__main__":
    browser, page = login_and_save_session(headless=False)
    print("Logged in. Current URL:", page.url)
    input("Press Enter to close...")
    browser.close()
