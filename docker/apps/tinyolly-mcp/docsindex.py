"""Serve TinyOlly's docs/*.md to agents: cleaned of screenshots/HTML, split by heading, searchable.

Docs directory: $TINYOLLY_DOCS_DIR, else <repo>/docs relative to this file. Pages carry a small front matter
(title, description) that is shown in the listing; everything else is plain markdown.
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


def default_docs_dir() -> Path | None:
    env = os.environ.get("TINYOLLY_DOCS_DIR")
    for p in ([Path(env)] if env else []) + [Path(__file__).resolve().parents[3] / "docs"]:
        if p.is_dir():
            return p
    return None


def slug(heading: str) -> str:
    h = re.sub(r"[`*_]", "", heading).strip().lower()
    return re.sub(r"\s+", "-", re.sub(r"[^\w\s-]", "", h))


def parse_front_matter(text: str) -> tuple[dict, str]:
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip().strip('"').replace('\\"', '"')
    return meta, text[m.end():]


def clean(md: str) -> str:
    """Markdown for a terminal/agent: no HTML layout, images or mkdocs-only syntax."""
    md = re.sub(r"<div[^>]*>.*?</div>",                                    # screenshot blocks vanish, other HTML keeps its text
                lambda m: "" if "<img" in m.group(0) else re.sub(r"<[^>]+>", "", m.group(0)).strip(), md, flags=re.S)
    md = re.sub(r"<img[^>]*>", "", md)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)\n?", "", md)                       # screenshots
    md = re.sub(r"^!!! (\w+)(?: \"([^\"]*)\")?\n((?:    .*\n?|\n)+)",         # admonitions -> blockquote
                lambda m: f"> **{m.group(2) or m.group(1).title()}:** " + re.sub(r"^    ", "", m.group(3).strip(), flags=re.M).replace("\n", "\n> ") + "\n",
                md, flags=re.M)
    md = re.sub(r'^=== "([^"]+)"\n', r"**\1**\n", md, flags=re.M)         # content tabs
    md = re.sub(r"^    (?=\S)", "", md, flags=re.M) if "**cURL**" in md else md
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"


@dataclass
class Section:
    heading: str
    level: int
    body: str

    @property
    def slug(self) -> str:
        return slug(self.heading)


@dataclass
class Doc:
    name: str
    title: str
    description: str
    text: str
    sections: list[Section] = field(default_factory=list)


def _split(text: str) -> list[Section]:
    out, cur, in_code = [], Section("(intro)", 0, ""), False
    lines = []
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        m = None if in_code else re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            cur.body = "\n".join(lines).strip()
            if cur.body or cur.level:
                out.append(cur)
            cur, lines = Section(m.group(2).strip(), len(m.group(1)), ""), [line]
        else:
            lines.append(line)
    cur.body = "\n".join(lines).strip()
    out.append(cur)
    return [s for s in out if s.body]


def load(docs_dir: Path | None) -> dict[str, Doc]:
    docs: dict[str, Doc] = {}
    if not docs_dir:
        return docs
    for p in sorted(docs_dir.glob("*.md")):
        meta, body = parse_front_matter(p.read_text(encoding="utf-8"))
        text = clean(body)
        title = meta.get("title") or (re.search(r"^#\s+(.*)$", text, re.M) or [None, p.stem])[1]
        docs[p.stem.lower()] = Doc(p.stem.lower(), title, meta.get("description", ""), text, _split(text))
    return docs


def find_section(doc: Doc, query: str) -> list[Section]:
    q = slug(query)
    exact = [s for s in doc.sections if s.slug == q]
    return exact or [s for s in doc.sections if q in s.slug]


def search(docs: dict[str, Doc], query: str, limit: int = 10) -> list[dict]:
    terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 1]
    hits = []
    for d in docs.values():
        for s in d.sections:
            hay = (s.heading + "\n" + s.body).lower()
            score = sum(hay.count(t) for t in terms) + 5 * sum(t in s.heading.lower() for t in terms)
            if terms and all(t in hay or t in d.title.lower() for t in terms):
                score += 10
            if score and any(t in hay for t in terms):
                i = min((hay.find(t) for t in terms if t in hay), default=0)
                snippet = s.body[max(0, i - 80): i + 200].replace("\n", " ").strip()
                hits.append({"doc": d.name, "section": s.slug, "heading": s.heading, "score": score, "snippet": snippet})
    hits.sort(key=lambda h: -h["score"])
    return hits[: max(1, limit)]
