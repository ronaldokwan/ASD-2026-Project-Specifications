"""Pure functions exposed by the shared MCP server.

Callers supply grounded inputs; these tools make no LLM or service calls.
``server.py`` registers MCP tools and any required compatibility routes. See
``tool-contracts.md`` for the tool contracts.
"""

import re
from datetime import date

_URL_PATTERN = re.compile(r"https?://|www\.", re.IGNORECASE)
_SPAM_PHRASES = (
    "buy now",
    "click here",
    "discount code",
    "free money",
    "act now",
    "limited time offer",
    "subscribe to my",
    "check out my channel",
)
_POSITIVE_WORDS = ("great", "excellent", "love", "amazing", "perfect", "fantastic")
_NEGATIVE_WORDS = ("terrible", "awful", "worst", "broken", "useless", "horrible")
_LOYALTY_TIERS = ("Bronze", "Silver", "Gold")

_CATALOGUE_CATEGORIES = ("Audio", "Computing", "Home", "Wearables")
_CATALOGUE_STATUSES = ("active", "draft", "archived")
_SKU_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_]{2,31}$")
_PRICE_MIN = 1.0
_PRICE_MAX = 9999.0
_DESCRIPTION_MAX_CHARS = 1200
_DESCRIPTION_MIN_WORDS = 8
_PRICE_OUTLIER_PCT = 50.0


def check_review_quality(
    review_text, rating, existing_review_count=0, average_rating=None
):
    """Student 5's tool: a deterministic moderation check for one review.

    Flags spam/link content, reviews too short to be useful, and reviews
    whose text sentiment looks inconsistent with the star rating given -
    the kind of check a moderator would otherwise do by hand.

    Args:
        review_text: the review body submitted by the customer.
        rating: the 1-5 star rating submitted alongside it.
        existing_review_count: how many other reviews this product already
            has (grounding fact from the caller's own database).
        average_rating: that product's average rating so far, if any.

    Returns:
        {"flagged": bool, "reasons": [str, ...], "spam_score": float,
         "duplicate_risk": "low"|"possible", "word_count": int}
    """
    text = (review_text or "").strip()
    words = text.split()
    word_count = len(words)
    lowered = text.lower()

    reasons = []
    spam_hits = 0

    if word_count < 3:
        reasons.append(
            "review is too short to be useful ({} word(s))".format(word_count)
        )

    if _URL_PATTERN.search(text):
        reasons.append("review contains a link")
        spam_hits += 1

    matched_phrases = [phrase for phrase in _SPAM_PHRASES if phrase in lowered]
    if matched_phrases:
        reasons.append(
            "review contains promotional language: " + ", ".join(matched_phrases)
        )
        spam_hits += len(matched_phrases)

    try:
        rating = int(rating)
    except (TypeError, ValueError):
        rating = None

    has_positive = any(word in lowered for word in _POSITIVE_WORDS)
    has_negative = any(word in lowered for word in _NEGATIVE_WORDS)
    if rating is not None:
        if rating <= 2 and has_positive and not has_negative:
            reasons.append("low rating but the text reads entirely positive")
        elif rating >= 4 and has_negative and not has_positive:
            reasons.append("high rating but the text reads entirely negative")

    duplicate_risk = "low"
    if (
        existing_review_count
        and word_count <= 4
        and not has_positive
        and not has_negative
    ):
        duplicate_risk = "possible"

    spam_score = round(min(1.0, spam_hits / 3), 2)
    flagged = bool(reasons)

    return {
        "flagged": flagged,
        "reasons": reasons or ["no issues found"],
        "spam_score": spam_score,
        "duplicate_risk": duplicate_risk,
        "word_count": word_count,
    }


def check_customer_profile(loyalty_tier, joined_at, has_phone, has_address, as_of_date):
    """Validate a privacy-minimised Customer Account profile.

    ``as_of_date`` is supplied by the caller so membership duration is
    deterministic and can be audited. No customer name, email, phone value or
    address value is accepted by this tool.
    """
    errors = []
    warnings = []

    tier_valid = loyalty_tier in _LOYALTY_TIERS
    if not tier_valid:
        errors.append(
            "loyalty_tier must be one of {}".format(", ".join(_LOYALTY_TIERS))
        )

    joined_date = None
    try:
        joined_date = date.fromisoformat(str(joined_at))
    except (TypeError, ValueError):
        errors.append("joined_at must be an ISO date in YYYY-MM-DD format")

    reference_date = None
    try:
        reference_date = date.fromisoformat(str(as_of_date))
    except (TypeError, ValueError):
        errors.append("as_of_date must be an ISO date in YYYY-MM-DD format")

    membership_days = None
    if joined_date is not None and reference_date is not None:
        if joined_date > reference_date:
            errors.append("joined_at cannot be in the future")
        else:
            membership_days = (reference_date - joined_date).days

    missing_optional_fields = []
    if not has_phone:
        missing_optional_fields.append("phone")
    if not has_address:
        missing_optional_fields.append("address")
    if missing_optional_fields:
        warnings.append(
            "Optional profile fields are missing: {}.".format(
                ", ".join(missing_optional_fields)
            )
        )

    if errors:
        profile_status = "invalid"
    elif missing_optional_fields:
        profile_status = "incomplete"
    else:
        profile_status = "complete"

    return {
        "tool": "check_customer_profile",
        "tier_valid": tier_valid,
        "membership_days": membership_days,
        "profile_status": profile_status,
        "missing_optional_fields": missing_optional_fields,
        "warnings": warnings,
        "errors": errors,
    }


def _optional_number(value):
    """Return ``value`` as a float, ``None`` when absent, or raise ValueError."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    return float(value)


def check_product_listing(
    sku,
    name,
    category,
    price,
    status,
    description="",
    comparable_count=0,
    comparable_avg_price=None,
    comparable_min_price=None,
    comparable_max_price=None,
):
    """Student 1's tool: is one catalogue listing ready to publish?

    Checks the listing against the catalogue rules (SKU, name, category,
    price range, status, description length) and positions its price
    against comparable products in the same category.

    The ``comparable_*`` facts are grounding supplied by the caller from its
    own database - the other products in the category, excluding this one -
    so the tool never reaches back into the catalogue service.

    Returns:
        {"tool": "check_product_listing", "sku": str,
         "listing_status": "ready"|"needs_attention"|"invalid",
         "price_position": "below_range"|"within_range"|"above_range"|
                           "no_comparables"|"unknown",
         "price_vs_average_pct": float|None, "comparable_count": int,
         "description_word_count": int,
         "issues": [str], "warnings": [str], "errors": [str]}
    """
    errors = []
    issues = []
    warnings = []

    sku = str(sku or "").strip().upper()
    if not _SKU_PATTERN.match(sku):
        errors.append(
            "sku must be 3-32 characters: letters, digits, hyphen or underscore"
        )

    name = str(name or "").strip()
    if not 2 <= len(name) <= 120:
        errors.append("name must be between 2 and 120 characters")

    if category not in _CATALOGUE_CATEGORIES:
        errors.append(
            "category must be one of {}".format(", ".join(_CATALOGUE_CATEGORIES))
        )

    try:
        price = _optional_number(price)
    except (TypeError, ValueError):
        price = None
    if price is None or not _PRICE_MIN <= price <= _PRICE_MAX:
        errors.append(
            "price must be a number between {} and {}".format(_PRICE_MIN, _PRICE_MAX)
        )
        price = None

    if status not in _CATALOGUE_STATUSES:
        errors.append("status must be one of {}".format(", ".join(_CATALOGUE_STATUSES)))

    description = str(description or "").strip()
    if len(description) > _DESCRIPTION_MAX_CHARS:
        errors.append(
            "description must be {} characters or fewer".format(_DESCRIPTION_MAX_CHARS)
        )
    word_count = len(description.split())

    try:
        comparable_count = int(comparable_count or 0)
        avg_price = _optional_number(comparable_avg_price)
        min_price = _optional_number(comparable_min_price)
        max_price = _optional_number(comparable_max_price)
    except (TypeError, ValueError):
        errors.append("comparable grounding facts must be numbers")
        comparable_count, avg_price, min_price, max_price = 0, None, None, None
    if comparable_count < 0:
        errors.append("comparable_count cannot be negative")
        comparable_count = 0

    if not description:
        issues.append("description is empty")
    elif word_count < _DESCRIPTION_MIN_WORDS:
        issues.append(
            "description has {} word(s); at least {} are recommended".format(
                word_count, _DESCRIPTION_MIN_WORDS
            )
        )
    if status == "draft":
        issues.append("status is draft, so shoppers cannot see the product yet")
    elif status == "archived":
        warnings.append("status is archived, so the product is hidden from shoppers")

    price_position = "unknown"
    price_vs_average_pct = None
    if price is not None:
        if comparable_count == 0 or avg_price is None or avg_price <= 0:
            price_position = "no_comparables"
            warnings.append(
                "no comparable products in this category to check the price against"
            )
        else:
            price_vs_average_pct = round((price - avg_price) / avg_price * 100, 1)
            if min_price is not None and price < min_price:
                price_position = "below_range"
            elif max_price is not None and price > max_price:
                price_position = "above_range"
            else:
                price_position = "within_range"
            if abs(price_vs_average_pct) >= _PRICE_OUTLIER_PCT:
                warnings.append(
                    "price is {}% {} the category average of {:.2f}".format(
                        abs(price_vs_average_pct),
                        "above" if price_vs_average_pct > 0 else "below",
                        avg_price,
                    )
                )

    if errors:
        listing_status = "invalid"
    elif issues:
        listing_status = "needs_attention"
    else:
        listing_status = "ready"

    return {
        "tool": "check_product_listing",
        "sku": sku,
        "listing_status": listing_status,
        "price_position": price_position,
        "price_vs_average_pct": price_vs_average_pct,
        "comparable_count": comparable_count,
        "description_word_count": word_count,
        "issues": issues,
        "warnings": warnings,
        "errors": errors,
    }
