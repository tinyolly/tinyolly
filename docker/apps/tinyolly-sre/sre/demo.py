"""Demo shift driver (opt-in): runs fault scenarios on a timer so problems come and go while the agent is on shift.

Scenarios are data (scenarios.json). Flags change through a FlagBackend (the flagd JSON file on Docker, or the flagd-ui API on k8s).
The agent is never told what was injected: each flip is published as an ordinary change marker (unless DEMO_ANNOUNCE=0),
exactly as a real flag change would be. Every flag is reset on start, stop and exit, so the shop is never left broken."""
from __future__ import annotations
import json, logging, os, random, threading, time
import httpx

E = os.getenv
log = logging.getLogger("sre")
HERE = os.path.dirname(__file__)


# ---- flag backends ----
class FlagBackend:
    name = "base"
    def _load(self) -> dict: raise NotImplementedError
    def _save(self, d: dict) -> None: raise NotImplementedError
    def get_all(self) -> dict[str, str]:
        return {k: v.get("defaultVariant", "off") for k, v in self._load()["flags"].items()}
    def set_many(self, changes: dict[str, str]) -> dict[str, tuple[str, str]]:
        """Apply {flag: variant} in one write. Returns {flag: (old, new)} for flags that really changed."""
        d = self._load(); flags = d["flags"]; done = {}
        for flag, variant in changes.items():
            if flag not in flags: raise ValueError(f"unknown flag {flag}")
            if variant not in flags[flag].get("variants", {}): raise ValueError(f"{flag}: no variant {variant}")
            old = flags[flag].get("defaultVariant", "off")
            if old != variant: flags[flag]["defaultVariant"] = variant; done[flag] = (old, variant)
        if done: self._save(d)
        return done
    def set(self, flag: str, variant: str): return self.set_many({flag: variant})
    def reset(self):
        """Every flag that has an `off` variant goes to `off`."""
        d = self._load()
        return self.set_many({k: "off" for k, v in d["flags"].items() if "off" in v.get("variants", {})})


class FileFlags(FlagBackend):
    """The flagd JSON file. Written in place (same inode) so flagd's file watch, and a single-file bind mount, see the change."""
    name = "file"
    def __init__(self, path): self.path = path
    def _load(self):
        with open(self.path) as fh: return json.load(fh)
    def _save(self, d):
        with open(self.path, "r+") as fh: fh.seek(0); json.dump(d, fh, indent=2); fh.write("\n"); fh.truncate()


class FlagdUiFlags(FlagBackend):
    """The OTel demo's flagd-ui sidecar (k8s Helm chart): it reads and writes the flag file flagd serves, and flagd reloads it at once.
    (The chart copies the flagd-config ConfigMap into an emptyDir at pod start, so patching the ConfigMap does not reach flagd.)"""
    name = "flagd-ui"
    def __init__(self, url=None):
        self.url = (url or E("DEMO_FLAGD_UI_URL", "http://flagd:4000")).rstrip("/"); self.c = httpx.Client(timeout=10)
    def _load(self):
        r = self.c.get(f"{self.url}/api/read-file"); r.raise_for_status(); return r.json()
    def _save(self, d):
        self.c.post(f"{self.url}/api/write-to-file", json={"data": d}).raise_for_status()


def flag_backend() -> FlagBackend | None:
    kind = E("DEMO_FLAGS", "")
    path = E("DEMO_FLAG_FILE", "/flags/demo.flagd.json")
    if kind in ("flagd-ui", "k8s"): return FlagdUiFlags()
    if kind == "file" or (not kind and os.path.exists(path)): return FileFlags(path)
    return None


def load_scenarios(path=None) -> list[dict]:
    with open(path or E("DEMO_SCENARIOS", os.path.join(HERE, "scenarios.json"))) as fh: return json.load(fh)["scenarios"]


# ---- the shift ----
class Shift:
    """stopped -> running (gap -> fault -> cooldown -> gap ...) <-> paused. One scenario at a time.
    `announce(title, attrs)` publishes a change marker; `clock`/`sleep` are injectable for tests."""
    def __init__(self, flags: FlagBackend, scenarios: list[dict], announce=None, seed=None, script=None, speed=None,
                 quiet_every=None, gap_s=None, first_gap_s=None, clock=time.time):
        self.flags, self.announce, self.clock = flags, announce if E("DEMO_ANNOUNCE", "1") == "1" else None, clock
        self.by_id = {s["id"]: s for s in scenarios}
        seed = seed if seed is not None else E("DEMO_SEED")
        self.rng = random.Random(int(seed) if seed not in (None, "") else None)
        script = script if script is not None else [x.strip() for x in E("DEMO_SCRIPT", "").split(",") if x.strip()]
        if script == ["all"]: script = [x["id"] for x in scenarios]          # capture runs: every scenario once, in file order
        bad = [x for x in script if x not in self.by_id]
        if bad: raise ValueError(f"DEMO_SCRIPT: unknown scenario(s) {bad}; known: {sorted(self.by_id)}")
        self.script, self.scripted = list(script), bool(script)
        self.speed = max(1.0, float(speed or E("DEMO_SPEED", "1")))
        self.quiet_every = int(quiet_every if quiet_every is not None else E("DEMO_QUIET_EVERY", "4"))
        self.profile = E("DEMO_PROFILE", "realistic")            # quick: stronger variants, short faults/cooldowns (scenario "quick" blocks)
        if self.profile == "quick":
            self.by_id = {k: {**v, **(v.get("quick") or {})} for k, v in self.by_id.items()}
        self.gap_s = gap_s or [int(x) for x in E("DEMO_GAP_SECONDS", "20,30" if self.profile == "quick" else "60,120").split(",")]
        self.first_gap_s = float(first_gap_s if first_gap_s is not None else E("DEMO_FIRST_GAP_SECONDS", "240"))   # the agent's baseline needs ~4 min
        self.state, self.phase, self.current, self.next_at, self.phase_end = "stopped", "", None, None, None
        self.history: list[dict] = []; self.n_faults = 0; self.last_id = ""
        self.forced: str | None = None
        self.on_end = None                                     # called after every shift (writes the shift report)
        self.on_fault_end = None                               # called with the time a fault's flags went off (detector cutoff)
        self.lock, self.wake = threading.RLock(), threading.Event()
        self.thread: threading.Thread | None = None
        self.created_at = clock()

    # -- flags --
    def _apply(self, changes: dict[str, str], why: str):
        return self._announce(self.flags.set_many(changes) if changes else {}, why)

    def _announce(self, done, why):
        for flag, (old, new) in done.items():
            log.info("demo: flag %s %s -> %s (%s)", flag, old, new, why)
            if self.announce:
                try: self.announce(f"flag {flag}: {old} -> {new}", {"flag": flag, "from": old, "to": new})
                except Exception as e: log.warning("demo: change marker failed: %s", e)
        return done

    def reset(self, why="reset"):
        """All flags off (markers only for flags that really changed)."""
        with self.lock:
            try: self._announce(self.flags.reset(), why)
            except Exception as e: log.warning("demo: reset failed: %s", e)

    # -- picking --
    def pick(self) -> dict | None:
        """Next scenario: the script in order (then the shift ends), else weighted random, never the same twice in a row,
        with the quiet control every `quiet_every` faults."""
        if self.script: return self.by_id[self.script.pop(0)]
        if self.scripted: return None                       # a scripted shift ends with its script
        if self.quiet_every and "quiet" in self.by_id and self.n_faults and self.n_faults % self.quiet_every == 0 and self.last_id != "quiet":
            return self.by_id["quiet"]
        pool = [s for s in self.by_id.values() if s.get("weight", 1) > 0 and s["id"] != self.last_id]
        return self.rng.choices(pool, weights=[s.get("weight", 1) for s in pool])[0] if pool else None

    # -- the loop --
    def _wait(self, seconds) -> bool:
        """Sleep up to `seconds` (paused time doesn't count). False if the shift stopped or a trigger arrived."""
        end = self.clock() + seconds
        while True:
            with self.lock:
                if self.state == "stopped" or self.forced is not None: return False
                if self.state == "paused": end += 1
            left = end - self.clock()
            if left <= 0: return True
            self.phase_end = end
            self.wake.wait(min(1.0, left)); self.wake.clear()

    def _run_one(self, s: dict) -> bool:
        dur = self.rng.uniform(*s["duration_s"]) / self.speed    # DEMO_SPEED>1 only with the fast detector profile (05-start-sre.sh --fast)
        rec = {"id": s["id"], "title": s["title"], "flags": dict(s["flags"]), "started": self.clock(), "ended": None,
               "expected": s.get("expected", {}), "announced": bool(self.announce)}
        with self.lock: self.current, self.phase = rec, "fault"; self.history.append(rec)
        log.info("demo: scenario %s for %ds", s["id"], dur)
        try: self._apply(s["flags"], f"scenario {s['id']}")
        except Exception as e: log.warning("demo: scenario %s failed to apply: %s", s["id"], e)
        ok = self._wait(dur)
        self._apply({f: "off" for f in s["flags"]}, f"scenario {s['id']} ended")
        if self.on_fault_end and s["flags"] and self.profile == "quick":
            try: self.on_fault_end(self.clock())
            except Exception as e: log.warning("demo: on_fault_end failed: %s", e)
        with self.lock: rec["ended"] = self.clock(); self.current = None; self.last_id = s["id"]
        if s["id"] != "quiet": self.n_faults += 1
        if not ok: return False
        self.phase = "cooldown"
        return self._wait(s.get("cooldown_s", 0) / self.speed)

    def _loop(self, once=False):
        try:
            while True:
                with self.lock:
                    if self.state == "stopped": break
                    forced, self.forced = self.forced, None
                if forced: s = self.by_id[forced]
                else:
                    if once: break
                    self.phase = "gap"; gap = self.rng.uniform(*self.gap_s) / self.speed
                    gap = max(gap, self.first_gap_s - (self.clock() - self.created_at))    # the agent's baseline needs this long after boot
                    self.next_at = self.clock() + gap
                    if not self._wait(gap): continue
                    s = self.pick()
                    if not s: log.info("demo: script finished"); break
                self.next_at = None
                self._run_one(s)
        finally:
            with self.lock:
                self.state, self.phase, self.next_at, self.phase_end = "stopped", "", None, None
            self.reset("shift ended")
            log.info("demo: shift stopped")
            if self.on_end and self.history:
                try: self.on_end()
                except Exception as e: log.warning("demo: on_end failed: %s", e)

    # -- controls --
    def start(self, once=False):
        with self.lock:
            if self.state == "paused": self.state = "running"; self.wake.set(); return self.status()
            if self.thread and self.thread.is_alive(): return self.status()
            self.reset("shift start")
            self.state, self.started_at = "running", self.clock()
            self.thread = threading.Thread(target=self._loop, args=(once,), daemon=True); self.thread.start()
        log.info("demo: shift started (speed %sx, script %s)", self.speed, ",".join(self.script) or "random")
        return self.status()

    def pause(self):
        with self.lock:
            if self.state == "running": self.state = "paused"
        return self.status()

    def stop(self):
        with self.lock:
            alive = self.thread and self.thread.is_alive(); self.state = "stopped"; self.wake.set()
        if alive: self.thread.join(timeout=15)
        else: self.reset("shift stop")
        return self.status()

    def trigger(self, sid: str):
        """Run scenario `sid` now (ends the current one). Starts a one-scenario shift if none is running."""
        if sid not in self.by_id: raise KeyError(sid)
        with self.lock:
            self.forced = sid; self.wake.set()
            running = self.thread and self.thread.is_alive()
        return self.status() if running else self.start(once=True)

    def status(self, presenter=True) -> dict:
        """presenter=False hides what is injected (for the room-facing header)."""
        with self.lock:
            now = self.clock()
            out = {"state": self.state, "phase": self.phase, "next_fault_in_s": int(self.next_at - now) if self.next_at and self.phase == "gap" else None,
                   "phase_left_s": int(self.phase_end - now) if self.phase_end and self.state != "stopped" else None, "faults_run": self.n_faults,
                   "flags_backend": self.flags.name, "announce": bool(self.announce), "speed": self.speed}
            if presenter:
                out.update(current=self.current, script_left=list(self.script), scenarios=sorted(self.by_id), history=self.history[-50:])
            return out
