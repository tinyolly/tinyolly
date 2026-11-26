"""Inferred service-map nodes for CLIENT spans nothing answered: LLMs and MCP servers behind agentgateway, other upstreams.

Span shapes follow a real agentgateway-demo trace (2026-11-25): the gateway's SERVER span carries route, endpoint, model and
tokens; the CLIENT span under it carries only `agentgateway.outbound.subtype` (and `mcp.target` / `gen_ai.tool.name` for MCP).
"""
import pytest

from tinyolly_common.graph_infer import infer_peer

T0 = 1_700_000_000 * 10**9
SERVER, CLIENT = 2, 3


def _a(d):
    return [{"key": k, "value": {"stringValue": str(v)}} for k, v in d.items()]


def _res(service, spans):
    return {"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]},
            "scopeSpans": [{"spans": spans}]}


def _sp(trace, n, parent, kind, name, attrs=None, error=False):
    return {"traceId": "%032x" % trace, "spanId": "%016x" % (trace * 100 + n), "kind": kind, "name": name,
            "parentSpanId": "%016x" % (trace * 100 + parent) if parent else "",
            "startTimeUnixNano": str(T0 + trace * 10**9 + n * 10**6), "endTimeUnixNano": str(T0 + trace * 10**9 + n * 10**6 + 5 * 10**6),
            "status": {"code": 2} if error else {}, "attributes": _a(attrs or {})}


LLM_SERVER = {"route": "default/ollama", "endpoint": "192.168.68.71:11434", "protocol": "llm", "gen_ai.operation.name": "chat",
              "gen_ai.provider.name": "openai", "gen_ai.request.model": "qwen3.8:27b-mtp-q4_K_M",
              "gen_ai.usage.input_tokens": "193", "gen_ai.usage.output_tokens": "24"}


def agent_run(trace):
    """shopping-agent -> gateway -> shop (answered), -> MCP tools/call (unanswered), -> LLM (unanswered)."""
    agent = [
        _sp(trace, 1, 0, SERVER, "shopping_agent.run"),
        _sp(trace, 2, 1, CLIENT, "GET", {"http.url": "http://agentgateway-proxy/product/1"}),
        _sp(trace, 3, 1, CLIENT, "POST", {"http.url": "http://agentgateway-proxy/mcp"}),
        _sp(trace, 4, 1, CLIENT, "openai.chat", {"gen_ai.operation.name": "chat", "gen_ai.request.model": "qwen3.8:27b-mtp-q4_K_M"}),
        _sp(trace, 5, 4, CLIENT, "POST", {"http.url": "http://agentgateway-proxy/v1/chat/completions"}),
    ]
    gateway = [
        _sp(trace, 10, 2, SERVER, "GET /*", {"route": "boutique/shop", "endpoint": "10.244.0.51:8080"}),
        _sp(trace, 11, 10, CLIENT, "GET frontend.boutique.svc.cluster.local:80",
            {"agentgateway.outbound.subtype": "Http", "http.host": "shop.demo"}),
        _sp(trace, 20, 3, SERVER, "tools/call", {"route": "default/mcp", "protocol": "mcp", "mcp.method.name": "tools/call",
                                                  "mcp.target": "mcp-target", "gen_ai.tool.name": "fetch"}),
        _sp(trace, 21, 20, CLIENT, "tools/call mcp-target_fetch", {"agentgateway.outbound.subtype": "Mcp", "mcp.target": "mcp-target",
                                                                    "mcp.method.name": "tools/call", "gen_ai.tool.name": "fetch"}),
        _sp(trace, 30, 5, SERVER, "POST /v1/*", LLM_SERVER),
        _sp(trace, 31, 30, CLIENT, "POST", {"agentgateway.outbound.subtype": "Llm",
                                            "http.host": "agentgateway-proxy.agentgateway-system.svc.cluster.local"}),
    ]
    frontend = [_sp(trace, 40, 11, SERVER, "GET")]
    return {"resourceSpans": [_res("shopping-agent", agent), _res("agentgateway-proxy", gateway), _res("frontend", frontend)]}


def _edges(graph):
    return {(e["source"], e["target"]): e for e in graph["edges"]}


@pytest.mark.asyncio
async def test_gateway_llm_and_mcp_hops_become_nodes(storage):
    for t in (1, 2):
        await storage.store_traces(agent_run(t))
    graph = await storage.get_service_graph()
    edges = _edges(graph)
    types = {n["id"]: n["type"] for n in graph["nodes"]}

    assert types["ollama"] == "llm"
    llm = edges[("agentgateway-proxy", "ollama")]
    assert llm["value"] == 2
    assert (llm["tokens_in"], llm["tokens_out"]) == (386, 48)
    assert llm["models"] == {"qwen3.8:27b-mtp-q4_K_M": 2}
    assert llm["endpoints"] == {"192.168.68.71:11434": 2}

    assert types["mcp-target"] == "mcp"
    mcp = edges[("agentgateway-proxy", "mcp-target")]
    assert mcp["tools"] == {"fetch": 2} and mcp["methods"] == {"tools/call": 2}

    # unchanged: the answered hops, and no node for the gateway itself or for spans that have children
    assert ("shopping-agent", "agentgateway-proxy") in edges and ("agentgateway-proxy", "frontend") in edges
    assert not any(t == "external" for t in types.values())
    assert ("shopping-agent", "ollama") not in edges
    assert types["shopping-agent"] == "agent" and types["agentgateway-proxy"] == "service" and types["frontend"] == "service"


@pytest.mark.asyncio
async def test_direct_llm_call_without_gateway_uses_the_provider(storage):
    spans = [_sp(1, 1, 0, SERVER, "run"),
             _sp(1, 2, 1, CLIENT, "openai.chat", {"gen_ai.operation.name": "chat", "gen_ai.provider.name": "openai",
                                                   "gen_ai.request.model": "gpt-5", "gen_ai.usage.input_tokens": "10"}),
             _sp(1, 3, 2, CLIENT, "POST", {"url.full": "https://api.openai.com/v1/chat/completions"})]
    await storage.store_traces({"resourceSpans": [_res("app", spans)]})
    edge = _edges(await storage.get_service_graph())[("app", "openai")]
    assert edge["tokens_in"] == 10 and edge["models"] == {"gpt-5": 1}


@pytest.mark.asyncio
async def test_uninstrumented_upstream_becomes_external_but_known_services_do_not(storage):
    spans = [_sp(1, 1, 0, SERVER, "run"),
             _sp(1, 2, 1, CLIENT, "GET", {"server.address": "api.stripe.com"}),
             _sp(1, 3, 1, CLIENT, "GET", {"server.address": "worker.default.svc.cluster.local"})]
    await storage.store_traces({"resourceSpans": [_res("app", spans), _res("worker", [_sp(2, 1, 0, SERVER, "job")])]})
    graph = await storage.get_service_graph()
    types = {n["id"]: n["type"] for n in graph["nodes"]}
    assert types.get("api.stripe.com") == "external"
    assert ("app", "worker") not in _edges(graph)          # known service with no matching child: no guessed edge


def test_spans_with_children_or_not_client_are_ignored():
    client = {"kind": CLIENT, "attributes": _a({"server.address": "x.example"})}
    assert infer_peer(client, None, has_child=True) is None
    assert infer_peer({**client, "kind": SERVER}, None, has_child=False) is None
    assert infer_peer(client, None, has_child=False, external=False) is None
    assert infer_peer(client, None, has_child=False)[:2] == ("x.example", "external")


def test_external_names_skip_ips_and_telemetry_export_and_use_rpc_service():
    def peer(attrs, name="call"):
        r = infer_peer({"kind": CLIENT, "name": name, "attributes": _a(attrs)}, None, has_child=False, services=["currencyservice"])
        return r[0] if r else None
    assert peer({"net.peer.name": "10.96.135.219"}) is None
    assert peer({"rpc.service": "hipstershop.CartService", "net.peer.name": "10.96.135.219"}) == "CartService"
    assert peer({"rpc.service": "hipstershop.CurrencyService"}) is None            # known service, any case
    assert peer({"rpc.service": "opentelemetry.proto.collector.trace.v1.TraceService"}) is None
    assert peer({"peer.service": "stripe", "server.address": "10.0.0.1"}) == "stripe"
    assert peer({"server.address": "agentregistry.agentregistry.svc.cluster.local"}) == "agentregistry"   # k8s Service name



@pytest.mark.asyncio
async def test_calls_blocked_at_the_gateway_become_red_edges(storage):
    """Real shapes: llm-guard -> SERVER `POST /v1/*` 403 reason=Guardrail; mcp-deny -> SERVER `tools/call` 400
    reason=Authorization. Neither has a CLIENT child."""
    await storage.store_traces(agent_run(1))
    agent = [_sp(2, 1, 0, SERVER, "shopping_agent.run", error=True),
             _sp(2, 3, 1, CLIENT, "POST", error=True), _sp(2, 5, 1, CLIENT, "POST", error=True)]
    gateway = [_sp(2, 20, 3, SERVER, "tools/call", {"route": "default/mcp", "protocol": "mcp", "mcp.method.name": "tools/call",
                                                     "mcp.target": "mcp-target", "gen_ai.tool.name": "fetch", "reason": "Authorization"}, error=True),
               _sp(2, 30, 5, SERVER, "POST /v1/*", {**LLM_SERVER, "reason": "Guardrail"}, error=True)]
    await storage.store_traces({"resourceSpans": [_res("shopping-agent", agent), _res("agentgateway-proxy", gateway)]})
    edges = _edges(await storage.get_service_graph())
    llm, mcp = edges[("agentgateway-proxy", "ollama")], edges[("agentgateway-proxy", "mcp-target")]
    assert llm["blocked"] == {"Guardrail": 1} and llm["denied_count"] == 1 and llm["value"] == 1
    assert mcp["blocked"] == {"Authorization": 1} and mcp["denied_count"] == 1


@pytest.mark.asyncio
async def test_only_blocked_calls_still_draw_the_edge(storage):
    gateway = [_sp(1, 30, 0, SERVER, "POST /v1/*", {**LLM_SERVER, "reason": "Guardrail"}, error=True)]
    await storage.store_traces({"resourceSpans": [_res("agentgateway-proxy", gateway)]})
    graph = await storage.get_service_graph()
    e = _edges(graph)[("agentgateway-proxy", "ollama")]
    assert (e["value"], e["denied_count"], e["blocked"]) == (0, 1, {"Guardrail": 1})
    assert {n["id"]: n["type"] for n in graph["nodes"]}["ollama"] == "llm"


@pytest.mark.asyncio
async def test_trace_spans_are_annotated_with_inferred_peers(storage):
    from tinyolly_common.graph_infer import annotate_peers
    await storage.store_traces(agent_run(1))
    spans = annotate_peers(await storage.get_trace_spans("%032x" % 1))
    peers = {s["name"]: s["inferredPeer"] for s in spans if "inferredPeer" in s}
    assert peers["POST"]["name"] == "ollama" and peers["POST"]["tokens_in"] == 193
    assert peers["tools/call mcp-target_fetch"] == {"name": "mcp-target", "type": "mcp", "method": "tools/call", "tool": "fetch"}
    assert "GET frontend.boutique.svc.cluster.local:80" not in peers      # answered by frontend



@pytest.mark.asyncio
async def test_calls_to_an_ip_use_reverse_dns(storage, monkeypatch):
    import socket
    names = {"10.96.135.219": "cartservice.boutique.svc.cluster.local", "10.96.117.173": "currencyservice.boutique.svc.cluster.local"}
    def fake(ip):
        if ip in names:
            return names[ip], [], [ip]
        raise socket.herror("no PTR")
    monkeypatch.setattr(socket, "gethostbyaddr", fake)
    spans = [_sp(1, 1, 0, SERVER, "GET"),
             _sp(1, 2, 1, CLIENT, "grpc", {"net.peer.name": "10.96.135.219"}),        # uninstrumented: external node
             _sp(1, 3, 1, CLIENT, "grpc", {"net.peer.name": "10.96.117.173"}),        # known service: no guessed edge
             _sp(1, 4, 1, CLIENT, "grpc", {"net.peer.name": "10.1.2.3"})]             # no PTR: skipped
    await storage.store_traces({"resourceSpans": [_res("frontend", spans), _res("currencyservice", [_sp(2, 1, 0, SERVER, "Convert")])]})
    graph = await storage.get_service_graph()
    types = {n["id"]: n["type"] for n in graph["nodes"]}
    assert types.get("cartservice") == "external"
    assert "10.1.2.3" not in types and ("frontend", "currencyservice") not in _edges(graph)
