from __future__ import annotations

import pytest

from PhyAgentOS.cli.commands import _make_provider
from PhyAgentOS.config.schema import Config


def test_config_api_key_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    config = Config.model_validate(
        {
            "agents": {"defaults": {"model": "deepseek/deepseek-chat", "provider": "auto"}},
            "providers": {"deepseek": {"apiKey": "config-key"}},
        }
    )

    provider = _make_provider(config)

    assert config.get_provider_name() == "deepseek"
    assert config.get_api_key() == "config-key"
    assert provider.api_key == "config-key"


def test_env_api_key_used_when_config_api_key_is_empty(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    config = Config.model_validate(
        {
            "agents": {"defaults": {"model": "deepseek/deepseek-chat", "provider": "auto"}},
            "providers": {"deepseek": {"apiKey": ""}},
        }
    )

    provider = _make_provider(config)

    assert config.get_provider_name() == "deepseek"
    assert config.get_api_key() == "env-key"
    assert provider.api_key == "env-key"


def test_provider_override_uses_matching_env_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    config = Config.model_validate(
        {
            "agents": {"defaults": {"model": "anthropic/claude-sonnet-4-5", "provider": "auto"}},
            "providers": {"deepseek": {"apiKey": ""}},
        }
    )

    provider = _make_provider(
        config,
        model="claude-sonnet-4-5",
        provider_name_override="deepseek",
    )

    assert provider.api_key == "env-key"


def test_missing_config_and_env_key_keeps_no_api_key_error(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = Config.model_validate(
        {
            "agents": {"defaults": {"model": "deepseek/deepseek-chat", "provider": "auto"}},
            "providers": {"deepseek": {"apiKey": ""}},
        }
    )

    with pytest.raises(Exception) as exc_info:
        _make_provider(config)

    assert exc_info.value.__class__.__name__ == "Exit"
