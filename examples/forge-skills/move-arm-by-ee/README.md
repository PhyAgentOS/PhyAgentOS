# move-arm-by-ee Bundle

This directory is the complete source payload for the MuJoCo profile:

- `SKILL.md`: Agent task instructions and Tool call sequence.
- `skill.yaml`: Skill metadata, profile requirements, and immutable Node locks.
- `profiles/mujoco/`: Dora dataflow and all node configuration files.
- `assets/`: Piper URDF, MuJoCo model, meshes, and third-party licenses.
- `THIRD_PARTY_NOTICES.md`: asset provenance and redistribution notices.

Before publishing, replace every zero-valued Node `sha256` in `skill.yaml` with the
matching GitHub `.tar.gz` Release Asset digest. Then regenerate
`archive-manifest.json`, create the flat Skill `.tar.gz`, upload it to TOS, and register
its final URL, SHA-256, and size in the Resource Registry.

The committed `archive-manifest.json` describes the current example payload. Any source
change requires regenerating it before packaging.
