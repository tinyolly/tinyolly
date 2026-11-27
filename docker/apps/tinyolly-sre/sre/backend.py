"""The contract between the generic agent and a telemetry product."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Signal:
    kind: str      # "errors", "alert", ...
    entity: str    # what it is about (a service); signals on the same entity join one incident
    text: str
    via: str = ""  # the service that showed the symptom, when `entity` is the deeper service the failure starts in
    op: str = ""   # the operation, for a signal about one operation


class Backend:
    name = "base"
    mcp_url = ""          # MCP server the model may use as tools ("" = no tools)
    mcp_auth = ""         # Authorization header value for it, if any
    mcp_allow: set[str] | None = None   # tool allowlist; None = every tool the server lists (it must be read-only)

    # never offered: TinyOlly's docs and playbooks describe the demo's faults, so the agent would read the answers
    mcp_deny: frozenset[str] = frozenset({"list_docs", "search_docs", "read_doc", "list_skills", "get_skill"})

    def usable(self, tools: list[dict]) -> list[dict]:
        return [t for t in tools if t["name"] not in self.mcp_deny and (self.mcp_allow is None or t["name"] in self.mcp_allow)]

    def detect(self) -> list[Signal]:
        """Cheap checks, no model call. Return the signals active right now."""
        raise NotImplementedError

    def evidence(self, trigger: str, entity: str = "", recovery: bool = False) -> tuple[str, str, str]:
        """(text for the prompt, top entity, top trace id). Raw facts the model cites from."""
        raise NotImplementedError

    def topology(self) -> set[tuple[str, str]]:
        """(caller, callee) pairs, used to group related incidents. Empty = no grouping across entities."""
        return set()

    def links(self) -> dict[str, str]:
        """URL templates with {id}, for the console: "trace" and "service"."""
        return {}

    duties: list[str] = []   # routine reviews to rotate through (names in core.ASKS)

    def review_evidence(self, duty: str, ctx: str = "") -> str:
        """Evidence text for a review-type duty ("digest" is built by the backend from published rows)."""
        return ""

    def changes(self, minutes: float = 15) -> list[dict]:
        return []

    def mark_change(self, title: str, attrs: dict) -> None:
        """Record a real-world change (flag flip, deploy) as a change marker, the way a CD or flag system would. Best effort."""

    def publish(self, kind: str, title: str, attrs: dict) -> None:
        """Write a finding back where humans look. Best effort."""
