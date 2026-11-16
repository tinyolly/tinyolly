#!/usr/bin/env python3
"""Capture the OpenTelemetry Demo screenshots (and real MCP output) used in docs/otel-demo*.md.

Needs TinyOlly and the demo running (docs/otel-demo.md). It takes the healthy shots, injects the demo's
paymentFailure flag with a change marker, waits for errors to show, takes the failure shots, records what the
MCP tools answer, then turns the flag off.

    scripts/make-otel-demo-images.py --mode k8s                  # kind: UI :5005, MCP :8765
    scripts/make-otel-demo-images.py --mode docker --ui http://localhost:5105 --mcp http://localhost:8865/mcp

Each shot is written twice (preview + full size, see scripts/make-doc-images.py). The MCP text answers go to
/tmp/otel-demo-mcp-output.json so the docs can quote real output. Chrome required.
"""
import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["docker", "k8s"], required=True)
    ap.add_argument("--ui", default="http://localhost:5005")
    ap.add_argument("--mcp", default="http://localhost:8765/mcp")
    args = ap.parse_args()
    os.environ["TINYOLLY_UI"] = args.ui
    os.environ["MCP_URL"] = args.mcp
    sys.path.insert(0, str(HERE))
    t = load("t", "test-otel-demo.py")        # flag setter, trace helpers, MCP client
    mdi = load("mdi", "make-doc-images.py")   # shot writers (preview + full size)
    mcp = t.MCP(args.mcp)
    out, notes = {}, []

    def ui(name, tab):
        time.sleep(25)  # the service map and catalog are cached for about 20 s
        mdi.shoot_ui(name, tab, args.ui)
        notes.append(name)
        print("ok", name, flush=True)

    class Client:  # what mdi.shoot_mcp expects
        def call_content(self, tool, a):
            return mcp.call(tool, a)

    def chart(name, tool, a):
        mdi.shoot_mcp(name, (tool, a), Client())
        notes.append(name)
        print("ok", name, flush=True)

    def place_order_trace(error=False):
        """A trace that goes through PlaceOrder (error=True: one that failed at payment)."""
        cands = sorted(t.traces(300), key=lambda x: -x.get("span_count", 0))
        for tr in cands[:60]:
            if error and not tr.get("has_error"):
                continue
            spans = t.trace_detail(tr["trace_id"]).get("spans", [])
            if any("PlaceOrder" in (s.get("name") or "") for s in spans) and (not error or any(s.get("serviceName") == "payment" for s in spans)):
                return tr["trace_id"]
        return None

    # ---------------------------------------------------------------- healthy
    ok, detail = t.set_flag(args.mode, None, None)
    print("flags reset:", ok, detail, flush=True)
    time.sleep(60)
    ui("ui-otel-service-map", "map")
    ui("ui-otel-catalog", "catalog")
    chart("mesh-otel-service-map", "chart_service_map", {})
    good = place_order_trace()
    if good:
        out["healthy_trace_waterfall"] = mcp.text("get_trace", {"trace_id": good, "format": "waterfall"})
    out["list_services"] = mcp.text("list_services", {"format": "table"})

    # ---------------------------------------------------------------- paymentFailure
    ok, detail = t.set_flag(args.mode, "paymentFailure", "50%")
    print("paymentFailure 50%:", ok, detail, flush=True)
    t.http("/api/events", "POST", {"title": "flag: paymentFailure 50%", "source": "otel-demo", "kind": "flag",
                                    "attributes": {"flag": "paymentFailure", "variant": "50%"}})
    t_on = time.time()
    if not t.eventually(lambda: t.recent_error_traces(t_on, "payment"), 240, 10):
        print("no payment errors appeared", flush=True)
    time.sleep(75)  # let the error rate build up
    ui("ui-otel-failure-catalog", "catalog")
    ui("ui-otel-failure-service-map", "map")
    chart("mesh-otel-failure-map", "chart_service_map", {})
    bad = place_order_trace(error=True)
    if bad:
        chart("mesh-otel-trace-path", "chart_trace_path", {"trace_id": bad})
        out["failing_trace_waterfall"] = mcp.text("get_trace", {"trace_id": bad, "format": "waterfall"})
        out["failing_trace_id"] = bad
    out["service_map_errors"] = mcp.text("get_service_map", {"only": "errors"})
    out["search_error_traces_payment"] = mcp.text("search_traces", {"service": "payment", "errors_only": True, "limit": 3})
    out["get_edge_checkout_payment"] = mcp.text("get_edge", {"source": "checkout", "target": "payment", "minutes": 10})

    ok, detail = t.set_flag(args.mode, None, None)
    print("flags reset:", ok, detail, flush=True)
    Path("/tmp/otel-demo-mcp-output.json").write_text(json.dumps(out, indent=2))
    print("captured:", notes, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
