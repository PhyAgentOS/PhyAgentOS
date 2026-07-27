"""Channels management screen."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Label

from PhyAgentOS.channels.registry import discover_channel_names, load_channel_class
from PhyAgentOS.config.loader import save_config
from PhyAgentOS.tui.widgets.app_header import AppHeader
from PhyAgentOS.tui.widgets.section_title import SectionTitle


class ChannelsScreen(Screen):
    """Channels management screen."""

    def compose(self) -> ComposeResult:
        yield AppHeader()
        with Vertical(id="channels-main"):
            yield SectionTitle("Channels")
            yield Label("Enter 开关渠道 · Tab 菜单 · Esc 返回聊天", classes="hint")
            yield DataTable(id="channels-table")
        yield Footer()

    def on_mount(self) -> None:
        """Populate channels table."""
        table = self.query_one("#channels-table", DataTable)
        table.add_columns("Channel", "Enabled", "Status")
        table.cursor_type = "row"

        config = self.app.config
        for modname in sorted(discover_channel_names()):
            section = getattr(config.channels, modname, None)
            enabled = section and getattr(section, "enabled", False)
            try:
                cls = load_channel_class(modname)
                display = cls.display_name
            except ImportError:
                display = modname.title()

            status = "enabled" if enabled else "disabled"
            table.add_row(display, "✓" if enabled else "✗", status, key=modname)

        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Toggle channel on selection."""
        channel_name = event.row_key.value
        if not channel_name:
            return

        config = self.app.config
        section = getattr(config.channels, channel_name, None)
        if section is None:
            return

        # Toggle enabled state
        section.enabled = not section.enabled
        save_config(config)
        self.app.reload_config()

        # Refresh table
        table = self.query_one("#channels-table", DataTable)
        table.clear(columns=True)
        self.on_mount()
