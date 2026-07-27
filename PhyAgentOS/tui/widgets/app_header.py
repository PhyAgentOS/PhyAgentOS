"""Custom slim application header."""

import subprocess
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from PhyAgentOS import __logo__, __version__


def _repo_version() -> str:
    """Best-effort version: git tag in a dev checkout, else package version."""
    try:
        repo_root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            ["git", "describe", "--tags"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=repo_root,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return f"v{__version__}"


class AppHeader(Horizontal):
    """Left: branding. Right: active model + version."""

    def compose(self) -> ComposeResult:
        yield Static(f"{__logo__} PhyAgentOS", classes="header-title")
        yield Static("", classes="header-right")

    def on_mount(self) -> None:
        self.refresh_header()

    def refresh_header(self) -> None:
        model = self.app.config.agents.defaults.model
        self.query_one(".header-right", Static).update(f"{model} · {_repo_version()}")
