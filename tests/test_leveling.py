import types
import os, sys
import pytest
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from helpers import leveling


def test_level_curve():
    assert leveling.level_from_xp(0) == 1
    assert leveling.level_from_xp(2400) == 5
    assert leveling.level_from_xp(13500) == 10


def test_pvp_more_than_pve():
    res = {"winner": "team1", "str_gap": 0}
    pvp = leveling.calc_battle_xp(res, is_pve=False, streak=1, strength_gap=0)
    pve = leveling.calc_battle_xp(res, is_pve=True, streak=1, strength_gap=0)
    assert pvp > pve


def test_antifarm_zero_after_11():
    res = {"winner": "team1", "str_gap": 0}
    xp = leveling.calc_battle_xp(res, is_pve=True, streak=11, strength_gap=0)
    assert xp == 0


def test_level_up_triggers_reward(monkeypatch):
    called = {}

    async def fake_reward(uid, lvl, ctx):
        called['lvl'] = lvl

    try:
        import handlers
    except ModuleNotFoundError:
        pytest.skip("telegram not available")
    monkeypatch.setattr(handlers, 'grant_level_reward', fake_reward)
    user_id = 1
    ctx = types.SimpleNamespace(bot=types.SimpleNamespace(send_message=lambda *a, **kw: None))
    res = {"winner": "team1", "str_gap": 0}
    # ensure db has user
    import db
    conn = db.get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (id, username) VALUES (?, ?)", (user_id, 'test'))
    conn.commit()
    conn.close()
    # force level up
    db.update_xp(user_id, 150*10, 10, 0)
    import asyncio
    asyncio.run(handlers.apply_xp(user_id, res, True, ctx))
    assert called.get('lvl') is not None
