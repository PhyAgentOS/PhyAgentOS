# PhyAgentOS User Manual

> Documentation version: 0.1.4.post4. This manual covers the current Forge-only execution path. PhyAgentOS no longer provides the legacy Runtime, Watchdog, or Markdown Session queue.

## 1. Requirements and installation

Base requirements:

- Python 3.11 or 3.12;
- Git;
- a supported LLM provider;
- a reachable Forge Gateway 1.0.0;
- for non-`off` verification, a model that supports image input and structured JSON output.

```bash
git clone https://github.com/PhyAgentOS/PhyAgentOS.git
cd PhyAgentOS
python -m pip install -e .

# Tests and development
python -m pip install -e ".[dev]"
```

Primary commands after installation:

```text
paos onboard
paos agent
paos gateway
paos status
paos channels status
paos channels login
paos provider login <provider>
```

## 2. Onboarding

```bash
paos onboard
```

By default this creates or refreshes:

```text
~/.PhyAgentOS/config.json
~/.PhyAgentOS/workspace/
```

If configuration already exists, declining overwrite preserves existing values while adding new fields. Configuration validation never silently falls back to the removed execution path. A root-level `runtime` key raises an explicit error and must be replaced with `forge`.

Use custom configuration or workspace paths as follows:

```bash
paos agent --config /path/to/config.json --workspace /path/to/workspace
paos gateway --config /path/to/config.json --workspace /path/to/workspace
```

## 3. Configure the model provider

Minimal provider example:

```json
{
  "agents": {
    "defaults": {
      "model": "openrouter/openai/gpt-4o-mini",
      "provider": "openrouter",
      "workspace": "~/.PhyAgentOS/workspace"
    }
  },
  "providers": {
    "openrouter": {
      "apiKey": "YOUR_API_KEY"
    }
  }
}
```

The Agent and verifier use the same model by default. Set `agents.verification.model` and `agents.verification.provider` to separate them. Never commit API keys; long-running deployments should also restrict configuration-file permissions.

OAuth providers can be authenticated with:

```bash
paos provider login openai-codex
paos provider login github-copilot
```

## 4. Configure Forge

```json
{
  "agents": {
    "verification": {
      "serviceEnabled": true,
      "timeoutS": 180,
      "evidenceRetention": "failed",
      "maxReplansPerEpisode": 2,
      "maxVerifierCallsPerRun": 50,
      "replanTimeoutS": 120,
      "serviceHost": "127.0.0.1",
      "servicePort": 8100
    }
  },
  "forge": {
    "enabled": true,
    "baseUrl": "http://127.0.0.1:9001",
    "apiVersion": "paos-forge-gateway-mvp-plus.v1",
    "requestTimeoutS": 10,
    "pollIntervalS": 0.5,
    "executionTimeoutS": 300,
    "evidence": {
      "requiredImageSources": ["front"],
      "captureTimeoutS": 5,
      "postCaptureTimeoutS": 5,
      "connectionTimeoutS": 2,
      "maxArtifactBytes": 8388608,
      "associationQuality": "best_effort"
    }
  }
}
```

PAOS reads `/agent/runtime/capabilities` at startup and refuses startup unless:

- `api_version` is exactly `paos-forge-gateway-mvp-plus.v1`;
- `supports.sessions`, `supports.command_id`, and `supports.runtime_context` are true;
- `supports.serial_actions_only` is true;
- `actions` is an object, and every submitted action is present in it.

Each `requiredImageSources` entry must match the `id` published on Gateway `/ws/images`. If the list is empty, PAOS discovers sources from runtime-context image readiness. If discovery also yields none, non-`off` work fails with `FORGE_EVIDENCE_CONFIGURATION_REQUIRED`.

See the [Forge Configuration Reference](04-forge-configuration-reference.md) for every field and default.

## 5. Startup order

Recommended order:

1. Start Forge Runtime, Dora, and the robot or simulator.
2. Start Forge Gateway 1.0.0.
3. Confirm Gateway capabilities, status, context, and image streams.
4. Start the PAOS Agent or Gateway.

Interactive mode:

```bash
paos agent
```

One-message mode:

```bash
paos agent -m "Inspect Forge capabilities, execute one supported action, audit the outcome, and report execution facts separately from the task verdict."
```

If that message submits a Forge task, the process does not exit after the first model response. It keeps Agent and Orchestrator alive until the root lineage terminates and completion/recovery system events are handled.

Long-running mode:

```bash
paos gateway
paos gateway --port 18790 --verbose
```

This entry point runs the Agent, enabled channels, Cron, Heartbeat, and Forge Orchestrator together.

## 6. Submit the first task

### 6.1 Inspect capabilities first

Action types and inputs are Gateway-defined and should not be guessed from examples. Ask the Agent:

```text
Call forge_get_context and list current readiness, actions, required inputs, and input mappings. Do not execute an action.
```

### 6.2 Describe the goal and acceptance criteria

A good request states:

- the user goal;
- the acceptable high-level action scope;
- observable, independently decidable success criteria;
- safety or task constraints that must be preserved;
- the verification mode;
- required evidence kinds and sources.

Example:

```text
Read Forge capabilities and choose an appropriate high-level action to place the red object in the tray.
Use recovery verification. The goal is “the red object is inside the tray.”
Criteria: (1) the red object is visibly within the tray boundary in the final image;
(2) the blue object remains in its original area. Constraint: do not move the blue object.
Use front before/after images as evidence.
```

The Agent eventually calls `forge_execute_task` with a structure such as:

```json
{
  "task_description": "...",
  "action_type": "<advertised action>",
  "inputs": {},
  "verification": {
    "mode": "recovery",
    "goal": "The red object is inside the tray.",
    "success_criteria": [
      "The red object is visibly within the tray boundary in the final image.",
      "The blue object remains in its original area."
    ],
    "constraints": ["Do not move the blue object."],
    "evidence_policy": {
      "required_kinds": ["rgb_image"],
      "required_sources": ["front"],
      "minimum_association": "best_effort"
    }
  }
}
```

PAOS generates session and command IDs. Callers cannot specify, reuse, or copy them from prior tasks.

## 7. Verification modes

| Mode | Use when | Behavior |
|:-----|:---------|:---------|
| `off` | Gateway command completion is sufficient | Does not build a verification Evidence Bundle or call the verifier; finalizes from execution status. |
| `audit` | Evaluating verifier quality without blocking execution outcomes | A missing before snapshot does not prevent dispatch; records verdict/error; preserves execution-derived terminal status; never replans. |
| `enforce` | Task completion requires semantic evidence | Only verifier `success` succeeds. Missing evidence, invalid output, errors, `failure`, `replan_required`, and `inconclusive` fail. |
| `recovery` | The Planner may try again after a recoverable failure | Same fail-closed behavior as enforce; valid `replan_required` creates a Recovery Request. |

Every non-`off` task requires a non-empty goal, at least one non-empty criterion, and an available Verification Service.

## 8. Query, cancel, review, and reset

The Agent can use:

- `forge_get_session(session_id)` to return the full persistent record;
- `forge_cancel_session(session_id, reason)` to cancel non-terminal work and request Gateway cancellation after dispatch;
- `verify_forge_session(session_id)` to review a terminal session whose evidence is retained;
- `forge_reset(inputs)` only when no active lineage exists;
- `forge_get_context()` for startup-cached capabilities plus live status and context.

`verify_forge_session` is a review. It never changes `status`, the Execution Record, or the original automatic attempt. It appends an attempt and refreshes the verification view in `verification_result.json`.

## 9. Understand states

| PAOS state | Meaning | Terminal |
|:-----------|:--------|:---------|
| `accepted` | Request and generated identities are durable | No |
| `capturing_before` | Waiting for and persisting pre-execution evidence | No |
| `dispatching` | Dispatch intent is durable and POST is in progress | No |
| `running` | Gateway session is not terminal | No |
| `finalizing` | Writing Execution Record and waiting for after evidence | No |
| `awaiting_verification` | Evidence Bundle is ready for verification | No |
| `verifying` | Independent Verification Service is evaluating | No |
| `awaiting_replan` | Recovery Request exists and awaits a Planner child | No |
| `replanned` | Parent was atomically replaced by a new child | Yes |
| `succeeded` / `failed` | PAOS finalized according to the current mode | Yes |
| `timed_out` / `cancelled` | Execution timed out or was cancelled | Yes |

For `enforce` and `recovery`, inspect all of:

```text
record.status
record.execution.status
record.verification.verdict.verdict
record.error_code / record.error_message
```

They represent PAOS task outcome, Gateway execution fact, semantic verdict, and failure reason respectively.

## 10. Artifacts and retention

```text
<workspace>/.paos/forge/orchestrator.sqlite3
<workspace>/artifacts/forge/<session_id>/
  execution_record.json
  before_snapshot.json
  after_snapshot.json
  evidence_bundle.json
  verification_result.json
  evidence/
```

Evidence retention policies:

| Value | Entity-artifact handling |
|:------|:-------------------------|
| `all` | Retain every entity |
| `failed` | Delete entities after final success; retain them after failure |
| `none` | Delete entities after verification |

After deletion, the Evidence Bundle still retains URI, source, phase, time, sequence, byte size, SHA-256, `retained=false`, and `deleted_at` for audit. Retention never deletes or overwrites the Execution Record.

## 11. Restart and recovery

- No dispatch intent: the Orchestrator may continue the task.
- Dispatch intent recorded: only GET the original Gateway session; never automatically repeat the action.
- Original session exists and identity matches: continue polling, after capture, or verification.
- Original session returns 404: mark `FORGE_EXECUTION_STATE_LOST`.
- Verification was interrupted: mark the old attempt abandoned and retry.
- Awaiting replan: the recovery system event may be delivered again; transactional child creation deduplicates it.

On normal shutdown PAOS attempts to cancel the active Gateway session and stores the cancel response. The physical system still needs independent safe shutdown and operator override; PAOS cancellation is not a hardware emergency stop.

## 12. Embodiment and knowledge workspaces

`EMBODIED.md`, `ENVIRONMENT.md`, SceneGraph, and the `embodiments` configuration belong to the knowledge layer. Single mode uses `agents.defaults.workspace`. Fleet mode can organize shared and per-robot knowledge workspaces, but the current process still has one Forge endpoint and one serialized execution slot.

```json
{
  "embodiments": {
    "mode": "fleet",
    "sharedWorkspace": "~/.PhyAgentOS/workspaces/shared",
    "instances": [
      {
        "robotId": "robot_001",
        "workspace": "~/.PhyAgentOS/workspaces/robot_001",
        "profileName": "lab-arm",
        "enabled": true
      }
    ]
  }
}
```

This configuration contains no driver, Target, or Gateway routing semantics.

## 13. Legacy workspace cleanup

PAOS never deletes user-owned files automatically. Back up the workspace, then optionally remove obsolete execution protocol files:

```text
RUNTIME.md
TARGETS.md
SKILLRUNTIME.md
SESSIONS.md
configs/runtime/
artifacts/runtime/
```

Keep `EMBODIED.md`, `ENVIRONMENT.md`, `LESSONS.md`, `TASK.md`, and other user knowledge. Current code neither reads nor generates the obsolete execution protocol.

## 14. Troubleshooting

### API or capability failure at startup

Ensure the URL points to Forge Gateway 1.0.0 and inspect `/agent/runtime/capabilities`. Version and required supports cannot be downgraded through configuration.

### `FORGE_ACTION_UNSUPPORTED`

The requested action is absent from startup-cached capabilities. Call `forge_get_context`, then replan from advertised actions and required inputs. Restart PAOS after Gateway capability changes so startup validation and the Agent summary refresh together.

### `FORGE_EVIDENCE_CONFIGURATION_REQUIRED`

No global image sources are configured and runtime context exposes none. Configure real source IDs and ensure `/ws/images` is publishing.

### `FORGE_EVIDENCE_UNAVAILABLE`

A required source is missing from the before or after window. Check WebSocket connectivity, media format, size limits, source IDs, increasing sequences, and capture timeouts.

### `FORGE_EXECUTION_STATE_LOST`

PAOS persisted dispatch intent but Gateway returns 404. The system intentionally refuses to repeat an unknown physical action. Inspect the physical world and Gateway logs before creating a new high-level task.

### `VERIFICATION_EVIDENCE_UNAVAILABLE`

The bundle is incomplete, an artifact is missing/deleted, a digest differs, or the capture window is invalid. For later reviews, use `all`, or use `failed` when failed evidence must remain.

### `VERIFICATION_INVALID_VERDICT`

The model failed to return exactly one legal result per criterion or cited an unknown evidence ID. Select a more reliable model; do not weaken the public contract.

### `VERIFICATION_SERVICE_UNAVAILABLE`

Check provider settings, model support, `servicePort` conflicts, and timeout. `audit` records the error and preserves execution outcome; `enforce` and `recovery` fail closed.

### Busy / active lineage

Another root lineage is not terminal. Query it with `forge_get_session` and cancel if necessary. Never edit SQLite directly to bypass serialization.

## Next reading

- [Framework Introduction](01-framework-introduction.md)
- [Forge Configuration Reference](04-forge-configuration-reference.md)
- [Operations Manual](../user_manual/README_en.md)
- [Forge Integration Contract](../forge/README.md)
- [Documentation Index](../README.md)
