"""The contract between the generic agent and a telemetry product."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Signal:
    kind: str      # "errors", "alert", ...
    entity: str    # what it is about (a service); signals on the same entity join one incident
    text: str


class Backend:
    name = "base"
    mcp_url = ""          # MCP server the model may use as tools ("" = no tools)
    mcp_auth = ""         # Authorization header value for it, if any
    mcp_allow: set[str] | None = None   # tool allowlist; None = every tool the server lists (it must be read-only)

    def detect(self) -> list[Signal]:
        """Cheap checks, no model call. Return the signals active right now."""
        raise NotImplementedError

    def evidence(self, trigger: str, entity: str = "", recovery: bool = False) -> tuple[str, str, str]:
        """(text for the prompt, top entity, top trace id). Raw facts the model cites from."""
        raise NotImplementedError

    duties: list[str] = []   # routine reviews to rotate through (names in core.ASKS)

    def review_evidence(self, duty: str, ctx: str = "") -> str:
        """Evidence text for a review-type duty ("digest" is built by the backend from published rows)."""
        return ""

    def changes(self, minutes: float = 15) -> list[dict]:
        return []

    def publish(self, kind: str, title: str, attrs: dict) -> None:
        """Write a finding back where humans look. Best effort."""
