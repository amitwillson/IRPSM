"""
Scrapes the works listing table(s) using the session saved by login.py,
following pagination automatically, and writes the result to
output/works.csv.

Works generically against any HTML <table>: it reads the header row for
column names and every subsequent row as a record. If the works list uses
something other than a plain <table> (e.g. a div-based grid), inspect
recon_output/dashboard.png / works_page.png and adjust TABLE_SELECTOR /
ROW_SELECTOR below.

Usage:
    python scrape_works.py
"""
import csv
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

BASE_URL = os.environ["IRPSM_BASE_URL"]
WORKS_URL = os.environ.get("IRPSM_WORKS_URL")
STORAGE_STATE_PATH = "storage_state.json"
OUT_DIR = Path(__file__).parent / "output"

TABLE_SELECTOR = os.environ.get("IRPSM_TABLE_SELECTOR", "table")
NEXT_PAGE_SELECTOR = os.environ.get(
    "IRPSM_NEXT_PAGE_SELECTOR",
    "a:has-text('Next'), a:has-text('>'), .pagination a[rel='next']",
)
MAX_PAGES = int(os.environ.get("IRPSM_MAX_PAGES", "500"))


def extract_table(page):
    tables = page.query_selector_all(TABLE_SELECTOR)
    rows_out = []
    header = None
    for table in tables:
        rows = table.query_selector_all("tr")
        for row in rows:
            cells = row.query_selector_all("th, td")
            values = [c.inner_text().strip() for c in cells]
            if not values:
                continue
            is_header_row = row.query_selector("th") is not None
            if is_header_row and header is None:
                header = values
                continue
            rows_out.append(values)
    return header, rows_out


def main():
    if not WORKS_URL:
        print("IRPSM_WORKS_URL is not set in .env — run recon_dashboard.py to find it.")
        return
    if not Path(STORAGE_STATE_PATH).exists():
        print(f"{STORAGE_STATE_PATH} not found — run `python login.py` first.")
        return

    OUT_DIR.mkdir(exist_ok=True)
    all_rows = []
    header = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=STORAGE_STATE_PATH)
        page = context.new_page()
        page.goto(WORKS_URL, wait_until="networkidle")

        for page_num in range(1, MAX_PAGES + 1):
            page.wait_for_timeout(500)
            h, rows = extract_table(page)
            header = header or h
            all_rows.extend(rows)
            print(f"Page {page_num}: collected {len(rows)} rows (total {len(all_rows)})")

            next_button = page.query_selector(NEXT_PAGE_SELECTOR)
            if not next_button or not next_button.is_enabled():
                break
            next_button.click()
            page.wait_for_load_state("networkidle")
            time.sleep(0.5)

        browser.close()

    out_path = OUT_DIR / "works.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if header:
            writer.writerow(header)
        writer.writerows(all_rows)

    print(f"\nWrote {len(all_rows)} rows to {out_path}")


if __name__ == "__main__":
    main()
