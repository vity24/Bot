import os, sys, types, asyncio, time
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
try:
    import handlers
except ModuleNotFoundError:
    import pytest
    pytest.skip("telegram not available", allow_module_level=True)

class DummyBot:
    async def send_message(self, *a, **kw):
        pass
    async def edit_message_text(self, *a, **kw):
        pass
    async def delete_message(self, *a, **kw):
        pass


async def fake_run(*a, **kw):
    return {'winner':'team1','score':{'team1':1,'team2':0},'log':[], 'str_gap':0}

async def fake_apply(*a, **kw):
    pass

def test_pvp_pairing(monkeypatch):
    handlers.PVP_QUEUE.clear()
    monkeypatch.setattr(handlers, '_build_team', lambda uid, ids=None: [])
    monkeypatch.setattr(handlers, '_start_pvp_duel', lambda *a, **kw: asyncio.get_event_loop().create_task(fake_run()))
    monkeypatch.setattr(handlers, 'apply_xp', lambda *a, **kw: asyncio.get_event_loop().create_task(fake_apply()))

    bot = DummyBot()
    app_data = {}
    ctx1 = types.SimpleNamespace(bot=bot, user_data={'fight_mode':'pvp'}, application=types.SimpleNamespace(user_data=app_data))
    ctx2 = types.SimpleNamespace(bot=bot, user_data={'fight_mode':'pvp'}, application=types.SimpleNamespace(user_data=app_data))

    async def call(uid, ctx):
        user = types.SimpleNamespace(id=uid, username=f'u{uid}')
        msg = types.SimpleNamespace(chat_id=uid, reply_text=lambda *a, **kw: None)
        update = types.SimpleNamespace(message=msg, effective_user=user)
        await handlers.start_duel(update, ctx)

    asyncio.get_event_loop().run_until_complete(asyncio.gather(call(1, ctx1), call(2, ctx2)))
    assert not handlers.PVP_QUEUE


def test_pvp_queue_cleanup(monkeypatch):
    handlers.PVP_QUEUE.clear()
    handlers.PVP_QUEUE[1] = {"created": time.time() - handlers.PVP_TTL - 1}
    handlers.cleanup_pvp_queue()
    assert not handlers.PVP_QUEUE
