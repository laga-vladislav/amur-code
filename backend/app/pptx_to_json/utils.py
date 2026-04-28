from __future__ import annotations

from typing import Any


def int_value(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def rgb_to_hex(rgb: Any) -> str | None:
    if rgb is None:
        return None
    try:
        return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
    except Exception:
        return None
