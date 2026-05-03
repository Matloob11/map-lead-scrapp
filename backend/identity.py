from __future__ import annotations

import re
from datetime import datetime, timezone
from hashlib import sha1


PHONE_EXTENSION_PATTERN = re.compile(
    r"\b(?:ext|extension|x)\.?\s*\d+\b",
    re.IGNORECASE,
)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_phone(phone_number: str) -> str:
    digits = re.sub(r"\D", "", PHONE_EXTENSION_PATTERN.sub("", phone_number or ""))
    if len(digits) > 10:
        return digits[-10:]
    return digits


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def clean_identity_part(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def build_lead_id(
    business_name: str = "",
    phone_number: str = "",
    email: str = "",
    address: str = "",
    map_link: str = "",
) -> str:
    phone_key = normalize_phone(phone_number)
    email_key = normalize_email(email)

    if phone_key:
        seed = f"phone:{phone_key}"
    elif email_key:
        seed = f"email:{email_key}"
    else:
        identity_parts = [
            clean_identity_part(part)
            for part in (business_name, address, map_link)
            if part and part.strip()
        ]
        seed = "|".join(identity_parts) or utc_timestamp()

    return "GM-" + sha1(seed.encode("utf-8")).hexdigest()[:10].upper()
