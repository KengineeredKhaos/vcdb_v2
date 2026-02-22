# app/slices/customers/taxonomy.py

"""
customers.taxonomy

These are IRL-world facts interpreted to code-world semantics for utility.
Slice-local semantics for Customers:
- persisted keys (category_key, rating_value)
- eligibility enums (veteran/homeless/method/branch/era)
- tier groupings and rank rules for rollups
"""

VETERAN_STATUS = ("unknown", "verified", "unverified", "not_veteran")
HOMELESS_STATUS = ("unknown", "verified", "unverified")
VETERAN_METHOD = ("dd214", "va_id", "state_dl_veteran", "other")
BRANCH = ("USA", "USMC", "USN", "USAF", "USSF", "USCG")
ERA = ("WWI", "WWII", "Korea", "Vietnam", "ColdWar", "GW-IF-EF", "PsyWar")

NEEDS_CATEGORY_KEY = (
    "food",
    "hygiene",
    "health",
    "housing",
    "clothing",
    "income",
    "employment",
    "transportation",
    "education",
    "family",
    "peergroup",
    "tech",
)

TIER1 = ("food", "hygiene", "health", "housing", "clothing")
TIER2 = ("income", "employment", "transportation", "education")
TIER3 = ("family", "peergroup", "tech")

RATING_ALLOWED = ("immediate", "marginal", "sufficient", "unknown", "na")
RANK = {"immediate": 1, "marginal": 2, "sufficient": 3}
