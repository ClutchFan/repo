from finagent.agent.llm import LLMClient


class FakeMsg:
    def __init__(self, c): self.content = c


class FakeChoice:
    def __init__(self, c): self.message = FakeMsg(c)


class FakeResp:
    def __init__(self, c): self.choices = [FakeChoice(c)]


class FakeChat:
    captured_kwargs = None

    def create(self, **kw):
        FakeChat.captured_kwargs = kw
        return FakeResp('{"value": 42}')


class FakeCompletions:
    chat = type("C", (), {"completions": FakeChat()})()


class FakeOpenAI:
    def __init__(self): self.chat = FakeCompletions().chat


def test_complete_json_request_shape():
    FakeChat.captured_kwargs = None
    client = LLMClient(FakeOpenAI(), "gpt-4o")

    result = client.complete_json(
        "sys",
        [{"role": "user", "content": "hi"}],
        {"type": "object"}
    )

    # Verify the response content
    assert result == {"value": 42}

    # Verify request shape
    assert FakeChat.captured_kwargs is not None
    assert FakeChat.captured_kwargs["model"] == "gpt-4o"

    # Check messages - system message first, then user message
    messages = FakeChat.captured_kwargs["messages"]
    assert len(messages) == 2
    assert messages[0] == {"role": "system", "content": "sys"}
    assert messages[1] == {"role": "user", "content": "hi"}

    # Check response format
    assert FakeChat.captured_kwargs["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "result",
            "strict": True,
            "schema": {"type": "object"}
        }
    }

    # No tools should be present or None
    assert "tools" not in FakeChat.captured_kwargs or FakeChat.captured_kwargs["tools"] is None


def test_complete_json_with_tools():
    FakeChat.captured_kwargs = None
    client = LLMClient(FakeOpenAI(), "gpt-4o")

    test_tools = [{"type": "function", "function": {"name": "test_tool"}}]

    result = client.complete_json(
        "sys",
        [{"role": "user", "content": "hi"}],
        {"type": "object"},
        tools=test_tools
    )

    assert result == {"value": 42}

    # Verify tools were passed correctly
    assert FakeChat.captured_kwargs["tools"] == test_tools
