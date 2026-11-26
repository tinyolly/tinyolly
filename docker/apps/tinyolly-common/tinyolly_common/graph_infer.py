"""Infer the service-map node behind a CLIENT span that nothing answered.

An edge normally comes from a parent span and a child span in two services. When the callee emits no spans (an LLM such as
Ollama, an MCP server, any uninstrumented upstream) the caller's CLIENT span is a leaf and the hop vanishes. `infer_peer`
names the node that span called, from its own attributes and its parent's (agentgateway puts the model, endpoint and
tokens on the SERVER span and only `agentgateway.outbound.subtype` on the CLIENT span under it).
"""
import asyncio
import ipaddress
import os
import socket
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .otlp_utils import get_attr_value

CLIENT_KINDS = (3, "3", "SPAN_KIND_CLIENT")
MODEL_KEYS = ["gen_ai.request.model", "gen_ai.response.model"]
LLM_OPERATIONS = {"chat", "text_completion", "generate_content", "embeddings", "completion"}
HOST_KEYS = ["peer.service", "server.address", "net.peer.name", "http.host"]


def _attr(span: Optional[Dict[str, Any]], keys) -> Any:
    return get_attr_value(span, list(keys)) if span else None


def _host(span: Dict[str, Any]) -> Optional[str]:
    host = _attr(span, HOST_KEYS)
    if not host:
        url = _attr(span, ["url.full", "http.url"])
        if url and "://" in str(url):
            host = str(url).split("://", 1)[1].split("/", 1)[0]
    if not host:
        return None
    host = str(host).rsplit("@", 1)[-1]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _known(name: str, services: Iterable[str]) -> bool:
    """True if `name` is a service already on the map (`frontend`, `frontend.boutique.svc.cluster.local`, `CartService`)."""
    known = {str(s).lower() for s in services}
    name = name.lower()
    return name in known or name.split(".", 1)[0] in known


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def _external_name(span: Dict[str, Any]) -> Optional[str]:
    """Who an uninstrumented CLIENT span called: `peer.service`, else the gRPC service (`hipstershop.CartService` ->
    `CartService`), else the host. None for a bare IP (no identity) or the app exporting its own telemetry."""
    rpc = str(_attr(span, ["rpc.service"]) or "")
    if rpc.startswith("opentelemetry.proto.collector") or "/Export" in str(span.get("name", "")) and "opentelemetry" in str(span.get("name", "")):
        return None
    name = _attr(span, ["peer.service"]) or (rpc.rsplit(".", 1)[-1] if rpc else None) or _host(span)
    if name and _is_ip(str(name)):
        name = ip_name(str(name))                       # reverse DNS (resolve_ips), else no identity: skip it
    return _short_name(str(name)) if name else None


# ---- reverse DNS for calls made to an IP (in Kubernetes, cluster DNS has PTR records for Service IPs)
_IP_NAMES: Dict[str, Tuple[Optional[str], float]] = {}
IP_NAME_TTL = 600


def ip_name(ip: str) -> Optional[str]:
    """The cached name for `ip` (`cartservice` for `cartservice.boutique.svc.cluster.local`), or None."""
    hit = _IP_NAMES.get(ip)
    return hit[0] if hit and time.time() - hit[1] < IP_NAME_TTL else None


def _short_name(host: Optional[str]) -> Optional[str]:
    if not host:
        return None
    return host.split(".", 1)[0] if ".svc." in host else host


def candidate_ips(spans: Iterable[Dict[str, Any]]) -> set:
    """IPs that leaf CLIENT spans were sent to and that are not resolved yet (or expired)."""
    out = set()
    for s in spans:
        if s.get("kind") in CLIENT_KINDS:
            host = _host(s)
            if host and _is_ip(host) and ip_name(host) is None:
                out.add(host)
    return out


async def resolve_ips(ips: Iterable[str], timeout: float = 1.0, limit: int = 50) -> None:
    """Reverse-resolve up to `limit` IPs into the cache, in threads, `timeout` seconds at most. Misses are cached too.
    Off with SERVICE_MAP_RESOLVE_IPS=0."""
    if os.getenv("SERVICE_MAP_RESOLVE_IPS", "1") in ("0", "false", "False"):
        return
    todo = [ip for ip in ips if not (ip in _IP_NAMES and time.time() - _IP_NAMES[ip][1] < IP_NAME_TTL)][:limit]
    if not todo:
        return
    loop = asyncio.get_running_loop()

    async def one(ip: str) -> None:
        try:
            host = (await asyncio.wait_for(loop.run_in_executor(None, socket.gethostbyaddr, ip), timeout))[0]
        except Exception:
            host = None
        _IP_NAMES[ip] = (_short_name(host), time.time())

    await asyncio.gather(*(one(ip) for ip in todo))


def _route_backend(span: Dict[str, Any], parent: Optional[Dict[str, Any]]) -> Optional[str]:
    """agentgateway `route` is `<namespace>/<name>`; the name is the backend (`default/ollama` -> `ollama`)."""
    route = _attr(span, ["route"]) or _attr(parent, ["route"])
    return str(route).rsplit("/", 1)[-1] if route else None


def is_agent_span(span: Dict[str, Any]) -> bool:
    """A span that makes its service an agent: a GenAI call it makes (CLIENT span with `gen_ai.operation.name`), or an agent
    span (`gen_ai.agent.name`, `invoke_agent`). Gateways carry gen_ai.* on SERVER spans, so they are not agents."""
    op = _attr(span, ["gen_ai.operation.name"])
    if _attr(span, ["gen_ai.agent.name"]) or op in ("invoke_agent", "create_agent"):
        return True
    return bool(op) and span.get("kind") in CLIENT_KINDS


def infer_blocked(span: Dict[str, Any], has_child: bool, is_error: bool) -> Optional[Tuple[str, str, str]]:
    """(node id, node type, reason) for an LLM or MCP call the gateway refused, or None.

    agentgateway answers a refused call itself: the SERVER span (`protocol` llm/mcp) errors, carries `reason`
    (`Guardrail`, `Authorization`, ...) and has no outgoing CLIENT span. The node is named as `infer_peer` names it,
    so the blocked calls land on the same `ollama` / `mcp-target` node as the ones that went through."""
    if has_child or not is_error or span.get("kind") in CLIENT_KINDS:
        return None
    protocol = str(_attr(span, ["protocol"]) or "").lower()
    reason = str(_attr(span, ["reason", "error.type"]) or "blocked")
    if protocol == "llm":
        name = _route_backend(span, None) or _attr(span, ["gen_ai.provider.name", "gen_ai.system"]) or "llm"
        return str(name), "llm", reason
    if protocol == "mcp":
        name = _attr(span, ["mcp.target"]) or _route_backend(span, None) or "mcp"
        return str(name), "mcp", reason
    return None


def infer_external_enabled() -> bool:
    return os.getenv("SERVICE_MAP_INFER_EXTERNAL", "1") not in ("0", "false", "False")


def infer_peer(span: Dict[str, Any], parent: Optional[Dict[str, Any]], has_child: bool,
               services: Iterable[str] = (), external: bool = True) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """(node id, node type, edge extras) for a leaf CLIENT span, or None.

    Rules, first match wins, each node named like a service (as databases are):
    - LLM call -> the gateway route's backend (`default/ollama` -> `ollama`), else `gen_ai.provider.name` (`openai`), else the
      host; type `llm`. Extras: `model`, `tokens_in`, `tokens_out`, `endpoint`.
    - MCP call -> `mcp.target` (the gateway's MCP backend), else the route's backend; type `mcp`. Extras: `method`, `tool`.
    - Any other upstream host that is not a known service -> the host; type `external` (only when `external`).
    """
    if has_child or span.get("kind") not in CLIENT_KINDS:
        return None

    subtype = str(_attr(span, ["agentgateway.outbound.subtype"]) or "").lower()
    model = _attr(span, MODEL_KEYS) or _attr(parent, MODEL_KEYS)
    operation = str(_attr(span, ["gen_ai.operation.name"]) or _attr(parent, ["gen_ai.operation.name"]) or "")
    if subtype == "llm" or (model and (not operation or operation in LLM_OPERATIONS)):
        extras = {
            "tokens_in": _int(_attr(span, ["gen_ai.usage.input_tokens"]) or _attr(parent, ["gen_ai.usage.input_tokens"])),
            "tokens_out": _int(_attr(span, ["gen_ai.usage.output_tokens"]) or _attr(parent, ["gen_ai.usage.output_tokens"])),
        }
        if model:
            extras["model"] = str(model)
        endpoint = _attr(parent, ["endpoint"]) or _attr(span, ["endpoint"])
        if endpoint:
            extras["endpoint"] = str(endpoint)
        name = _route_backend(span, parent) or _attr(span, ["gen_ai.provider.name", "gen_ai.system"]) \
            or _attr(parent, ["gen_ai.provider.name", "gen_ai.system"]) or (str(endpoint).rsplit(":", 1)[0] if endpoint else None) \
            or _host(span) or "llm"
        return str(name), "llm", extras

    target = _attr(span, ["mcp.target"]) or _attr(parent, ["mcp.target"])
    if subtype == "mcp" or target:
        method = _attr(span, ["mcp.method.name"]) or _attr(parent, ["mcp.method.name"])
        extras = {"method": str(method)} if method else {}
        tool = _attr(span, ["gen_ai.tool.name"]) or _attr(parent, ["gen_ai.tool.name"])
        if tool and method == "tools/call":
            extras["tool"] = str(tool)
        return str(target or _route_backend(span, parent) or "mcp"), "mcp", extras

    if not external:
        return None
    name = _external_name(span)
    if not name or _known(name, services):
        return None
    return name, "external", {}


def annotate_peers(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add `inferredPeer` to the spans of ONE trace whose callee emits no spans: {name, type} plus `model`/`tokens_in`/
    `tokens_out` (LLM), `tool`/`method` (MCP), or `blocked` (the reason a gateway refused it). LLM and MCP only: the
    external-host rule needs the whole service list, so it stays on the service map. Returns the same list."""
    from .otlp_utils import is_error_status
    by_id = {s.get("spanId", s.get("span_id")): s for s in spans}
    parents = {s.get("parentSpanId", s.get("parent_span_id")) for s in spans}
    for s in spans:
        sid = s.get("spanId", s.get("span_id"))
        has_child = sid in parents
        peer = infer_peer(s, by_id.get(s.get("parentSpanId", s.get("parent_span_id"))), has_child, external=False)
        if peer:
            s["inferredPeer"] = {"name": peer[0], "type": peer[1], **peer[2]}
            continue
        blocked = infer_blocked(s, has_child, is_error_status(s.get("status", {}) or {}))
        if blocked:
            s["inferredPeer"] = {"name": blocked[0], "type": blocked[1], "blocked": blocked[2]}
    return spans
