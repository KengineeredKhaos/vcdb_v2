from __future__ import annotations

from typing import Final

# Canon: Points-of-Contact (POC) scope taxonomy.
# This is slice-local taxonomy (shared by Resources/Sponsors) and not
# Governance policy: it is used constantly by forms/validation/services.

POC_SCOPES: Final[tuple[str, ...]] = (
    "general",
    "ops",
    "billing",
    "scheduling",
    "finance",
    "admin",
    "logistics",
    "marketing",
    "publicity",
    "promotions",
    "social_media",
    "graphics",
    "event_coor",
    "volunteer",
)

DEFAULT_POC_SCOPE: Final[str] = "general"
POC_MAX_RANK: Final[int] = 99
