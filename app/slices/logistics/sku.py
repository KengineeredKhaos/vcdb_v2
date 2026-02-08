# app/slices/logistics/sku.py


"""
**Format: 15–18 chars (illustrated w/ hyphens for readability):**
`CAT-SUB-SRC-SZ-COL-CND-SEQ`

- **CAT** (2): category

  - UW = undergarments
  - OW = outerwear
  - CW = cold-weather
  - FW = footwear
  - CG = camping
  - AC = accouterments
  - FD = foodstuffs
  - DG = Durable Goods

- **SUB** (2–3): subcategory

  - TP = top
  - BT = bottom
  - SK = socks
  - GL = gloves
  - HT = hats
  - BG = bags
  - SL = sleep
  - SH = shelter
  - KT = kit

- **SRC** (2): source

  - DR = DRMO/Defense surplus
  - LC = local commercial

- **SZ** (2–3): size

  - pattern: "^(XS|S|M|L|XL|2X|3X|NA|[0-1][0-9][05])$"
  - footwear 0.5 steps encoded as three digits; or NA for not-sized items.",


- **COL** (2–3): color/pattern

  - BK = black
  - BL = blue
  - LB = light blue
  - BR = brown
  - TN = tan
  - GN = green
  - RD = red
  - OR = orange
  - YL = yellow
  - WT = white
  - OD = olive drab
  - CY = coyote
  - FG = foliage
  - MC = multicam
  - MX = mixed/assorted

- **CND (issuance_class)** (1): classification for issuance (internal, Customer-dependent factor)

  - V = veteran only
  - H = homeless only
  - D = durable goods, returned after use
  - U = unclassified

- **SEQ** (3): unique base-36 counter per subfamily (000–ZZZ)

Store without hyphens in system for compact codes;
Print with hyphens for humans.

"""

import re

NEW_RE = re.compile(
    r"^(?P<cat>UW|OW|CW|FW|CG|AC|FD|DG)-"
    r"(?P<sub>TP|BT|SK|GL|HT|BG|SL|SH|KT)-"
    r"(?P<src>DR|LC)-"
    r"(?P<size>XS|S|M|L|XL|2X|3X|NA|[0-1][0-9][05])-"
    r"(?P<col>BK|BL|LB|BR|TN|GN|RD|OR|YL|WT|OD|CY|FG|MC|MX)-"
    r"(?P<issuance_class>[VHDU])-"
    r"(?P<seq>[0-9A-Z]{3})$"
)

ALPHA_SIZES = {"XS", "S", "M", "L", "XL", "2X", "3X"}
LEGACY_ALPHA_MAP = {"SM": "S", "MD": "M", "LG": "L"}  # legacy cleanup
# -----------------
# Helpers to ensure
# uniform sku's
# -----------------


def is_size_alpha(tok: str) -> bool:
    return tok in ALPHA_SIZES


def is_size_numeric(tok: str) -> bool:
    # three digits, last digit 0 or 5
    return len(tok) == 3 and tok.isdigit() and tok[-1] in {"0", "5"}


def normalize_size_token(size: str) -> str:
    """
    Accepts alpha (XS,S,M,L,XL,2X,3X), numeric 3-char (000..199, step .5), or NA.
    Applies legacy mapping (SM/MD/LG -> S/M/L). Returns canonical token.
    """
    s = size.upper()
    s = LEGACY_ALPHA_MAP.get(s, s)
    if s == "NA" or s in ALPHA_SIZES or is_size_numeric(s):
        return s
    raise ValueError(f"invalid size token: {size!r}")


def display_size_token(tok: str) -> str:
    """
    Pretty-print size: 'M' -> 'M', '2X' -> '2X', '075' -> '7.5', '060' -> '6', 'NA' -> 'N/A'
    """
    if tok == "NA":
        return "N/A"
    if tok in ALPHA_SIZES:
        return tok
    if is_size_numeric(tok):
        whole = int(tok[:-1])
        half = tok[-1] == "5"
        return f"{whole}{'.5' if half else ''}"
    # Fallback to raw token; validators should prevent this.
    return tok


def from_parts(
    *,
    cat: str,
    sub: str,
    src: str,
    size: str,
    col: str,
    issuance_class: str,
    seq: str,
) -> str:
    """
    Build a SKU string from explicit parts and validate it.

    Example:
        from_parts(
            cat="UW", sub="KT", src="DR",
            size="NA", col="OD", issuance_class="V", seq="001"
        ) -> "UW-KT-DR-NA-OD-V-001"

    Raises:
        ValueError:
    if the resulting SKU is not valid per NEW_RE/validate_sku().
    """
    parts: dict[str, str] = {
        "cat": cat.upper(),
        "sub": sub.upper(),
        "src": src.upper(),
        "size": normalize_size_token(size),
        "col": col.upper(),
        "issuance_class": issuance_class.upper(),
        "seq": seq.upper(),
    }
    sku = "{cat}-{sub}-{src}-{size}-{col}-{issuance_class}-{seq}".format(
        **parts
    )
    if not validate_sku(sku):
        raise ValueError(f"invalid SKU parts: {parts!r}")
    return sku


def to_compact(sku: str) -> str:
    """
    Return a compact representation (no hyphens). Useful for labels or
    environments with scan-length constraints.
    """
    return normalize(sku).replace("-", "")


def normalize(s: str) -> str:
    return (s or "").strip().upper()


def validate_sku(sku: str) -> bool:
    return bool(NEW_RE.match(normalize(sku)))


def parse_sku(sku: str) -> dict[str, str]:
    m = NEW_RE.match(normalize(sku))
    if not m:
        raise ValueError("invalid SKU")
    return m.groupdict()


def classification_key_for(x, sep: str = "/") -> str:
    """
    Return the short classification key for a SKU (e.g., 'FW/HT').

    Accepts either:
      - a full SKU string like 'FW-HT-LC-NA-BK-U-00C', or
      - a parsed parts dict from parse_sku(...) with keys 'cat' and 'sub'.

    `sep` defaults to '/' so the key is 'CAT/SUB'. Change to '-' if you
    need 'CAT-SUB' for a particular consumer.
    """
    if isinstance(x, str):
        parts = parse_sku(x)
    else:
        parts = x
    return f"{parts['cat']}{sep}{parts['sub']}"


BASE36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def int_to_b36(n: int, width=3) -> str:
    if n < 0:
        raise ValueError("neg")
    out = ""
    if n == 0:
        out = "0"
    else:
        while n:
            n, r = divmod(n, 36)
            out = BASE36[r] + out
    return out.rjust(width, "0")[-width:]


def b36_to_int(s: str) -> int:
    s = normalize(s)
    n = 0
    for ch in s:
        n = n * 36 + BASE36.index(ch)
    return n


def family_key(p: dict[str, str]) -> tuple[str, ...]:
    return (
        p["cat"],
        p["sub"],
        p["src"],
        p["size"],
        p["col"],
        p["issuance_class"],
    )


__all__ = ["classification_key_for", "parse_sku", "validate_sku"]
