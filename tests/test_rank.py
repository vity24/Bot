import types, asyncio, pytest

try:
    import bot
except ModuleNotFoundError:
    pytest.skip("telegram not available", allow_module_level=True)

class DummyMessage:
    def __init__(self):
        self.text = None
    async def reply_text(self, text, **kwargs):
        self.text = text

class DummyBot:
    pass

def test_rank_output(monkeypatch):
    monkeypatch.setattr(bot, 'is_user_subscribed', lambda b, u: True)
    msg = DummyMessage()
    update = types.SimpleNamespace(effective_user=types.SimpleNamespace(id=1), message=msg)
    ctx = types.SimpleNamespace(bot=DummyBot())
    asyncio.get_event_loop().run_until_complete(bot.rank(update, ctx))
    assert "Рейтинги" in msg.text
