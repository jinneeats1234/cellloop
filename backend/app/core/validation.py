"""Reusable input rules for request bodies and query parameters."""

from collections.abc import Callable
from typing import Annotated

from fastapi import HTTPException, status
from pydantic import AfterValidator


def text_rule(label: str, min_len: int = 0, max_len: int = 2000) -> Callable[[str], str]:
    """Strip surrounding whitespace, reject NUL bytes, then enforce length on the trimmed text.

    (Field(min_length=…) alone would accept "   " as three characters.)
    """

    def check(value: str) -> str:
        if "\x00" in value:
            raise ValueError(f"{label} contains an invalid character")
        value = value.strip()
        if len(value) < min_len:
            raise ValueError(f"{label} needs at least {min_len} characters" if min_len > 1 else f"{label} is required")
        if len(value) > max_len:
            raise ValueError(f"{label} must be at most {max_len} characters")
        return value

    return check


def Text(label: str, min_len: int = 0, max_len: int = 2000):  # noqa: N802 (reads like a type)
    return Annotated[str, AfterValidator(text_rule(label, min_len, max_len))]


def clean_query(value: str | None, label: str = "Search", max_len: int = 200) -> str | None:
    """Same rule for query-string parameters (returns 422 rather than raising ValueError)."""
    if value is None:
        return None
    try:
        return text_rule(label, 0, max_len)(value) or None
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


def like_contains(term: str) -> str:
    """A LIKE pattern matching `term` literally: % and _ are data, not wildcards. Use with escape='\\\\'."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
