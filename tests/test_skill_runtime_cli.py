import sys
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parents[1]))

from PhyAgentOS.cli.commands import app  # noqa: E402


def test_skill_command_exposes_runtime_lifecycle_commands() -> None:
    result = CliRunner().invoke(app, ["skill", "--help"])

    assert result.exit_code == 0
    for command in (
        "list",
        "inspect",
        "start",
        "status",
        "logs",
        "stop",
        "search",
        "install",
        "update",
        "remove",
    ):
        assert command in result.stdout


def test_forge_node_command_exposes_distribution_lifecycle() -> None:
    result = CliRunner().invoke(app, ["forge-node", "--help"])

    assert result.exit_code == 0
    for command in ("install", "verify"):
        assert command in result.stdout


def test_skill_distribution_commands_use_registry_only() -> None:
    runner = CliRunner()
    for command in ("search", "install", "update"):
        result = runner.invoke(app, ["skill", command, "--help"])
        assert result.exit_code == 0
        assert "--index" not in result.stdout


def test_skill_search_merges_registry_with_local_status(monkeypatch) -> None:
    from PhyAgentOS.skill_runtime import catalog, registry

    class FakeRegistry:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def search_skills(self, query: str):
            assert query == "arm"
            return [
                {"name": "move-arm-by-ee", "description": "demo"},
                {"name": "other-arm", "description": "other"},
            ]

    class FakeCatalog:
        def list(self):
            return [SimpleNamespace(name="move-arm-by-ee")]

    monkeypatch.setattr(registry, "RegistryClient", FakeRegistry)
    monkeypatch.setattr(catalog, "SkillCatalog", FakeCatalog)

    result = CliRunner().invoke(app, ["skill", "search", "arm"])

    assert result.exit_code == 0
    assert "move-arm-by-ee" in result.stdout
    assert "installed" in result.stdout
    assert "not-installed" in result.stdout
