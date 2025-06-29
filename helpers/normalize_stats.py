import re


def normalize_stats_input(raw: str, pos: str) -> str:
    """Приводит сырую строку из /editcard к каноническому формату."""
    raw = raw.strip()
    if pos == "G":
        m = re.fullmatch(r"(\d+)\s+([\d.,]+)", raw)
        if m:
            wins, gaa = m.groups()
            return f"Поб {wins} КН {gaa}"
        return raw
    return f"Очки {raw}" if raw.isdigit() else raw
