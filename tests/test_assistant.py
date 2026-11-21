import json

import httpx
import pytest

from app.assistant import (
    AssistantConfigurationError,
    AssistantProviderError,
    OnboardingAssistant,
    OpenAICompatibleClient,
    UNSUPPORTED_ANSWER,
)
from app.knowledge import get_role
from app.sessions import MAX_HISTORY_MESSAGES


class FakeProvider:
    def __init__(self, content: str) -> None:
        self.content = content
        self.messages: list[dict[str, str]] | None = None

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.messages = messages
        return self.content


def test_guide_prompt_contains_selected_role_task_and_curated_notes() -> None:
    provider = FakeProvider(
        json.dumps(
            {
                "answer": "Start with a small monthly budget table.",
                "steps": [{"title": "Enter data", "instructions": "Select a cell and enter a label."}],
                "source_ids": ["libreoffice_calc_data_guide_24_8"],
                "unsupported": False,
            }
        )
    )
    role = get_role("finance_analyst")
    task = role["tasks"][0]
    assistant = OnboardingAssistant(provider)

    result = assistant.generate_guide(role, task, [])

    assert result.unsupported is False
    assert result.steps[0]["title"] == "Enter data"
    assert provider.messages is not None
    prompt = provider.messages[0]["content"]
    assert "Finance analyst" in prompt
    assert "monthly_budget" in prompt
    assert "calc_enter_and_edit_data" in prompt
    assert "https://books.libreoffice.org/en/CG248/CG24802-EnteringandEditingData.html" in prompt


def test_unknown_source_ids_do_not_become_citations() -> None:
    provider = FakeProvider(
        json.dumps(
            {
                "answer": "Unsupported answer",
                "source_ids": ["https://attacker.example/fake-source"],
                "unsupported": False,
            }
        )
    )
    role = get_role("finance_analyst")
    assistant = OnboardingAssistant(provider)

    result = assistant.answer_question(role, None, [], "How do I use an unsupported feature?")

    assert result.unsupported is True
    assert result.answer == UNSUPPORTED_ANSWER
    assert result.source_ids == ()


def test_model_generated_urls_are_not_returned_as_answer_content() -> None:
    provider = FakeProvider(
        json.dumps(
            {
                "answer": "Read https://attacker.example/manual for instructions.",
                "source_ids": ["libreoffice_calc_guide_24_8"],
                "unsupported": False,
            }
        )
    )
    role = get_role("finance_analyst")
    assistant = OnboardingAssistant(provider)

    result = assistant.answer_question(role, None, [], "Where can I read more?")

    assert result.unsupported is True
    assert "attacker.example" not in result.answer
    assert result.source_ids == ()


def test_openai_compatible_client_sends_configured_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
    monkeypatch.delenv("TOGETHER_MODEL", raising=False)
    monkeypatch.delenv("TOGETHER_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "demo-secret")
    monkeypatch.setenv("OPENAI_MODEL", "demo-model")
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]},
        )

    client = OpenAICompatibleClient(transport=httpx.MockTransport(handle))

    content = client.complete([{"role": "user", "content": "Hello"}])

    assert content == '{"answer":"ok"}'
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["authorization"] == "Bearer demo-secret"
    assert captured["payload"]["model"] == "demo-model"
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["payload"]["max_tokens"] == 2000


def test_model_request_allows_more_than_30_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "demo-secret")
    monkeypatch.setenv("OPENAI_MODEL", "demo-model")
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["timeout"] = request.extensions["timeout"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]},
        )

    client = OpenAICompatibleClient(transport=httpx.MockTransport(handle))

    client.complete([{"role": "user", "content": "Hello"}])

    assert captured["timeout"]["read"] > 30


def test_json_fenced_model_output_is_parsed() -> None:
    provider = FakeProvider(
        "```json\n"
        '{"answer":"Supported","source_ids":["libreoffice_calc_guide_24_8"],"unsupported":false}'
        "\n```"
    )
    role = get_role("finance_analyst")

    result = OnboardingAssistant(provider).answer_question(role, None, [], "What does the guide say?")

    assert result.unsupported is False
    assert result.answer == "Supported"
    assert result.source_ids == ("libreoffice_calc_guide_24_8",)


def test_together_compatible_client_uses_together_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOGETHER_API_KEY", "together-secret")
    monkeypatch.setenv("TOGETHER_MODEL", "together-model")
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]},
        )

    client = OpenAICompatibleClient(transport=httpx.MockTransport(handle))

    assert client.complete([{"role": "user", "content": "Hello"}]) == '{"answer":"ok"}'
    assert captured["url"] == "https://api.together.xyz/v1/chat/completions"
    assert captured["authorization"] == "Bearer together-secret"
    assert captured["payload"]["model"] == "together-model"


def test_openai_compatible_client_requires_key_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
    monkeypatch.delenv("TOGETHER_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    with pytest.raises(AssistantConfigurationError, match="OPENAI_API_KEY and OPENAI_MODEL"):
        OpenAICompatibleClient().complete([])


def test_provider_failure_does_not_expose_provider_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
    monkeypatch.delenv("TOGETHER_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "demo-secret")
    monkeypatch.setenv("OPENAI_MODEL", "demo-model")

    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal provider detail and credential=secret")

    client = OpenAICompatibleClient(transport=httpx.MockTransport(handle))

    with pytest.raises(AssistantProviderError) as error:
        client.complete([])

    assert "internal provider detail" not in str(error.value)
    assert "secret" not in str(error.value)


def test_prompt_history_is_limited_to_the_configured_message_count() -> None:
    provider = FakeProvider(
        json.dumps({"answer": "Supported", "source_ids": ["libreoffice_calc_guide_24_8"], "unsupported": False})
    )
    role = get_role("finance_analyst")
    history = [{"role": "user", "content": f"message {index}"} for index in range(MAX_HISTORY_MESSAGES + 3)]

    OnboardingAssistant(provider).answer_question(role, None, history, "follow up")

    assert provider.messages is not None
    history_messages = provider.messages[1:-1]
    assert len(history_messages) == MAX_HISTORY_MESSAGES
    assert history_messages[0]["content"] == "message 3"