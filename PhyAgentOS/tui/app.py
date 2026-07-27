"""PhyAgentOS TUI Application."""

import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen

from PhyAgentOS import __logo__, __version__
from PhyAgentOS.config.loader import load_config
from PhyAgentOS.config.schema import Config
from PhyAgentOS.tui.themes import THEMES, get_theme_name
from PhyAgentOS.tui.widgets.app_header import AppHeader


class PhyAgentOSApp(App):
    """PhyAgentOS Terminal User Interface."""

    TITLE = f"{__logo__} PhyAgentOS"
    SUB_TITLE = f"v{__version__}"

    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("escape", "back_or_quit", "Back / Quit x2"),
        Binding("ctrl+r", "restart_gateway", "Restart Gateway"),
        Binding("ctrl+1", "switch_screen('chat')", "Chat", show=False),
        Binding("ctrl+2", "switch_screen('providers')", "Providers", show=False),
        Binding("ctrl+3", "switch_screen('channels')", "Channels", show=False),
        Binding("ctrl+4", "switch_screen('settings')", "Settings", show=False),
    ]

    def __init__(self, config_path: str | None = None):
        super().__init__()
        for theme in THEMES.values():
            self.register_theme(theme)
        self._config_path = config_path
        self._config: Config | None = None
        self._gateway_service = None
        self._esc_last = 0.0
        if config_path:
            from PhyAgentOS.config.loader import set_config_path

            set_config_path(Path(config_path).expanduser())
        self.theme = get_theme_name(self.config.tui.theme)

    @property
    def config(self) -> Config:
        if self._config is None:
            self._config = load_config(self._config_file)
        return self._config

    @property
    def _config_file(self) -> Path | None:
        return Path(self._config_path).expanduser() if self._config_path else None

    def reload_config(self) -> None:
        self._config = load_config(self._config_file)

    def compose(self) -> ComposeResult:
        # Chrome (AppHeader/Footer) is composed inside each screen, because
        # App.compose mounts onto the default screen which gets covered when
        # the chat screen is pushed.
        yield from ()

    def on_mount(self) -> None:
        self._start_gateway()
        self.switch_to_chat()

    def _start_gateway(self) -> None:
        from PhyAgentOS.tui.services.gateway_service import GatewayService
        self._gateway_service = GatewayService(self.config, self)
        self.run_worker(self._gateway_service.start(), exclusive=False)

    async def restart_gateway(self) -> None:
        """Stop the gateway, reload config, and start it again."""
        from PhyAgentOS.tui.services.gateway_service import GatewayService

        if self._gateway_service is not None:
            await self._gateway_service.stop()
        self.reload_config()
        self._gateway_service = GatewayService(self.config, self)
        await self._gateway_service.start()
        if self._gateway_service.error:
            self.notify(
                f"Gateway not started: {self._gateway_service.error}",
                severity="error",
                timeout=8,
            )
        else:
            self.notify("Gateway restarted")
        try:
            self.query_one(AppHeader).refresh_header()
        except Exception:
            pass
        try:
            from PhyAgentOS.tui.widgets.status_pane import StatusPane

            self.screen.query_one(StatusPane).refresh_status()
        except Exception:
            pass

    async def action_restart_gateway(self) -> None:
        await self.restart_gateway()

    def switch_to_chat(self) -> None:
        from PhyAgentOS.tui.screens.chat import ChatScreen
        self.push_screen(ChatScreen())

    def action_back_or_quit(self) -> None:
        """Esc: close menu, go back from sub-screens, double-press to quit."""
        from PhyAgentOS.tui.screens.chat import ChatScreen

        if isinstance(self.screen, ChatScreen):
            if self.screen.menu_open:
                self.screen.close_menu()
                return
            now = time.monotonic()
            if now - self._esc_last < 2.0:
                self._esc_last = 0.0
                self.exit()
            else:
                self._esc_last = now
                self.notify("再按一次 Esc 退出", timeout=2)
        else:
            self._esc_last = 0.0
            self.switch_screen(ChatScreen())

    def action_switch_screen(self, screen_name: str) -> None:
        screen_map = {
            "chat": self._get_chat_screen,
            "providers": self._get_providers_screen,
            "channels": self._get_channels_screen,
            "settings": self._get_settings_screen,
        }
        factory = screen_map.get(screen_name)
        if factory:
            self.switch_screen(factory())

    def _get_chat_screen(self) -> Screen:
        from PhyAgentOS.tui.screens.chat import ChatScreen
        return ChatScreen()

    def _get_providers_screen(self) -> Screen:
        from PhyAgentOS.tui.screens.providers import ProvidersScreen
        return ProvidersScreen()

    def _get_channels_screen(self) -> Screen:
        from PhyAgentOS.tui.screens.channels import ChannelsScreen
        return ChannelsScreen()

    def _get_settings_screen(self) -> Screen:
        from PhyAgentOS.tui.screens.settings import SettingsScreen
        return SettingsScreen()

    async def on_unmount(self) -> None:
        if self._gateway_service is not None:
            await self._gateway_service.stop()


def run_tui(config_path: str | None = None) -> None:
    """Run the PhyAgentOS TUI."""
    app = PhyAgentOSApp(config_path=config_path)
    app.run()
