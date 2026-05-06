from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
GOOGLE_MAPS_URL = "https://www.google.com/maps"
ALERT_AUDIO_FILE = ROOT_DIR / "alert" / "alert.mp3"

OUTREACH_CONTACTS_FILE = ROOT_DIR / "outreach_contacts.csv"
FINAL_LEADS_FILE = ROOT_DIR / "final_leads.csv"
MORNING_LEADS_FILE = ROOT_DIR / "morning_leads.csv"
EVENING_LEADS_FILE = ROOT_DIR / "evening_leads.csv"
LEGACY_OUTREACH_CONTACTS_FILE = OUTREACH_CONTACTS_FILE
LOG_DIR = ROOT_DIR / "logs"
FULL_LEAD_LOG_FILE = LOG_DIR / "leads_full_database.csv"
RUNTIME_LOG_FILE = LOG_DIR / "scraper.log"

DEFAULT_MAX_RESULTS = 20
DEFAULT_WORKERS = 1

SUGGESTED_BUSINESS_TYPES = [
    "Restaurants",
    "Cafes",
    "Coffee Shops",
    "Plumbers",
    "Electricians",
    "Roofers",
    "HVAC Contractors",
    "Real Estate Agents",
    "Dentists",
    "Dental Clinics",
    "Chiropractors",
    "Gyms",
    "Law Firms",
    "Auto Repair Shops",
    "Mechanics",
    "Hair Salons",
    "Barbershops",
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
    "Day Spas",
    "Pet Groomers",
    "Tattoo Shops",
    "Furniture Stores",
]

KEYWORD_VARIATIONS = {
    "restaurant": ["restaurant", "restaurants", "diner", "eatery", "cafe"],
    "cafe": ["cafe", "cafes", "coffee shop"],
    "coffee shop": ["coffee shop", "coffee shops", "cafe"],
    "plumber": ["plumber", "plumbers", "plumbing service", "plumbing contractor"],
    "electrician": ["electrician", "electricians", "electrical contractor"],
    "roofer": ["roofer", "roofers", "roofing contractor"],
    "hvac contractor": ["hvac contractor", "hvac company", "air conditioning repair", "heating repair"],
    "real estate agent": ["real estate agent", "property dealer", "realtor"],
    "dentist": ["dentist", "dentists", "dental clinic", "dental care"],
    "dental clinic": ["dental clinic", "dentist", "dental care"],
    "chiropractor": ["chiropractor", "chiropractors", "spine clinic"],
    "gym": ["gym", "gyms", "fitness center", "fitness club"],
    "law firm": ["law firm", "law firms", "attorney office", "legal services"],
    "auto repair shop": ["auto repair shop", "mechanic", "car repair", "auto workshop"],
    "mechanic": ["mechanic", "auto repair shop", "car repair"],
    "hair salon": ["hair salon", "hair salons", "beauty salon"],
    "barbershop": ["barbershop", "barber shop", "barber"],
    "landscaping service": ["landscaping service", "landscaper", "garden service"],
    "cleaning service": ["cleaning service", "house cleaning", "commercial cleaning"],
    "accountant": ["accountant", "accountants", "tax consultant", "bookkeeper"],
    "pest control": ["pest control", "exterminator", "pest service"],
    "moving company": ["moving company", "movers", "relocation service"],
    "veterinarian": ["veterinarian", "vet clinic", "animal hospital"],
    "car wash": ["car wash", "auto detailing", "detailing service"],
    "boutique": ["boutique", "boutiques", "fashion store"],
    "bakery": ["bakery", "bakeries", "cake shop"],
    "clinic": ["clinic", "medical clinic", "health clinic"],
    "day spa": ["day spa", "spa", "beauty spa"],
    "pet groomer": ["pet groomer", "pet grooming", "dog grooming"],
    "tattoo shop": ["tattoo shop", "tattoo studio"],
    "furniture store": ["furniture store", "furniture shop", "home furniture"],
}
