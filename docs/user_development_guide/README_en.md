# PhyAgentOS Integration Development Guide

> Version: 0.1.4.post4 · [中文](README.md)

This guide is for integrators of Forge Gateway, robot capabilities, evidence sources, LLM providers, and PAOS Agent tools. Robot execution now enters only through Forge Gateway 1.0.0. PAOS no longer exposes Target, Policy, SkillRuntime, or SessionRunner extension points.

## 1. Choose the correct extension point

| Need | Where to change | PAOS-side work |
|:-----|:----------------|:---------------|
| New robot or simulator | Forge Runtime / Dora / hardware integration | No PAOS driver; validate the Gateway contract |
| New high-level action | Gateway capabilities and action dispatch | Usually no product code; add generic contract/E2E tests and docs |
| New policy | Policy/runtime behind the Forge action | Expose generic policy identity and result semantics |
| New camera | Gateway `/ws/images` producer | Configure source ID and test before/after sequence |
| New structured state | Gateway `/ws/state` or a public evidence-kind extension | For a new kind, update contracts/resolver/retention/tests together |
| New verifier model | PAOS Provider configuration/implementation | Support multimodal input and strict JSON output |
| New Agent entry point | PAOS Channel | Use MessageBus/AgentLoop; never call Gateway directly |
| New execution tool | Prefer generic Forge tools | Never bypass Orchestrator/Store or expose caller identities |

## 2. Integrate a Gateway action

### 2.1 Capability declaration

Gateway advertises the action under `/agent/runtime/capabilities`:

```json
{
  "actions": {
    "place_object": {
      "description": "Place an object in a target area.",
      "policy_id": "manipulation_policy",
      "command": "place_object",
      "required_parameters": ["object", "target"],
      "input_mapping": {
        "object": "object",
        "target": "target"
      },
      "result_semantics": "command_completed",
      "completion": {
        "source": "policy_command_status"
      }
    }
  }
}
```

Guidelines:

- `description`, `required_parameters`, and `input_mapping` help Planner create legal inputs.
- `policy_id` and `command` form execution identity and remain consistent in create/get responses.
- `result_semantics` and `completion` describe what Gateway completion means.
- Never add `verify_grasp`, `grasp_verify_enabled`, or verifier prompts to capabilities.
- Action-specific results may appear in command `outputs`; task success still follows criteria.

### 2.2 Create and get

PAOS POSTs:

```json
{
  "session_id": "forge_<paos-generated>",
  "command_id": "command_<paos-generated>",
  "action_type": "place_object",
  "instruction": "Place the red object in the tray.",
  "source": "paos-agent",
  "inputs": {
    "object": "red object",
    "target": "tray"
  }
}
```

Gateway create/get responses allow PAOS to resolve:

```json
{
  "ok": true,
  "data": {
    "session": {
      "session_id": "forge_<same>",
      "action_type": "place_object",
      "status": "running"
    },
    "command": {
      "command_id": "command_<same>",
      "session_id": "forge_<same>",
      "request_id": "command_<same>",
      "action_type": "place_object",
      "policy_id": "manipulation_policy",
      "command": "place_object",
      "status": "running"
    }
  }
}
```

At terminal state, session and command statuses match and use only `succeeded`, `failed`, or `cancelled`. PAOS never infers terminal state from outputs, stability, or fixed waiting.

### 2.3 Cancel

`POST /agent/sessions/{session_id}/cancel` accepts a reason. Gateway should make a best effort to stop unfinished work and return a persistent JSON response. Even if cancellation transport fails, PAOS records the failure and finalizes its own state.

## 3. Integrate image evidence

Each `/ws/images` message is a JSON object:

```json
{
  "type": "image",
  "id": "front",
  "seq": 42,
  "timestamp": 1785744000.123,
  "content_type": "image/jpeg",
  "data": "<base64>"
}
```

Requirements:

- `id` remains stable across reconnects and the deployment.
- `seq` increases monotonically per source.
- `timestamp` may be absent; if present, it is finite, real source time.
- `content_type` is JPEG, PNG, or WebP and matches entity magic bytes.
- Decoded frame size does not exceed PAOS `maxArtifactBytes`.
- At least one updated sequence is published after Gateway terminal state for the after boundary.

Maintain independent sequences for multiple cameras. Do not encode camera identity in action type or rely on array ordering.

## 4. Integrate robot state

When task `required_kinds` contains `robot_state`, PAOS requires `/ws/state` messages in both before and after phases. Each message is a JSON object subject to `maxArtifactBytes`.

Gateway 1.0.0 has no uniform source-time contract for state, so PAOS records `received_at` only. A future authoritative timestamp requires a public Gateway/Evidence contract upgrade, not Adapter field guessing.

## 5. Design the Task Verification Contract

Integrators do not create verifier branches per action. Help users and Agent write observable criteria.

Avoid:

```text
goal: grasp succeeded
criterion: policy returned succeeded
```

Prefer:

```text
goal: object is held securely above the table
criteria:
  - final image shows the object clear of the table surface
  - gripper and object maintain visible contact
constraints:
  - no other object leaves the workspace
```

Gateway command status is useful execution evidence but cannot replace evidence of the environmental result.

## 6. Provider and verifier integration

Verifier providers use the existing provider registry. A new provider supports:

- `chat_with_retry()`;
- system plus multimodal user content;
- `temperature=0`;
- timeout and cancellation;
- a pure JSON-object response;
- reconstruction in the child Verification Service from a serializable provider spec.

Public output passes `VerificationVerdict`, covers every criterion exactly once, and cites only valid evidence IDs.

## 7. PAOS extension boundary

### Valid extensions

- generic evidence kinds;
- new public-contract versions with an explicit compatibility decision;
- Gateway-neutral observation reliability;
- Store/event observability;
- providers;
- channels and other non-execution entry points.

### Do not introduce

- action-specific verifier flags or prompts;
- robot SDKs or policy clients inside PAOS;
- another SessionRunner or file queue;
- terminal inference from fixed sleeps, stability, or outputs;
- caller-supplied session/command IDs;
- direct POST/retry outside Store and Orchestrator;
- verdicts written into Execution Records.

## 8. Fake Gateway test loop

Default integration tests use a local fake HTTP/WebSocket server matching real response shapes:

1. Strict capabilities validation passes.
2. Collectors receive all before sources.
3. Test proves before snapshot is durable before create.
4. Create returns matching identity.
5. GET progresses through queued/running/terminal.
6. Higher sequences arrive after terminal.
7. Assertions cover Execution, Evidence, Verification, and final state.
8. Timeout/cancel, 404 resume, disconnect, reordering, missing evidence, and invalid identity are covered.

Optional real-Gateway tests read `FORGE_GATEWAY_URL` only and never mutate Gateway source, configuration, or runtime data.

## 9. Integration acceptance checklist

- [ ] Gateway API version and four required supports are correct.
- [ ] Action capability is complete and identity is stable.
- [ ] Required inputs/input mapping are intelligible to Planner.
- [ ] Create/get/cancel share a consistent response envelope.
- [ ] `request_id == command_id`.
- [ ] Session/command/action/policy/command identities remain consistent.
- [ ] Terminal enumeration and session/command status agree.
- [ ] Every image source has stable ID and increasing sequence.
- [ ] Before is available before POST and after is available after terminal.
- [ ] Task semantics require no action-specific verifier code.
- [ ] Fake Gateway happy path and critical refusal paths pass.

## Next reading

- [Developer Manual](../en/03-developer-manual.md)
- [Communication Architecture](COMMUNICATION_en.md)
- [Forge Integration Contract](../forge/README.md)
- [Configuration Reference](../en/04-forge-configuration-reference.md)
