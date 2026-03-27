# app/slices/customers/taxonomy.py

"""
customers.taxonomy

These are IRL-world facts interpreted to code-world semantics for utility.
Slice-local semantics for Customers:
- persisted keys (category_key, rating_value)
- eligibility enums (veteran/homeless/method/branch/era)
- tier groupings and rank rules for rollups
"""

INTAKE_STEPS = (
    "ensure",
    "eligibility",
    "needs_tier1",
    "needs_tier2",
    "needs_tier3",
    "review",
    "complete",
)

VETERAN_STATUS = ("unknown", "verified", "unverified", "not_veteran")
HOMELESS_STATUS = ("unknown", "verified", "unverified")
VETERAN_METHOD = ("dd214", "va_id", "state_dl_veteran", "other")
BRANCH = ("USA", "USMC", "USN", "USAF", "USSF", "USCG")
ERA = ("WWI", "WWII", "Korea", "Vietnam", "ColdWar", "GWOT", "PsyWar")

NEEDS_CATEGORY_KEY = (
    # Tier 1 (physiological)
    "food",
    "hygiene",
    "health",
    "housing",
    "clothing",
    # Tier 2 (security)
    "income",
    "employment",
    "transportation",
    "education",
    # Tier 3 (social)
    "family",
    "peergroup",
    "tech",
)

TIER1 = ("food", "hygiene", "health", "housing", "clothing")
TIER2 = ("income", "employment", "transportation", "education")
TIER3 = ("family", "peergroup", "tech")

RATING_ALLOWED = ("immediate", "marginal", "sufficient", "unknown", "na")
RANK = {"immediate": 1, "marginal": 2, "sufficient": 3}
