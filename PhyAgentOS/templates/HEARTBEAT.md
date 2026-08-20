# Heartbeat Tasks

This file is checked every 30 minutes by your PhyAgentOS agent.
Add tasks below that you want the agent to work on periodically.

If this file has no tasks (only headers and comments), the agent will skip the heartbeat.

## Active Tasks

<!-- Add your periodic tasks below this line -->

- [ ] Read ENVIRONMENT.md and check if any objects have changed state. If something notable happened (e.g., an object fell, moved, or disappeared), proactively report to the user.
- [ ] If the user asks about a Forge task, use `forge_get_session` rather than inferring its state from elapsed time.

## Completed

<!-- Move completed tasks here or delete them -->
