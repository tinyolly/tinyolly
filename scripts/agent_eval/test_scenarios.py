"""Every scenario's ground truth is gradeable, and its own ideal answer passes while a vague one fails."""
import importlib.util
import pathlib

HERE = pathlib.Path(__file__).parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scenarios, grader = load("scenarios"), load("grader")

IDEAL = {
    "baseline": ("The mesh looks healthy: all edges are mTLS with no errors.", []),
    "flaky": ("productcatalogservice: the frontend edge shows 50% UC, the upstream closed the connection.", ["get_edge"]),
    "fault": ("currencyservice has an injected delay (flag DI) adding about 2 s.", ["what_changed"]),
    "canary": ("Traffic to productcatalogservice is split to a slow v2 canary.", ["get_version_split"]),
    "deny": ("The outsider workload is refused: STRICT mTLS denies its plaintext connections (DENY).", ["find_denied"]),
}


def test_each_scenario_has_ideal_answer_that_passes_and_vague_one_that_fails():
    assert set(IDEAL) == set(scenarios.SCENARIOS)
    for name, sc in scenarios.SCENARIOS.items():
        text, tools = IDEAL[name]
        assert grader.grade(text, [{"name": t, "args": {}} for t in tools], sc["truth"])["passed"], name
        assert not grader.grade("Something might be off, hard to say.", [], sc["truth"])["passed"], name


def test_scenarios_name_both_injection_paths():
    for name, sc in scenarios.SCENARIOS.items():
        assert sc["seed"] and isinstance(sc["kind"], list), name
