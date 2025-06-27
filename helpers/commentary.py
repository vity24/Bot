import random
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
    period = session.current_period
    if period < 1 or period > 3:
        return ""
    title = f"🏁 {PERIOD_TITLES[period-1]} период завершён!"
    score_line = f"📊 На табло: {session.name1} {session.score['team1']} — {session.score['team2']} {session.name2}"

    events: List[str] = []
    for _ in range(random.randint(3, 5)):
        pool = random.choice([GOAL_CLIPS, SAVE_CLIPS, MISS_CLIPS, MEME_CLIPS])
        template = random.choice(pool)
        if "{player}" in template:
            name, team = _random_player(session)
            events.append(template.format(player=name, team=team))
        elif "{goalie}" in template:
            name, team = _random_goalie(session)
            events.append(template.format(goalie=name, team=team))
        else:
            events.append(template.format(team=session.name1))
    event_text = "\n".join(events)

    face1 = random.randint(5, 15)
    face2 = random.randint(5, 15)
    xg1 = round(random.uniform(0.5, 2.5), 2)
    xg2 = round(random.uniform(0.5, 2.5), 2)
    stat_line = random.choice([
        f"📈 Вбрасывания: {session.name1} {face1} — {face2} {session.name2}",
        f"XG за период: {session.name1} {xg1} — {session.name2} {xg2}",
    ])

    fan_or_expert_template = random.choice(FAN_CLIPS + EXPERT_CLIPS)
    if "{player}" in fan_or_expert_template:
        name, team = _random_player(session)
        fan_or_expert = fan_or_expert_template.format(player=name, team=team, team1=session.name1, team2=session.name2)
    else:
        fan_or_expert = fan_or_expert_template.format(team=session.name1, team1=session.name1, team2=session.name2)

    if period == 1:
        closing = "⏱ Второй период начинается — скорректируй тактику, тренер!"
    elif period == 2:
        closing = "⏱ Финальный период впереди — настрой свою команду!"
    else:
        closing = ""

    return f"{title}\n{score_line}\n\n{event_text}\n{stat_line}\n\n{fan_or_expert}\n\n{closing}"
