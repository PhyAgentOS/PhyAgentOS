# RoboTwin20 EnvironmentAdapter

This is an independently installable adapter workspace. It is not part of the
`PhyAgentOS` wheel and must not be installed into the PAOS control-plane
environment. The base adapter package has no third-party dependency; optional
OpenAI and perception dependencies are installed only in adapter/provider
environments. A deployment-specific backend is installed in a separate
RoboTwin runtime environment and injected through the `RoboTwinSensorBackend`
protocol.

RoboTwin/SAPIEN packages, Torch/YOLO models, simulator assets, task files,
embodiment configuration, and benchmark data stay outside PAOS and outside this
source bundle. A profile should pass an external asset root to the backend; this
adapter never copies or imports those assets and never reads actor/entity truth,
segmentation truth, internal poses, or simulator success checks.

The only public observation seam is camera/depth/state sensor output with a
timezone-aware timestamp, scene revision, frame, calibration reference, and
typed artifact references. Missing calibration or any required sensor kind is a
hard failure. The adapter is no-motion: it provides environment lifecycle and
observation only; action providers remain a later, separately reviewed seam.

Example isolated setup:

```text
paos                           # ToolSpec/Gateway/generic validation only
paos-robotwin20-adapter        # composition, artifact IO, process clients
RoboTwin20                     # simulator and RGB/depth/state capture only
hephaestus-locateanything      # LocateAnything/Torch/Transformers worker env
seg                            # SAM2/Torch worker env
robotwin-assets                # external assets, mounted by profile
```

Run the fail-closed runtime preflight before implementing or starting a
provider backend:

```bash
PYTHONPATH=examples/forge-adapters/robotwin20/src \
python -m robotwin20_adapter.preflight \
  --runtime-root /home/yanxu/robotwin20-runtime/RoboTwin \
  --runtime-python /home/yanxu/miniconda3/envs/RoboTwin20/bin/python
```

The check validates the external source layout, all three official asset
families, embodiment configuration, full runtime modules, editable XPolicyLab
installation, a real Torch CUDA kernel, Vulkan device discovery, SAPIEN scene
creation, and task-class import. It deliberately does not call `setup_demo`,
`play_once`, `check_success`, or any robot/action method. A nonzero exit means
the RoboTwin provider must remain unavailable.

After preflight passes, run the runtime-only sensor backend from the RoboTwin20
environment. Its artifact root must be external to PAOS and Hephaestus:

```bash
cd /home/yanxu/PhyAgentOS-forge
PYTHONPATH=examples/forge-adapters/robotwin20/src \
/home/yanxu/miniconda3/envs/RoboTwin20/bin/python \
examples/forge-adapters/robotwin20/runtime/robotwin_backend.py \
  --runtime-root /home/yanxu/robotwin20-runtime/RoboTwin \
  --artifact-root /home/yanxu/robotwin20-runtime/artifacts \
  --forbidden-root /home/yanxu/PhyAgentOS-forge \
  --sensor-ref camera/head \
  --seed 0
```

To emit the exact provider-neutral snapshot consumed by the `scene.observe`
ToolEndpoint, use `--format scene_observe`. This command is intended to run in
the Python 3.10 RoboTwin process; PAOS (Python 3.11+) consumes the JSON through
the Gateway/provider boundary and must not import RoboTwin modules directly:

```bash
PYTHONPATH=examples/forge-adapters/robotwin20/src \
/home/yanxu/miniconda3/envs/RoboTwin20/bin/python \
examples/forge-adapters/robotwin20/runtime/robotwin_backend.py \
  --runtime-root /home/yanxu/robotwin20-runtime/RoboTwin \
  --artifact-root /home/yanxu/robotwin20-runtime/artifacts \
  --forbidden-root /home/yanxu/PhyAgentOS-forge \
  --sensor-ref camera/head \
  --seed 0 \
  --format scene_observe
```

The snapshot fields are the same ones returned by
`ForgeToolClient.invoke_query_tool("scene.observe", ...)` through the Fake
Gateway: observation identity, timestamp, scene revision, frame, calibration,
freshness, and typed artifact references. Runtime warnings may be emitted by
third-party renderers; the JSON object is the provider payload, not simulator
truth.

The next `scene.understand` seam is exposed as
`RoboTwinSceneUnderstandingProvider`. It accepts an injected inference service
and forwards only the observation identity plus artifact references. The
adapter does not ship a detector/VLM and rejects provider-specific result
fields; the generic `scene.understand` endpoint owns the public ToolSpec
projection and fail-closed error semantics.

For a real GPT-backed inference deployment, install the optional provider
dependency in the adapter/provider environment only:

```bash
python -m pip install -e 'examples/forge-adapters/robotwin20[openai]'
export CUSTOM_API_KEY='(set outside the repository)'
```

Construct `OpenAIResponsesSceneUnderstandingInference` with an injected
`FilesystemArtifactResolver('/external/artifacts')` (or another resolver
implementing the same port) and wrap it with
`RoboTwinSceneUnderstandingProvider`. The
default configuration follows the existing Hephaestus relay format
(`gpt-5.6-sol`, Responses API, `https://api.shuaiapi.com/v1`) but is owned by
this adapter and can be overridden through `OpenAIResponsesConfig`. The API
key is read at invocation time and is never persisted or sent through PAOS.
The provider emits only `entities`, `relations`, `spatial_envelopes`, and
`ambiguities`; PAOS performs the final contract validation, including binding
each claim's provenance to an artifact in the requested observation, and
projects the result through the same Gateway endpoint used by the Fake path.

The perception boundary is intentionally split by PAOS use case:

| Capability | ToolSpec | Adapter/provider responsibility |
|---|---|---|
| Object recognition/detection | `scene.understand` | Infer entities from RGB or other observation artifacts; never read simulator actor truth. |
| Instance segmentation | `scene.understand` | Produce an opaque, provenance-bound mask artifact through a replaceable provider. |
| Metric 3D localization | `scene.understand` | Combine depth, calibration, frame transforms, and masks; fail closed when any input is missing. |
| Grasp pose proposal | `grasp.propose` | Emit candidate poses and provenance only; it does not authorize motion. |
| IK/collision/workspace readiness | `manipulation.prepare` | Evaluate candidates before any bounded Action. |

The GPT Responses provider covers RGB semantic recognition and relations. The
adapter now also contains a single-view composition that binds each semantic
entity to a LocateAnything proposal, releases that model process, invokes SAM2
with the exact box, and deterministically localizes the mask with aligned depth
and calibration. It materializes provider-neutral `instance_mask`,
`object_point_cloud`, and `metric_localization` records through the existing
`scene.understand` contract. The adapter also exposes a separate
`GraspGenProposalProvider`: it consumes an explicitly bound object point-cloud
or fused-entity artifact and returns provider-neutral candidate poses through
`grasp.propose`; it never performs IK, collision admission, or motion and does
not fold any provider into `scene.observe` or a RoboTwin-named Skill.

The perception models retain their existing isolated environments. Configure
them through the adapter profile without importing either environment into
PAOS or RoboTwin20:

```bash
export PAOS_ROBOTWIN20_ADAPTER_ROOT=/home/yanxu/PhyAgentOS-forge/examples/forge-adapters/robotwin20
export ROBOTWIN20_ARTIFACT_ROOT=/home/yanxu/robotwin20-runtime/artifacts
export LOCATEANYTHING_PYTHON=/home/yanxu/.hephaestus/envs/hephaestus-locateanything/bin/python
export LOCATEANYTHING_CACHE_DIR=/home/yanxu/.hephaestus/cache/huggingface/hub
export LOCATEANYTHING_MODULES_CACHE_DIR=/home/yanxu/.hephaestus/cache/huggingface/modules
export SAM2_PYTHON=/home/yanxu/miniconda3/envs/seg/bin/python
export SAM2_REPO_ROOT=/home/yanxu/Grounded-SAM-2
export SAM2_CHECKPOINT=/home/yanxu/Grounded-SAM-2/checkpoints/sam2.1_hiera_large.pt
```

Load `profiles/robotwin20/perception.yaml`, then pass the mapping and the
semantic inference provider to `build_single_view_perception`. Inject the
resulting inference object into `RoboTwinSceneUnderstandingProvider`; PAOS
continues to call it only through the generic Gateway endpoint. Worker startup,
request, shutdown, model revision, checkpoint, device, and timeout settings are
profile-owned. Commands never use a shell. The proposal process exits before
the SAM2 process starts, so the two existing model environments remain
independently replaceable.

The shipped unit/conformance path remains reproducible with fake model workers.
A no-motion live run has also exercised the configured LocateAnything revision
and SAM2 checkpoint against an existing `320x240` RoboTwin RGB-D observation.
LocateAnything returned one `red block` proposal, SAM2 materialized an aligned
mask, and the complete Fake Gateway route returned all three derived artifacts
plus a camera-frame metric envelope with `motion_authorized=false`. The run used
a fixed semantic entity as composition input; it was not a fresh GPT invocation
and does not validate grasp proposal or execution. Both model processes exited
after their bounded stage and no worker remained resident.

The grasp provider is configured independently through
`profiles/robotwin20/graspgen.yaml`. Its worker receives only an adapter-resolved
point-cloud path and returns 4x4 matrices plus scores; the adapter validates the
homogeneous transform, converts it to a normalized quaternion and approach
vector, applies deterministic confidence-ordered SE(3) NMS, and projects the
candidate funnel. GraspGen/Torch/checkpoint settings remain in the external
worker profile. The repository currently contains the worker protocol and
conformance tests, but no local GraspGen checkpoint is assumed; until the
profile points at a verified external model environment the provider must stay
`unavailable` rather than fabricate candidates.

Although this reference wiring lives beside the RoboTwin adapter example, the
provider itself depends only on the generic `PointCloudArtifactResolver` and
`GraspWorkerClient` ports. A future hardware or replay adapter can reuse the
same provider with its own artifact resolver/profile; no RoboTwin or SAPIEN
object is part of the provider API.

The adapter also exposes `RoboTwinReadinessEvaluator` as the independent seam
for `manipulation.prepare`. It accepts the frozen observation/candidate request
and delegates to an injected no-motion evaluator, such as a separately
provisioned IK/collision/workspace worker. It returns only prepared candidates,
three passing readiness checks, and opaque evidence references. Invalid or
unbound candidates, unknown/failing checks, duplicate references, provider
specific fields, and evaluator failures remain fail-closed at the PAOS endpoint.
The evaluator never imports PAOS, RoboTwin, SAPIEN, Hephaestus, or an actuator,
and never authorizes motion. A real evaluator must be profile-owned and
independently conformance-tested before any Action provider is considered.

For deterministic no-motion conformance, `profiles/robotwin20/readiness-replay.yaml`
builds the same evaluator through `readiness_replay_worker.py` and the existing
JSONL process client. Set `READINESS_FIXTURE`, its exact
`READINESS_FIXTURE_SHA256`, `READINESS_EVIDENCE_MANIFEST`,
`READINESS_EVIDENCE_MANIFEST_SHA256`, `READINESS_WORKER_PYTHON`, and
`PAOS_ROBOTWIN20_ADAPTER_ROOT` in the deployment environment. The fixture and
evidence manifest must be external regular files with no group/world write bits.
The worker matches the complete observation/candidate identity and validates
each evidence reference against the manifest's revision, frame, calibration,
source, and timezone-aware capture timestamp before returning replay evidence;
unknown cases, digest/path/schema mismatches, worker identity changes, missing
or drifted evidence, and non-no-motion responses fail closed. Replay is protocol
evidence only, not a claim of real IK, collision, trajectory, or physical success.

Once a real or independently validated worker result has been manually reviewed,
`ReadinessReplayClient.record_replay(request, absolute_path)` can persist the
validated projection as an immutable adapter-local canonical JSON artifact. The
artifact carries worker, fixture, evidence-manifest, request, result, and
timezone-aware generation bindings plus a SHA-256 content ID. Existing files may
only be replayed when the bytes are identical; divergent overwrites, malformed
JSON, path/symlink or permission violations, request/result drift, and any
`motion_authorized=true` value fail closed. This artifact is an audit/replay
record, not a PAOS `EvidenceBundle`, physical-success verdict, or Action/Gateway
admission. The manual-review gate remains a prerequisite for real wiring.

The first end-to-end no-motion run across the currently configured providers
is recorded under
`/home/yanxu/robotwin20-runtime/artifacts/paos-real-chain-20260905T0020Z/`.
It binds RoboTwin `beat_block_hammer/demo_clean`, seed `0`, and
`aloha-agilex`. The run manifest records preflight, scene observation, real
`gpt-5.6-sol` scene understanding, LocateAnything/SAM2/RGB-D derived
artifacts, profile digests, source/derived artifact hashes, and raw worker
stdout/stderr. The first three stages passed; GraspGen and readiness are
explicitly unavailable because their required profile environment variables are
not configured. No Action, Dora, or motion stage was attempted.

The next provider-gated run restored the external GraspGen profile and
replayed the real `entity://red-rectangular-block-1` point cloud through
`GraspGenProposalProvider` without motion. It returned 24 normalized,
provider-neutral candidates with funnel `24/24/24/24`. Evidence is stored at
`/home/yanxu/robotwin20-runtime/artifacts/paos-graspgen-live-20260905T0040Z/`;
the manifest SHA-256 is
`a7627a6d8583bf4da502dfe1deaf8c3ec1e978f8f274ede545446614f43ae336`.
The worker keeps JSONL on stdout and routes model logs to stderr. This is
grasp-provider evidence only; IK/collision readiness, Action/Gateway, Dora,
and physical execution remain gated.

This initializes one simulation scene and captures RGB, depth, calibration, and
joint/end-effector state artifacts. It does not call `play_once`,
`check_success`, segmentation APIs, actor/entity APIs, or any action route.

The first verified capture used `beat_block_hammer/demo_clean`, seed `0`, and
produced a `240x320` RGB PNG, a `240x320` float32 depth NPY, calibration JSON,
and state JSON under `/home/yanxu/robotwin20-runtime/artifacts`. The injected
PAOS adapter returned the three public kinds `rgb`, `depth`, and `state` with a
stable scene revision. On the RTX 5060 Ti host, SAPIEN emitted OIDN CUDA
denoiser warnings during this smoke run, but the sensor artifacts were
successfully persisted; this remains a runtime risk and is not treated as a
perception-quality claim.
