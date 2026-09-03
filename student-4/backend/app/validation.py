"""Request validation for the Inventory and Stock API.

Keeps every business rule in one place so POST, PUT and the AI endpoint all
agree on what a valid stock record looks like.
"""

import re

from .config import Config

SKU_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_]{2,31}$")


class ValidationError(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def clean_stock(payload, partial=False):
    """Validate and normalise a stock payload.

    ``partial=True`` (PUT) allows a subset of fields; missing fields are simply
    left out so the database microservice keeps the stored values.
    """
    if not isinstance(payload, dict):
        raise ValidationError(["request body must be a JSON object"])

    errors = []
    cleaned = {}

    def present(field):
        return field in payload and payload[field] not in (None, "")

    # --- sku ---------------------------------------------------------------
    if present("sku"):
        sku = str(payload["sku"]).strip().upper()
        if not SKU_PATTERN.match(sku):
            errors.append("sku must be 3-32 characters: letters, digits, hyphen or underscore")
        else:
            cleaned["sku"] = sku
    elif not partial:
        errors.append("sku is required")

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
        category = str(payload["category"]).strip()
        if not 2 <= len(category) <= 60:
            errors.append("category must be between 2 and 60 characters")
        else:
            cleaned["category"] = category
    elif not partial:
        errors.append("category is required")

    # --- location ----------------------------------------------------------
    if present("location"):
        location = str(payload["location"]).strip()
        if not 2 <= len(location) <= 100:
            errors.append("location must be between 2 and 100 characters")
        else:
            cleaned["location"] = location
    elif not partial:
        errors.append("location is required")

    # --- quantity ----------------------------------------------------------
    if present("quantity"):
        try:
            quantity = int(str(payload["quantity"]).strip())
        except (TypeError, ValueError):
            errors.append("quantity must be an integer")
        else:
            if not Config.QUANTITY_MIN <= quantity <= Config.QUANTITY_MAX:
                errors.append("quantity must be between {} and {}".format(
                    Config.QUANTITY_MIN, Config.QUANTITY_MAX))
            else:
                cleaned["quantity"] = quantity
    elif not partial:
        errors.append("quantity is required")

    # --- restock_threshold -------------------------------------------------
    if present("restock_threshold"):
        try:
            threshold = int(str(payload["restock_threshold"]).strip())
        except (TypeError, ValueError):
            errors.append("restock_threshold must be an integer")
        else:
            if not Config.RESTOCK_THRESHOLD_MIN <= threshold <= Config.RESTOCK_THRESHOLD_MAX:
                errors.append("restock_threshold must be between {} and {}".format(
                    Config.RESTOCK_THRESHOLD_MIN, Config.RESTOCK_THRESHOLD_MAX))
            else:
                cleaned["restock_threshold"] = threshold
    elif not partial:
        errors.append("restock_threshold is required")

    # --- stock_level (optional, computed from quantity vs threshold) ------
    if present("stock_level"):
        stock_level = str(payload["stock_level"]).strip().lower()
        if stock_level not in Config.VALID_STOCK_LEVELS:
            errors.append("stock_level must be one of {}".format(
                ", ".join(Config.VALID_STOCK_LEVELS)))
        else:
            cleaned["stock_level"] = stock_level

    if errors:
        raise ValidationError(errors)
    if partial and not cleaned:
        raise ValidationError(["no updatable fields supplied"])
    return cleaned
