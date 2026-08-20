# Agent Skills

Skills are Markdown instructions that extend the agent's behavior.

## Locations

- Workspace skills: `skills/<skill-name>/SKILL.md`
- Built-in skills: packaged under `PhyAgentOS/skills/<skill-name>/SKILL.md`
- Workspace skills override built-in skills with the same name.

## Frontmatter

Each skill may start with YAML frontmatter:

```yaml
---
name: example-skill
description: Short user-facing summary.
metadata: {"PhyAgentOS":{"always":false,"available":true}}
---
```

The metadata key may be `PhyAgentOS` or `openclaw`; both are accepted.

## Loading Rules

- Skills with `always: true` are loaded directly into context when requirements are met.
- Other available skills appear in the skills summary and can be read on demand.
- Skills with unmet requirements are listed as unavailable.
- Dependency requirements can declare CLI binaries or environment variables under `requires`.

## Built-in Skills

- Forge execution is exposed through built-in Agent tools rather than a skill registry.
- A robot-specific skill may teach planning conventions, but it must discover live actions
  through `forge_get_context` and execute through `forge_execute_task`.

## Authoring Rules

- Keep a skill focused on one capability or workflow.
- Put reusable scripts and references inside the skill directory.
- Do not duplicate or invent Forge Action Manifest entries in a skill.
