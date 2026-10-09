"""行业词典与同义词扩展用例：这两层直接决定口语描述的召回率。"""

from app.ai.lexicon import DOMAIN_TERMS, expand_query
from app.ai.retriever import BM25Index, tokenize
from app.ai.synthetic_cases import build_synthetic_case_documents, synthetic_cases


def test_domain_terms_survive_tokenization() -> None:
    """「阀芯」「油位」这类术语不能被切成单字丢掉，否则关键信号直接消失。"""
    tokens = tokenize("阀芯有点卡，油位下降得快")

    assert "阀芯" in tokens
    assert "油位" in tokens


def test_expand_query_adds_canonical_wording() -> None:
    expanded = expand_query("声音不对，有咔咔的响声")

    assert "声音不对" in expanded
    assert "异响" in expanded


def test_expand_query_keeps_original_text_when_nothing_matches() -> None:
    assert expand_query("食堂午餐菜单") == "食堂午餐菜单"
    assert expand_query(None) == ""


def test_domain_terms_are_long_enough_to_survive_tokenizer() -> None:
    # 单字词会被 tokenize 丢弃，词典里不该混进单字
    assert all(len(term) >= 2 for term in DOMAIN_TERMS)


def test_colloquial_valve_query_retrieves_the_mechanical_case() -> None:
    """回归用例：这条口语描述在加词典与同义扩展前是查不到的。"""
    index = BM25Index(build_synthetic_case_documents())

    hits = index.search("下去之后声音不对，咔咔响，阀芯有点卡", top_k=3)
    doc_ids = [hit.document.doc_id for hit in hits]

    assert doc_ids, "应当召回案例"
    assert any(doc_id.endswith("机械故障:012") for doc_id in doc_ids), doc_ids


def test_every_colloquial_query_finds_its_own_case_in_top_5() -> None:
    """整体召回率护栏：单条不要求，多数必须命中，防止检索层退化而测试仍全绿。"""
    index = BM25Index(build_synthetic_case_documents())
    cases = synthetic_cases()

    hit_count = sum(
        1
        for case in cases
        if case.doc_id in [hit.document.doc_id for hit in index.search(case.colloquial, top_k=5)]
    )

    assert hit_count / len(cases) >= 0.9
