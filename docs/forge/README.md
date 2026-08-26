# PAOS Forge Skill Installation and Development

> PhyAgentOS 0.1.4.post4 · Forge ToolEndpoint `forge.tool.endpoint/v1alpha1` · [中文](README_zh.md)

This document describes the current PAOS Forge Skill installation, runtime, and
development path. Gateway, Forge Runtime, Dora dataflows, policies, and hardware
integrations remain external to PAOS.

`move-arm-by-ee` uses the Gateway Tool API and an explicitly managed local Dora
dataflow.

The [Skill Bundle manual publishing guide](skill-bundle-publishing.md) documents
the archive root, Node locks, asset collection, TOS upload, static-catalog
registration, and post-release acceptance. PAOS uses only the unified Resource
Registry API and does not read repository YAML directly.

## 1. Current PAOS Skill install and development flow

The current executable Skill path is:

```text
Resource Registry
  ├── Skill name -> TOS Bundle URL + SHA-256 + size
  └── Node artifact_id -> immutable GitHub Release URL
             │
             ▼
paos skill install
  ├── verify and install the Skill Bundle
  ├── resolve and install missing locked Nodes
  └── build an immutable per-profile runtime environment
             │
             ▼
paos skill start -> Dora dataflow -> Forge Gateway Tool API
```

The reference `move-arm-by-ee` source under
`examples/forge-skills/move-arm-by-ee/` is not a built-in Skill and is not
installed by cloning the repository. Installed Skills live under
`~/.PhyAgentOS/skills/`.

### 0.1 Install and run a published Skill

After installing PAOS, the CLI uses the public development Registry by default:

```text
https://paos-resource-manager.dev.x-era.com
```

No Registry configuration is required for the default path. Resolution priority
is:

1. `PAOS_RESOURCE_REGISTRY_URL`;
2. `resourceRegistry.url` in `~/.PhyAgentOS/config.json`;
3. the built-in public development Registry.

Install and run the MuJoCo demo:

```bash
paos skill search move-arm-by-ee
paos skill install move-arm-by-ee
paos skill inspect move-arm-by-ee

paos skill start move-arm-by-ee --profile mujoco
paos skill status move-arm-by-ee
paos agent -m "move the gripper forward by 5 cm"
paos skill stop move-arm-by-ee
```

`install` prints the Bundle source and size, warns that locked Node archives may
also be downloaded, and asks for `y/N` confirmation before downloading. Use
`--yes` or `-y` only for non-interactive automation:

```bash
paos skill install move-arm-by-ee --yes
```

Downloads show the artifact name, URL, transferred bytes, total size, speed,
remaining time, cache hits, and resumed progress. A failed install does not
replace the previously installed Skill.

### 0.2 Download and installation model

The Skill Bundle is a flat `.tar.gz` containing `skill.yaml`, `SKILL.md`,
`archive-manifest.json`, profiles, configuration, and assets. PAOS verifies the
Registry SHA-256/size and every file listed in the embedded archive manifest.

Each Forge Node lock records:

```text
artifact_id
version
platform
arch
artifact_type = executable_tar_gz
entrypoint
sha256
```

A Node Release archive contains exactly one root-level executable named by
`entrypoint`. PAOS verifies the GitHub Asset SHA-256, safely extracts the
executable, writes a local installation receipt, and links exact Node versions
into the Skill environment.

Installed resources are organized as:

```text
~/.PhyAgentOS/
├── skills/<skill-name>/
├── cache/
└── forge_runtime/
    ├── nodes/<node-id>/versions/<artifact-id>/
    │   ├── .paos-node.json
    │   └── <entrypoint>
    └── environments/<skill-name>/<profile>/
        ├── <lock-digest>/
        └── current -> <lock-digest>
```

Reinstalling the same Skill is idempotent: valid cached downloads and Nodes
that already satisfy their locks are reused.

### 0.3 Local Skill development loop

Set up the repository development environment:

```bash
cd PhyAgentOS
uv sync
uv run paos skill --help
dora --version
```

Develop the Skill source with this minimum layout:

```text
<skill>/
├── SKILL.md
├── skill.yaml
├── profiles/<profile>/{dataflow.yaml,*.yaml}
└── assets/
```

Package and validate it locally:

```bash
uv run python scripts/package_skill.py \
  examples/forge-skills/move-arm-by-ee \
  --output-dir dist
```

The packaging script regenerates `archive-manifest.json`, creates a
deterministic Bundle, safely extracts it for validation, and prints its SHA-256
and `size_bytes`.

Install the local Bundle through the same Node-resolution and environment
builder used by Registry installs:

```bash
uv run paos skill install dist/move-arm-by-ee-0.2.0.tar.gz
uv run paos skill inspect move-arm-by-ee
uv run paos skill start move-arm-by-ee --profile mujoco
uv run paos skill status move-arm-by-ee
uv run paos skill stop move-arm-by-ee
```

This local loop is the required development milestone. It does not require a
TOS account: unresolved Node locks are obtained from the Registry, while the
Skill Bundle is read from `dist/`.

New Node development remains in the Node's own repository. Publish a versioned
single-executable `.tar.gz` as an immutable GitHub Release Asset, register its
`artifact_id`, and copy the GitHub digest into `skill.yaml` before rebuilding
the Skill Bundle.

For the complete workflows, see:

- [Skill collaboration and local development](skill-development-workflow.md)
- [Skill Bundle packaging and publishing](skill-bundle-publishing.md)
- [move-arm-by-ee manual release example](../../examples/forge-skills/move-arm-by-ee-manual-publishing.md)
- [move-arm-by-ee quick start](../../examples/quick_start.md)
