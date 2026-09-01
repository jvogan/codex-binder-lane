"""Strict JSON helpers for portable Binder Lane contracts."""

from __future__ import annotations

import json
from typing import Any


class StrictJSONError(ValueError):
    """Raised when JSON has ambiguous or non-portable semantics."""


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJSONError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise StrictJSONError(f"non-finite JSON number is forbidden: {value}")


def loads(value: str | bytes | bytearray) -> Any:
    """Parse JSON while rejecting duplicate keys and non-finite numbers."""

    try:
        return json.loads(
            value,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_constant,
        )
    except StrictJSONError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StrictJSONError(str(exc)) from exc


def canonical_bytes(value: Any) -> bytes:
    """Serialize deterministic UTF-8 JSON without non-standard numbers."""

    try:
        text = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise StrictJSONError(str(exc)) from exc
    return (text + "\n").encode("utf-8")
