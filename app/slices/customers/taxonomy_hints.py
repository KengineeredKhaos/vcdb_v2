from __future__ import annotations

from typing import Final

# Optional semantic maps extracted from the retired policy_service_taxonomy.json.
# Merge into customers/taxonomy.py if you still want these structures.

BASIC_NEEDS_SEMANTIC_MAP: Final[dict] = {'clothing': {'shirt': {'attributes': {'size': ['S',
                                                'M',
                                                'L',
                                                'XL',
                                                '2X',
                                                '3x']}}},
 'housing': {'sleeping_gear': {'bag': {}, 'camp_gear': {}}}}
