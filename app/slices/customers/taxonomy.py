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
HOUSING_STATUS = ("unknown", "housed", "unhoused")
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

RATING_ALLOWED = (
    "immediate",
    "marginal",
    "sufficient",
    "unknown",
    "not_applicable",
)
RANK = {"immediate": 1, "marginal": 2, "sufficient": 3}


NEED_LABELS = {
    "food": "Food",
    "hygiene": "Hygiene",
    "health": "Health",
    "housing": "Housing",
    "clothing": "Clothing",
    "income": "Income",
    "employment": "Employment",
    "transportation": "Transportation",
    "education": "Education",
    "family": "Family",
    "peergroup": "Peer Group",
    "tech": "Technology",
}

REFERRAL_METHODS = (
    "phone",
    "email",
    "in_person",
    "handoff",
    "other",
)

REFERRAL_MATCH_BUCKETS = ("exact", "adjacent", "review")

REFERRAL_OUTCOMES = (
    "connected",
    "attempted_no_contact",
    "declined_by_customer",
    "declined_by_resource",
    "waitlisted",
    "in_progress",
    "completed",
    "unable_to_verify",
    "other",
)
