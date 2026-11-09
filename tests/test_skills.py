from pathlib import Path

from foxstar_bot.skills import SkillRegistry


def test_skill_registry_lists_and_loads_skills(tmp_path: Path):
    skill_dir = tmp_path / "skills" / "signup_roster_compare"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "# Signup Roster Compare\n\n"
        "Compare a guild roster against a signup list.\n\n"
        "1. Search knowledge.\n"
        "2. Normalize names.\n",
        encoding="utf-8",
    )

    registry = SkillRegistry(tmp_path / "skills")
    listed = registry.list_skills()
    loaded = registry.load_skill("signup_roster_compare")
    found = registry.search_skills("signup roster")

    assert len(listed) == 1
    assert listed[0].name == "signup_roster_compare"
    assert "Compare a guild roster" in listed[0].summary
    assert "Normalize names" in loaded
    assert found and found[0].name == "signup_roster_compare"


def test_skill_registry_searches_skill_body(tmp_path: Path):
    skill_dir = tmp_path / "skills" / "signup_roster_compare"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "# Signup Roster Compare\n\n"
        "Workflow for roster attendance.\n\n"
        "Use this when the user wants to 统计接龙人数、未接龙名单、请假和替补。\n",
        encoding="utf-8",
    )

    registry = SkillRegistry(tmp_path / "skills")
    found = registry.search_skills("接龙 名单", max_results=5)

    assert found and found[0].name == "signup_roster_compare"


def test_skill_registry_loads_companion_code_files(tmp_path: Path):
    skill_dir = tmp_path / "skills" / "yfinance_quote"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "# Yahoo Finance Quote Lookup\n\nUse the bundled helper code.\n",
        encoding="utf-8",
    )
    (skill_dir / "query_yfinance_http.py").write_text(
        "SYMBOLS = ['NVDA']\nprint('ok')\n",
        encoding="utf-8",
    )

    registry = SkillRegistry(tmp_path / "skills")
    loaded = registry.load_skill("yfinance_quote")

    assert "Reference file: query_yfinance_http.py" in loaded
    assert "SYMBOLS = ['NVDA']" in loaded
