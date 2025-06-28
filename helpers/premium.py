import random
from typing import List, Dict, DefaultDict
from collections import defaultdict
from battle import BattleSession


def generate_premium_log(session: BattleSession, result: dict, xp_gain: int = 85, rating_delta: int = 1) -> str:
    """Generate telecast-style premium log for the match."""
    lines: List[str] = []

    # XP reward block
    mvp = result.get("mvp")
    goals_by_player = defaultdict(int)
    for g in session.goals:
        goals_by_player[g["player"]] += 1
    reason = "за отличную игру!"
    if result.get("winner") in ("team1", "team2"):
        top_goals = goals_by_player.get(mvp, 0)
        if mvp and top_goals >= 2:
            reason = f"за дубль {mvp} и уверенную победу!"
        else:
            reason = "за уверенную победу!"
    lines.append(f"💎 <b>+{xp_gain} XP {reason}</b>")

    # group goals by period to match scoreboard
    goals_by_period: DefaultDict[int, List[Dict]] = defaultdict(list)
    for g in session.goals:
        goals_by_period[g.get("period", 1)].append(g)

    goalies = [p for p in session.team1 + session.team2 if (p.get("pos") or "").startswith("G")]

    max_period = max(goals_by_period.keys(), default=session.current_period or 3)
    for period in range(1, max_period + 1):
        period_lines: List[str] = []

        # add real goal scorers for this period (exactly as many as scored)
        goal_events = goals_by_period.get(period, [])
        for g in goal_events:
            period_lines.append(
                f"🥅 <b>{g['player']}</b> 🎯 кладёт шайбу в сетку! <i>({g['team']})</i>"
            )

        # add a few extra events (4-5) for richness
        extra_events_target = len(goal_events) + random.randint(4, 5)
        while len(period_lines) < extra_events_target:
            r = random.random()
            if r < 0.4 and goalies:
                gk = random.choice(goalies)
                period_lines.append(
                    f"🛡 <b>{gk['name']}</b> спасает бросок!"
                )
            elif r < 0.7:
                period_lines.append("🏟 <i>Фанаты запускают волну!</i>")
            elif r < 0.9:
                xg1 = round(random.uniform(0.5, 3.0), 1)
                xg2 = round(random.uniform(0.5, 3.0), 1)
                period_lines.append(
                    f"📊 <b>XG:</b> {session.name1} {xg1} — {session.name2} {xg2}"
                )
            else:
                period_lines.append(
                    "⏱ <b>Готовь тактику на следующий период!</b>"
                )

        random.shuffle(period_lines)
        lines.extend(period_lines)

    # Final summary block
    s1 = result.get("score", {}).get("team1", 0)
    s2 = result.get("score", {}).get("team2", 0)
    lines.append(
        f"🏆 Матч окончен: <i>{session.name1}</i> {s1} — {s2} <i>{session.name2}</i>"
    )
    mvp = result.get("mvp")
    if mvp:
        goals = sum(1 for g in session.goals if g["player"] == mvp)
        goal_word = "гол" if goals == 1 else "гола"
        lines.append(f"🎯 Звезда матча: <b>{mvp}</b> — {goals} {goal_word}")
    lines.append(f"🎖 +{xp_gain} XP, рейтинг +{rating_delta}")

    return "\n".join(lines)
