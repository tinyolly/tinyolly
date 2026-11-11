"""Docs tools: cleaning, sections, search, paging. Run: ./run-tests.sh"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import docsindex  # noqa: E402
import server  # noqa: E402

PAGE = '''---
title: "Sample page"
description: "A: colon in the description"
---

# Sample page

<div align="center">
  <img src="../images/x.png" width="600">
  <p><em>screenshot caption</em></p>
</div>

Intro text about the widget.

!!! note "Heads up"
    Indented admonition body.

## Setup

=== "cURL"
    ```bash
    curl localhost:5005
    ```

```bash
# Not a heading inside a code block
echo hi
```

## Troubleshooting

Check the frobnicator logs.
'''


@pytest.fixture
def docs(tmp_path, monkeypatch):
    (tmp_path / "sample.md").write_text(PAGE)
    (tmp_path / "big.md").write_text("# Big\n\n" + "\n\n".join(f"## Part {i}\n\n" + "word " * 400 for i in range(60)))
    loaded = docsindex.load(tmp_path)
    monkeypatch.setattr(server, "DOCS", loaded)
    return loaded


def test_front_matter_and_cleaning(docs):
    d = docs["sample"]
    assert d.title == "Sample page" and d.description == "A: colon in the description"
    assert "<img" not in d.text and "<div" not in d.text and "screenshot caption" not in d.text   # screenshots vanish
    assert "> **Heads up:** Indented admonition body." in d.text
    assert "**cURL**" in d.text and "=== " not in d.text and "---\ntitle" not in d.text


def test_sections_ignore_headings_inside_code(docs):
    heads = [s.heading for s in docs["sample"].sections]
    assert heads == ["Sample page", "Setup", "Troubleshooting"] and "Not a heading inside a code block" not in heads


def test_list_and_search(docs):
    names = [d["name"] for d in json.loads(server.list_docs())]
    assert names == ["big", "sample"]
    r = json.loads(server.search_docs("frobnicator"))["results"]
    assert r[0]["doc"] == "sample" and r[0]["section"] == "troubleshooting" and "frobnicator" in r[0]["snippet"]
    assert json.loads(server.search_docs("zzzzqqq"))["results"] == []


def test_read_section_and_unknown(docs):
    d = json.loads(server.read_doc("sample", section="Setup"))
    assert "curl localhost:5005" in d["markdown"] and "frobnicator" not in d["markdown"]
    assert "available" in json.loads(server.read_doc("nope"))
    assert "sections" in json.loads(server.read_doc("sample", section="missing"))
    assert json.loads(server.read_doc("sample.md"))["doc"] == "sample"


def test_big_doc_is_paged_not_truncated(docs):
    got, off = "", 0
    while off is not None:
        d = json.loads(server.read_doc("big", offset=off))
        assert len(json.dumps(d)) <= server.MAX_CHARS + 600
        got, off = got + d["markdown"], d["next_offset"]
    assert got == docs["big"].text


def test_resource_and_missing_docs_dir(docs, monkeypatch):
    assert "Intro text" in server.doc_resource("sample")
    monkeypatch.setattr(server, "DOCS", {})
    assert "not found" in json.loads(server.list_docs())["error"]


def test_real_repo_docs_are_served():
    real = docsindex.load(docsindex.default_docs_dir())
    assert {"quickstart", "docker", "kubernetes", "api", "mcp"} <= set(real)
    assert all(d.title and d.description for d in real.values())          # front matter on every page
    assert all("<img" not in d.text for d in real.values())
