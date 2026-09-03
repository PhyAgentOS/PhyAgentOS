# Environment State Projection

This file is a machine-generated, non-authoritative projection of an immutable observation
snapshot. Forge execution does not treat it as evidence or task state; use the appropriate
Query Tool and Evidence artifacts for live robot state and semantic verification.

```json
{
  "paos": {
    "protocol": "paos.state-file.v1",
    "kind": "environment",
    "mode": "projection",
    "revision": "scene-0001",
    "source": "snapshot://forge/example"
  },
  "data": {
    "schema_version": "paos.environment.v1",
    "scene_revision": "scene-0001",
    "snapshot_ref": "evidence://forge/example/after_snapshot",
    "phase": "live",
    "captured_at": "2026-09-03T00:00:00+00:00",
    "source_id": "sensor://workspace/camera",
    "frame": "world",
    "calibration_ref": "calibration://workspace/current",
    "scene_graph": {
      "nodes": [],
      "relations": []
    },
    "objects": {},
    "robots": {},
    "map": {}
  }
}
```
