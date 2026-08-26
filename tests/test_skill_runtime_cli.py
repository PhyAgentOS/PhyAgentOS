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


def test_skill_install_confirms_by_default_and_yes_skips_prompt(monkeypatch) -> None:
    from PhyAgentOS.cli import commands

    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        commands,
        "_install_skill_from_registry",
        lambda name, *, ask_confirmation: calls.append((name, ask_confirmation)),
    )
    runner = CliRunner()

    assert runner.invoke(app, ["skill", "install", "demo"]).exit_code == 0
    assert runner.invoke(app, ["skill", "install", "demo", "--yes"]).exit_code == 0

    assert calls == [("demo", True), ("demo", False)]


def test_local_skill_install_uses_the_same_confirmation(tmp_path: Path, monkeypatch) -> None:
    from PhyAgentOS.cli import commands

    bundle = tmp_path / "demo.tar.gz"
    bundle.write_bytes(b"bundle")
    calls: list[tuple[Path, bool]] = []
    monkeypatch.setattr(
        commands,
        "_install_skill_from_local_bundle",
        lambda path, *, ask_confirmation: calls.append((path, ask_confirmation)),
    )

    result = CliRunner().invoke(app, ["skill", "install", str(bundle)])

    assert result.exit_code == 0
    assert calls == [(bundle, True)]


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
