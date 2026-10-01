"""Unit tests for the shared MCP tools (pure functions, no network, no LLM).

Run from the repository root: pytest ai-services/mcp-server/tests -v
"""

import os
import sys

SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVICE_ROOT)

from tools import (
    check_customer_profile,
    check_product_listing,
    check_review_quality,
)


def test_flags_short_reviews():
    result = check_review_quality("ok", 5)
    assert result["flagged"] is True
    assert "too short" in result["reasons"][0]


def test_flags_links_and_spam_phrases():
    result = check_review_quality("Great deal, buy now at www.example.com!", 5)
    assert result["flagged"] is True
    assert result["spam_score"] > 0


def test_flags_rating_text_mismatch():
    result = check_review_quality(
        "This is terrible, worst purchase ever.", 5, existing_review_count=3
    )
    assert result["flagged"] is True
    assert any("high rating" in reason for reason in result["reasons"])


def test_clean_review_is_not_flagged():
    result = check_review_quality(
        "The battery lasts all day and the sound quality is very clear.",
        5,
        existing_review_count=10,
        average_rating=4.5,
    )
    assert result["flagged"] is False
    assert result["reasons"] == ["no issues found"]
    assert result["spam_score"] == 0


def test_duplicate_risk_flagged_for_generic_short_text_on_popular_products():
    result = check_review_quality("nice", 4, existing_review_count=20)
    assert result["duplicate_risk"] == "possible"


def test_non_integer_rating_is_tolerated():
    result = check_review_quality("Solid headphones, would recommend to a friend.", "5")
    assert result["flagged"] is False


def test_customer_profile_complete_with_deterministic_membership_days():
    result = check_customer_profile("Gold", "2024-08-19", True, True, "2026-10-01")
    assert result == {
        "tool": "check_customer_profile",
        "tier_valid": True,
        "membership_days": 773,
        "profile_status": "complete",
        "missing_optional_fields": [],
        "warnings": [],
        "errors": [],
    }


def test_customer_profile_reports_missing_optional_fields():
    result = check_customer_profile("Silver", "2025-01-10", False, False, "2026-10-01")
    assert result["profile_status"] == "incomplete"
    assert result["missing_optional_fields"] == ["phone", "address"]


def test_customer_profile_returns_structured_tier_and_date_errors():
    result = check_customer_profile("Platinum", "not-a-date", True, True, "2026-10-01")
    assert result["tier_valid"] is False
    assert result["profile_status"] == "invalid"
    assert result["membership_days"] is None
    assert len(result["errors"]) == 2


def test_customer_profile_rejects_future_joining_date():
    result = check_customer_profile("Bronze", "2026-10-02", True, True, "2026-10-01")
    assert result["profile_status"] == "invalid"
    assert result["membership_days"] is None
    assert "future" in result["errors"][0]


AURORA = {
    "sku": "SKU-AUD-1001",
    "name": "Aurora Wireless Headphones",
    "category": "Audio",
    "price": 199.95,
    "status": "active",
    "description": (
        "Over-ear Bluetooth headphones with active noise cancelling "
        "and a 30 hour battery."
    ),
}


def test_product_listing_ready_and_within_comparable_range():
    result = check_product_listing(
        **AURORA,
        comparable_count=2,
        comparable_avg_price=150.0,
        comparable_min_price=59.0,
        comparable_max_price=249.0,
    )
    assert result["tool"] == "check_product_listing"
    assert result["listing_status"] == "ready"
    assert result["price_position"] == "within_range"
    assert result["price_vs_average_pct"] == 33.3
    assert result["description_word_count"] == 12
    assert result["issues"] == result["errors"] == []


def test_product_listing_flags_draft_and_short_description():
    result = check_product_listing(
        **dict(AURORA, status="draft", description="Nice headphones.")
    )
    assert result["listing_status"] == "needs_attention"
    assert any("draft" in issue for issue in result["issues"])
    assert any("2 word(s)" in issue for issue in result["issues"])
    assert result["price_position"] == "no_comparables"


def test_product_listing_positions_price_outliers():
    above = check_product_listing(
        **dict(AURORA, price=900),
        comparable_count=2,
        comparable_avg_price=150.0,
        comparable_min_price=59.0,
        comparable_max_price=249.0,
    )
    assert above["price_position"] == "above_range"
    assert any("above the category average" in w for w in above["warnings"])

    below = check_product_listing(
        **dict(AURORA, price=20),
        comparable_count=2,
        comparable_avg_price=150.0,
        comparable_min_price=59.0,
        comparable_max_price=249.0,
    )
    assert below["price_position"] == "below_range"
    assert below["price_vs_average_pct"] == -86.7


def test_product_listing_reports_contract_errors_without_raising():
    result = check_product_listing(
        sku="!!",
        name="X",
        category="Garden",
        price="free",
        status="sold",
        description="x" * 1201,
    )
    assert result["listing_status"] == "invalid"
    assert result["price_position"] == "unknown"
    assert len(result["errors"]) == 6


def test_product_listing_archived_is_a_warning_not_an_issue():
    result = check_product_listing(**dict(AURORA, status="archived"))
    assert result["listing_status"] == "ready"
    assert any("archived" in w for w in result["warnings"])
