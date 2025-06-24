"""Helper utilities for formatting ranking outputs."""

from __future__ import annotations


def shorten_number(score: int) -> str:
    """Return score shortened like 1.2k."""
    sign = '-' if score < 0 else ''
    n = abs(score)
    if n >= 1000:
        value = n / 1000
        text = f"{value:.1f}".rstrip("0").rstrip(".")
        return f"{sign}{text}k"
    return f"{sign}{n}"


def format_ranking_row(index: int, username: str, score: int, level: int) -> str:
    """Format a ranking row as a two-line block without special separators."""
    medal = "🥇" if index == 1 else "🥈" if index == 2 else "🥉" if index == 3 else ""
    prefix = f"{medal} " if medal else "  "
    line1 = f"{prefix}{index}. {username}"

    lvl_field = f"{level:>2}"
    score_text = shorten_number(score)
    line2 = f"    {score_text} очк. 🔼{lvl_field}"

    return f"{line1}\n{line2}"


def format_my_rank(rank: int, total: int, score: int, level: int) -> str:
    """Format the player's own rank line for the bottom of ratings."""
    line1 = f"👀 Ты — #{rank} из {total}"
    lvl_field = f"{level:>2}"
    score_text = shorten_number(score)
    line2 = f"    {score_text} очк. 🔼{lvl_field}"
    return f"{line1}\n{line2}"
