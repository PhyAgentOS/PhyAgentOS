import sys
from pathlib import Path

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
