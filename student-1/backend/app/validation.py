"""Request validation for the Product Catalogue API.

Keeps every business rule in one place so POST, PUT and the AI endpoint all
agree on what a valid product looks like.
"""

import re

from .config import Config

SKU_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_]{2,31}$")


def canonical_category(value):
    candidate = str(value).strip().casefold()
    for category in Config.VALID_CATEGORIES:
        if category.casefold() == candidate:
            return category
    return None


class ValidationError(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def clean_product(payload, partial=False):
    """Validate and normalise a product payload.

    ``partial=True`` (PUT) allows a subset of fields; missing fields are simply
    left out so the database microservice keeps the stored values.
    """
    if not isinstance(payload, dict):
        raise ValidationError(["request body must be a JSON object"])

    errors = []
    cleaned = {}

    def present(field):
        return field in payload and payload[field] not in (None, "")

    if present("sku"):
        sku = str(payload["sku"]).strip().upper()
        if not SKU_PATTERN.match(sku):
            errors.append(
                "sku must be 3-32 characters: letters, digits, hyphen or underscore"
            )
        else:
            cleaned["sku"] = sku

    # --- name --------------------------------------------------------------
    if present("name"):
        name = str(payload["name"]).strip()
        if not 2 <= len(name) <= 120:
            errors.append("name must be between 2 and 120 characters")
        else:
            cleaned["name"] = name
    elif not partial:
        errors.append("name is required")

    # --- category ----------------------------------------------------------
    if present("category"):
        category = canonical_category(payload["category"])
        if category is None:
            errors.append(
                "category must be one of {}".format(", ".join(Config.VALID_CATEGORIES))
            )
        else:
            cleaned["category"] = category
    elif not partial:
        errors.append("category is required")

    # --- price -------------------------------------------------------------
    if present("price"):
        try:
            price = float(
                str(payload["price"]).replace("$", "").replace(",", "").strip()
            )
        except (TypeError, ValueError):
            errors.append("price must be a number")
        else:
            if not Config.PRICE_MIN <= price <= Config.PRICE_MAX:
                errors.append(
                    "price must be between {} and {}".format(
                        Config.PRICE_MIN, Config.PRICE_MAX
                    )
                )
            else:
                cleaned["price"] = round(price, 2)
    elif not partial:
        errors.append("price is required")

    # --- description (optional) -------------------------------------------
    if present("description"):
        description = str(payload["description"]).strip()
        if len(description) > 1200:
            errors.append("description must be 1200 characters or fewer")
        else:
            cleaned["description"] = description
    elif not partial:
        cleaned["description"] = ""

    # --- status (optional, defaults to active) -----------------------------
    if present("status"):
        status = str(payload["status"]).strip().lower()
        if status not in Config.VALID_STATUSES:
            errors.append(
                "status must be one of {}".format(", ".join(Config.VALID_STATUSES))
            )
        else:
            cleaned["status"] = status
    elif not partial:
        cleaned["status"] = "active"

    if errors:
        raise ValidationError(errors)
    if partial and not cleaned:
        raise ValidationError(["no updatable fields supplied"])
    return cleaned
