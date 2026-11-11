"""Skills: structure, MCP exposure (tools, prompts, resources), and that they only call tools/parameters that really exist."""
import asyncio
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import server  # noqa: E402

SKILL_FILES = sorted((ROOT / "skills").glob("*.md"))


def tools():
    return {t.name: set((t.input_schema or {}).get("properties", {})) for t in asyncio.run(server.mcp.list_tools())}


def test_there_are_skills():
    assert len(SKILL_FILES) >= 6


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.stem)
def test_skill_structure(path):
    text = path.read_text()
    assert text.startswith("---\nname: " + path.stem + "\ndescription: Use when"), "front matter: name must equal the file name, description must say when to use it"
    assert len(text.splitlines()) < 120, "keep skills short enough to be read in full"


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.stem)
def test_skills_only_reference_real_tools_and_params(path):
    known = tools()
    text = path.read_text()
    for m in re.finditer(r"`([a-z_]+)\(([^`]*)\)`", text):
        name, args = m.group(1), m.group(2)
        assert name in known, f"{path.stem} calls unknown tool {name}"
        for kw in re.findall(r"(\w+)\s*=", args):
            assert kw in known[name], f"{path.stem}: {name}() has no parameter {kw} (has {sorted(known[name])})"
    for sk in re.findall(r"`(tinyolly-[a-z-]+)`", text):
        assert sk in server.SKILLS, f"{path.stem} references missing skill {sk}"


def test_served_as_tools_prompts_and_resources():
    listed = json.loads(server.list_skills())
    assert {p["name"] for p in listed} == {p.stem for p in SKILL_FILES}
    assert "Steps" in server.get_skill("tinyolly-triage") and server.get_skill("triage") == server.get_skill("tinyolly-triage")
    assert "available" in json.loads(server.get_skill("nope"))
    assert "Steps" in server.skill_resource("tinyolly-triage") and "No skill" in server.skill_resource("zzz")
    prompts = {p.name for p in asyncio.run(server.mcp.list_prompts())}
    assert prompts == set(server.SKILLS)
    assert "tinyolly-skills://{name}" in {str(t.uri_template) for t in asyncio.run(server.mcp.list_resource_templates())}


def test_prompt_takes_a_focus():
    res = asyncio.run(server.mcp.get_prompt("tinyolly-triage", {"focus": "checkout is slow"}))
    text = res.messages[0].content.text
    assert "Focus: checkout is slow" in text and "TinyOlly triage" in text


def test_nothing_is_installed_into_the_client():
    assert not (ROOT / "install-skills.sh").exists()                      # skills live only inside the MCP server
    assert not list((ROOT / "skills").glob("*/SKILL.md"))
