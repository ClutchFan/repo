from finagent.agent.llm import LLMClient


class FakeMsg:
    def __init__(self, c): self.content = c


class FakeChoice:
    def __init__(self, c): self.message = FakeMsg(c)


class FakeResp:
    def __init__(self, c): self.choices = [FakeChoice(c)]


class FakeChat:
    def create(self, **kw): return FakeResp('{"value": 42}')


class FakeCompletions:
    chat = type("C", (), {"completions": FakeChat()})()


class FakeOpenAI:
    def __init__(self): self.chat = FakeCompletions().chat


def test_complete_json():
    c = LLMClient(FakeOpenAI(), "gpt-4o")
    assert c.complete_json("sys", [{"role": "user", "content": "hi"}],
                           {"type": "object"}) == {"value": 42}
