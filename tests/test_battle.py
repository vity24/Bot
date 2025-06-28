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
