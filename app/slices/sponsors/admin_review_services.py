# app/slices/sponsors/admin_review_services.py

from __future__ import annotations

"""
Sponsors unified Admin-facing lane.

This module will hold Sponsor intervention and advisory Admin services when
those workflows are implemented.

Intervention pattern:
- raise_<operation>_admin_issue()
- <operation>_review_get()
- resolve_<operation>_admin_issue()
- close_<operation>_admin_issue()

Advisory pattern:
- publish_<operation>_admin_advisory()
- optional <operation>_advisory_get()
- optional close_<operation>_admin_advisory()
"""
