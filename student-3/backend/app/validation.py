"""Customer input validation shared by create and update routes."""

import re
from datetime import date

from .config import Config

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class ValidationError(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def clean_customer(payload, partial=False):
    if not isinstance(payload, dict):
        raise ValidationError(["request body must be a JSON object"])

    errors = []
    cleaned = {}

    def present(field):
        return field in payload and payload[field] not in (None, "")

    if present("name"):
        name = str(payload["name"]).strip()
        if not 2 <= len(name) <= 120:
            errors.append("name must be between 2 and 120 characters")
        else:
            cleaned["name"] = name
    elif not partial:
        errors.append("name is required")

    if present("email"):
        email = str(payload["email"]).strip().lower()
        if len(email) > 254 or not EMAIL_PATTERN.fullmatch(email):
            errors.append("email must be a valid email address")
        else:
            cleaned["email"] = email
    elif not partial:
        errors.append("email is required")

    for field, maximum in (("phone", 40), ("address", 500)):
        if field in payload:
            value = str(payload.get(field) or "").strip()
            if len(value) > maximum:
                errors.append("{} must be {} characters or fewer".format(field, maximum))
            else:
                cleaned[field] = value or None
        elif not partial:
            cleaned[field] = None

    if present("loyalty_tier"):
        tier = str(payload["loyalty_tier"]).strip().title()
        if tier not in Config.LOYALTY_TIERS:
            errors.append("loyalty_tier must be one of {}".format(
                ", ".join(Config.LOYALTY_TIERS)))
        else:
            cleaned["loyalty_tier"] = tier
    elif not partial:
        cleaned["loyalty_tier"] = "Bronze"

    if present("joined_at"):
        joined_at = str(payload["joined_at"]).strip()
        try:
            parsed = date.fromisoformat(joined_at)
        except ValueError:
            errors.append("joined_at must be an ISO date in YYYY-MM-DD format")
        else:
            cleaned["joined_at"] = parsed.isoformat()
    elif not partial:
        cleaned["joined_at"] = date.today().isoformat()

    if errors:
        raise ValidationError(errors)
    if partial and not cleaned:
        raise ValidationError(["no updatable fields supplied"])
    return cleaned
