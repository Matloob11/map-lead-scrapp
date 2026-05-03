from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
GOOGLE_MAPS_URL = "https://www.google.com/maps"

OUTREACH_CONTACTS_FILE = ROOT_DIR / "outreach_contacts.csv"
FINAL_LEADS_FILE = ROOT_DIR / "final_leads.csv"
LEGACY_OUTREACH_CONTACTS_FILE = OUTREACH_CONTACTS_FILE
LOG_DIR = ROOT_DIR / "logs"
FULL_LEAD_LOG_FILE = LOG_DIR / "leads_full_database.csv"
RUNTIME_LOG_FILE = LOG_DIR / "scraper.log"

DEFAULT_MAX_RESULTS = 20
DEFAULT_WORKERS = 1

SUGGESTED_BUSINESS_TYPES = [
    "Restaurants",
    "Plumbers",
    "Electricians",
    "Roofers",
    "HVAC Contractors",
    "Real Estate Agents",
    "Dentists",
    "Chiropractors",
    "Gyms",
    "Law Firms",
    "Auto Repair Shops",
    "Hair Salons",
    "Landscaping Services",
    "Cleaning Services",
    "Accountants",
    "Pest Control",
    "Moving Companies",
    "Veterinarians",
    "Car Wash",
    "Boutiques",
    "Bakeries",
    "Clinics",
]
