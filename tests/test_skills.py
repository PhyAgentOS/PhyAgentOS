from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).parents[1]))

from PhyAgentOS.agent.skills import SkillsLoader  # noqa: E402

BUILTIN_SKILLS = Path(__file__).parents[1] / "PhyAgentOS" / "skills"


def test_move_arm_by_ee_requires_active_runtime(tmp_path: Path) -> None:
    loader = SkillsLoader(
        tmp_path,
        builtin_skills_dir=BUILTIN_SKILLS,
        installed_skills_dir=tmp_path / "installed",
    )

    metadata = loader.get_skill_metadata("move-arm-by-ee")
    assert metadata is not None
    assert metadata["name"] == "move-arm-by-ee"
    assert metadata["description"]

    available_names = {skill["name"] for skill in loader.list_skills()}
    all_names = {skill["name"] for skill in loader.list_skills(filter_unavailable=False)}
    assert "move-arm-by-ee" not in available_names
    assert "move-arm-by-ee" in all_names

    summary = ElementTree.fromstring(loader.build_skills_summary())
    skill = next(node for node in summary.findall("skill") if node.findtext("name") == "move-arm-by-ee")
    assert skill.attrib["available"] == "false"
    assert skill.findtext("requires") == "runtime: move-arm-by-ee"


def test_move_arm_by_ee_is_active_when_runtime_is_ready(tmp_path: Path) -> None:
    loader = SkillsLoader(
        tmp_path,
        builtin_skills_dir=BUILTIN_SKILLS,
        installed_skills_dir=tmp_path / "installed",
        runtime_availability_provider=lambda name: name == "move-arm-by-ee",
    )

    assert "move-arm-by-ee" in {skill["name"] for skill in loader.list_skills()}
    assert loader.get_active_skills() == ["move-arm-by-ee"]
