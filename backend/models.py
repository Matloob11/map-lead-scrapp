from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Optional

from .identity import build_lead_id, utc_timestamp


TIME_VALUE_PATTERN = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([AP]M)\s*$", re.IGNORECASE)


def classify_opening_period(opening_time: str) -> str:
    parsed_time = parse_time_value(opening_time)
    if not parsed_time:
        return "unknown"

    hours, _minutes = parsed_time
    return "morning" if hours < 12 else "evening"


def parse_time_value(value: str) -> Optional[tuple[int, int]]:
    match = TIME_VALUE_PATTERN.match(value or "")
    if not match:
        return None

    hours = int(match.group(1)) % 12
    minutes = int(match.group(2) or 0)
    meridiem = match.group(3).upper()

    if meridiem == "PM":
        hours += 12

    return hours, minutes


@dataclass
class Lead:
    lead_id: str = ""
    business_name: str = ""
    category: str = ""
    address: str = ""
    phone_number: str = ""
    email: str = ""
    website: str = ""
    has_website: bool = False
    map_link: str = ""
    reviews_count: Optional[int] = None
    reviews_average: Optional[float] = None
    description: str = ""
    opening_time: str = ""
    closing_time: str = ""
    opening_period: str = ""
    hours_summary: str = ""
    search_query: str = ""
    source: str = "Google Maps"
    scraped_at: str = field(default_factory=utc_timestamp)

    @property
    def is_target(self) -> bool:
        return not self.has_website

    @property
    def has_contact(self) -> bool:
        return bool(self.phone_number or self.email)

    @property
    def store_title(self) -> str:
        return self.business_name

    @property
    def profession(self) -> str:
        return self.category or self.search_query

    def finalize_identity(self) -> None:
        self.lead_id = build_lead_id(
            business_name=self.business_name,
            phone_number=self.phone_number,
            email=self.email,
            address=self.address,
            map_link=self.map_link,
        )
        self.opening_period = classify_opening_period(self.opening_time)

    def as_full_row(self) -> dict:
        return asdict(self)

    def as_final_row(self) -> dict:
        return {
            "lead_id": self.lead_id,
            "store_title": self.store_title,
            "profession": self.profession,
            "phone_number": self.phone_number,
            "email": self.email,
            "opening_time": self.opening_time,
            "closing_time": self.closing_time,
            "opening_period": self.opening_period,
            "map_link": self.map_link,
            "search_query": self.search_query,
        }
