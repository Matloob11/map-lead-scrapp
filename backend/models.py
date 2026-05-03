from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

from .identity import build_lead_id, utc_timestamp


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

    def as_full_row(self) -> dict:
        return asdict(self)

    def as_final_row(self) -> dict:
        return {
            "lead_id": self.lead_id,
            "phone_number": self.phone_number,
            "profession": self.profession,
            "store_title": self.store_title,
            "email": self.email,
        }
