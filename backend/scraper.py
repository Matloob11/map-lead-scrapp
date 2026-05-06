from __future__ import annotations

from datetime import datetime
import logging
import os
import platform
import re
import threading
import urllib.parse
from typing import Callable, Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from .config import GOOGLE_MAPS_URL
from .models import Lead
from .session_cache import get_seen_urls, mark_url_seen


RESULT_SELECTOR = 'a.hfpxzc, a[href*="/maps/place"]'
EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
NOISE_EMAIL_DOMAINS = {
    "google.com",
    "gstatic.com",
    "googleusercontent.com",
    "schema.org",
}
TIME_TOKEN_PATTERN = r"(?:1[0-2]|0?\d)(?::[0-5]\d)?\s*(?:AM|PM)"
TIME_RANGE_PATTERN = re.compile(
    rf"({TIME_TOKEN_PATTERN})\s*(?:-|[\u2013\u2014]|to)\s*({TIME_TOKEN_PATTERN})",
    re.IGNORECASE,
)
DAY_MARKER_PATTERN = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Today)",
    re.IGNORECASE,
)
_WEBSITE_VERIFICATION_CACHE: dict[str, bool] = {}
_WEBSITE_VERIFICATION_LOCK = threading.Lock()


class ScraperControl:
    def __init__(self, on_auto_pause: Optional[Callable] = None):
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._stop_event = threading.Event()
        self._stop_reason = ""
        self.on_auto_pause = on_auto_pause

    def is_stopped(self) -> bool:
        return self._stop_event.is_set()

    def stop_reason(self) -> str:
        return self._stop_reason

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

    def stop(self, reason: str = "manual"):
        self._stop_reason = reason
        self._stop_event.set()
        self._pause_event.set()


def run_single_search(
    query: str,
    target_saved: Optional[int],
    on_lead_extracted: Optional[Callable[[Lead], bool]] = None,
    control: Optional[ScraperControl] = None,
    headless: bool = False,
) -> list[Lead]:
    if control and control.is_stopped():
        return []
    if target_saved is not None and target_saved <= 0:
        return []

    leads: list[Lead] = []
    accepted_count = 0

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
                if lead.business_name and not lead.has_website:
                    verified_has_website = _verify_website_via_google_search(
                        page,
                        lead.business_name,
                        lead.address,
                        control,
                    )
                    if verified_has_website:
                        lead.has_website = True
                if lead.business_name and lead.is_target:
                    accepted = _accept_extracted_lead(lead, leads, on_lead_extracted)
                    if accepted:
                        accepted_count += 1
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
            stagnant_rounds = 0
            max_scrolls = 2000

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

                    if (
                        target_saved is not None
                        and on_lead_extracted is None
                        and accepted_count >= target_saved
                    ):
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

                        if not lead.has_website:
                            verified_has_website = _verify_website_via_google_search(
                                details_page,
                                lead.business_name,
                                lead.address,
                                control,
                            )
                            if verified_has_website:
                                lead.has_website = True

                        if lead.has_website:
                            logging.debug(
                                "Skipped website-owned listing: %s | %s",
                                lead.business_name,
                                lead.map_link,
                            )
                        else:
                            accepted = _accept_extracted_lead(lead, leads, on_lead_extracted)
                            if accepted:
                                accepted_count += 1
                            logging.info(
                                "Target found: %s | %s | Phone: %s | Email: %s | URL: %s",
                                lead.lead_id,
                                lead.business_name,
                                lead.phone_number or "-",
                                lead.email or "-",
                                lead.map_link,
                            )

                        mark_url_seen(query, place_link)
                    except Exception as exc:
                        logging.warning("Failed to extract listing for %s: %s", query, exc)

                if (
                    target_saved is not None
                    and on_lead_extracted is None
                    and accepted_count >= target_saved
                ):
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
    opening_time, closing_time, hours_summary = _extract_business_hours(page)

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
        opening_time=opening_time,
        closing_time=closing_time,
        hours_summary=hours_summary,
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


def _accept_extracted_lead(
    lead: Lead,
    leads: list[Lead],
    on_lead_extracted: Optional[Callable[[Lead], bool]] = None,
) -> bool:
    leads.append(lead)
    if on_lead_extracted:
        return bool(on_lead_extracted(lead))
    return bool(lead.has_contact)


def _verify_website_via_google_search(
    page: Page,
    business_name: str,
    address: str,
    control: Optional[ScraperControl] = None,
) -> bool:
    cache_key = _website_verification_cache_key(business_name, address)
    if cache_key:
        with _WEBSITE_VERIFICATION_LOCK:
            if cache_key in _WEBSITE_VERIFICATION_CACHE:
                return _WEBSITE_VERIFICATION_CACHE[cache_key]

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
                        _cache_website_verification(cache_key, False)
                        return False
                    continue
                _cache_website_verification(cache_key, False)
                return False

            links = page.locator("div#search a").evaluate_all("elements => elements.map(e => e.href)")

            ignore_domains = [
                "facebook.com",
                "instagram.com",
                "yelp.com",
                "yellowpages.com",
                "linkedin.com",
                "twitter.com",
                "tiktok.com",
                "mapquest.com",
                "foursquare.com",
                "zoominfo.com",
                "tripadvisor.com",
                "justdial.com",
                "indiamart.com",
                "pinterest.com",
                "youtube.com",
                "trustpilot.com",
                "glassdoor.com",
                "bbb.org",
                "chamberofcommerce.com",
                "whatsapp.com",
                "zomato.com",
                "swiggy.com",
                "ubereats.com",
                "doordash.com",
                "grubhub.com",
                "yellowbot.com",
                "manta.com",
                "angi.com",
                "houzz.com",
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
                        _cache_website_verification(cache_key, True)
                        return True

                    valid_links_checked += 1
                    if valid_links_checked >= 4:
                        break
                except Exception:
                    pass

            _cache_website_verification(cache_key, False)
            return False
        except Exception as exc:
            logging.warning("Verification search failed: %s", exc)
            _cache_website_verification(cache_key, False)
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


def _extract_business_hours(page: Page) -> tuple[str, str, str]:
    raw_texts = _collect_hours_texts(page)
    opening_time, closing_time = _parse_hours_from_texts(raw_texts)
    if opening_time or closing_time:
        return opening_time, closing_time, " | ".join(raw_texts)

    button = page.locator('button[data-item-id="oh"]').first
    opened_panel = False
    try:
        if button.count() > 0:
            button.click(timeout=1500)
            page.wait_for_timeout(600)
            opened_panel = True
            raw_texts.extend(_collect_hours_rows(page))
    except Exception:
        pass
    finally:
        if opened_panel:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass

    unique_texts = [value for value in dict.fromkeys(raw_texts) if value]
    opening_time, closing_time = _parse_hours_from_texts(unique_texts)
    return opening_time, closing_time, " | ".join(unique_texts)


def _collect_hours_texts(page: Page) -> list[str]:
    selectors = [
        ('button[data-item-id="oh"]', "aria-label"),
        ('button[data-item-id="oh"]', None),
        ('div[aria-label*="Hours"]', "aria-label"),
        ('div[aria-label*="Hours"]', None),
        ('button[aria-label*="open hours"]', "aria-label"),
        ('button[aria-label*="Open"]', "aria-label"),
        ('button[aria-label*="Closed"]', "aria-label"),
        ('button[aria-label*="Closes"]', "aria-label"),
        ('button[aria-label*="Opens"]', "aria-label"),
    ]

    values: list[str] = []
    for selector, attribute in selectors:
        extracted_values = (
            _extract_attr_values(page, selector, attribute)
            if attribute
            else _extract_text_values(page, selector)
        )
        for value in extracted_values:
            normalized = _squash_whitespace(value)
            if normalized and "suggest an edit" not in normalized.lower():
                values.append(normalized)

    return [value for value in dict.fromkeys(values) if value]


def _collect_hours_rows(page: Page) -> list[str]:
    selectors = [
        "table.eK4R0e tr",
        "div[role='dialog'] table tr",
        "table tr",
    ]

    row_texts: list[str] = []
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()
        except Exception:
            continue

        if count <= 0:
            continue

        for index in range(min(count, 10)):
            try:
                text = _squash_whitespace(locator.nth(index).inner_text(timeout=1000))
            except Exception:
                continue
            if text:
                row_texts.append(text)

        if row_texts:
            break

    return row_texts


def _parse_hours_from_texts(texts: list[str]) -> tuple[str, str]:
    if not texts:
        return "", ""

    today_name = datetime.now().strftime("%A")
    for text in texts:
        opening_time, closing_time = _parse_day_hours_segment(text, today_name)
        if opening_time or closing_time:
            return opening_time, closing_time

    for text in texts:
        opening_time, closing_time = _parse_time_range(text)
        if opening_time or closing_time:
            return opening_time, closing_time

    for text in texts:
        lower_text = text.lower()
        if "24 hours" in lower_text:
            return "12:00 AM", "11:59 PM"

        open_match = re.search(rf"opens?\s+({TIME_TOKEN_PATTERN})", text, re.IGNORECASE)
        close_match = re.search(rf"closes?\s+({TIME_TOKEN_PATTERN})", text, re.IGNORECASE)
        if open_match or close_match:
            return (
                _normalize_time_token(open_match.group(1)) if open_match else "",
                _normalize_time_token(close_match.group(1)) if close_match else "",
            )

    return "", ""


def _parse_day_hours_segment(text: str, today_name: str) -> tuple[str, str]:
    normalized = _squash_whitespace(text)
    if not normalized:
        return "", ""

    for marker in (today_name, "Today"):
        pattern = re.compile(
            rf"{marker}\s*:?\s*(.*?)(?=(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Today)\b|$)",
            re.IGNORECASE,
        )
        match = pattern.search(normalized)
        if not match:
            continue

        segment = match.group(1).strip(" .")
        if "24 hours" in segment.lower():
            return "12:00 AM", "11:59 PM"
        return _parse_time_range(segment)

    if DAY_MARKER_PATTERN.search(normalized):
        return "", ""
    return _parse_time_range(normalized)


def _parse_time_range(text: str) -> tuple[str, str]:
    matches = TIME_RANGE_PATTERN.findall(text or "")
    if not matches:
        return "", ""

    opening_time = _normalize_time_token(matches[0][0])
    closing_time = _normalize_time_token(matches[-1][1])
    return opening_time, closing_time


def _normalize_time_token(value: str) -> str:
    cleaned = _squash_whitespace(value).upper().replace(".", "")
    match = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*([AP]M)$", cleaned)
    if not match:
        return cleaned

    hours = int(match.group(1))
    minutes = match.group(2) or "00"
    meridiem = match.group(3)
    return f"{hours}:{minutes} {meridiem}"


def _website_verification_cache_key(business_name: str, address: str) -> str:
    normalized_name = _squash_whitespace((business_name or "").lower())
    normalized_address = _squash_whitespace((address or "").lower())
    if not normalized_name:
        return ""
    return f"{normalized_name}|{normalized_address}"


def _cache_website_verification(cache_key: str, value: bool) -> None:
    if not cache_key:
        return
    with _WEBSITE_VERIFICATION_LOCK:
        _WEBSITE_VERIFICATION_CACHE[cache_key] = value


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


def _extract_text_values(page: Page, selector: str, limit: int = 8) -> list[str]:
    values: list[str] = []
    try:
        locator = page.locator(selector)
        count = min(locator.count(), limit)
        for index in range(count):
            text = locator.nth(index).inner_text(timeout=1500)
            normalized = _squash_whitespace(text)
            if normalized:
                values.append(normalized)
    except Exception:
        return []
    return values


def _extract_attr_values(page: Page, selector: str, attribute: str, limit: int = 8) -> list[str]:
    values: list[str] = []
    try:
        locator = page.locator(selector)
        count = min(locator.count(), limit)
        for index in range(count):
            value = locator.nth(index).get_attribute(attribute, timeout=1500)
            normalized = _squash_whitespace(value or "")
            if normalized:
                values.append(normalized)
    except Exception:
        return []
    return values


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
