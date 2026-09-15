# Website Gap Lead Finder

Desktop tool for agencies: open Google Maps, search business categories by location, keep only places that **do not show a website**, and export outreach CSVs.

## Output

| File | Contents |
| --- | --- |
| `final_leads.csv` | Client-ready: lead ID, name, profession, phone, email, open/close, Maps URL, query |
| `morning_leads.csv` | Opens before 12:00 |
| `evening_leads.csv` | Opens at/after 12:00 |
| `logs/leads_full_database.csv` | Full record (address, reviews, description, scrape time) |
| `logs/scraper.log` | Runtime log |

Every contact gets a stable `GM-…` ID. Phones are normalized so the same number is stored once across later runs. Use the ID in the full database CSV to reopen the Maps URL.

Default category suggestions in `backend/config.py` include restaurants, cafes, dentists, and similar local services.

## Stack

- Python
- CustomTkinter (`ui/app_window.py`)
- Playwright Chromium
- pygame for the alert sound

No `.env`.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

## Run

```bash
python app.py
```

Enter one or more keywords (`Restaurants, Cafes, Dentists`), comma-separated locations, how many leads to save, then **Find Leads**.

Follow Google Maps terms and local law. This is a research aid, not a license to scrape at scale.

## Layout

```text
app.py                    Launcher
ui/app_window.py          CustomTkinter UI
backend/config.py         Paths, defaults, suggestions
backend/models.py         Lead model, export rows
backend/identity.py       Stable ID, phone/email normalize
backend/deduplication.py
backend/scraper.py        Playwright Maps scraper
backend/storage.py
backend/logging_config.py
alert/
logs/
```

## License

See `LICENSE`.
