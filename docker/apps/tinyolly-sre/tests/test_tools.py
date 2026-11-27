from sre.backend import Backend


def test_docs_and_playbooks_are_never_offered_to_the_model():
    offered = [{"name": n} for n in ("get_trace", "read_doc", "search_docs", "list_docs", "list_skills", "get_skill")]
    assert [t["name"] for t in Backend().usable(offered)] == ["get_trace"]
