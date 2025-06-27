import random
from typing import List
from battle import BattleSession


def generate_premium_log(session: BattleSession, result: dict, xp_gain: int = 85, rating_delta: int = 1) -> List[str]:
    """Generate telecast-style premium log for the match."""
    lines: List[str] = []

    # Real goal scorers from the session
    for goal in session.goals:
        player = goal["player"]
        team = goal["team"]
        lines.append(f"🥅 <b>{player}</b> 🎯 кладёт шайбу в сетку! <i>({team})</i>")

    # Random save moments
    goalies = [p for p in session.team1 + session.team2 if (p.get("pos") or "").startswith("G")]
    if goalies:
        for _ in range(random.randint(1, 2)):
            g = random.choice(goalies)
            lines.append(f"🛡 <b>{g['name']}</b> спасает после мощного броска!")

    # Random fan noise
    if random.random() < 0.5:
        lines.append("🏟 <i>Фанаты запускают волну, арена гудит!</i>")

    # Random expected goals stats
    xg1 = round(random.uniform(0.5, 3.0), 1)
    xg2 = round(random.uniform(0.5, 3.0), 1)
    lines.append(f"📊 <b>XG:</b> {session.name1} {xg1} — {session.name2} {xg2}")

    # Occasional tactic prompt
    if random.random() < 0.3:
        lines.append("⏱ <b>Время сменить тактику!</b>")

    # Viral hype messages
    if random.random() < 0.2:
        lines.append("🌟 ТВОЯ КОМАНДА В ТРЕНДЕ! 4 победы подряд!")
        lines.append("💎 VIP-ложи аплодируют твоей игре!")

    # Rare meme events
    lines.append("🤣 Судья чуть сам шайбу не поймал!")
    if random.random() < 0.02:
        lines.append("🚑 Купари легко травмировался — пропустит матч (2% шанс)")

    # Final summary
    s1 = result.get("score", {}).get("team1", 0)
    s2 = result.get("score", {}).get("team2", 0)
    lines.append(f"🏆 Матч окончен: {session.name1} {s1} — {s2} {session.name2}")
    mvp = result.get("mvp")
    if mvp:
        goals = sum(1 for g in session.goals if g["player"] == mvp)
        goal_word = "гол" if goals == 1 else "гола"
        lines.append(f"🎯 Звезда матча: <b>{mvp}</b> — {goals} {goal_word}")
    lines.append(f"🎖 +{xp_gain} XP, рейтинг +{rating_delta}")

    return lines
