#!/usr/bin/env python3
"""Behaviour tests for the collector presets: run each preset on a real collector, send known telemetry with
telemetrygen, and assert what comes out of the debug exporter (or the failover file).

`scripts/test-collector-configs.sh` only proves a config *starts*; this proves it *does what its blurb says*.
Needs docker (Colima) and ~2 minutes. Usage:  scripts/test-preset-behavior.py [preset ...]
Presets: sampling logs-dedup transform-ottl pii-redaction connectors-metrics connectors-routing
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(ROOT, "docker/otelcol-configs/templates")
VERSION = re.search(r"^OTELCOL_VERSION=([0-9.]+)", open(os.path.join(ROOT, "versions.env")).read(), re.M).group(1)
COLLECTOR = f"ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-contrib:{VERSION}"
TELEMETRYGEN = f"ghcr.io/open-telemetry/opentelemetry-collector-contrib/telemetrygen:v{VERSION}"
NET = f"preset-test-{os.getpid()}"
WORK = tempfile.mkdtemp(prefix=".preset-test-", dir=ROOT)   # inside the repo: Colima only shares $HOME
os.chmod(WORK, 0o777)
failures = []
containers = []


def sh(cmd, check=False):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"{cmd}\n{r.stderr}")
    return r.stdout + r.stderr


def check(name, ok, detail=""):
    print(("ok    " if ok else "FAIL  ") + name + ("" if ok else f"   -> {detail}"))
    if not ok:
        failures.append(name)


def make_config(preset, name, drop_otlp=True, keep=()):
    """Copy a preset for testing: no OpAMP, detailed debug output, and (optionally) no real OTLP export."""
    text = open(os.path.join(TPL, preset + ".yaml")).read()
    text = re.sub(r"^extensions:\n(?:  .*\n|\n)*?(?=\S)", "", text, count=1, flags=re.M)
    text = text.replace("extensions: [opamp]", "extensions: []")
    text = re.sub(r"verbosity: \w+", "verbosity: detailed", text)
    if drop_otlp:
        def strip(m):
            items = [i.strip() for i in m.group(1).split(",") if i.strip() and (i.strip() != "otlp" or "otlp" in keep)]
            return "exporters: [" + ", ".join(items) + "]"
        text = re.sub(r"exporters: \[([^\]]*)\]", strip, text)
    path = os.path.join(WORK, f"{name}.yaml")
    open(path, "w").write(text)
    return path


def start_collector(name, config, extra="", ports="", alias=None):
    """Start a collector on the private test network. Container names must be unique to this test run: never name
    one after a real service (an earlier version did, and `docker rm -f <name>` would have deleted the real one).
    Use alias= to make it reachable under a service name on the private network only."""
    assert name.startswith("pt-"), f"test container names must start with pt-: {name}"
    sh(f"docker rm -f {name}")
    alias_arg = f"--network-alias {alias}" if alias else ""
    sh(f"docker run -d --name {name} --network {NET} {alias_arg} {ports} -v {config}:/c.yaml -v {WORK}:/var/lib/otelcol {extra} "
       f"{COLLECTOR} --config /c.yaml", check=True)
    containers.append(name)
    for _ in range(20):
        if "Everything is ready" in sh(f"docker logs {name}"):
            return
        time.sleep(0.5)
    raise RuntimeError(f"collector {name} did not start:\n{sh(f'docker logs {name} | tail -5')}")


def gen(kind, target, *args):
    sh(f"docker run --rm --network {NET} {TELEMETRYGEN} {kind} --otlp-endpoint {target}:4317 --otlp-insecure --rate 0 "
       + " ".join(args))


def logs_of(name):
    return sh(f"docker logs {name}")


def blocks(text, kind):
    """Split debug output into per-resource blocks: kind = ResourceSpans | ResourceLog | ResourceMetrics."""
    return re.split(rf"{kind} #\d+", text)[1:]


def service_of(block):
    m = re.search(r"service\.name: Str\(([^)]*)\)", block)
    return m.group(1) if m else None


def span_names_by_service(text):
    out = {}
    for b in blocks(text, "ResourceSpans"):
        out.setdefault(service_of(b), []).extend(re.findall(r"^\s+Name\s*: (.*)$", b, re.M))
    return out


def log_records(text):
    recs = []
    for b in blocks(text, "ResourceLog"):
        svc = service_of(b)
        for rec in re.split(r"LogRecord #\d+", b)[1:]:
            recs.append({
                "svc": svc,
                "sev": (re.search(r"SeverityText: (.*)", rec) or [None, ""])[1].strip(),
                "body": (re.search(r"Body: Str\((.*)\)", rec) or [None, ""])[1],
                "text": rec,
            })
    return recs


def settle(seconds=8):
    time.sleep(seconds)


# ----------------------------------------------------------------------------------------------------------------
def test_sampling():
    print("\n== sampling")
    name = f"pt-sampling-{os.getpid()}"
    start_collector(name, make_config("sampling", "sampling"))
    gen("logs", name, "--logs 400", "--service sampled", "--body 'routine info'")
    gen("logs", name, "--logs 60", "--service sampled", "--severity-text ERROR", "--severity-number 17", "--body 'something failed'")
    gen("logs", name, "--logs 40", "--service sampled", "--severity-text WARN", "--severity-number 13", "--body 'careful'")
    settle()
    recs = [r for r in log_records(logs_of(name)) if r["svc"] == "sampled"]
    by = {k: sum(1 for r in recs if r["sev"].upper().startswith(k)) for k in ("INFO", "ERROR", "WARN")}
    check("all 60 ERROR logs are kept", by["ERROR"] == 60, by)
    check("all 40 WARN logs are kept", by["WARN"] == 40, by)
    check("INFO logs are sampled (~25% of 400)", 40 <= by["INFO"] <= 170, by)

    # traces: errors always kept, OK traces thinned to ~10%
    gen("traces", name, "--traces 400", "--service ok-svc", "--status-code Ok")
    gen("traces", name, "--traces 30", "--service err-svc", "--status-code Error")
    settle(12)
    spans = span_names_by_service(logs_of(name))
    ok_n = len(spans.get("ok-svc", [])) // 2
    err_n = len(spans.get("err-svc", [])) // 2
    check("all 30 error traces are kept", err_n == 30, f"{err_n}")
    check("OK traces are thinned to about 10% of 400", 10 <= ok_n <= 90, f"{ok_n}")


def test_logs_dedup():
    print("\n== logs-dedup")
    name = f"pt-dedup-{os.getpid()}"
    start_collector(name, make_config("logs-dedup", "dedup"))
    gen("logs", name, "--logs 60", "--service d", "--body 'spam info'")
    gen("logs", name, "--logs 20", "--service d", "--severity-text ERROR", "--severity-number 17", "--body 'spam error'")
    gen("logs", name, "--logs 20", "--service d", "--body 'spam traced'",
        "--trace-id 5b8efff798038103d269b633813fc60c", "--span-id eee19b7ec3c1b174")
    settle(15)
    recs = [r for r in log_records(logs_of(name)) if r["svc"] == "d"]
    info = [r for r in recs if r["body"] == "spam info"]
    err = [r for r in recs if r["body"] == "spam error"]
    traced = [r for r in recs if r["body"] == "spam traced"]
    check("60 identical INFO logs collapse to one record", len(info) == 1, len(info))
    check("...carrying dedup_count 60", bool(info) and re.search(r"dedup_count: Int\(60\)", info[0]["text"]) is not None,
          info[0]["text"][:200] if info else "none")
    check("ERROR logs are NOT deduplicated (20 stay 20)", len(err) == 20, len(err))
    check("logs with a trace id are NOT deduplicated (20 stay 20)", len(traced) == 20, len(traced))


def test_transform():
    print("\n== transform-ottl")
    name = f"pt-transform-{os.getpid()}"
    start_collector(name, make_config("transform-ottl", "transform"))
    for svc, path in [("p-healthz", "/healthz"), ("p-health-db", "/health/db"), ("p-ready-q", "/ready?x=1"),
                      ("p-healthcare", "/healthcare/records"), ("p-readymade", "/ready-made"), ("p-api", "/api/orders")]:
        gen("traces", name, "--traces 2", f"--service {svc}", f"--telemetry-attributes 'url.path=\"{path}\"'",
            "--telemetry-attributes 'http.route=\"/users/123/orders/456\"'")
    gen("logs", name, "--logs 1", "--service t-logs", "--body '{\"level\":\"debug\",\"msg\":\"noisy\"}'")
    gen("logs", name, "--logs 1", "--service t-logs", "--body '{\"level\":\"error\",\"msg\":\"boom\"}'")
    gen("logs", name, "--logs 1", "--service t-logs", "--body '{\"user\":\"bob\",\"action\":\"login\"}'")
    settle()
    text = logs_of(name)
    spans = span_names_by_service(text)
    for svc in ("p-healthz", "p-health-db", "p-ready-q"):
        check(f"probe path dropped ({svc})", svc not in spans, spans.get(svc))
    for svc in ("p-healthcare", "p-readymade", "p-api"):
        check(f"non-probe path kept ({svc})", len(spans.get(svc, [])) > 0, "dropped")
    check("route normalized to /users/{id}/orders/{id}", "/users/{id}/orders/{id}" in text and "/users/123/orders/456" not in text)
    check("deployment.environment.name added", "deployment.environment.name: Str(demo)" in text)
    recs = [r for r in log_records(text) if r["svc"] == "t-logs"]
    bodies = " ".join(r["body"] for r in recs)
    check("JSON log with level=debug is dropped", "noisy" not in bodies and "noisy" not in " ".join(r["text"] for r in recs))
    err = [r for r in recs if "boom" in r["text"]]
    check("JSON log with level=error is kept", len(err) == 1, len(recs))
    flat = [r for r in recs if "login" in r["text"]]
    check("JSON body is flattened to attributes", bool(flat) and "user: Str(bob)" in flat[0]["text"], flat[0]["text"][:200] if flat else "missing")


def test_pii():
    print("\n== pii-redaction")
    name = f"pt-pii-{os.getpid()}"
    start_collector(name, make_config("pii-redaction", "pii"))
    secrets = {
        "visa grouped": "4111 1111 1111 1111", "visa contiguous": "4111111111111111", "mastercard 2-series": "2221000000000009",
        "amex grouped": "3782 822463 10005", "amex contiguous": "378282246310005", "email": "jane.doe+x@example.com",
        "bearer token": "Bearer abcdef0123456789abcdef", "api_key in url": "https://x.io/p?api_key=SECRETVALUE1&a=1",
        "signature in url": "https://x.io/p?X-Amz-Signature=deadbeef99&b=2",
    }
    keep = {"epoch ns": "1794270417960000000", "18-digit id": "123456789012345678", "prose": "the bearer of bad news arrived", "plain url": "https://x.io/p?page=2&sort=asc"}
    body = " | ".join(f"{k}={v}" for k, v in {**secrets, **keep}.items())
    gen("logs", name, "--logs 1", "--service pii", f"--body '{body}'")
    attrs = " ".join(f"--telemetry-attributes 'k{i}=\"{v}\"'" for i, v in enumerate(list(secrets.values()) + list(keep.values())))
    gen("metrics", name, "--metrics 1", "--service pii", attrs)
    settle()
    text = logs_of(name)
    for label, value in secrets.items():
        probe = value.split("=")[-1].split("&")[0] if "=" in value else value
        check(f"masked: {label}", probe not in text, f"'{probe}' still visible")
    for label, value in keep.items():
        check(f"not masked: {label}", value in text, "was masked")
    check("metric attributes are redacted too", "k0: Str(****)" in text or "****" in re.sub(r".*ResourceMetrics", "", text, flags=re.S))


def test_connectors_metrics():
    print("\n== connectors-metrics")
    name = f"pt-connm-{os.getpid()}"
    start_collector(name, make_config("connectors-metrics", "connm"))
    gen("traces", name, "--traces 5", "--service cm-a", "--status-code Ok")
    gen("traces", name, "--traces 3", "--service cm-a", "--status-code Error")
    gen("traces", name, "--traces 4", "--service cm-b", "--status-code Ok")
    time.sleep(22)                                           # connectors flush every 15 s
    text = logs_of(name)
    mblocks = blocks(text, "ResourceMetrics")
    dur = [b for b in mblocks if "tinyolly.span.duration" in b]
    check("signaltometrics: duration histogram per service (service.name on the series)",
          {service_of(b) for b in dur} >= {"cm-a", "cm-b"}, {service_of(b) for b in dur})
    err = [b for b in mblocks if "tinyolly.span.error.count" in b and service_of(b) is not None or "tinyolly.span.error.count" in b]
    err_text = " ".join(err)
    check("count: error-count metric exists", "tinyolly.span.error.count" in text)
    m = re.findall(r"tinyolly\.span\.error\.count.*?(?:service\.name: Str\((cm-a|cm-b)\).*?)?Value: (\d+)", err_text, re.S)
    check("count: error counter reports the 3 error spans of cm-a", any(v == "3" for _, v in m) or "Value: 3" in err_text, m[:4])
    check("servicegraph/spanmetrics still emit RED metrics", "traces.span.metrics.calls" in text or "calls_total" in text)


def test_routing_failover():
    print("\n== connectors-routing (routing + failover)")
    recv = f"pt-sink-{os.getpid()}"                          # stands in for TinyOlly's receiver (alias below)
    sink_cfg = os.path.join(WORK, "sink.yaml")
    open(sink_cfg, "w").write(
        "receivers:\n  otlp:\n    protocols:\n      grpc:\n        endpoint: 0.0.0.0:4343\n"
        "exporters:\n  debug:\n    verbosity: detailed\n"
        "service:\n  pipelines:\n    traces:\n      receivers: [otlp]\n      exporters: [debug]\n")
    start_collector(recv, sink_cfg, alias="tinyolly-otlp-receiver")   # the hostname the preset's otlp exporters use
    name = f"pt-routing-{os.getpid()}"
    start_collector(name, make_config("connectors-routing", "routing", drop_otlp=False, keep=("otlp",)))
    backup = os.path.join(WORK, "failover-traces.jsonl")

    gen("traces", name, "--traces 4", "--service r-ok", "--status-code Ok")
    gen("traces", name, "--traces 2", "--service r-err", "--status-code Error")
    settle(10)
    got = span_names_by_service(logs_of(recv))
    check("healthy primary: OK and error spans all reach TinyOlly's receiver", len(got.get("r-ok", [])) == 8 and len(got.get("r-err", [])) == 4, {k: len(v) for k, v in got.items()})
    text = logs_of(recv)
    err_block = [b for b in blocks(text, "ResourceSpans") if service_of(b) == "r-err"]
    check("error spans are tagged collector.route=errors", bool(err_block) and all("collector.route: Str(errors)" in b for b in err_block))
    ok_block = [b for b in blocks(text, "ResourceSpans") if service_of(b) == "r-ok"]
    check("OK spans are not tagged", bool(ok_block) and all("collector.route" not in b for b in ok_block))
    check("healthy primary: nothing is written to the backup file", not os.path.exists(backup) or os.path.getsize(backup) == 0)

    sh(f"docker stop {recv}")                                # primary goes down
    gen("traces", name, "--traces 3", "--service r-down", "--status-code Ok")
    settle(10)
    size = os.path.getsize(backup) if os.path.exists(backup) else 0
    check("primary down: spans fail over to the backup file instead of being lost", size > 0 and b"r-down" in open(backup, "rb").read(), f"size={size}")


TESTS = {
    "sampling": test_sampling, "logs-dedup": test_logs_dedup, "transform-ottl": test_transform, "pii-redaction": test_pii,
    "connectors-metrics": test_connectors_metrics, "connectors-routing": test_routing_failover,
}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(TESTS)
    unknown = [w for w in wanted if w not in TESTS]
    if unknown:
        sys.exit(f"unknown preset(s): {unknown}; choose from {list(TESTS)}")
    try:
        sh(f"docker network create {NET}", check=True)
        for w in wanted:
            try:
                TESTS[w]()
            except Exception as e:  # a crashed scenario is a failure, not a skipped test
                check(f"{w}: scenario ran", False, repr(e)[:300])
    finally:
        for c in containers:
            sh(f"docker rm -f {c}")
        sh(f"docker network rm {NET}")
        shutil.rmtree(WORK, ignore_errors=True)
    print(f"\n{len(failures)} failure(s)" if failures else "\nall preset behaviour checks passed")
    sys.exit(1 if failures else 0)
