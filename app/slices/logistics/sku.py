# app/slices/logistics/sku.py
import re
from typing import Tuple, Dict

SKU_RE = re.compile(
    r"^(?P<cat>[A-Z]{2})-(?P<sub>[A-Z]{2,3})-(?P<src>[A-Z]{2})-(?P<size>[A-Z0-9]{2,3})-(?P<col>[A-Z]{2,3})-(?P<grade>[A-Z])-(?P<seq>[0-9A-Z]{3})$"
)

BASE36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
B36MAP = {ch: i for i, ch in enumerate(BASE36)}


def validate_sku(sku: str) -> bool:
    return bool(SKU_RE.match((sku or "").strip().upper()))


def parse_sku(sku: str) -> Dict[str, str]:
    m = SKU_RE.match((sku or "").strip().upper())
    if not m:
        raise ValueError("invalid SKU format")
    return m.groupdict()  # cat,sub,src,size,col,grade,seq


def format_sku(
    cat: str, sub: str, src: str, size: str, col: str, grade: str, seq: str
) -> str:
    sku = f"{cat}-{sub}-{src}-{size}-{col}-{grade}-{seq}".upper()
    if not validate_sku(sku):
        raise ValueError("invalid SKU parts")
    return sku


def b36_to_int(s: str) -> int:
    s = s.upper()
    if not s or any(ch not in B36MAP for ch in s):
        raise ValueError("invalid base36")
    n = 0
    for ch in s:
        n = n * 36 + B36MAP[ch]
    return n


def int_to_b36(n: int, width: int = 3) -> str:
    if n < 0:
        raise ValueError("negative not allowed")
    digits = []
    if n == 0:
        digits = ["0"]
    else:
        while n > 0:
            n, r = divmod(n, 36)
            digits.append(BASE36[r])
    s = "".join(reversed(digits)) or "0"
    return s.rjust(width, "0")[-width:]  # clamp to width


def family_key(parts: Dict[str, str]) -> Tuple[str, str, str, str, str, str]:
    return (
        parts["cat"],
        parts["sub"],
        parts["src"],
        parts["size"],
        parts["col"],
        parts["grade"],
    )
