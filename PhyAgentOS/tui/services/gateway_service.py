"""Gateway lifecycle service for TUI."""

import asyncio
from typing import TYPE_CHECKING

from PhyAgentOS.config.schema import Config

if TYPE_CHECKING:
    from textual.app import App


class GatewayService:
    """Manages gateway services (Cron, Heartbeat, Channels) lifecycle within TUI."""

    def __init__(self, config: Config, app: "App") -> None:
        self.config = config
        self.app = app
        self._agent = None
        self._cron = None
        self._heartbeat = None
        self._channels = None
        self._bus = None
        self._running = False
        self._error: str | None = None
        self._tasks: list[asyncio.Task] = []

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def agent(self):
        return self._agent

    @property
    def bus(self):
        return self._bus

    @property
    def error(self) -> str | None:
        return self._error

    async def start(self) -> None:
        """Start all gateway services. Gracefully handles missing configuration."""
        from PhyAgentOS.bus.queue import MessageBus

        self._bus = MessageBus()

        try:
            await self._start_services()
        except Exception as e:
            self._error = str(e)
            self.app.log.warning(f"Gateway not started: {e}")

    async def _start_services(self) -> None:
        """Create and start provider, agent, cron, heartbeat and channels."""
        from PhyAgentOS.agent.loop import AgentLoop
        from PhyAgentOS.channels.manager import ChannelManager
        from PhyAgentOS.config.paths import get_cron_dir
        from PhyAgentOS.cron.service import CronService
        from PhyAgentOS.cron.types import CronJob
        from PhyAgentOS.heartbeat.service import HeartbeatService
        from PhyAgentOS.providers.base import GenerationSettings
        from PhyAgentOS.session.manager import SessionManager

        provider = self._make_provider()

        config = self.config
        defaults = config.agents.defaults
        provider.generation = GenerationSettings(
            temperature=defaults.temperature,
            max_tokens=defaults.max_tokens,
            reasoning_effort=defaults.reasoning_effort,
        )

        # Cron
        cron_store_path = get_cron_dir() / "jobs.json"
        self._cron = CronService(cron_store_path)

        # Agent
        session_manager = SessionManager(config.workspace_path)
        self._agent = AgentLoop(
            bus=self._bus,
            provider=provider,
            workspace=config.workspace_path,
            model=defaults.model,
            max_iterations=defaults.max_tool_iterations,
            context_window_tokens=defaults.context_window_tokens,
            brave_api_key=config.tools.web.search.api_key or None,
            web_proxy=config.tools.web.proxy or None,
            exec_config=config.tools.exec,
            cron_service=self._cron,
            restrict_to_workspace=config.tools.restrict_to_workspace,
            session_manager=session_manager,
            mcp_servers=config.tools.mcp_servers,
            channels_config=config.channels,
            runtime_workspace=config.runtime_workspace_path,
            runtime_enabled=config.runtime.enabled,
            runtime_target_enabled=config.runtime.target_enabled,
        )

        # Cron callback
        async def on_cron_job(job: CronJob) -> str | None:
            reminder_note = (
                "[Scheduled Task] Timer finished.\n\n"
                f"Task '{job.name}' has been triggered.\n"
                f"Scheduled instruction: {job.payload.message}"
            )
            return await self._agent.process_direct(
                reminder_note,
                session_key=f"cron:{job.id}",
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to or "direct",
            )

        self._cron.on_job = on_cron_job

        # Channels
        self._channels = ChannelManager(config, self._bus)

        # Heartbeat
        hb_cfg = config.gateway.heartbeat

        async def on_heartbeat_execute(tasks: str) -> str:
            async def _silent(*_args, **_kwargs):
                pass
            return await self._agent.process_direct(
                tasks,
                session_key="heartbeat",
                channel="cli",
                chat_id="direct",
                on_progress=_silent,
            )

        async def on_heartbeat_notify(response: str) -> None:
            from PhyAgentOS.bus.events import OutboundMessage
            await self._bus.publish_outbound(
                OutboundMessage(channel="cli", chat_id="direct", content=response)
            )

        self._heartbeat = HeartbeatService(
            workspace=config.workspace_path,
            provider=provider,
            model=self._agent.model,
            on_execute=on_heartbeat_execute,
            on_notify=on_heartbeat_notify,
            interval_s=hb_cfg.interval_s,
            enabled=hb_cfg.enabled,
        )

        # Start all services
        await self._cron.start()
        await self._heartbeat.start()
        self._tasks.append(asyncio.create_task(self._agent.run()))
        self._tasks.append(asyncio.create_task(self._channels.start_all()))
        self._running = True

    def _make_provider(self):
        """Create LLM provider from config."""
        from PhyAgentOS.providers.azure_openai_provider import AzureOpenAIProvider
        from PhyAgentOS.providers.openai_codex_provider import OpenAICodexProvider

        config = self.config
        model = config.agents.defaults.model
        provider_name = config.get_provider_name(model)
        p = config.get_provider(model)

        if provider_name == "openai_codex" or model.startswith("openai-codex/"):
            provider = OpenAICodexProvider(default_model=model)
        elif provider_name == "custom":
            from PhyAgentOS.providers.custom_provider import CustomProvider
            provider = CustomProvider(
                api_key=p.api_key if p else "no-key",
                api_base=(p.api_base if p else None) or config.get_api_base(model) or "http://localhost:8000/v1",
                default_model=model,
            )
        elif provider_name == "azure_openai":
            if not p or not p.api_key or not p.api_base:
                raise RuntimeError("Azure OpenAI requires api_key and api_base")
            provider = AzureOpenAIProvider(
                api_key=p.api_key,
                api_base=p.api_base,
                default_model=model,
            )
        else:
            from PhyAgentOS.providers.litellm_provider import LiteLLMProvider
            from PhyAgentOS.providers.registry import find_by_name
            spec = find_by_name(provider_name)
            if not model.startswith("bedrock/") and not (p and p.api_key) and not (spec and (spec.is_oauth or spec.is_local)):
                raise RuntimeError(
                    f"No API key configured for model '{model}'. "
                    "Configure the matching provider (Ctrl+2) or change the model (Ctrl+4)."
                )
            provider = LiteLLMProvider(
                api_key=p.api_key if p else None,
                api_base=(p.api_base if p else None) or config.get_api_base(model),
                default_model=model,
                extra_headers=p.extra_headers if p else None,
                provider_name=provider_name,
            )

        return provider

    async def stop(self) -> None:
        """Stop all gateway services."""
        self._running = False
        if self._heartbeat:
            self._heartbeat.stop()
        if self._cron:
            self._cron.stop()
        if self._agent:
            self._agent.stop()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._channels:
            await self._channels.stop_all()
        if self._agent:
            await self._agent.close_mcp()
