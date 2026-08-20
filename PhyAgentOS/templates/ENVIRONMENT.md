# Environment State

This optional file stores compact, long-lived scene knowledge supplied by the user or an
external perception system. Forge execution does not write this file automatically; use
`forge_get_context` for live robot state.

```json
{
  "schema_version": "PhyAgentOS.environment.v2",
  "updated_at": "2026-05-23T00:00:00Z",
  "targets": {},
  "objects": {},
  "scene_graph": {
    "relations": []
  },
  "perception": {
    "runs": {}
  },
  "map": {},
  "tf": {}
}
```
