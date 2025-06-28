import random
from collections import defaultdict
from typing import List
from battle import BattleSession

GOAL_CLIPS = [
    "🚀 {player} ({team}) выкатился из-за ворот и закинул шайбу под перекладину!",
    "💥 {player} ({team}) обыграл защитника один в один и пробил вратаря!",
    "🥅 ГОЛ! {player} ({team}) завершил молниеносную контратаку.",
]

SAVE_CLIPS = [
    "🛡 {goalie} ({team}) ловит шайбу в ловушку — шикарный сейв!",
    "⚡ {goalie} ({team}) щитком выручает команду в упор!",
]

MISS_CLIPS = [
    "🎯 Штанга! Арена ахнула — чуть-чуть не хватило {player} ({team}).",
    "😱 {player} ({team}) промахивается с убойной позиции!",
]

FAN_CLIPS = [
    "🏟 Фанаты {team} поют гимн прямо на трибунах!",
    "🎵 Трибуны ревут, волна прокатилась по стадиону!",
]

EXPERT_CLIPS = [
    "🎙 Эксперт: “{team1} держит шайбу, но {team2} опаснее на добиваниях.”",
    "📺 Студия: “{player} за последние 5 минут дважды угрожал воротам — вратарь явно нервничает.”",
]

MEME_CLIPS = [
    "🤣 Судья чуть сам шайбу не поймал на пузо!",
    "🤪 {player} ({team}) чуть не уронил клюшку от скорости!",
]

PERIOD_TITLES = ["Первый", "Второй", "Третий"]


def _random_player(session: BattleSession) -> tuple[str, str]:
    players = session.team1 + session.team2
    p = random.choice(players)
    team = session.name1 if p in session.team1 else session.name2
    return p["name"], team


def _random_goalie(session: BattleSession) -> tuple[str, str]:
    goalies = [p for p in session.team1 + session.team2 if (p.get("pos") or "").startswith("G")]
    if not goalies:
        return _random_player(session)
    g = random.choice(goalies)
    team = session.name1 if g in session.team1 else session.name2
    return g["name"], team


def format_period_summary(session: BattleSession) -> str:
    """Return a short recap of the just finished period."""
    period = session.current_period
    if period < 1 or period > 3:
        return ""

    title = f"🏁 {PERIOD_TITLES[period-1]} период завершён!"
    score_line = (
        f"📊 На табло: {session.name1} {session.score['team1']} — {session.score['team2']} {session.name2}"
    )

    period_events = [e for e in session.events if e.get("period") == period]
    goal_lines: List[str] = []
    other_lines: List[str] = []
    for ev in period_events:
        player = ev.get("player", "")
        team = ev.get("team", "")
        if ev.get("type") == "goal":
            goal_lines.append(f"🥅 <b>{player}</b> ({team}) забивает!")
        elif ev.get("type") == "save":
            other_lines.append(f"🛡 {player} ({team}) спасает бросок")
        elif ev.get("type") == "penalty":
            other_lines.append(f"🚔 {player} ({team}) удалён")
        elif ev.get("type") == "injury":
            other_lines.append(f"💢 {player} ({team}) травмирован")
        elif ev.get("type") == "fight":
            other_lines.append(f"🥊 {player} ({team}) начинает драку")
        elif ev.get("type") == "block":
            other_lines.append(f"🚫 {player} ({team}) блокирует бросок")
        elif ev.get("type") == "post":
            other_lines.append(f"🔔 {player} ({team}) попадает в штангу")
        elif ev.get("type") == "miss":
            other_lines.append(f"❌ {player} ({team}) мимо ворот")

    random.shuffle(other_lines)
    lines = goal_lines + other_lines
    if len(lines) < 5:
        while len(lines) < 5:
            template = random.choice(FAN_CLIPS + MEME_CLIPS)
            if "{player}" in template:
                name, tm = _random_player(session)
                lines.append(template.format(player=name, team=tm))
            else:
                lines.append(template.format(team=session.name1))
    lines = lines[:8]

    closing = (
        "⏱ Второй период начинается — скорректируй тактику, тренер!"
        if period == 1
        else "⏱ Финальный период впереди — настрой свою команду!"
        if period == 2
        else ""
    )

    event_text = "\n".join(lines)
    return f"{title}\n{score_line}\n\n{event_text}\n\n{closing}"


def format_final_summary(session: BattleSession, result: dict, xp_gain: int, level: int, leveled_up: bool = False) -> str:
    """Generate concise final match summary without XP details."""
    s1 = result.get("score", {}).get("team1", 0)
    s2 = result.get("score", {}).get("team2", 0)
    header = f"🏆 Матч окончен: <i>{session.name1}</i> {s1} — {s2} <i>{session.name2}</i>"

    parts: List[str] = [header]

    mvp = result.get("mvp")
    goals_by_player = defaultdict(int)
    for g in session.goals:
        goals_by_player[g["player"]] += 1

    players = {p["name"]: p for p in session.team1 + session.team2}
    saves_by_player = defaultdict(int)
    for e in session.events:
        if (
            e.get("type") == "save"
            and players.get(e.get("player"), {}).get("pos") == "G"
        ):
            saves_by_player[e["player"]] += 1

    if mvp:
        if players.get(mvp, {}).get("pos") == "G":
            saves = saves_by_player.get(mvp, 0)
            parts.append(f"🎯 Звезда матча: <b>{mvp}</b> — {saves} сейвов")
        else:
            goals = goals_by_player.get(mvp, 0)
            goal_word = "гол" if goals == 1 else "гола"
            parts.append(f"🎯 Звезда матча: <b>{mvp}</b> — {goals} {goal_word}")


    # XP reward is sent separately, so do not include it in the summary

    return "\n".join(parts)
