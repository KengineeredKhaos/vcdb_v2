# tests/slices/resources/test_matching_matrix_guardrails.py

from __future__ import annotations

from app.slices.resources.matching_matrix import (
    NEED_MATCH_MATRIX,
    collect_capability_code_refs,
)
from app.slices.resources.taxonomy import all_capability_codes


def test_matching_matrix_taxonomy_drift_guardrail() -> None:
    refs = collect_capability_code_refs()
    taxonomy_codes = set(all_capability_codes())

    matrix_codes = refs["exact"] | refs["adjacent"] | refs["review"]
    excluded_codes = refs["excluded"]
    covered_codes = matrix_codes | excluded_codes

    errors: list[str] = []

    matrix_missing = sorted(matrix_codes - taxonomy_codes)
    if matrix_missing:
        errors.append(
            "Matrix codes missing from taxonomy: " + ", ".join(matrix_missing)
        )

    excluded_missing = sorted(excluded_codes - taxonomy_codes)
    if excluded_missing:
        errors.append(
            "Excluded codes missing from taxonomy: "
            + ", ".join(excluded_missing)
        )

    uncovered_taxonomy = sorted(taxonomy_codes - covered_codes)
    if uncovered_taxonomy:
        errors.append(
            "Taxonomy codes not accounted for in matching matrix or "
            "exclusions: " + ", ".join(uncovered_taxonomy)
        )

    assert not errors, "\n".join(errors)


def test_matching_matrix_row_integrity_no_exact_adjacent_overlap() -> None:
    overlaps: list[str] = []

    for need_key, row in NEED_MATCH_MATRIX.items():
        exact = set(row.get("exact", ()))
        adjacent = set(row.get("adjacent", ()))
        dupes = sorted(exact & adjacent)
        if dupes:
            overlaps.append(f"{need_key}: " + ", ".join(dupes))

    assert not overlaps, (
        "Capabilities cannot appear in both exact and adjacent for the "
        "same need row:\n" + "\n".join(overlaps)
    )
