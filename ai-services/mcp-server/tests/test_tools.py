"""Unit tests for the shared MCP tools (pure functions, no network, no LLM).

Run from the repository root:  pytest ai-services/mcp-server/tests -v
"""

import os
import sys

SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVICE_ROOT)

from tools import check_order_fulfilment, check_review_quality  # noqa: E402


def test_flags_short_reviews():
    result = check_review_quality("ok", 5)
    assert result["flagged"] is True
    assert "too short" in result["reasons"][0]


def test_flags_links_and_spam_phrases():
    result = check_review_quality("Great deal, buy now at www.example.com!", 5)
    assert result["flagged"] is True
    assert result["spam_score"] > 0


def test_flags_rating_text_mismatch():
    result = check_review_quality("This is terrible, worst purchase ever.", 5, existing_review_count=3)
    assert result["flagged"] is True
    assert any("high rating" in reason for reason in result["reasons"])


def test_clean_review_is_not_flagged():
    result = check_review_quality(
        "The battery lasts all day and the sound quality is very clear.", 5,
        existing_review_count=10, average_rating=4.5,
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


def test_pending_order_with_committed_inventory_is_ready_to_ship():
    result = check_order_fulfilment("ORD-100", "pending", 2, 3, 89.90, True)
    assert result["ready_to_ship"] is True
    assert result["blockers"] == []


def test_non_pending_order_is_not_ready_to_ship():
    result = check_order_fulfilment("ORD-101", "delivered", 1, 1, 20, True)
    assert result["ready_to_ship"] is False
    assert any("pending" in blocker for blocker in result["blockers"])


def test_incomplete_order_reports_every_blocker():
    result = check_order_fulfilment("", "pending", 0, 0, 0, False)
    assert result["ready_to_ship"] is False
    assert len(result["blockers"]) == 5
