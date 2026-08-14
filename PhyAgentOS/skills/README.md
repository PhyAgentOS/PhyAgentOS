# PhyAgentOS Skills

This directory contains built-in skills that extend PhyAgentOS's capabilities.

## Skill Format

Each skill is a directory containing a `SKILL.md` file with:
- YAML frontmatter (name, description, metadata)
- Markdown instructions for the agent

## Attribution

These skills are adapted from [OpenClaw](https://github.com/openclaw/openclaw)'s skill system.
The skill format and metadata structure follow OpenClaw's conventions to maintain compatibility.

## Available Skills

| Skill | Description |
|-------|-------------|
| `github` | Interact with GitHub using the `gh` CLI |
| `weather` | Get weather info using wttr.in and Open-Meteo |
| `summarize` | Summarize URLs, files, and YouTube videos |
| `tmux` | Remote-control tmux sessions |
| `clawhub` | Search and install skills from ClawHub registry |
| `skill-creator` | Create new skills |
| `pipergo2-demo` | Plan and verify PiperGo2 actions through Forge tools |

## Runtime-gated Skills

These skills become available only after their declared runtime has been started explicitly
and its Gateway Tool API is healthy:

| Skill | Description |
|-------|-------------|
| `move-arm-by-ee` | Resolve relative end-effector motion and execute an absolute pose |
