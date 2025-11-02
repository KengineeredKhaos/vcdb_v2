from app.slices.logistics.sku import (
    validate_sku,
    parse_sku,
    from_parts,
    to_compact,
    coerce_seq,
)


def test_from_parts_and_parse_roundtrip():
    s = from_parts(
        cat="UG",
        sub="WHK",
        src="DR",
        size="MD",
        col="OD",
        issuance_class="V",
        seq="001",
    )
    assert s == "UG-WHK-DR-MD-OD-V-001"
    assert validate_sku(s)
    p = parse_sku(s)
    assert p["cat"] == "UG" and p["sub"] == "WHK" and p["src"] == "DR"
    assert (
        p["size"] == "MD"
        and p["col"] == "OD"
        and p["issuance_class"] == "V"
        and p["seq"] == "001"
    )
    assert to_compact(s) == "UGWHKDRMDODV001"


def test_coerce_seq_int_and_str():
    assert coerce_seq(0) == "000"
    assert coerce_seq(7) == "007"
    assert coerce_seq(42) == "042"
    assert coerce_seq(999) == "999"


def test_reject_bad_sequences_and_fields():
    bad = [
        "UG-WHK-DR-MD-OD-V-01",  # seq too short
        "UG-WHK-DR-MD-OD-V-0000",  # seq too long
        "UG-WHK-XX-MD-OD-V-001",  # bad source
        "UG-WHK-DR-QQ-OD-V-001",  # bad size
        "UG-WHK-DR-MD-QQ-V-001",  # bad color
        "UG-WHK-DR-MD-OD-X-001",  # bad issuance_class
    ]
    for s in bad:
        assert not validate_sku(s)
