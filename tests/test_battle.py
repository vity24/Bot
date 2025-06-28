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
