"""The MCP image must contain every module the server imports (a new module once missed the image and crashed the pod)."""
import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
DOCKERFILE = APP.parent.parent / "dockerfiles" / "Dockerfile.tinyolly-mcp"


def test_dockerfile_copies_all_top_level_modules():
    text = DOCKERFILE.read_text()
    copied = " ".join(re.findall(r"^COPY\s+(.+?)\s+\./?\s*$", text, re.M))
    if "docker/apps/tinyolly-mcp/*.py" in copied:
        return                                              # a glob covers every module, present and future
    missing = [p.name for p in APP.glob("*.py") if f"docker/apps/tinyolly-mcp/{p.name}" not in copied]
    assert not missing, f"not copied into the image: {missing}"
