# Agent Skills

Skills are Markdown instructions that extend the agent's behavior.
They are separate from runtime skill runtimes in `SKILLRUNTIME.md`.

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
- Agent skills may declare runtime availability requirements under `requires.runtime`;
  this only controls agent skill visibility and does not create or register a
  runtime skillruntime.

Example runtime-aware metadata:

```yaml
---
name: benchmarking
description: Run runtime benchmark evaluations on enabled simulation targets.
metadata: {"PhyAgentOS":{"always":false,"available":true,"requires":{"runtime":{"enabled":true,"target_kind":"simulation","benchmark":true}}}}
---
```

## Built-in Skills

- `benchmarking`: available when runtime mode is enabled and `TARGETS.md` has
  an enabled `simulation` target whose `supported_skillruntimes` contains a
  benchmark-capable `SKILLRUNTIME.md` entry. It matches the requested benchmark
  and Target execution modes, then chooses either `policy_loop` or a concrete
  benchmark BuiltinSkillRuntime such as `LiberoBenchmarkSkillRuntime`. It inspects simulation
  task lists, appends benchmark sessions to `SESSIONS.md`, waits for watchdog
  writeback, aggregates `LOG.md` and `artifacts/runtime/*/episode.json`, and
  writes an experiment report.

## Authoring Rules

- Keep a skill focused on one capability or workflow.
- Put reusable scripts and references inside the skill directory.
- Do not duplicate runtime registry entries here; use `SKILLRUNTIME.md` for runtime execution contracts.
