"""Helper utilities for formatting ranking outputs."""

from __future__ import annotations


def shorten_number(score: int) -> str:
    """Return score shortened like 1.2k."""
    sign = '-' if score < 0 else ''
    n = abs(score)
    if n >= 1000:
        return f"{sign}{n/1000:.1f}k"
    return f"{sign}{n}"


def format_ranking_row(index: int, username: str, score: int, level: int) -> str:
    """Format a ranking row with aligned columns."""
    medal = "🥇" if index == 1 else "🥈" if index == 2 else "🥉" if index == 3 else " "
    name = username
    if len(name) > 10:
        name = name[:10] + "…"
    name_field = f"{name:<11}"
    score_field = f"{shorten_number(score):>6}"
    return f"{medal} {index:>2}. {name_field} — {score_field} очк. | 🔼 {level}"
