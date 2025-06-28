import os, sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from battle import BattleSession, BattleController
import random

def make_player(id=1):
    return {
        'id': id,
        'name': f'P{id}',
        'pos': 'F',
        'points': 50,
        'country': 'CA',
        'born': '1990',
        'weight': '90',
        'rarity': 'common',
        'owner_level': 1,
    }

def test_same_player_ids_across_teams_ok():
    random.seed(0)
    team1 = [make_player(1), make_player(2)]
    team2 = [make_player(1), make_player(3)]
    session = BattleSession(team1, team2)
    controller = BattleController(session)
    res = controller.auto_play()
    assert 'winner' in res


def test_battle_returns_strength_gap():
    random.seed(1)
    team1 = [make_player(1), make_player(2)]
    team2 = [make_player(3), make_player(4)]
    session = BattleSession(team1, team2)
    controller = BattleController(session)
    res = controller.auto_play()
    assert 'str_gap' in res


def test_no_draw_after_overtime():
    random.seed(2)
    team1 = [make_player(i) for i in range(1, 7)]
    team1[5]['pos'] = 'G'
    team2 = [make_player(i) for i in range(7, 13)]
    team2[5]['pos'] = 'G'
    session = BattleSession(team1, team2)
    controller = BattleController(session)
    res = controller.auto_play()
    assert res['winner'] in {'team1', 'team2'}


def test_overtime_sudden_death():
    random.seed(4)
    team1 = [make_player(i) for i in range(1, 7)]
    team1[5]['pos'] = 'G'
    team2 = [make_player(i) for i in range(7, 13)]
    team2[5]['pos'] = 'G'
    session = BattleSession(team1, team2)
    controller = BattleController(session)
    res = controller.auto_play()
    ot_goals = [g for g in session.goals if g['period'] == 4]
    assert len(ot_goals) <= 1
    if ot_goals:
        assert res['winner'] in {'team1', 'team2'}
        # no events from shootout period when OT goal scored
        assert not any(e for e in session.events if e.get('period') == 5)


def test_mvp_based_on_stats():
    random.seed(3)
    team1 = [make_player(i) for i in range(1, 7)]
    team1[5]['pos'] = 'G'
    team2 = [make_player(i) for i in range(7, 13)]
    team2[5]['pos'] = 'G'
    session = BattleSession(team1, team2)
    controller = BattleController(session)
    res = controller.auto_play()
    from collections import Counter
    goals = Counter(g['player'] for g in session.goals)
    max_goals = max(goals.values(), default=0)
    top_scorers = {n for n, g in goals.items() if g == max_goals and g > 0}
    saves = Counter(
        e['player']
        for e in session.events
        if e['type'] == 'save' and any(p['name'] == e['player'] and p['pos'] == 'G' for p in session.team1 + session.team2)
    )
    max_saves = max(saves.values(), default=0)
    top_goalies = {n for n, s in saves.items() if s == max_saves and s > 0}
    assert res['mvp'] in top_scorers.union(top_goalies)


def test_summary_shows_goals_for_field_player():
    from helpers.commentary import format_final_summary

    # create session with one scorer field player
    team1 = [make_player(1)]
    team2 = [make_player(2)]
    session = BattleSession(team1, team2)
    session.goals = [{"player": "P1", "team": "A", "period": 1}]
    session.events = []
    result = {"score": {"team1": 1, "team2": 0}, "mvp": "P1"}

    summary = format_final_summary(session, result, 0, 1)
    assert "P1" in summary
    assert "1 гол" in summary


def test_summary_shows_saves_for_goalie():
    from helpers.commentary import format_final_summary

    # goalie MVP with saves
    gk = make_player(3)
    gk['pos'] = 'G'
    team1 = [gk]
    team2 = [make_player(4)]
    session = BattleSession(team1, team2)
    session.goals = []
    session.events = [
        {"player": "P3", "type": "save"},
        {"player": "P3", "type": "save"},
    ]
    result = {"score": {"team1": 0, "team2": 0}, "mvp": "P3"}

    summary = format_final_summary(session, result, 0, 1)
    assert "P3" in summary
    assert "2 сейвов" in summary
