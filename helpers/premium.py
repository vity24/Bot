import random
from typing import List, Dict, DefaultDict
from collections import defaultdict
from battle import BattleSession


def generate_premium_log(session: BattleSession, result: dict, xp_gain: int = 85, rating_delta: int = 1) -> List[str]:
    """Generate telecast-style premium log for the match."""
    lines: List[str] = []

    # group goals by period to match scoreboard
    goals_by_period: DefaultDict[int, List[Dict]] = defaultdict(list)
    for g in session.goals:
        goals_by_period[g.get("period", 1)].append(g)

    goalies = [p for p in session.team1 + session.team2 if (p.get("pos") or "").startswith("G")]

    max_period = max(goals_by_period.keys(), default=session.current_period or 3)
    for period in range(1, max_period + 1):
        period_lines: List[str] = []

        # add real goal scorers for this period
        for g in goals_by_period.get(period, []):
            period_lines.append(f"🥅 <b>{g['player']}</b> 🎯 кладёт шайбу в сетку! <i>({g['team']})</i>")

        target = random.randint(7, 8)
        while len(period_lines) < target:
            r = random.random()
            if r < 0.4 and goalies:
                gk = random.choice(goalies)
                period_lines.append(f"🛡 <b>{gk['name']}</b> спасает бросок в упор!")
            elif r < 0.7:
                period_lines.append("🏟 <i>Фанаты запускают волну, арена гудит!</i>")
            elif r < 0.9:
                xg1 = round(random.uniform(0.5, 3.0), 1)
                xg2 = round(random.uniform(0.5, 3.0), 1)
                period_lines.append(f"📊 <b>XG:</b> {session.name1} {xg1} — {session.name2} {xg2}")
            else:
                period_lines.append("⏱ <b>Время сменить тактику на следующий период!</b>")

        random.shuffle(period_lines)
        lines.extend(period_lines)

    # Final summary block
    s1 = result.get("score", {}).get("team1", 0)
    s2 = result.get("score", {}).get("team2", 0)
    lines.append(f"🏆 Матч завершён: {session.name1} {s1} — {s2} {session.name2}")
    mvp = result.get("mvp")
    if mvp:
        goals = sum(1 for g in session.goals if g["player"] == mvp)
        goal_word = "гол" if goals == 1 else "гола"
        lines.append(f"🎯 Звезда матча: <b>{mvp}</b> — {goals} {goal_word}")
    lines.append(f"🎖 +{xp_gain} XP, рейтинг +{rating_delta}")

    return lines
