# IRPSM Works Extractor

Logs into the IRPSM portal (https://ircep.gov.in/IRPSM/LoginController) with
your ID + password, pauses for you to enter the OTP sent to you, scrapes the
full works listing (with pagination), and exports it to a Google Sheet.

**This must be run on your own machine** — it needs real network access to
ircep.gov.in and needs you present to type the OTP. It cannot run inside a
CI/cloud sandbox.

Because the exact HTML of the login form and works-listing page isn't known
ahead of time, this is set up as a two-step process: first a quick "recon"
against the real site to find the right field/element selectors, then the
actual scrape. You only need to do the recon once.

## Setup

```bash
cd scraper
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Edit `.env` and fill in `IRPSM_USER_ID` and `IRPSM_PASSWORD`.

## Step 1: Recon the login page

```bash
python recon.py
```

This opens a real browser window on the login page and prints/saves every
input field, button, and form it finds (`recon_output/login_fields.json`
and a screenshot). Match the field `name`/`id` to fill in, in `.env`:

- `IRPSM_USERID_SELECTOR`
- `IRPSM_PASSWORD_SELECTOR`
- `IRPSM_LOGIN_BUTTON_SELECTOR`

Selectors are CSS, e.g. `#userId` or `input[name="password"]`.

## Step 2: Log in and find the OTP field

```bash
python login.py
```

This fills in your ID/password and submits. If an OTP screen appears, run
`recon.py`'s inspection logic in your head against what you see (or rerun
`recon.py` — it's safe to run again mid-session against whatever page is
loaded) to find the OTP input's selector, then set in `.env`:

- `IRPSM_OTP_SELECTOR`
- `IRPSM_OTP_SUBMIT_SELECTOR` (if a separate submit button confirms the OTP)

Re-run `python login.py`. It will now pause and prompt you to type the OTP
you receive, then save your authenticated session to `storage_state.json`
(gitignored — never commit this file, it's equivalent to being logged in).

## Step 3: Find the works listing URL

```bash
python recon_dashboard.py
```

Lists every link on the post-login dashboard. Find the one for "Works" (or
whatever it's labeled) and set `IRPSM_WORKS_URL` in `.env` to its full URL.

## Step 4: Filtering to PH 53

Only "PH 53" works are wanted, not the full listing. Run:

```bash
python recon_works.py
```

This opens the works page and dumps every dropdown/text input/button
(`recon_output/works_controls.json` + a screenshot) — look for a
Phase-related `<select>` and check its `options` list for an entry like
`PH 53` or `Phase 53`. Then set in `.env`:

- `IRPSM_FILTER_SELECTOR` — CSS selector for that control
- `IRPSM_FILTER_TYPE` — `select` (dropdown) or `text` (free-text box)
- `IRPSM_FILTER_VALUE` — the exact option text/value, e.g. `PH 53`
- `IRPSM_FILTER_SUBMIT_SELECTOR` — only if a separate "Search"/"Go" button
  applies the filter (leave blank if selecting the dropdown reloads
  automatically)

If you can't find a working filter control, that's fine — leave
`IRPSM_FILTER_SELECTOR` blank. `scrape_works.py` always applies a
**client-side safety net** afterwards: any scraped row that doesn't
contain `IRPSM_ROW_FILTER_TEXT` (defaults to `PH 53`) in any column is
dropped before writing the CSV. This means the final output is always
PH 53-only even if the site-side filter isn't wired up, at the cost of
still crawling the full listing first.

## Step 5: Scrape

```bash
python scrape_works.py
```

Visits the works URL, applies the PH 53 filter (if configured), extracts
every `<table>` row, follows "Next" page links automatically, drops any
row that doesn't mention "PH 53" (the safety net above), and writes the
result to `output/works.csv`.

If the works list isn't a plain HTML `<table>` (e.g. it's a JS grid built
from `<div>`s), open `recon_output/works_page.png`, look at the real page
structure in your browser's dev tools, and set `IRPSM_TABLE_SELECTOR` /
`IRPSM_NEXT_PAGE_SELECTOR` in `.env` to match. This is the part most
likely to need a small tweak, since the site's markup can't be inspected
in advance.

## Step 6: Google Sheets setup

1. Go to https://console.cloud.google.com/, create (or pick) a project.
2. Enable the **Google Sheets API** and **Google Drive API**.
3. Create a **Service Account** (IAM & Admin → Service Accounts), then
   create a JSON key for it and download it as `scraper/service_account.json`
   (gitignored — never commit it).
4. Note the service account's email (looks like
   `xyz@project.iam.gserviceaccount.com`).

The upload script creates the sheet under the service account itself. To
see/edit it in your own Google account, either:
- share the sheet (once created) with your own email from within Sheets, or
- pre-create an empty Google Sheet in your own account named to match
  `GOOGLE_SHEET_NAME` in `.env`, and share **that** sheet with the service
  account's email (Editor access) before running the upload.

```bash
python upload_to_sheets.py
```

This reads `output/works.csv` and writes it into the sheet, printing the
sheet's URL when done.

## Re-running later

OTPs expire, so you'll need `python login.py` again each session (it
overwrites `storage_state.json`). After that, `scrape_works.py` and
`upload_to_sheets.py` can be re-run any time to refresh the data.
