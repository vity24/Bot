import re


def normalize_stats_input(raw: str, pos: str) -> str:
    """Приводит сырую строку из /editcard к каноническому формату."""
    raw = raw.strip()
    if pos == "G":
        m = re.fullmatch(r"(\d+)\s+([\d.]+)", raw)
        return f"Поб {m[1]} КН {m[2]}" if m else raw
    return f"Очки {raw}" if raw.isdigit() else raw
