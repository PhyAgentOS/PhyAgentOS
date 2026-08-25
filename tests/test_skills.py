from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).parents[1]))

from PhyAgentOS.agent.skills import SkillsLoader  # noqa: E402

BUILTIN_SKILLS = Path(__file__).parents[1] / "PhyAgentOS" / "skills"
EXAMPLE_SKILL = (
    Path(__file__).parents[1] / "examples" / "forge-skills" / "move-arm-by-ee" / "SKILL.md"
)


def _install_move_arm_example(root: Path) -> Path:
    target = root / "move-arm-by-ee"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(EXAMPLE_SKILL.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def test_move_arm_by_ee_is_not_a_builtin_skill(tmp_path: Path) -> None:
    loader = SkillsLoader(
        tmp_path,
        builtin_skills_dir=BUILTIN_SKILLS,
        installed_skills_dir=tmp_path / "installed",
    )
    assert loader.get_skill_metadata("move-arm-by-ee") is None


def test_installed_move_arm_by_ee_requires_active_runtime(tmp_path: Path) -> None:
    installed = tmp_path / "installed"
    _install_move_arm_example(installed)
    loader = SkillsLoader(
        tmp_path,
        builtin_skills_dir=BUILTIN_SKILLS,
        installed_skills_dir=installed,
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
    installed = tmp_path / "installed"
    _install_move_arm_example(installed)
    loader = SkillsLoader(
        tmp_path,
        builtin_skills_dir=BUILTIN_SKILLS,
        installed_skills_dir=installed,
        runtime_availability_provider=lambda name: name == "move-arm-by-ee",
    )

    assert "move-arm-by-ee" in {skill["name"] for skill in loader.list_skills()}
    assert loader.get_active_skills() == ["move-arm-by-ee"]
