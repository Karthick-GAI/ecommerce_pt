"""
E-commerce specific ground truth for retrieval accuracy evaluation.

Relevance scale:
  3 — Highly relevant: directly answers the query
  2 — Relevant: closely related, useful
  1 — Marginally relevant: related topic
  0 — Not relevant (absence = 0)

Product IDs are string slugs — matched against actual DB by substring search
in the evaluation script if exact IDs differ between dataset seedings.
"""

from __future__ import annotations

# ── Ground truth dataset ───────────────────────────────────────────────────────
# Format: query_text → {product_name_substring: relevance_score}
# Use lowercase substrings that will uniquely identify the product in the catalogue.

GROUND_TRUTH: dict[str, dict[str, int]] = {

    # ── Electronics: Earbuds ──────────────────────────────────────────────────
    "wireless earbuds for running under 3000": {
        "airdopes 141": 3,
        "boult z40": 3,
        "jbl tune 215": 2,
        "realme buds q2": 2,
        "airdopes 441": 1,
    },
    "noise cancelling headphones for office work": {
        "wh-1000xm5": 3,
        "quietcomfort 45": 3,
        "evolve2 55": 3,
        "wh-1000xm4": 2,
        "q45": 1,
    },
    "best gaming headset with mic": {
        "cloud alpha": 3,
        "blackshark v2": 3,
        "arctis 7": 2,
        "immortal im1000": 2,
        "quantum 350": 1,
    },

    # ── Electronics: Smartphones ──────────────────────────────────────────────
    "smartphone under 15000 with good camera": {
        "redmi note 13": 3,
        "poco x6": 3,
        "galaxy m34": 2,
        "realme 11 pro": 2,
    },
    "budget 5g smartphone under 10000": {
        "redmi 12 5g": 3,
        "motorola g34": 3,
        "poco m6 pro": 2,
        "galaxy m14 5g": 2,
    },

    # ── Electronics: Laptops ─────────────────────────────────────────────────
    "lightweight laptop for college student under 50000": {
        "pavilion plus": 3,
        "ideapad slim 5": 3,
        "vivobook 15": 2,
        "swift go": 2,
        "inspiron 15": 1,
    },
    "gaming laptop with dedicated gpu": {
        "rog strix": 3,
        "katana 15": 3,
        "ideapad gaming 3": 2,
        "victus 15": 2,
        "nitro 5": 1,
    },

    # ── Fashion: Footwear ─────────────────────────────────────────────────────
    "running shoes for marathon training": {
        "air zoom pegasus": 3,
        "ultraboost 22": 3,
        "ghost 15": 2,
        "gel nimbus": 2,
        "880v13": 1,
    },
    "waterproof hiking boots for trekking": {
        "mh500": 3,
        "newton ridge": 3,
        "waterproof trekking": 2,
        "trail boots": 2,
        "x ultra 4": 1,
    },

    # ── Sports & Fitness ──────────────────────────────────────────────────────
    "yoga mat non-slip thick for home": {
        "domyos yoga": 3,
        "tpe yoga mat": 3,
        "nivia yoga": 2,
        "eva yoga mat": 2,
        "amazon basics yoga": 1,
    },
    "protein powder for muscle building whey": {
        "impact whey": 3,
        "gold standard whey": 3,
        "raw whey": 2,
        "pro performance": 2,
    },

    # ── Home & Kitchen ────────────────────────────────────────────────────────
    "air fryer for healthy cooking family of 4": {
        "philips hd92": 3,
        "easy fry 4l": 3,
        "healthifry 4l": 2,
        "prolife digi": 2,
    },
    "robot vacuum cleaner for pet hair": {
        "roomba i3": 3,
        "deebot t10": 3,
        "s5 max": 2,
        "mi robot vacuum": 2,
    },

    # ── Beauty & Personal Care ─────────────────────────────────────────────────
    "face moisturiser for dry skin spf": {
        "hydro boost": 3,
        "lacto calamine sunscreen": 3,
        "vitamin c spf": 2,
        "minimalist spf 50": 2,
    },

    # ── Books ─────────────────────────────────────────────────────────────────
    "python machine learning book for beginners": {
        "hands-on machine learning": 3,
        "python machine learning": 3,
        "ml with scikit": 2,
    },
    "system design interview preparation": {
        "system design interview": 3,
        "designing data-intensive": 3,
        "clean architecture": 1,
    },

    # ── Accessories ───────────────────────────────────────────────────────────
    "smartwatch with gps and health monitoring": {
        "forerunner 265": 3,
        "apple watch se": 3,
        "galaxy watch6": 2,
        "amazfit gtr 4": 2,
    },
    "gaming mouse rgb lightweight": {
        "g304 lightspeed": 3,
        "deathadder v3": 3,
        "aerox 5": 2,
        "pulsefire haste": 2,
    },
    "mechanical keyboard tenkeyless for programming": {
        "keychron k2": 3,
        "anne pro 2": 3,
        "ducky one 3": 2,
    },
    "27 inch 4k monitor for graphic design": {
        "27uk850": 3,
        "s2722qc": 3,
        "pa278": 2,
        "pd2705": 2,
    },

    # ── Comparative ──────────────────────────────────────────────────────────
    "compare sony bose noise cancelling headphones": {
        "wh-1000xm5": 3,
        "quietcomfort 45": 3,
        "nc700": 2,
        "wh-1000xm4": 2,
    },
    "gifts for mom who likes cooking": {
        "induction cooktop": 3,
        "air fryer": 3,
        "cookware": 2,
        "oven toaster grill": 2,
    },
    "office chair ergonomic lower back support": {
        "jupiter pro": 3,
        "savya apex": 3,
        "durian apex": 2,
    },
}


def get_all_queries() -> list[str]:
    return list(GROUND_TRUTH.keys())


def get_relevance(query: str) -> dict[str, int]:
    return GROUND_TRUTH.get(query, {})
