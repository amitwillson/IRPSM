"""
Uploads output/works.csv to a Google Sheet using a service account.
See README "Google Sheets setup" for how to create the service account
and share the target sheet with it.

Usage:
    python upload_to_sheets.py
"""
import csv
import os
from pathlib import Path

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "service_account.json")
SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME", "IRPSM Works Export")
CSV_PATH = Path(__file__).parent / "output" / "works.csv"


def main():
    if not CSV_PATH.exists():
        print(f"{CSV_PATH} not found — run scrape_works.py first.")
        return
    if not Path(SERVICE_ACCOUNT_JSON).exists():
        print(f"{SERVICE_ACCOUNT_JSON} not found — see README Google Sheets setup.")
        return

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_JSON, scopes=SCOPES)
    client = gspread.authorize(creds)

    try:
        sheet = client.open(SHEET_NAME)
    except gspread.SpreadsheetNotFound:
        sheet = client.create(SHEET_NAME)
        print(f"Created new sheet '{SHEET_NAME}'. Share it with your own account to view it")
        print("in the Google Sheets UI (the service account owns it by default).")

    worksheet = sheet.sheet1
    worksheet.clear()
    if rows:
        worksheet.update(values=rows, range_name="A1")

    print(f"Uploaded {len(rows)} rows (including header) to '{SHEET_NAME}'.")
    print(f"Sheet URL: {sheet.url}")


if __name__ == "__main__":
    main()
