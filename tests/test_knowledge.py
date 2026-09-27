import pytest

from ultron.knowledge import Knowledge, extract_urls
from ultron.tools import run_tool


@pytest.fixture
def kb(tmp_path):
    return Knowledge(tmp_path / "knowledge.json")


def test_learn_and_recall_persists(tmp_path):
    path = tmp_path / "knowledge.json"
    kb = Knowledge(path)
    kb.learn("Quantum mechanics", "Wavefunctions and the Schrödinger equation.", ["https://en.wikipedia.org/wiki/Quantum_mechanics"])
    reloaded = Knowledge(path)
    entry = reloaded.get("quantum mechanics")
    assert entry["topic"] == "Quantum mechanics"
    assert "Schrödinger" in entry["notes"]
    assert entry["sources"] == ["https://en.wikipedia.org/wiki/Quantum_mechanics"]


def test_relearning_appends_rather_than_overwrites(kb):
    kb.learn("Physics", "Newton's laws.")
    kb.learn("Physics", "Thermodynamics.")
    notes = kb.get("physics")["notes"]
    assert "Newton's laws." in notes and "Thermodynamics." in notes


def test_relearning_same_notes_does_not_duplicate(kb):
    kb.learn("Physics", "Newton's laws.")
    kb.learn("Physics", "Newton's laws.")
    assert kb.get("physics")["notes"].count("Newton's laws.") == 1


def test_get_matches_by_keyword_overlap(kb):
    kb.learn("Organic chemistry", "Carbon compounds.")
    assert kb.get("chemistry")["topic"] == "Organic chemistry"
    assert kb.get("astrophysics") is None


def test_topics_and_forget(kb):
    kb.learn("Math", "Algebra.")
    kb.learn("History", "Rome.")
    assert set(kb.topics()) == {"Math", "History"}
    assert kb.forget("math") is True
    assert kb.topics() == ["History"]
    assert kb.forget("nothing") is False


def test_extract_urls():
    text = "See https://example.com/a and https://example.com/a and http://foo.org/b)."
    assert extract_urls(text) == ["https://example.com/a", "http://foo.org/b"]


def test_run_tool_knowledge_dispatch(kb):
    assert run_tool("save_knowledge", {"topic": "Tor", "notes": "Onion routing."}, knowledge=kb).startswith("Learned")
    assert "Onion routing." in run_tool("recall_knowledge", {"topic": "tor"}, knowledge=kb)
    assert "- Tor" in run_tool("list_knowledge", {}, knowledge=kb)
    assert "not studied" in run_tool("recall_knowledge", {"topic": "biology"}, knowledge=kb)


def test_run_tool_knowledge_disabled():
    assert run_tool("list_knowledge", {}, knowledge=None) == "Knowledge storage is disabled."
