"""Settings screen for PhyAgentOS TUI."""

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Select

from PhyAgentOS.config.loader import save_config
from PhyAgentOS.tui.themes import THEME_LABELS, get_theme_name
from PhyAgentOS.tui.widgets.app_header import AppHeader
from PhyAgentOS.tui.widgets.section_title import SectionTitle


class SettingsScreen(Screen):
    """Settings screen."""

    def compose(self) -> ComposeResult:
        yield AppHeader()
        with Vertical(id="settings-wrap"):
            yield SectionTitle("Settings")
            yield Label("Tab 菜单 · Esc 返回聊天", classes="hint")
            with ScrollableContainer(id="settings-main"):

                # Appearance
                with Vertical(classes="settings-group"):
                    yield Label("Appearance", classes="settings-group-title")
                    with Horizontal(classes="form-row"):
                        yield Label("Theme:", classes="form-label")
                        yield Select(
                            [(label, key) for key, label in THEME_LABELS.items()],
                            id="setting-theme",
                            allow_blank=False,
                        )

                # Agent Defaults
                with Vertical(classes="settings-group"):
                    yield Label("Agent Defaults", classes="settings-group-title")
                    with Horizontal(classes="form-row"):
                        yield Label("Model:", classes="form-label")
                        yield Input(id="setting-model", classes="form-input")
                    with Horizontal(classes="form-row"):
                        yield Label("Temperature:", classes="form-label")
                        yield Input(id="setting-temperature", classes="form-input")
                    with Horizontal(classes="form-row"):
                        yield Label("Max Tokens:", classes="form-label")
                        yield Input(id="setting-max-tokens", classes="form-input")
                    with Horizontal(classes="form-row"):
                        yield Label("Context Window:", classes="form-label")
                        yield Input(id="setting-context-window", classes="form-input")

                # Gateway
                with Vertical(classes="settings-group"):
                    yield Label("Gateway", classes="settings-group-title")
                    with Horizontal(classes="form-row"):
                        yield Label("Port:", classes="form-label")
                        yield Input(id="setting-gateway-port", classes="form-input")

                # Tools
                with Vertical(classes="settings-group"):
                    yield Label("Tools", classes="settings-group-title")
                    with Horizontal(classes="form-row"):
                        yield Label("Web Search API Key:", classes="form-label")
                        yield Input(id="setting-web-search-key", classes="form-input", password=True)
                    with Horizontal(classes="form-row"):
                        yield Label("Exec Timeout:", classes="form-label")
                        yield Input(id="setting-exec-timeout", classes="form-input")

            with Horizontal(id="settings-footer"):
                yield Button("Save Settings", variant="primary", id="save-settings")
        yield Footer()

    def on_mount(self) -> None:
        """Load current settings."""
        config = self.app.config

        # Agent defaults
        self.query_one("#setting-model", Input).value = config.agents.defaults.model
        self.query_one("#setting-temperature", Input).value = str(config.agents.defaults.temperature)
        self.query_one("#setting-max-tokens", Input).value = str(config.agents.defaults.max_tokens)
        self.query_one("#setting-context-window", Input).value = str(config.agents.defaults.context_window_tokens)

        # Gateway
        self.query_one("#setting-gateway-port", Input).value = str(config.gateway.port)

        # Tools
        self.query_one("#setting-web-search-key", Input).value = config.tools.web.search.api_key
        self.query_one("#setting-exec-timeout", Input).value = str(config.tools.exec.timeout)

        # Appearance
        self.query_one("#setting-theme", Select).value = get_theme_name(config.tui.theme)

        self.query_one("#setting-model", Input).focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Apply theme immediately and persist (no gateway restart needed)."""
        if event.select.id != "setting-theme":
            return
        theme_name = get_theme_name(str(event.value))
        event.select.value = theme_name
        self.app.theme = theme_name
        config = self.app.config
        config.tui.theme = theme_name
        save_config(config)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle save button."""
        if event.button.id == "save-settings":
            self._save_settings()
            await self.app.restart_gateway()

    def _save_settings(self) -> None:
        """Save all settings to config."""
        config = self.app.config

        # Agent defaults
        config.agents.defaults.model = self.query_one("#setting-model", Input).value
        try:
            config.agents.defaults.temperature = float(self.query_one("#setting-temperature", Input).value)
        except ValueError:
            pass
        try:
            config.agents.defaults.max_tokens = int(self.query_one("#setting-max-tokens", Input).value)
        except ValueError:
            pass
        try:
            config.agents.defaults.context_window_tokens = int(self.query_one("#setting-context-window", Input).value)
        except ValueError:
            pass

        # Gateway
        try:
            config.gateway.port = int(self.query_one("#setting-gateway-port", Input).value)
        except ValueError:
            pass

        # Tools
        config.tools.web.search.api_key = self.query_one("#setting-web-search-key", Input).value
        try:
            config.tools.exec.timeout = int(self.query_one("#setting-exec-timeout", Input).value)
        except ValueError:
            pass

        save_config(config)
        self.app.reload_config()
        self.notify("Settings saved successfully")
