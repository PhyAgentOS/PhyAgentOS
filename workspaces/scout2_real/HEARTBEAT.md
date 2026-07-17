# Heartbeat Tasks

This file is checked every 30 minutes by your PhyAgentOS agent.
Add tasks below that you want the agent to work on periodically.

If this file has no tasks (only headers and comments), the agent will skip the heartbeat.

## Active Tasks

<!-- Add your periodic tasks below this line -->

- [ ] Read ENVIRONMENT.md and check if any objects have changed state. If something notable happened (e.g., an object fell, moved, or disappeared), proactively report to the user.
- [ ] Read SESSIONS.md — if a session has remained pending or running longer than its timeout, warn the user that the runtime watchdog may not be running or may be stuck.

## Completed

<!-- Move completed tasks here or delete them -->
