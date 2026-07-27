"""Providers management screen."""

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Input,
    Label,
)

from PhyAgentOS.config.loader import save_config
from PhyAgentOS.providers.registry import PROVIDERS
from PhyAgentOS.tui.widgets.app_header import AppHeader
from PhyAgentOS.tui.widgets.section_title import SectionTitle


class ProvidersScreen(Screen):
    """Providers management screen."""

    def __init__(self) -> None:
        super().__init__()
        self._selected_provider: str | None = None

    def compose(self) -> ComposeResult:
        yield AppHeader()
        with Vertical(id="providers-main"):
            yield SectionTitle("Providers")
            yield Label("Tab 菜单 · Esc 返回聊天", classes="hint")
            with Horizontal(id="providers-body"):
                with Vertical(id="provider-list-container"):
                    yield DataTable(id="provider-table")
                with ScrollableContainer(id="provider-form-container"):
                    yield Label("Select a provider to configure", id="form-placeholder")
                    yield Vertical(id="provider-form")
        yield Footer()

    def on_mount(self) -> None:
        """Populate provider table."""
        table = self.query_one("#provider-table", DataTable)
        table.add_columns("Provider", "Status")
        table.cursor_type = "row"

        config = self.app.config
        for spec in PROVIDERS:
            p = getattr(config.providers, spec.name, None)
            if p is None:
                continue
            if spec.is_oauth:
                status = "OAuth"
            elif spec.is_local:
                status = p.api_base if p.api_base else "not set"
            else:
                status = "configured" if p.api_key else "not set"
            table.add_row(spec.label, status, key=spec.name)

        table.focus()

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle provider selection."""
        provider_name = event.row_key.value
        if provider_name:
            self._selected_provider = provider_name
            await self._show_provider_form(provider_name)

    async def _show_provider_form(self, provider_name: str) -> None:
        """Show configuration form for selected provider."""
        form = self.query_one("#provider-form", Vertical)
        await form.remove_children()

        placeholder = self.query_one("#form-placeholder", Label)
        placeholder.display = False

        spec = next((s for s in PROVIDERS if s.name == provider_name), None)
        if not spec:
            return

        config = self.app.config
        p = getattr(config.providers, provider_name, None)

        form.mount(Label(f"Configure: {spec.label}", classes="settings-group-title"))

        # API Key
        if not spec.is_oauth and not spec.is_local:
            form.mount(Label("API Key:"))
            api_key_input = Input(
                value=p.api_key if p else "",
                password=True,
                id=f"input-{provider_name}-api-key",
            )
            form.mount(api_key_input)

        # API Base
        if spec.is_local or provider_name in ("custom", "azure_openai", "ollama", "vllm"):
            form.mount(Label("API Base:"))
            api_base_input = Input(
                value=p.api_base if p and p.api_base else "",
                id=f"input-{provider_name}-api-base",
            )
            form.mount(api_base_input)

        # OAuth button
        if spec.is_oauth:
            form.mount(Button(f"Login with {spec.label}", id=f"oauth-{provider_name}"))

        # Save button
        form.mount(Button("Save", variant="primary", id=f"save-{provider_name}"))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        button_id = event.button.id or ""

        if button_id.startswith("save-"):
            provider_name = button_id[5:]
            self._save_provider(provider_name)
            await self.app.restart_gateway()
        elif button_id.startswith("oauth-"):
            provider_name = button_id[6:]
            self._oauth_login(provider_name)

    def _save_provider(self, provider_name: str) -> None:
        """Save provider configuration."""
        config = self.app.config
        p = getattr(config.providers, provider_name, None)
        if p is None:
            return

        # Get values from inputs
        try:
            api_key_input = self.query_one(f"#input-{provider_name}-api-key", Input)
            p.api_key = api_key_input.value
        except Exception:
            pass

        try:
            api_base_input = self.query_one(f"#input-{provider_name}-api-base", Input)
            p.api_base = api_base_input.value or None
        except Exception:
            pass

        save_config(config)
        self.app.reload_config()

        # Refresh table
        table = self.query_one("#provider-table", DataTable)
        table.clear(columns=True)
        self.on_mount()

    def _oauth_login(self, provider_name: str) -> None:
        """Handle OAuth login."""
        # This would trigger the OAuth flow
        # For now, show a message
        form = self.query_one("#provider-form", Vertical)
        form.mount(Label(f"OAuth login for {provider_name} - run `paos provider login {provider_name}` in terminal"))
