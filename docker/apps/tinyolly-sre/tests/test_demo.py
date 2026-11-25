import json, os, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import httpx, pytest
from sre import core, demo

FLAGS = {"flags": {"paymentFailure": {"variants": {"off": False, "50%": 0.5}, "defaultVariant": "off"},
                   "adFailure": {"variants": {"off": False, "on": True}, "defaultVariant": "on"},
                   "noOff": {"variants": {"a": 1, "b": 2}, "defaultVariant": "a"}}}
SC = [{"id": "pay", "title": "Pay", "flags": {"paymentFailure": "50%"}, "duration_s": [0.3, 0.3], "cooldown_s": 0, "weight": 1},
      {"id": "ad", "title": "Ad", "flags": {"adFailure": "on"}, "duration_s": [0.3, 0.3], "cooldown_s": 0, "weight": 1},
      {"id": "quiet", "title": "Quiet", "flags": {}, "duration_s": [0.2, 0.2], "cooldown_s": 0, "weight": 0}]


@pytest.fixture
def flags(tmp_path):
    p = tmp_path / "demo.flagd.json"; p.write_text(json.dumps(FLAGS)); return demo.FileFlags(str(p))


def shift(flags, marks=None, **k):
    return demo.Shift(flags, SC, announce=(lambda t, a: marks.append(t)) if marks is not None else None, seed=1, script=k.pop("script", []), gap_s=[0.1, 0.1], first_gap_s=0, **k)


def test_file_flags_set_validate_reset_keep_inode(flags):
    ino = os.stat(flags.path).st_ino
    assert flags.set("paymentFailure", "50%") == {"paymentFailure": ("off", "50%")}
    assert flags.set("paymentFailure", "50%") == {}                      # no-op, no marker
    with pytest.raises(ValueError): flags.set("paymentFailure", "99%")
    with pytest.raises(ValueError): flags.set("nope", "on")
    flags.reset()
    assert flags.get_all() == {"paymentFailure": "off", "adFailure": "off", "noOff": "a"}
    assert os.stat(flags.path).st_ino == ino


def test_pick_never_repeats_and_inserts_quiet_control(flags):
    s = shift(flags, quiet_every=2)
    seen = []
    for _ in range(12):
        x = s.pick(); seen.append(x["id"]); s.last_id = x["id"]
        if x["id"] != "quiet": s.n_faults += 1
    assert all(a != b for a, b in zip(seen, seen[1:]))
    assert "quiet" in seen and seen.count("quiet") >= 3


def test_unknown_script_entry_is_rejected(flags):
    with pytest.raises(ValueError): shift(flags, script=["pay", "bogus"])


def test_scripted_shift_runs_in_order_announces_and_resets(flags):
    marks = []; s = shift(flags, marks, script=["pay", "ad"])
    s.start(); s.thread.join(5)
    assert [h["id"] for h in s.history] == ["pay", "ad"] and s.state == "stopped"
    # start resets adFailure (on -> off); each scenario flips on, then off
    assert marks == ["flag adFailure: on -> off", "flag paymentFailure: off -> 50%", "flag paymentFailure: 50% -> off",
                     "flag adFailure: off -> on", "flag adFailure: on -> off"]
    assert flags.get_all()["paymentFailure"] == "off" and flags.get_all()["adFailure"] == "off"


def test_announce_off_publishes_nothing(flags, monkeypatch):
    monkeypatch.setenv("DEMO_ANNOUNCE", "0")
    s = demo.Shift(flags, SC, announce=lambda *a: pytest.fail("announced"), seed=1, script=["pay"], gap_s=[0.1, 0.1], first_gap_s=0)
    s.start(); s.thread.join(5)
    assert s.history[0]["announced"] is False


def test_trigger_when_stopped_runs_once_and_stop_mid_fault_resets(flags):
    s = shift(flags)
    s.trigger("pay"); s.thread.join(5)
    assert [h["id"] for h in s.history] == ["pay"] and s.state == "stopped"
    long = shift(flags); long.by_id["pay"] = {**SC[0], "duration_s": [30, 30]}
    long.trigger("pay"); time.sleep(0.3)
    assert flags.get_all()["paymentFailure"] == "50%" and long.status()["phase"] == "fault"
    long.stop()
    assert flags.get_all()["paymentFailure"] == "off" and long.state == "stopped"
    with pytest.raises(KeyError): long.trigger("bogus")


def test_room_status_hides_the_injected_fault(flags):
    s = shift(flags)
    assert "current" not in s.status(presenter=False) and "history" in s.status()


def test_demo_http_controls(flags):
    from http.server import ThreadingHTTPServer
    from tests.test_core import agent
    a = agent(); a.shift = shift(flags)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), core.make_handler(a))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_port}"
        assert httpx.post(base + "/demo/trigger", json={"id": "bogus"}).status_code == 400
        assert httpx.post(base + "/demo/trigger", json={"id": "pay"}).json()["state"] == "running"
        assert httpx.get(base + "/api/investigations").json()["status"]["demo"]["state"] == "running"
        assert httpx.post(base + "/demo/stop").json()["state"] == "stopped"
        assert flags.get_all()["paymentFailure"] == "off"
        a.shift = None
        assert httpx.post(base + "/demo/start").status_code == 404
    finally: srv.shutdown()


def test_flagd_ui_backend_reads_and_writes_the_file(monkeypatch):
    import copy
    store = copy.deepcopy(FLAGS); posted = []
    class R:
        def __init__(self, j=None): self.j = j
        def raise_for_status(self): pass
        def json(self): return copy.deepcopy(self.j)
    f = demo.FlagdUiFlags("http://flagd:4000/")
    monkeypatch.setattr(f.c, "get", lambda url: R(store) if url == "http://flagd:4000/api/read-file" else pytest.fail(url))
    def post(url, json):
        assert url == "http://flagd:4000/api/write-to-file"; posted.append(json); store.clear(); store.update(json["data"]); return R()
    monkeypatch.setattr(f.c, "post", post)
    assert f.set("paymentFailure", "50%") == {"paymentFailure": ("off", "50%")}
    assert posted[0]["data"]["flags"]["paymentFailure"]["defaultVariant"] == "50%"
    f.reset(); assert f.get_all()["adFailure"] == "off"


def test_quick_profile_uses_quick_blocks_and_fences_after_each_fault(flags, monkeypatch):
    monkeypatch.setenv("DEMO_PROFILE", "quick")
    sc = [{**SC[0], "duration_s": [30, 30], "quick": {"flags": {"paymentFailure": "50%"}, "duration_s": [0.2, 0.2], "cooldown_s": 0}}, SC[2]]
    s = demo.Shift(flags, sc, seed=1, script=["pay"], first_gap_s=0, gap_s=[0.05, 0.05]); fences = []
    s.on_fault_end = fences.append
    assert s.gap_s == [0.05, 0.05] and s.by_id["pay"]["duration_s"] == [0.2, 0.2]
    s.start(); s.thread.join(5)
    assert s.history[0]["ended"] - s.history[0]["started"] < 1 and len(fences) == 1
    assert demo.Shift(flags, demo.load_scenarios()).by_id["payment-degraded"]["flags"] == {"paymentFailure": "90%"}
