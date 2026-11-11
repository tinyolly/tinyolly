"""Load the investigation skills (skills/<name>.md) that the MCP server serves as tools, prompts and resources.

They live only inside the MCP server (nothing is installed into the client). Directory: $TINYOLLY_SKILLS_DIR, else ./skills next to this file.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from docsindex import parse_front_matter


@dataclass
class Skill:
    name: str
    description: str
    body: str


def default_skills_dir() -> Path | None:
    env = os.environ.get("TINYOLLY_SKILLS_DIR")
    for p in ([Path(env)] if env else []) + [Path(__file__).resolve().parent / "skills"]:
        if p.is_dir():
            return p
    return None


def load(skills_dir: Path | None) -> dict[str, Skill]:
    out: dict[str, Skill] = {}
    if not skills_dir:
        return out
    for f in sorted(skills_dir.glob("*.md")):
        meta, body = parse_front_matter(f.read_text(encoding="utf-8"))
        name = meta.get("name") or f.stem
        out[name] = Skill(name, meta.get("description", ""), body.strip() + "\n")
    return out
