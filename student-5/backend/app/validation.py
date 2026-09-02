"""Request validation for the Reviews and Ratings API.

Keeps every business rule in one place so POST and PUT agree on what a valid
review looks like.
"""

import re

from .config import Config

SKU_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_]{2,31}$")
USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_]{0,63}$")


class ValidationError(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def clean_review(payload, partial=False):
    """Validate and normalise a review payload.

    ``partial=True`` (PUT) allows a subset of fields; missing fields are simply
    left out so the database microservice keeps the stored values.
    """
    if not isinstance(payload, dict):
        raise ValidationError(["request body must be a JSON object"])

    errors = []
    cleaned = {}

    def present(field):
        return field in payload and payload[field] not in (None, "")

    # --- product_sku ---------------------------------------------------------
    if present("product_sku"):
        sku = str(payload["product_sku"]).strip().upper()
        if not SKU_PATTERN.match(sku):
            errors.append("product_sku must be 3-32 characters: letters, digits, hyphen or underscore")
        else:
            cleaned["product_sku"] = sku
    elif not partial:
        errors.append("product_sku is required")

    # --- user_id ---------------------------------------------------------------
    if present("user_id"):
        user_id = str(payload["user_id"]).strip()
        if not USER_ID_PATTERN.match(user_id):
            errors.append("user_id must be 1-64 characters: letters, digits, hyphen or underscore")
        else:
            cleaned["user_id"] = user_id
    elif not partial:
        errors.append("user_id is required")

    # --- rating ------------------------------------------------------------
    if present("rating"):
        try:
            rating = int(str(payload["rating"]).strip())
        except (TypeError, ValueError):
            errors.append("rating must be a whole number")
        else:
            if not Config.RATING_MIN <= rating <= Config.RATING_MAX:
                errors.append("rating must be between {} and {}".format(
                    Config.RATING_MIN, Config.RATING_MAX))
            else:
                cleaned["rating"] = rating
    elif not partial:
        errors.append("rating is required")

    # --- review --------------------------------------------------------------
    if present("review"):
        review = str(payload["review"]).strip()
        if not Config.REVIEW_MIN_CHARS <= len(review) <= Config.REVIEW_MAX_CHARS:
            errors.append("review must be between {} and {} characters".format(
                Config.REVIEW_MIN_CHARS, Config.REVIEW_MAX_CHARS))
        else:
            cleaned["review"] = review
    elif not partial:
        errors.append("review is required")

    if errors:
        raise ValidationError(errors)
    if partial and not cleaned:
        raise ValidationError(["no updatable fields supplied"])
    return cleaned
