from __future__ import annotations

import logging
import os
import platform
import re
import urllib.parse
from typing import Callable, Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from .config import GOOGLE_MAPS_URL
from .models import Lead
from .session_cache import get_seen_urls, mark_url_seen

import threading

class ScraperControl:
    def __init__(self, on_auto_pause: Optional[Callable] = None):
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._stop_event = threading.Event()
        self.on_auto_pause = on_auto_pause

    def is_stopped(self) -> bool:
        return self._stop_event.is_set()

    def wait_if_paused(self):
        self._pause_event.wait()

    def pause(self):
        self._pause_event.clear()

    def trigger_auto_pause(self, msg: str):
        self.pause()
        if self.on_auto_pause:
            self.on_auto_pause(msg)

    def resume(self):
        self._pause_event.set()

    def stop(self):
        self._stop_event.set()
        self._pause_event.set() # Unpause to let it terminate


RESULT_SELECTOR = 'a.hfpxzc, a[href*="/maps/place"]'
EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
NOISE_EMAIL_DOMAINS = {
    "google.com",
    "gstatic.com",
    "googleusercontent.com",
    "schema.org",
}


def run_single_search(
    query: str, 
    total: Optional[int], 
    on_lead_extracted: Callable[[Lead], None] = None,
    control: Optional[ScraperControl] = None,
    headless: bool = False
) -> list[Lead]:
    if control and control.is_stopped():
        return []
    if total is not None and total <= 0:
        return []

    leads: list[Lead] = []

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright, headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 850},
            locale="en-US",
        )
        page = context.new_page()
        details_page = context.new_page()

        try:
            logging.info("Task started: %s", query)
            search_mode = _open_search_results(page, query, control)

            if search_mode == "single_place":
                lead = extract_place(page, query)
                if lead.business_name and lead.is_target:
                    leads.append(lead)
                    if on_lead_extracted:
                        on_lead_extracted(lead)
                    logging.info(
                        "Single place target found: %s | %s | Phone: %s | Email: %s | URL: %s",
                        lead.lead_id,
                        lead.business_name,
                        lead.phone_number or "-",
                        lead.email or "-",
                        lead.map_link,
                    )
                return leads

            if search_mode == "empty":
                return leads

            global_seen_links = get_seen_urls(query)
            already_done = len(global_seen_links)
            if already_done:
                logging.info("Resuming '%s': skipping %d already-processed URLs.", query, already_done)
            extracted_count = 0
            stagnant_rounds = 0
            
            # Using 500 max scrolls as a generous upper limit for infinite search
            max_scrolls = 500 if total is None else 500

            for _ in range(max_scrolls):
                if control:
                    control.wait_if_paused()
                    if control.is_stopped():
                        logging.info("Search stopped manually.")
                        break

                current_links = _read_place_links(page)
                new_links = [link for link in current_links if link not in global_seen_links]

                for place_link in new_links:
                    if control:
                        control.wait_if_paused()
                        if control.is_stopped():
                            break
                    
                    if total is not None and extracted_count >= total:
                        break

                    global_seen_links.add(place_link)
                    
                    try:
                        details_page.goto(place_link, wait_until="domcontentloaded", timeout=60000)
                        details_page.wait_for_selector("h1.DUwDvf", timeout=15000)
                        details_page.wait_for_timeout(900)

                        lead = extract_place(details_page, query)
                        if not lead.business_name:
                            mark_url_seen(query, place_link)
                            continue

                        # Professional Double Verification:
                        # If Google Maps doesn't list a website, search Google to make absolutely sure.
                        if not lead.has_website:
                            verified_has_website = _verify_website_via_google_search(details_page, lead.business_name, lead.address, control)
                            if verified_has_website:
                                lead.has_website = True

                        if lead.has_website:
                            logging.debug(
                                "Skipped website-owned listing: %s | %s",
                                lead.business_name,
                                lead.map_link,
                            )
                        else:
                            leads.append(lead)
                            if on_lead_extracted:
                                on_lead_extracted(lead)
                            logging.info(
                                "Target found: %s | %s | Phone: %s | Email: %s | URL: %s",
                                lead.lead_id,
                                lead.business_name,
                                lead.phone_number or "-",
                                lead.email or "-",
                                lead.map_link,
                            )
                        
                        mark_url_seen(query, place_link)
                        extracted_count += 1
                    except Exception as exc:
                        logging.warning("Failed to extract listing for %s: %s", query, exc)

                if total is not None and extracted_count >= total:
                    break
                    
                if control and control.is_stopped():
                    break

                if not new_links:
                    stagnant_rounds += 1
                    if stagnant_rounds >= 3:
                        logging.info("Reached end of scroll list for %s.", query)
                        break
                else:
                    stagnant_rounds = 0

                try:
                    page.locator(RESULT_SELECTOR).first.hover(timeout=2000)
                except Exception:
                    pass

                page.mouse.wheel(0, 7000)
                page.wait_for_timeout(1500)

        finally:
            details_page.close()
            context.close()
            browser.close()

    return leads


def extract_place(page: Page, search_query: str) -> Lead:
    website = _first_attr(page, ['a[data-item-id="authority"]'], "href")
    if not website:
        website = _first_text(page, ['a[data-item-id="authority"] .Io6YTe'])

    lead = Lead(
        business_name=_first_text(page, ["h1.DUwDvf"]),
        category=_first_text(
            page,
            [
                'button[jsaction*="pane.rating.category"]',
                "button.DkEaL",
                "div.LBgpqf button",
            ],
        ),
        address=_first_text(
            page,
            [
                'button[data-item-id="address"] .Io6YTe',
                'button[data-item-id="address"]',
            ],
        ),
        phone_number=_first_text(
            page,
            [
                'button[data-item-id^="phone:tel:"] .Io6YTe',
                'button[data-item-id^="phone:tel:"]',
                'a[href^="tel:"]',
            ],
        ),
        email=_extract_email_from_panel(page),
        website=website,
        has_website=bool(website),
        map_link=page.url,
        reviews_count=_extract_reviews_count(page),
        reviews_average=_extract_reviews_average(page),
        description=_first_text(page, [".PYvSYb", ".WeS02d"]),
        search_query=search_query,
    )
    lead.finalize_identity()
    return lead


def _launch_browser(playwright, headless: bool = False):
    launch_kwargs = {"headless": headless}

    if platform.system() == "Windows":
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        if os.path.exists(chrome_path):
            try:
                return playwright.chromium.launch(executable_path=chrome_path, **launch_kwargs)
            except Exception:
                logging.warning("System Chrome launch failed. Falling back to Playwright Chromium.")

    return playwright.chromium.launch(**launch_kwargs)

def _verify_website_via_google_search(page: Page, business_name: str, address: str, control: Optional[ScraperControl] = None) -> bool:
    """Returns True if a likely official website is found via Google Search."""
    while True:
        try:
            location_part = address if address else ""
            search_query = f"{business_name} {location_part}".strip()
            url = "https://www.google.com/search?q=" + urllib.parse.quote(search_query)
            
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            
            try:
                page.wait_for_selector("div#search", timeout=10000)
            except Exception:
                if control:
                    control.trigger_auto_pause("Google Search blocked (CAPTCHA). Please solve in browser and click Resume.")
                    control.wait_if_paused()
                    if control.is_stopped():
                        return False
                    continue # Retry after resume
                return False
                
            links = page.locator("div#search a").evaluate_all("elements => elements.map(e => e.href)")
        
            ignore_domains = [
                "facebook.com", "instagram.com", "yelp.com", "yellowpages.com", 
                "linkedin.com", "twitter.com", "tiktok.com", "mapquest.com", 
                "foursquare.com", "zoominfo.com", "tripadvisor.com", "justdial.com",
                "indiamart.com", "pinterest.com", "youtube.com", "trustpilot.com", 
                "glassdoor.com", "bbb.org", "chamberofcommerce.com", "whatsapp.com",
                "zomato.com", "swiggy.com", "ubereats.com", "doordash.com", "grubhub.com",
                "yellowbot.com", "manta.com", "angi.com", "houzz.com"
            ]
            
            valid_links_checked = 0
            for href in links:
                if not href or not href.startswith("http"):
                    continue
                    
                if "google." in href:
                    continue
                    
                try:
                    domain = href.split("/")[2].lower().replace("www.", "")
                    
                    is_noise = any(noise in domain for noise in ignore_domains)
                    if not is_noise:
                        return True
                        
                    valid_links_checked += 1
                    if valid_links_checked >= 4:
                        break
                except Exception:
                    pass
                    
            return False
        except Exception as e:
            logging.warning("Verification search failed: %s", e)
            return False


def _open_search_results(page: Page, query: str, control: Optional[ScraperControl] = None) -> str:
    while True:
        page.goto(GOOGLE_MAPS_URL, wait_until="domcontentloaded", timeout=60000)
        _accept_consent_if_needed(page)

        search_input = page.locator('input#searchboxinput, input[role="combobox"]').first
        search_input.wait_for(state="visible", timeout=15000)
        search_input.fill(query)
        page.keyboard.press("Enter")

        try:
            page.wait_for_selector(RESULT_SELECTOR, timeout=22000)
            return "result_list"
        except PlaywrightTimeoutError:
            try:
                page.wait_for_selector("h1.DUwDvf", timeout=6000)
                return "single_place"
            except PlaywrightTimeoutError:
                if control:
                    control.trigger_auto_pause(f"Maps empty/CAPTCHA for '{query}'. Solve and click Resume.")
                    control.wait_if_paused()
                    if control.is_stopped():
                        return "empty"
                    continue
                logging.warning("No map results were found for %s", query)
                return "empty"



def _read_place_links(page: Page) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    locator = page.locator(RESULT_SELECTOR)

    try:
        count = locator.count()
    except Exception:
        return links

    for index in range(count):
        try:
            href = locator.nth(index).get_attribute("href")
        except Exception:
            continue

        if not href or "/maps/place" not in href or href in seen:
            continue
        seen.add(href)
        links.append(href)

    return links


def _accept_consent_if_needed(page: Page) -> None:
    for selector in [
        'button[aria-label="Accept all"]',
        'button:has-text("Accept all")',
        'button:has-text("I agree")',
    ]:
        try:
            button = page.locator(selector).first
            if button.is_visible(timeout=2500):
                button.click()
                return
        except Exception:
            continue


def _first_text(page: Page, selectors: list[str]) -> str:
    for selector in selectors:
        text = _extract_text(page, selector)
        if text:
            return text
    return ""


def _first_attr(page: Page, selectors: list[str], attribute: str) -> str:
    for selector in selectors:
        value = _extract_attr(page, selector, attribute)
        if value:
            return value
    return ""


def _extract_text(page: Page, selector: str) -> str:
    try:
        locator = page.locator(selector).first
        if locator.count() > 0:
            return _squash_whitespace(locator.inner_text(timeout=1500))
    except Exception:
        return ""
    return ""


def _extract_attr(page: Page, selector: str, attribute: str) -> str:
    try:
        locator = page.locator(selector).first
        if locator.count() > 0:
            value = locator.get_attribute(attribute, timeout=1500)
            return value.strip() if value else ""
    except Exception:
        return ""
    return ""


def _extract_email_from_panel(page: Page) -> str:
    for selector in ["div[role='main']", "div.m6QErb", "body"]:
        text = _extract_text(page, selector)
        email = _first_email(text)
        if email:
            return email
    return ""


def _first_email(text: str) -> str:
    for match in EMAIL_PATTERN.findall(text or ""):
        email = match.strip(".,;:()[]{}<>").lower()
        domain = email.rsplit("@", 1)[-1]
        if domain not in NOISE_EMAIL_DOMAINS:
            return email
    return ""


def _extract_reviews_count(page: Page) -> Optional[int]:
    candidates = [
        _extract_text(page, 'button[jsaction*="pane.reviewChart.moreReviews"]'),
        _extract_text(page, 'span[aria-label*="reviews"]'),
        _extract_text(page, "span.F7k0ej"),
    ]

    for raw in candidates:
        if not raw:
            continue
        match = re.search(r"([\d,]+)", raw)
        if match:
            try:
                return int(match.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _extract_reviews_average(page: Page) -> Optional[float]:
    candidates = [
        _extract_text(page, 'div.F7nice span[aria-hidden="true"]'),
        _extract_text(page, "span.ce80pc"),
    ]

    for raw in candidates:
        match = re.search(r"\d(?:[\.,]\d)?", raw or "")
        if match:
            try:
                return float(match.group(0).replace(",", "."))
            except ValueError:
                continue
    return None


def _squash_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
