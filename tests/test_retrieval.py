from deadman.retrieval import BM25Index, tokenize
from deadman.sources import Passage


def make(pid: str, text: str) -> Passage:
    return Passage(id=pid, source_id="won", title="WoN", year=1776, location="", text=text)


def test_tokenize_normalizes_spelling_and_plurals():
    assert tokenize("The labor of the colonies") == tokenize("the labour of the colony")
    assert "the" not in tokenize("the market")


def test_search_ranks_relevant_passage_first():
    index = BM25Index([
        make("a", "The division of labour in a pin manufactory increases the quantity of work."),
        make("b", "The exclusive privileges of corporations and the monopoly of the colony trade."),
        make("c", "Sympathy with the sorrows of others and the impartial spectator."),
    ])
    results = index.search("monopoly exclusive privilege", k=2)
    assert results[0][0].id == "b"
    assert all(r[0].id != "c" for r in results)


def test_search_with_no_matching_terms_returns_nothing():
    index = BM25Index([make("a", "The division of labour.")])
    assert index.search("spaceship") == []
