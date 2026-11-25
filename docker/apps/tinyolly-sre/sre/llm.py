"""Model presets for the agent. Default: the local Ollama model (built and tested with qwen3.8 27B on a local GPU box).
Optional: OpenAI, or Claude through the Anthropic SDK. A preset is offered only when its endpoint/key is configured.

Every transport returns the same shape the agent loop uses: (message {content, tool_calls[, _raw]}, finish_reason, usage)."""
from __future__ import annotations
import json, os, threading
import httpx

E = os.getenv
MAX_TOKENS = int(E("MAX_TOKENS", "2500"))


def presets() -> dict[str, dict]:
    p = {"local": {"kind": "openai", "url": E("LLM_URL", "http://host.docker.internal:11434/v1").rstrip("/"), "key": E("LLM_API_KEY", ""),
                   "model": E("MODEL", "qwen3.8:27b-mtp-q4_K_M"), "label": "Local (Ollama)"}}
    if E("OPENAI_API_KEY"):
        p["openai"] = {"kind": "openai", "url": E("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"), "key": E("OPENAI_API_KEY"),
                       "model": E("OPENAI_MODEL", "gpt-5"), "label": "OpenAI"}
    if E("ANTHROPIC_API_KEY"):
        p["claude"] = {"kind": "anthropic", "url": "", "key": E("ANTHROPIC_API_KEY"), "model": E("ANTHROPIC_MODEL", "claude-opus-5-5"), "label": "Claude (Anthropic)"}
    return p


class Models:
    def __init__(self):
        self.p = presets(); self.lock = threading.Lock()
        want = E("LLM_PRESET", "local")
        self.name = want if want in self.p else "local"
        self.reach: dict[str, str] = {}                       # preset -> "ok" | error text, from check()

    @property
    def cur(self) -> dict: return self.p[self.name]
    @property
    def model(self) -> str: return self.cur["model"]

    def use(self, name: str):
        if name not in self.p: raise KeyError(name)
        with self.lock: self.name = name
        threading.Thread(target=self.check, args=(name,), daemon=True).start()

    def listing(self) -> dict:
        return {"current": self.name, "presets": [{"name": n, "label": v["label"], "model": v["model"], "reachable": self.reach.get(n, "unknown")}
                                                  for n, v in self.p.items()]}

    def check(self, name: str | None = None) -> str:
        """Cheap reachability probe (lists models; no tokens spent)."""
        name = name or self.name; c = self.p[name]
        try:
            if c["kind"] == "anthropic":
                import anthropic
                anthropic.Anthropic(api_key=c["key"], timeout=8, max_retries=0).models.retrieve(c["model"])
            else:
                r = httpx.get(f"{c['url']}/models", timeout=5, headers={"Authorization": f"Bearer {c['key']}"} if c["key"] else {})
                r.raise_for_status()
                ids = {m.get("id") for m in r.json().get("data", [])}
                if ids and c["model"] not in ids: raise RuntimeError(f"model {c['model']} not served there")
            self.reach[name] = "ok"
        except Exception as e:
            self.reach[name] = f"{type(e).__name__}: {str(e)[:120]}"
        return self.reach[name]

    def chat(self, messages, tools=None, timeout=60):
        c = self.cur
        return (_anthropic if c["kind"] == "anthropic" else _openai)(c, messages, tools, timeout)


def _openai(c, messages, tools, timeout):
    body = {"model": c["model"], "messages": [{k: v for k, v in m.items() if k != "_raw"} for m in messages], "max_tokens": MAX_TOKENS,
            **({"tools": tools} if tools else {})}
    r = httpx.post(f"{c['url']}/chat/completions", json=body, timeout=max(timeout, 5), headers={"Authorization": f"Bearer {c['key']}"} if c["key"] else {})
    r.raise_for_status()
    d = r.json(); return d["choices"][0]["message"], d["choices"][0].get("finish_reason"), d.get("usage") or {}


# ---- Claude, through the official Anthropic SDK ----
def to_anthropic(messages, tools):
    """The agent's OpenAI-shaped history -> (system, messages, tools) for the Messages API. Assistant turns that came
    from Claude are replayed from `_raw` unchanged (thinking blocks must come back exactly as they were returned)."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    out: list[dict] = []
    for m in messages:
        if m["role"] == "system": continue
        if m["role"] == "assistant":
            if m.get("_raw"): content = m["_raw"]
            else:
                content = ([{"type": "text", "text": m["content"]}] if m.get("content") else []) + [
                    {"type": "tool_use", "id": t["id"], "name": t["function"]["name"], "input": json.loads(t["function"].get("arguments") or "{}")}
                    for t in m.get("tool_calls") or []]
            out.append({"role": "assistant", "content": content or [{"type": "text", "text": "(no text)"}]})
        elif m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"] or "(empty)"}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) and out[-1]["content"] and out[-1]["content"][0].get("type") == "tool_result":
                out[-1]["content"].append(block)                 # all results of one turn in one user message
            else: out.append({"role": "user", "content": [block]})
        else:
            out.append({"role": "user", "content": m["content"]})
    atools = [{"name": t["function"]["name"], "description": t["function"].get("description", ""), "input_schema": t["function"].get("parameters") or {"type": "object", "properties": {}}}
              for t in tools or []]
    return system, out, atools


def _anthropic(c, messages, tools, timeout):
    import anthropic
    client = anthropic.Anthropic(api_key=c["key"], timeout=max(timeout, 10), max_retries=1)
    system, msgs, atools = to_anthropic(messages, tools)
    try:
        r = client.beta.messages.create(model=c["model"], max_tokens=max(MAX_TOKENS, 16000), system=system, messages=msgs,
                                        output_config={"effort": E("ANTHROPIC_EFFORT", "medium")},
                                        betas=["server-side-fallback-2026-07-01"], fallbacks="default",   # a declined request is re-run on a fallback model
                                        **({"tools": atools} if atools else {}))
    except anthropic.RateLimitError as e: raise RuntimeError(f"Claude rate limited: {e.message}") from e
    except anthropic.APIStatusError as e: raise RuntimeError(f"Claude API {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e: raise RuntimeError("Claude API unreachable") from e
    raw = [b.to_dict() for b in r.content]
    text = "".join(b.text for b in r.content if b.type == "text")
    calls = [{"id": b.id, "type": "function", "function": {"name": b.name, "arguments": json.dumps(b.input)}} for b in r.content if b.type == "tool_use"]
    if r.stop_reason == "refusal" and not text: text = "[the model declined this request]"
    msg = {"role": "assistant", "content": text, "tool_calls": calls, "_raw": raw}
    return msg, r.stop_reason, {"prompt_tokens": r.usage.input_tokens, "completion_tokens": r.usage.output_tokens}
