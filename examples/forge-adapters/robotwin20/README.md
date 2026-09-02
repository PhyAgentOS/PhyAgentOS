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
