# RoboTwin20 EnvironmentAdapter

This is an independently installable adapter workspace. It is not part of the
`PhyAgentOS` wheel and must not be installed into the PAOS control-plane
environment. The adapter package itself has no third-party dependency; a
deployment-specific backend may be installed in a separate RoboTwin runtime
environment and injected through the `RoboTwinSensorBackend` protocol.

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
paos-robotwin20-adapter/       # this package, installed in adapter env
robotwin20-runtime/            # RoboTwin/SAPIEN/Torch/YOLO dependencies
robotwin-assets/               # external assets, mounted by profile
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
