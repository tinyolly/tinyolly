#!/usr/bin/env python3
"""Fault-injection eval for TinyOlly's MCP tools: inject a known fault, ask an agent to investigate through MCP,
grade the answer against ground truth.

  scripts/agent_eval/eval.py --target docker                 # seeded Istio metrics on the Compose stack (scripts/docker-alt.sh)
  scripts/agent_eval/eval.py --target kind --scenarios flaky # real faults on the kind demo (istio-ambient-demo repo)
  scripts/agent_eval/eval.py --model qwen3.8:27b-mtp-q4_K_M --repeat 3 --no-skill-hint

The agent is a local Ollama model driving the MCP server's tools (the loop is in agent.py). Env: LOCAL_BASE (Ollama).
Writes eval-results.json next to the working directory and prints a table; always exits 0 unless --min-pass is given.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import agent  # noqa: E402
import grader  # noqa: E402
from mcp_client import MCPClient  # noqa: E402
from scenarios import QUESTION, SCENARIOS  # noqa: E402

SYSTEM = ("You are an SRE investigating an Istio ambient service mesh with TinyOlly's MCP tools. Gather evidence with the "
          "tools before you answer (check what changed recently and the mesh posture first), then answer in 3 to 5 sentences: "
          "the affected service, the evidence with numbers, and the likely cause. Stop and answer as soon as the evidence names a "
          "cause; do not keep exploring. If nothing is wrong, say the mesh looks healthy.")
SKILL_HINT = " A playbook is available: call get_skill('tinyolly-mesh-investigation') first and follow it."
TARGETS = {"docker": {"ui": "http://localhost:5105", "otlp": "http://localhost:4418", "mcp": "http://localhost:8865/mcp"},
           "kind": {"ui": "http://localhost:5005", "otlp": None, "mcp": "http://localhost:8765/mcp"}}


def ollama_chat(model, base):
    def chat(messages, tools):
        body = {"model": model, "messages": messages, "tools": tools, "stream": False, "think": False,
                "options": {"num_ctx": 32768, "temperature": 0.2}}
        req = urllib.request.Request(base.rstrip("/") + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            reply = json.load(resp)
        chat.tokens += reply.get("prompt_eval_count", 0) + reply.get("eval_count", 0)
        return reply
    chat.tokens = 0
    return chat


def inject_docker(name, urls):
    seed = HERE.parent / "seed_mesh.py"
    urllib.request.urlopen(urllib.request.Request(urls["ui"] + "/admin/reset", method="POST"), timeout=30).read()
    steps = SCENARIOS[name]["seed"]
    for i, scenario in enumerate(steps):
        duration = "60" if len(steps) == 1 else ("30" if i == 0 else "45")
        cmd = [sys.executable, str(seed), "--otlp", urls["otlp"], "--scenario", scenario, "--interval", "3", "--duration", duration]
        if i > 0:
            cmd += ["--ui", urls["ui"]]
        subprocess.run(cmd, check=True, capture_output=True)


def inject_kind(name, demo_dir):
    script = str(demo_dir / "03-scenario.sh")
    env = dict(os.environ, DOCKER_CONTEXT=os.environ.get("DOCKER_CONTEXT", "colima-tinyolly"))

    def run(*args):
        subprocess.run([script, *args], check=True, capture_output=True, env=env, timeout=600)
    run("fresh")
    time.sleep(60)                                # a baseline to compare against
    for step in SCENARIOS[name]["kind"]:
        run(*step)
        time.sleep(75)


def cleanup_kind(demo_dir):
    subprocess.run([str(demo_dir / "03-scenario.sh"), "reset"], capture_output=True, timeout=600,
                   env=dict(os.environ, DOCKER_CONTEXT=os.environ.get("DOCKER_CONTEXT", "colima-tinyolly")))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target", choices=sorted(TARGETS), default="docker")
    ap.add_argument("--scenarios", default=",".join(SCENARIOS), help="comma-separated: " + ", ".join(SCENARIOS))
    ap.add_argument("--model", default=os.environ.get("LOCAL_MODEL", "qwen3.8:27b-mtp-q4_K_M"))
    ap.add_argument("--base", default=os.environ.get("LOCAL_BASE", "http://192.168.68.71:11434"))
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--max-steps", type=int, default=10)
    ap.add_argument("--no-skill-hint", action="store_true", help="do not tell the agent a playbook skill exists")
    ap.add_argument("--demo-dir", default=str(HERE.parents[2] / "istio-ambient-demo"), help="kind target: the demo repo")
    ap.add_argument("--out", default="eval-results.json")
    ap.add_argument("--min-pass", type=float, help="exit 1 if the pass rate is below this (0-1)")
    args = ap.parse_args()

    urls = TARGETS[args.target]
    names = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        sys.exit(f"unknown scenarios: {unknown}")
    demo_dir = pathlib.Path(args.demo_dir)
    results = []
    for name in names:
        for run_no in range(1, args.repeat + 1):
            print(f"== {name} (run {run_no}): {SCENARIOS[name]['describe']}", flush=True)
            (inject_docker(name, urls) if args.target == "docker" else inject_kind(name, demo_dir))
            client = MCPClient(urls["mcp"])
            tools = agent.mcp_tools_to_ollama(client.list_tools())
            chat = ollama_chat(args.model, args.base)
            started = time.time()
            out = agent.run_agent(QUESTION, chat, client.call_tool, tools, max_steps=args.max_steps,
                                  system=SYSTEM + ("" if args.no_skill_hint else SKILL_HINT))
            g = grader.grade(out["answer"], out["tool_calls"], SCENARIOS[name]["truth"])
            results.append({"scenario": name, "run": run_no, "target": args.target, "model": args.model, **g,
                            "steps": out["steps"], "truncated": out["truncated"], "tokens": chat.tokens,
                            "seconds": round(time.time() - started, 1), "tools": [c["name"] for c in out["tool_calls"]],
                            "answer": out["answer"]})
            print(f"   {'PASS' if g['passed'] else 'FAIL'} score={g['score']:.2f} steps={out['steps']} tools={len(out['tool_calls'])}", flush=True)
    if args.target == "kind":
        cleanup_kind(demo_dir)
    pathlib.Path(args.out).write_text(json.dumps(results, indent=2))
    print("\nscenario   runs  pass  avg_score  avg_steps  avg_tokens")
    for name in names:
        rs = [r for r in results if r["scenario"] == name]
        print(f"{name:<10} {len(rs):>4} {sum(r['passed'] for r in rs):>5} {sum(r['score'] for r in rs) / len(rs):>10.2f} "
              f"{sum(r['steps'] for r in rs) / len(rs):>10.1f} {sum(r['tokens'] for r in rs) // len(rs):>11}")
    rate = sum(r["passed"] for r in results) / len(results)
    print(f"\npass rate {rate:.0%} ({sum(r['passed'] for r in results)}/{len(results)}); details in {args.out}")
    if args.min_pass is not None and rate < args.min_pass:
        sys.exit(1)


if __name__ == "__main__":
    main()
