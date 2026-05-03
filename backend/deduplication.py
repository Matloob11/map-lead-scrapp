from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from .identity import normalize_email, normalize_phone
from .models import Lead


@dataclass
class DeduplicationResult:
    unique_leads: list[Lead]
    actionable_count: int
    duplicate_count: int


def lead_contact_key(lead: Lead) -> str:
    return contact_key(
        phone_number=lead.phone_number,
        email=lead.email,
        lead_id=lead.lead_id,
    )


def contact_key(phone_number: str = "", email: str = "", lead_id: str = "") -> str:
    phone_key = normalize_phone(phone_number)
    if phone_key:
        return f"phone:{phone_key}"

    email_key = normalize_email(email)
    if email_key:
        return f"email:{email_key}"

    return f"id:{(lead_id or '').strip()}"


def dedupe_actionable_leads(
    leads: Iterable[Lead],
    existing_contact_keys: set[str] | None = None,
    log_duplicates: bool = True,
) -> DeduplicationResult:
    existing_contact_keys = existing_contact_keys or set()
    unique_leads: list[Lead] = []
    seen_contact_keys: set[str] = set()
    actionable_count = 0
    duplicate_count = 0

    for lead in leads:
        lead.finalize_identity()
        if not lead.is_target or not lead.has_contact:
            continue

        actionable_count += 1
        key = lead_contact_key(lead)
        if key in existing_contact_keys or key in seen_contact_keys:
            duplicate_count += 1
            if log_duplicates:
                logging.info(
                    "Duplicate skipped: %s | %s | %s | %s",
                    lead.lead_id,
                    key,
                    lead.business_name or "-",
                    lead.map_link or "-",
                )
            continue

        seen_contact_keys.add(key)
        unique_leads.append(lead)

    return DeduplicationResult(
        unique_leads=unique_leads,
        actionable_count=actionable_count,
        duplicate_count=duplicate_count,
    )
