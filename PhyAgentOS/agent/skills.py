"""Skills loader for agent capabilities."""

import json
import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from PhyAgentOS.config.loader import get_config_path

# Default builtin skills directory (relative to this file)
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"


class SkillsLoader:
    """
    Loader for agent skills.

    Skills are markdown files (SKILL.md) that teach the agent how to use
    specific tools or perform certain tasks.
    """

    def __init__(
        self,
        workspace: Path,
        builtin_skills_dir: Path | None = None,
        installed_skills_dir: Path | None = None,
        runtime_availability_provider: Callable[[str], bool] | None = None,
    ):
        self.workspace = workspace
        self.workspace_skills = workspace / "skills"
        self.installed_skills = (
            installed_skills_dir
            if installed_skills_dir is not None
            else get_config_path().parent / "skills"
        )
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR
        self.runtime_availability_provider = runtime_availability_provider

    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        """
        List all available skills.

        Args:
            filter_unavailable: If True, filter out skills with unmet requirements.

        Returns:
            List of skill info dicts with 'name', 'path', 'source'.
        """
        skills = []

        # Workspace skills (highest priority)
        if self.workspace_skills.exists():
            for skill_dir in self.workspace_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "workspace"})

        # Installed skill bundles
        if self.installed_skills.exists():
            for skill_dir in self.installed_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists() and not any(s["name"] == skill_dir.name for s in skills):
                        skills.append(
                            {"name": skill_dir.name, "path": str(skill_file), "source": "installed"}
                        )

        # Built-in skills
        if self.builtin_skills and self.builtin_skills.exists():
            for skill_dir in self.builtin_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists() and not any(s["name"] == skill_dir.name for s in skills):
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "builtin"})

        # Filter by requirements
        if filter_unavailable:
            return [
                s
                for s in skills
                if self._check_requirements(
                    self._get_skill_meta(s["name"]),
                    skill_name=s["name"],
                )
            ]
        return skills

    def load_skill(self, name: str) -> str | None:
        """
        Load a skill by name.

        Args:
            name: Skill name (directory name).

        Returns:
            Skill content or None if not found.
        """
        # Check workspace first
        workspace_skill = self.workspace_skills / name / "SKILL.md"
        if workspace_skill.exists():
            return workspace_skill.read_text(encoding="utf-8")

        # Check installed bundles
        installed_skill = self.installed_skills / name / "SKILL.md"
        if installed_skill.exists():
            return installed_skill.read_text(encoding="utf-8")

        # Check built-in
        if self.builtin_skills:
            builtin_skill = self.builtin_skills / name / "SKILL.md"
            if builtin_skill.exists():
                return builtin_skill.read_text(encoding="utf-8")

        return None

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """
        Load specific skills for inclusion in agent context.

        Args:
            skill_names: List of skill names to load.

        Returns:
            Formatted skills content.
        """
        parts = []
        for name in skill_names:
            content = self.load_skill(name)
            if content:
                content = self._strip_frontmatter(content)
                parts.append(f"### Skill: {name}\n\n{content}")

        return "\n\n---\n\n".join(parts) if parts else ""

    def build_skills_summary(self) -> str:
        """
        Build a summary of all skills (name, description, path, availability).

        This is used for progressive loading - the agent can read the full
        skill content using read_file when needed.

        Returns:
            XML-formatted skills summary.
        """
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""

        def escape_xml(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        lines = ["<skills>"]
        for s in all_skills:
            name = escape_xml(s["name"])
            path = s["path"]
            desc = escape_xml(self._get_skill_description(s["name"]))
            skill_meta = self._get_skill_meta(s["name"])
            available = self._check_requirements(skill_meta, skill_name=s["name"])

            lines.append(f"  <skill available=\"{str(available).lower()}\">")
            lines.append(f"    <name>{name}</name>")
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>{path}</location>")

            # Show missing requirements for unavailable skills
            if not available:
                missing = self._get_missing_requirements(skill_meta, skill_name=s["name"])
                if missing:
                    lines.append(f"    <requires>{escape_xml(missing)}</requires>")

            lines.append("  </skill>")
        lines.append("</skills>")

        return "\n".join(lines)

    def _get_missing_requirements(
        self,
        skill_meta: dict,
        *,
        skill_name: str | None = None,
    ) -> str:
        """Get a description of missing requirements."""
        missing = []
        if not self._metadata_available(skill_meta):
            missing.append("available: false")
        requires = skill_meta.get("requires", {})
        if not isinstance(requires, dict):
            missing.append("invalid requires metadata")
            return ", ".join(missing)
        for b in requires.get("bins", []):
            if not shutil.which(b):
                missing.append(f"CLI: {b}")
        for env in requires.get("env", []):
            if not os.environ.get(env):
                missing.append(f"ENV: {env}")
        for runtime in self._runtime_requirements(requires, skill_name=skill_name):
            if not self._runtime_available(runtime):
                missing.append(f"runtime: {runtime}")
        return ", ".join(missing)

    def _get_skill_description(self, name: str) -> str:
        """Get the description of a skill from its frontmatter."""
        meta = self.get_skill_metadata(name)
        if meta and meta.get("description"):
            return meta["description"]
        return name  # Fallback to skill name

    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter from markdown content."""
        if content.startswith("---"):
            match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
            if match:
                return content[match.end():].strip()
        return content

    def _parse_paos_metadata(self, raw: str) -> dict:
        """Parse skill metadata JSON from frontmatter (supports PhyAgentOS and openclaw keys)."""
        try:
            data = json.loads(raw)
            return data.get("PhyAgentOS", data.get("openclaw", {})) if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def _check_requirements(
        self,
        skill_meta: dict,
        *,
        skill_name: str | None = None,
    ) -> bool:
        """Check if skill requirements are met (bins, env vars)."""
        if not self._metadata_available(skill_meta):
            return False
        requires = skill_meta.get("requires", {})
        if not isinstance(requires, dict):
            return False
        for b in requires.get("bins", []):
            if not shutil.which(b):
                return False
        for env in requires.get("env", []):
            if not os.environ.get(env):
                return False
        for runtime in self._runtime_requirements(requires, skill_name=skill_name):
            if not self._runtime_available(runtime):
                return False
        return True

    @staticmethod
    def _runtime_requirements(
        requires: dict,
        *,
        skill_name: str | None,
    ) -> list[str]:
        value = requires.get("runtime", [])
        if isinstance(value, str):
            value = [value]
        if value is True and skill_name:
            return [skill_name]
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str) and item.strip()]

    def _runtime_available(self, name: str) -> bool:
        return bool(
            self.runtime_availability_provider
            and self.runtime_availability_provider(name)
        )

    def get_active_skills(self) -> list[str]:
        """Return available skills whose metadata requires an active runtime."""
        result = []
        for skill in self.list_skills(filter_unavailable=True):
            meta = self._get_skill_meta(skill["name"])
            requires = meta.get("requires", {})
            if not isinstance(requires, dict):
                continue
            if self._runtime_requirements(requires, skill_name=skill["name"]):
                result.append(skill["name"])
        return result

    @staticmethod
    def _metadata_available(skill_meta: dict) -> bool:
        """Return false only for an explicit available=false metadata marker."""
        available = skill_meta.get("available")
        if isinstance(available, str):
            return available.strip().lower() not in {"false", "0", "no", "off"}
        return available is not False

    def _get_skill_meta(self, name: str) -> dict:
        """Get PhyAgentOS metadata for a skill (cached in frontmatter)."""
        meta = self.get_skill_metadata(name) or {}
        return self._parse_paos_metadata(meta.get("metadata", ""))

    def get_always_skills(self) -> list[str]:
        """Get skills marked as always=true that meet requirements."""
        result = []
        for s in self.list_skills(filter_unavailable=True):
            meta = self.get_skill_metadata(s["name"]) or {}
            skill_meta = self._parse_paos_metadata(meta.get("metadata", ""))
            if skill_meta.get("always") or meta.get("always"):
                result.append(s["name"])
        return result

    def get_skill_metadata(self, name: str) -> dict | None:
        """
        Get metadata from a skill's frontmatter.

        Args:
            name: Skill name.

        Returns:
            Metadata dict or None.
        """
        content = self.load_skill(name)
        if not content:
            return None

        if content.startswith("---"):
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if match:
                # Simple YAML parsing
                metadata = {}
                for line in match.group(1).split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        metadata[key.strip()] = value.strip().strip('"\'')
                return metadata

        return None
