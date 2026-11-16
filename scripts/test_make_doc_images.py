import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("mdi", Path(__file__).with_name("make-doc-images.py"))
mdi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mdi)


def _png(width):
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + width.to_bytes(4, "big") + b"\x00\x00\x03\xe8" + b"\x00" * 20


def _setup(tmp_path, monkeypatch, readme):
    (tmp_path / "docs" / "images" / "full").mkdir(parents=True)
    monkeypatch.setattr(mdi, "ROOT", tmp_path)
    monkeypatch.setattr(mdi, "IMAGES", tmp_path / "docs" / "images")
    monkeypatch.setattr(mdi, "FULL", tmp_path / "docs" / "images" / "full")
    monkeypatch.setattr(mdi, "SHOTS", [("ui-logs", "ui", "logs")])
    monkeypatch.setattr(mdi, "OTEL_SHOTS", [])
    for d in (mdi.IMAGES, mdi.FULL):
        (d / "ui-logs.png").write_bytes(_png(2000 if d == mdi.IMAGES else 3000))
    (tmp_path / "README.md").write_text(readme)


def test_clickable_markdown_passes(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, "[![logs](docs/images/ui-logs.png)](docs/images/full/ui-logs.png)")
    assert mdi.check() == []


def test_clickable_html_passes(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, '<a href="docs/images/full/ui-logs.png"><img src="docs/images/ui-logs.png" width="400"></a>')
    assert mdi.check() == []


def test_bare_image_fails(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, "![logs](docs/images/ui-logs.png)")
    assert any("not click-to-expand" in p for p in mdi.check())


def test_bare_html_img_fails(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, '<img src="docs/images/ui-logs.png" width="400">')
    assert any("must sit inside" in p for p in mdi.check())


def test_missing_full_and_big_preview_fail(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, "")
    (mdi.FULL / "ui-logs.png").unlink()
    (mdi.IMAGES / "ui-logs.png").write_bytes(_png(2000) + b"x" * (mdi.MAX_PREVIEW_BYTES + 1))
    problems = mdi.check()
    assert any("missing" in p for p in problems) and any("previews must stay under" in p for p in problems)


def test_prefix_rules_for_docs_pages(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, "")
    page = tmp_path / "docs" / "mcp.md"
    page.write_text("[![x](../images/ui-logs.png)](../images/full/ui-logs.png)")  # markdown must not use ../
    assert any("markdown path" in p for p in mdi.check())
    page.write_text("[![x](images/ui-logs.png)](images/full/ui-logs.png)")
    assert mdi.check() == []
    page.write_text('<a href="images/full/ui-logs.png"><img src="images/ui-logs.png"></a>')  # HTML needs ../
    assert any("HTML path" in p for p in mdi.check())
    page.write_text('<a href="../images/full/ui-logs.png"><img src="../images/ui-logs.png"></a>')
    assert mdi.check() == []


def test_small_preview_fails(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, "")
    (mdi.IMAGES / "ui-logs.png").write_bytes(_png(900))
    assert any("only 900 px wide" in p for p in mdi.check())
