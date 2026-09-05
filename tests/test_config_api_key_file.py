from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from PhyAgentOS.config.loader import load_config
from PhyAgentOS.config.schema import Config


def _write_key(path: Path, value: str = "sk-test-key") -> None:
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_load_config_resolves_relative_api_key_file_without_mutating_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    key_path = tmp_path / "secret.key"
    _write_key(key_path)
    config_path.write_text(
        '{"agents":{"defaults":{"model":"gpt-5.6-sol","provider":"custom"}},'
        '"providers":{"custom":{"apiKeyFile":"secret.key","apiBase":"https://example.test/v1"}}}',
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.get_api_key("gpt-5.6-sol") == "sk-test-key"
    assert config.providers.custom.api_key == ""
    assert config.providers.custom.api_key_file == "secret.key"


def test_provider_rejects_inline_and_file_credentials() -> None:
    with pytest.raises(ValueError, match="only one"):
        Config.model_validate({"providers": {"custom": {"apiKey": "x", "apiKeyFile": "x"}}})


def test_api_key_file_rejects_symlink_and_permissive_mode(tmp_path: Path) -> None:
    key_path = tmp_path / "secret.key"
    _write_key(key_path)
    link_path = tmp_path / "link.key"
    link_path.symlink_to(key_path)
    config = Config.model_validate({
        "agents": {"defaults": {"model": "gpt-5.6-sol", "provider": "custom"}},
        "providers": {"custom": {"apiKeyFile": "link.key"}},
    })
    config._config_path = tmp_path / "config.json"
    with pytest.raises(ValueError, match="cannot be opened"):
        config.get_api_key("gpt-5.6-sol")

    key_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
    config.providers.custom.api_key_file = "secret.key"
    with pytest.raises(ValueError, match="group/other"):
        config.get_api_key("gpt-5.6-sol")
