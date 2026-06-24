"""Smoke checks for centralized OpenAI client (standard auto tier by default)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv()
load_dotenv(BACKEND_ROOT / ".env")

from openai_flex import (  # noqa: E402
    DEFAULT_TIMEOUT_SECONDS,
    call_openai_flex,
    create_chat_completion,
    get_service_tier,
    get_timeout_seconds,
)


def test_defaults() -> None:
    import os

    env = os.environ.copy()
    for key in ("OPENAI_SERVICE_TIER", "OPENAI_TIMEOUT_SECONDS"):
        env.pop(key, None)
    with patch.dict("os.environ", env, clear=True):
        assert get_service_tier() == "auto"
        assert get_timeout_seconds() == DEFAULT_TIMEOUT_SECONDS


def test_create_chat_completion_uses_auto_and_timeout() -> None:
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='{"ok": true}'))]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("openai_flex._build_client", return_value=mock_client), patch(
        "openai_flex.get_service_tier",
        return_value="auto",
    ), patch(
        "openai_flex.get_timeout_seconds",
        return_value=900.0,
    ):
        create_chat_completion(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "ping"}],
            temperature=0.0,
            response_format={"type": "json_object"},
        )

    mock_client.chat.completions.create.assert_called_once()
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["service_tier"] == "auto"
    assert kwargs["timeout"] == 900.0
    assert kwargs["model"] == "gpt-4o-mini"


def test_call_openai_flex_returns_text() -> None:
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="hello"))]
    with patch("openai_flex.create_chat_completion", return_value=mock_response):
        text = call_openai_flex(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "ping"}],
        )
    assert text == "hello"


def test_live_call() -> None:
    from llm import validate_api_key

    validate_api_key()
    text = call_openai_flex(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Reply with the single word: ok"},
            {"role": "user", "content": "ping"},
        ],
        temperature=0.0,
    )
    assert "ok" in text.lower()


def main() -> int:
    tests = [
        test_defaults,
        test_create_chat_completion_uses_auto_and_timeout,
        test_call_openai_flex_returns_text,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")

    if "--live" in sys.argv:
        test_live_call()
        print("ok test_live_call")
    else:
        print("Skipping live API call (pass --live to exercise OpenAI).")

    print(f"All {len(tests)} mock checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
