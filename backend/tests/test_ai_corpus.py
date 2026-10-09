"""语料用例：仿真案例展开，以及故障记录入库后的语料提取规则。"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.ai.corpus import build_corpus, build_fault_case_documents
from app.ai.document import SOURCE_FAULT_RECORD, SOURCE_SYNTHETIC
from app.ai.retriever import BM25Index
from app.ai.synthetic_cases import (
    BLUEPRINTS,
    INSTRUMENT_TYPES,
    build_synthetic_case_documents,
    synthetic_cases,
)

EQUIPMENT = "/api/v1/equipment"
FAULTS = "/api/v1/fault-records"


def test_synthetic_cases_cover_every_fault_type_and_instrument_type() -> None:
    cases = synthetic_cases()

    assert len(cases) == sum(len(items) for items in BLUEPRINTS.values())
    assert {case.fault_type for case in cases} == set(BLUEPRINTS)
    assert {case.instrument_type for case in cases} == set(INSTRUMENT_TYPES)
    assert len({case.doc_id for case in cases}) == len(cases)


def test_synthetic_documents_are_labelled_and_carry_all_sections() -> None:
    documents = build_synthetic_case_documents()

    assert documents
    for document in documents:
        assert document.source == SOURCE_SYNTHETIC
        for label in ("【仪器类型】", "【故障类型】", "【现象】", "【原因】", "【处置】"):
            assert label in document.text


def test_colloquial_query_retrieves_the_matching_case() -> None:
    """口语化描述应该能召回规范表述的案例——这是检索层的核心价值。"""
    cases = synthetic_cases()
    index = BM25Index(build_synthetic_case_documents())

    hit_count = 0
    for case in cases:
        hits = index.search(case.colloquial, top_k=3)
        if case.doc_id in [hit.document.doc_id for hit in hits]:
            hit_count += 1

    # 不做「每条都必须命中」的强断言，但要求整体命中率过半，否则检索层没有意义
    assert hit_count / len(cases) > 0.5


def test_fault_documents_require_reusable_content(
    api_client: TestClient,
    auth_headers: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    equipment = api_client.post(
        EQUIPMENT,
        headers=auth_headers,
        json={"equipment_no": "PLT-AI-1", "model": "YST-48R", "status": "在用"},
    ).json()["data"]

    # 现象、原因、处置齐全：应当入语料
    complete = api_client.post(
        FAULTS,
        headers=auth_headers,
        json={
            "equipment_id": equipment["id"],
            "fault_type": "密封失效",
            "description": "下井后压力异常，脉冲信号中断",
            "cause": "密封圈老化",
            "solution": "更换密封圈并复测密封性",
        },
    )
    assert complete.status_code == 200, complete.text

    # 只有现象、没有原因与处置：不入语料
    incomplete = api_client.post(
        FAULTS,
        headers=auth_headers,
        json={
            "equipment_id": equipment["id"],
            "fault_type": "电气故障",
            "description": "仅有现象描述",
        },
    )
    assert incomplete.status_code == 200, incomplete.text

    with session_factory() as session:
        documents = build_fault_case_documents(session)

    matched = [doc for doc in documents if doc.payload.get("equipment_no") == "PLT-AI-1"]
    assert len(matched) == 1

    document = matched[0]
    assert document.source == SOURCE_FAULT_RECORD
    assert document.payload["fault_type"] == "密封失效"
    assert document.payload["record_id"] == complete.json()["data"]["id"]
    assert "【设备型号】YST-48R" in document.text
    assert "密封圈老化" in document.text


def test_build_corpus_can_include_or_exclude_synthetic_cases(
    api_client: TestClient,
    auth_headers: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        with_synthetic = build_corpus(session, include_synthetic=True)
        without_synthetic = build_corpus(session, include_synthetic=False)

    assert len(with_synthetic) > len(without_synthetic)
    assert all(doc.source == SOURCE_FAULT_RECORD for doc in without_synthetic)
    assert any(doc.source == SOURCE_SYNTHETIC for doc in with_synthetic)
