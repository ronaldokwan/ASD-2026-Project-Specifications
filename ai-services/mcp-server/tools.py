"""MCP tools shared by every student feature.

Every tool here is a pure, deterministic function: no LLM call and no network
call to another microservice. The caller (a student backend) is responsible
for grounding the tool with real facts - the same "backend grounds, shared
service acts" split used by ai-mode's AgentRequest.context - so a tool can be
tested and reasoned about without any other service running.

Add your own feature's tool to this module and register it with both
``server.py`` (the real MCP/stdio server) and ``http_server.py`` (the plain
HTTP front door student backends call over the network). See
``tool-contracts.md`` for the contract of every tool below.
"""

import re

_URL_PATTERN = re.compile(r"https?://|www\.", re.IGNORECASE)
_SPAM_PHRASES = (
    "buy now", "click here", "discount code", "free money", "act now",
    "limited time offer", "subscribe to my", "check out my channel",
)
_POSITIVE_WORDS = ("great", "excellent", "love", "amazing", "perfect", "fantastic")
_NEGATIVE_WORDS = ("terrible", "awful", "worst", "broken", "useless", "horrible")


def check_review_quality(review_text, rating, existing_review_count=0, average_rating=None):
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
        reasons.append("review is too short to be useful ({} word(s))".format(word_count))

    if _URL_PATTERN.search(text):
        reasons.append("review contains a link")
        spam_hits += 1

    matched_phrases = [phrase for phrase in _SPAM_PHRASES if phrase in lowered]
    if matched_phrases:
        reasons.append("review contains promotional language: " + ", ".join(matched_phrases))
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
    if existing_review_count and word_count <= 4 and not has_positive and not has_negative:
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
