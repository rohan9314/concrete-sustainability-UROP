"""Repo-wide pytest guards: live OpenAI/Tavily stay opt-in."""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items) -> None:  # noqa: ARG001
    skip_openai = pytest.mark.skip(
        reason="Live OpenAI tests are opt-in; set RUN_LIVE_OPENAI_TESTS=1"
    )
    skip_tavily = pytest.mark.skip(
        reason="Live Tavily tests are opt-in; set RUN_LIVE_TAVILY_TESTS=1"
    )
    allow_openai = os.environ.get("RUN_LIVE_OPENAI_TESTS", "").strip() == "1"
    allow_tavily = os.environ.get("RUN_LIVE_TAVILY_TESTS", "").strip() == "1"
    for item in items:
        if not allow_openai and item.get_closest_marker("live_openai"):
            item.add_marker(skip_openai)
        if not allow_tavily and item.get_closest_marker("live_tavily"):
            item.add_marker(skip_tavily)
