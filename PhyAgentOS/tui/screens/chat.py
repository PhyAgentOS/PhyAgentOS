"""Chat screen for PhyAgentOS TUI (tiling layout + overlay menu)."""

import asyncio

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer

from PhyAgentOS.bus.events import InboundMessage
from PhyAgentOS.tui.widgets.app_header import AppHeader
from PhyAgentOS.tui.widgets.chat_input import ChatInput
from PhyAgentOS.tui.widgets.chat_view import ChatView
from PhyAgentOS.tui.widgets.log_view import LogView
from PhyAgentOS.tui.widgets.menu_overlay import MenuOverlay
from PhyAgentOS.tui.widgets.section_title import SectionTitle
from PhyAgentOS.tui.widgets.status_pane import StatusPane


class ChatScreen(Screen):
    """Main screen: chat (2fr) + status/logs column (1fr), Tab opens menu."""

    BINDINGS = [
        Binding("tab", "toggle_menu", "Menu"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._outbound_task: asyncio.Task | None = None
        self._sink_id: int | None = None

    def compose(self) -> ComposeResult:
        yield AppHeader()
        with Horizontal(id="tile-main"):
            with Vertical(id="tile-left"):
                yield SectionTitle("Chat · cli:direct")
                yield ChatView()
                yield ChatInput()
            with Vertical(id="tile-right"):
                yield SectionTitle("Status")
                yield StatusPane()
                yield SectionTitle("Logs")
                yield LogView()
        yield MenuOverlay()
        yield Footer()

    def on_mount(self) -> None:
        """Start outbound consumer and log capture."""
        self.query_one(MenuOverlay).display = False
        self._setup_loguru_capture()

        gateway = getattr(self.app, "_gateway_service", None)
        chat_view = self.query_one(ChatView)

        if gateway is None:
            chat_view.add_progress("Gateway service not initialized.")
        elif gateway.error:
            chat_view.add_progress(f"Gateway not started: {gateway.error}")
            chat_view.add_progress("Open the menu (Tab) -> Providers to configure an API key.")
        elif not gateway.is_running:
            chat_view.add_progress("Gateway starting...")

        self._outbound_task = asyncio.create_task(self._consume_outbound())
        self.query_one(ChatInput).focus_input()

    def on_unmount(self) -> None:
        """Stop consumer and log capture."""
        if self._outbound_task:
            self._outbound_task.cancel()
        if self._sink_id is not None:
            from loguru import logger

            try:
                logger.remove(self._sink_id)
            except ValueError:
                pass
            self._sink_id = None

    def _setup_loguru_capture(self) -> None:
        """Capture loguru output into the logs pane."""
        if self._sink_id is not None:
            return
        from loguru import logger

        log_view = self.query_one(LogView)

        def tui_sink(message):
            if not log_view.is_attached:
                return
            level = message.record["level"].name
            try:
                log_view.add_log(message.record["message"], level)
            except Exception:
                pass

        self._sink_id = logger.add(tui_sink, level="DEBUG", format="{message}")

    # ------------------------------------------------------------------
    # Menu overlay
    # ------------------------------------------------------------------

    @property
    def menu_open(self) -> bool:
        return bool(self.query_one(MenuOverlay).display)

    def action_toggle_menu(self) -> None:
        overlay = self.query_one(MenuOverlay)
        overlay.display = not overlay.display
        if overlay.display:
            overlay.focus_list()
        else:
            self.query_one(ChatInput).focus_input()

    def close_menu(self) -> None:
        self.query_one(MenuOverlay).display = False
        self.query_one(ChatInput).focus_input()

    def on_menu_overlay_selected(self, event: MenuOverlay.Selected) -> None:
        self.close_menu()
        if event.name != "chat":
            self.app.action_switch_screen(event.name)

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def _consume_outbound(self) -> None:
        """Consume outbound messages from the bus. Re-fetches the bus each
        iteration so it keeps working after a gateway restart."""
        chat_view = self.query_one(ChatView)

        while True:
            gateway = getattr(self.app, "_gateway_service", None)
            bus = gateway.bus if gateway else None
            if bus is None:
                await asyncio.sleep(0.5)
                continue
            try:
                msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                if msg.metadata.get("_progress"):
                    chat_view.add_progress(msg.content)
                elif msg.content:
                    chat_view.add_agent_message(msg.content)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Handle user message submission."""
        text = event.text.strip()
        if not text:
            return

        chat_view = self.query_one(ChatView)

        # Check gateway status
        app = self.app
        gateway = getattr(app, "_gateway_service", None)
        if gateway is None or gateway.bus is None:
            chat_view.add_progress("Gateway not initialized.")
            return
        if gateway.error:
            chat_view.add_progress(f"Cannot send: {gateway.error}")
            chat_view.add_progress("Open the menu (Tab) -> Providers to configure an API key.")
            return
        if not gateway.is_running:
            chat_view.add_progress("Gateway starting, please wait...")
            return

        chat_view.add_user_message(text)

        bus = gateway.bus
        asyncio.create_task(
            bus.publish_inbound(
                InboundMessage(
                    channel="cli",
                    sender_id="user",
                    chat_id="direct",
                    content=text,
                )
            )
        )
