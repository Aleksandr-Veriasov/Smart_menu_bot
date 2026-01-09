import pytest

from packages.integrations import deepseek_api


class DummySecret:
    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


class DummySettings:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.deepseek = type(
            "Deepseek",
            (),
            {
                "api_key": DummySecret(api_key),
                "base_url": base_url,
                "model": model,
            },
        )()


class FakeMessage:
    def __init__(self, content: str | None) -> None:
        self.content = content


class FakeChoice:
    def __init__(self, content: str | None) -> None:
        self.message = FakeMessage(content)


class FakeResponse:
    def __init__(self, content: str | None) -> None:
        self.choices = [FakeChoice(content)]


class FakeCompletions:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> FakeResponse:
        self.calls.append(kwargs)
        return self._response


class FakeChat:
    def __init__(self, response: FakeResponse) -> None:
        self.completions = FakeCompletions(response)


class FakeClient:
    def __init__(self, api_key: str, base_url: str, response: FakeResponse) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.chat = FakeChat(response)


class TestDeepSeekClient:
    def test_init_uses_settings_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dummy_settings = DummySettings(
            api_key="settings_key",
            base_url="https://deepseek.local",
            model="deepseek-chat",
        )
        monkeypatch.setattr(deepseek_api, "settings", dummy_settings)

        response = FakeResponse("ok")
        created: list[FakeClient] = []

        def fake_openai(*, api_key: str, base_url: str) -> FakeClient:
            client = FakeClient(api_key=api_key, base_url=base_url, response=response)
            created.append(client)
            return client

        monkeypatch.setattr(deepseek_api, "OpenAI", fake_openai)

        client = deepseek_api.DeepSeekClient()

        assert client.model == "deepseek-chat"
        assert created[0].api_key == "settings_key"
        assert created[0].base_url == "https://deepseek.local"

    def test_chat_returns_stripped_content_and_passes_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dummy_settings = DummySettings(
            api_key="settings_key",
            base_url="https://deepseek.local",
            model="deepseek-chat",
        )
        monkeypatch.setattr(deepseek_api, "settings", dummy_settings)

        response = FakeResponse("  hello  ")
        created: list[FakeClient] = []

        def fake_openai(*, api_key: str, base_url: str) -> FakeClient:
            client = FakeClient(api_key=api_key, base_url=base_url, response=response)
            created.append(client)
            return client

        monkeypatch.setattr(deepseek_api, "OpenAI", fake_openai)

        client = deepseek_api.DeepSeekClient()
        messages = ({"role": "user", "content": "hi"},)

        result = client.chat(messages, temperature=0.7, timeout=10.0)

        assert result == "hello"

        call = created[0].chat.completions.calls[0]
        assert call["model"] == "deepseek-chat"
        assert call["temperature"] == 0.7
        assert call["stream"] is False
        assert call["messages"] == [{"role": "user", "content": "hi"}]
        assert call["timeout"] == 10.0

    def test_chat_handles_none_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dummy_settings = DummySettings(
            api_key="settings_key",
            base_url="https://deepseek.local",
            model="deepseek-chat",
        )
        monkeypatch.setattr(deepseek_api, "settings", dummy_settings)

        response = FakeResponse(None)

        def fake_openai(*, api_key: str, base_url: str) -> FakeClient:
            return FakeClient(api_key=api_key, base_url=base_url, response=response)

        monkeypatch.setattr(deepseek_api, "OpenAI", fake_openai)

        client = deepseek_api.DeepSeekClient()
        result = client.chat([{"role": "user", "content": "hi"}])

        assert result == ""
