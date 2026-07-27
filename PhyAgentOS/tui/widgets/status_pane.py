"""Compact live status pane for the tiling chat screen."""

from textual.widgets import Static


class StatusPane(Static):
    """Shows model, gateway and channel status in the side column."""

    def on_mount(self) -> None:
        self.refresh_status()

    def refresh_status(self) -> None:
        config = self.app.config
        gateway = getattr(self.app, "_gateway_service", None)

        if gateway is None:
            gw_status = "not initialized"
        elif gateway.error:
            gw_status = "error"
        elif gateway.is_running:
            gw_status = "running"
        else:
            gw_status = "starting..."

        enabled = 0
        try:
            from PhyAgentOS.channels.registry import discover_channel_names

            for modname in discover_channel_names():
                section = getattr(config.channels, modname, None)
                if section and getattr(section, "enabled", False):
                    enabled += 1
        except Exception:
            pass

        self.update(
            f"Model: {config.agents.defaults.model}\n"
            f"Gateway: {gw_status}\n"
            f"Channels: {enabled} enabled"
        )
