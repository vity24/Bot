BASE = 150

def level_from_xp(xp: int) -> int:
    """Параболическая кривая роста."""
    return int((xp / BASE) ** 0.5) + 1

def xp_to_next(xp: int) -> int:
    lvl = level_from_xp(xp)
    cap = BASE * (lvl ** 2)
    return cap - xp

def calc_battle_xp(result, *, is_pve: bool, streak: int, strength_gap: float) -> int:
    win = result.get("winner") == "team1"
    if is_pve:
        base = 40 if win else 15
    else:
        base = 120 if win else 60
    mod_strength = 1 + max(-0.5, min(strength_gap, 0.5))
    mod_streak = 1 + min(max(streak - 1, 0), 5) * 0.1
    anti_farm = 1.0
    if is_pve and win:
        if streak >= 10:
            anti_farm = 0.0
        elif streak >= 5:
            anti_farm = 0.4
    xp_gain = int(base * mod_strength * mod_streak * anti_farm)
    return max(xp_gain, 0)
