# Website Gap Lead Finder

Desktop lead finder for web developers and agencies. It opens Google Maps, searches business categories by location, keeps only businesses that do not show a website, and exports outreach-ready contact data.

## Output files

- `final_leads.csv` in the project root: client-ready rows with lead ID, business name, profession, phone, email, opening time, closing time, Map URL, and search query.
- `morning_leads.csv` in the project root: saved leads whose opening time is before 12:00 PM.
- `evening_leads.csv` in the project root: saved leads whose opening time is 12:00 PM or later.
- `logs/leads_full_database.csv`: full lead record for deal tracking, including ID, name, category, address, Google Maps URL, reviews, description, opening/closing hours, query, and scrape time.
- `logs/scraper.log`: runtime log for debugging failed searches.

Every contact gets a stable `GM-...` lead ID. Phone numbers are normalized before saving, so the same number is written only once across later runs too. Use the lead ID in `logs/leads_full_database.csv` to find the Google Maps URL and study a client before a deal.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

## Run

```bash
python app.py
```

Use one or more business keywords like `Restaurants, Cafes, Dentists`, add one or more locations separated by commas, set the number of saved leads you want, and click `Find Leads`.

## Project Structure

```text
app.py                    # Small launcher
ui/app_window.py          # CustomTkinter desktop UI
backend/config.py         # Paths, defaults, suggestions
backend/models.py         # Lead model and export row helpers
backend/identity.py       # Stable ID and phone/email normalization
backend/deduplication.py  # Duplicate filtering by phone/email
backend/scraper.py        # Google Maps Playwright scraper
backend/storage.py        # CSV export and existing-file checks
backend/logging_config.py # Runtime logging setup
logs/                     # Full lead database and scraper logs at runtime
```

Use this responsibly and follow the rules of the sites and regions you operate in.
