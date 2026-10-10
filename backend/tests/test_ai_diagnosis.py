"""智能诊断用例：引用校验、降级路径、抗幻觉与权限。

所有接口用例都通过依赖覆盖注入假客户端，不会打到真实模型服务——
这一点必须保证，否则本地跑一次测试就会消耗真实额度。
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai import diagnosis
from app.ai.document import CaseDocument
from app.ai.index_store import IndexBundle
from app.ai.llm import LLMError, parse_json
from app.ai.retriever import BM25Index, search_with_fallback
from app.api.v1.ai import get_chat_client

DIAGNOSIS = "/api/v1/ai/diagnosis"
CORPUS_STATS = "/api/v1/ai/corpus/stats"


class FakeLLM:
    """假客户端：返回预设 JSON，并记录收到的提示词。"""

    model = "fake-model"

    def __init__(self, payload: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self.payload = payload or {}
        self.error = error
        self.calls: list[str] = []

    def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        self.calls.append(user)
        if self.error is not None:
            raise self.error
        return self.payload


@pytest.fixture
def llm_override(api_client: TestClient):
    """安装大模型依赖覆盖，默认「未配置模型」，用例可按需替换。"""

    def install(client_impl: Any) -> Any:
        api_client.app.dependency_overrides[get_chat_client] = lambda: client_impl
        return client_impl

    install(None)
    yield install
    api_client.app.dependency_overrides.pop(get_chat_client, None)


def _doc(doc_id: str, text: str, **payload: object) -> CaseDocument:
    return CaseDocument(source="synthetic", doc_id=doc_id, title=doc_id, text=text, payload=dict(payload))


# ---------------------------------------------------------------- 解析与检索


def test_parse_json_tolerates_code_fence() -> None:
    assert parse_json('```json\n{"confidence":"高"}\n```') == {"confidence": "高"}
    assert parse_json('{"causes": []}') == {"causes": []}


def test_parse_json_rejects_unparsable_output() -> None:
    with pytest.raises(LLMError):
        parse_json("抱歉，我无法回答这个问题。")


def test_search_falls_back_to_full_corpus_when_filter_too_narrow() -> None:
    index = BM25Index(
        [
            _doc("a", "【现象】下井后压力异常  【原因】密封圈老化", fault_type="密封失效"),
            _doc("b", "【现象】地面解码误码偏高  【原因】脉冲波形畸变", fault_type="电气故障"),
        ]
    )

    strict = search_with_fallback(index, "压力异常", filters={"fault_type": "信号异常"})
    relaxed = search_with_fallback(index, "压力异常", filters={"fault_type": "密封失效"})

    assert strict.relaxed is True
    assert [hit.document.doc_id for hit in strict.hits] == ["a"]
    assert relaxed.relaxed is False
    assert [hit.document.doc_id for hit in relaxed.hits] == ["a"]


def test_search_without_filters_never_reports_relaxation() -> None:
    index = BM25Index([_doc("a", "【现象】压力异常")])
    outcome = search_with_fallback(index, "完全无关的查询")
    assert outcome.hits == ()
    assert outcome.relaxed is False


# ---------------------------------------------------------------- 生成与校验


def test_diagnosis_uses_model_output_and_drops_unknown_citations(
    api_client: TestClient, auth_headers: dict[str, str], llm_override
) -> None:
    llm_override(
        FakeLLM(
            {
                "causes": [{"text": "密封圈老化", "case_ids": ["C1", "C99"]}],
                "actions": [{"text": "更换密封圈并复测", "case_ids": ["C1"]}],
                "confidence": "高",
                "note": "",
            }
        )
    )

    response = api_client.post(
        DIAGNOSIS,
        headers=auth_headers,
        json={"description": "下井后压力保持不住，怀疑密封圈老化"},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["found"] is True
    assert data["degraded"] is False
    assert data["confidence"] == "高"
    assert data["model"] == "fake-model"
    assert data["matches"], "应当检索到相似案例"

    first_doc_id = data["matches"][0]["doc_id"]
    # 编造的 C99 被丢弃，只保留真实检索到的案例
    assert data["causes"] == [{"text": "密封圈老化", "case_ids": [first_doc_id]}]
    assert data["actions"][0]["case_ids"] == [first_doc_id]
    assert data["citations"] == [first_doc_id]


def test_diagnosis_lowers_confidence_when_model_cites_nothing(
    api_client: TestClient, auth_headers: dict[str, str], llm_override
) -> None:
    llm_override(
        FakeLLM(
            {
                "causes": [{"text": "可能是电池组问题", "case_ids": []}],
                "actions": [],
                "confidence": "高",
                "note": "",
            }
        )
    )

    data = api_client.post(
        DIAGNOSIS,
        headers=auth_headers,
        json={"description": "下井后压力保持不住"},
    ).json()["data"]

    assert data["citations"] == []
    assert data["confidence"] == "低"
    assert "引用" in (data["note"] or "")


def test_diagnosis_degrades_when_model_fails(
    api_client: TestClient, auth_headers: dict[str, str], llm_override
) -> None:
    llm_override(FakeLLM(error=LLMError("请求超时")))

    response = api_client.post(
        DIAGNOSIS,
        headers=auth_headers,
        json={"description": "下井后压力保持不住，密封面渗漏"},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["degraded"] is True
    assert "降级" in (data["reason"] or "")
    assert data["matches"], "降级后仍应返回相似案例"
    assert data["confidence"] == "低"
    # 降级路径的原因与处置直接取自案例库，便于人工核对
    assert any(item["case_ids"] for item in data["causes"])


def test_diagnosis_degrades_when_no_api_key(api_client: TestClient, auth_headers: dict[str, str], llm_override) -> None:
    data = api_client.post(
        DIAGNOSIS,
        headers=auth_headers,
        json={"description": "下井后压力保持不住，密封面渗漏"},
    ).json()["data"]

    assert data["degraded"] is True
    assert "未配置大模型" in (data["reason"] or "")
    assert data["model"] is None


def test_diagnosis_returns_not_found_without_calling_model(
    api_client: TestClient, auth_headers: dict[str, str], llm_override, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = llm_override(FakeLLM({"causes": [{"text": "不该出现", "case_ids": ["C1"]}]}))
    # 语料为空是确定性的场景；固定成空索引，避免用例随语料增删而失效
    monkeypatch.setattr(
        diagnosis, "get_indexes", lambda *_args, **_kwargs: IndexBundle(bm25=BM25Index([]))
    )

    response = api_client.post(
        DIAGNOSIS,
        headers=auth_headers,
        json={"description": "与设备故障完全无关的一段描述"},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["found"] is False
    assert data["matches"] == []
    assert data["causes"] == []
    assert fake.calls == [], "检索为空时不应调用大模型，否则会得到编造的原因"


# ---------------------------------------------------------------- 接口边界


def test_diagnosis_requires_login(api_client: TestClient, llm_override) -> None:
    response = api_client.post(DIAGNOSIS, json={"description": "下井后压力保持不住"})
    assert response.status_code == 401


def test_diagnosis_rejects_too_short_description(
    api_client: TestClient, auth_headers: dict[str, str], llm_override
) -> None:
    response = api_client.post(DIAGNOSIS, headers=auth_headers, json={"description": "坏"})
    assert response.status_code == 400
    assert response.json()["code"] == 40001


def test_diagnosis_reports_missing_equipment(
    api_client: TestClient, auth_headers: dict[str, str], llm_override
) -> None:
    response = api_client.post(
        DIAGNOSIS,
        headers=auth_headers,
        json={"description": "下井后压力保持不住", "equipment_id": 999999},
    )
    assert response.status_code == 404
    assert response.json()["code"] == 40400


def test_corpus_stats_reports_sources(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = api_client.get(CORPUS_STATS, headers=auth_headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] > 0
    sources = {item["source"]: item["count"] for item in data["by_source"]}
    assert sources.get("synthetic", 0) > 0
    assert data["include_synthetic"] is True


def test_corpus_stats_requires_settings_permission(
    api_client: TestClient, readonly_headers: dict[str, str]
) -> None:
    assert api_client.get(CORPUS_STATS, headers=readonly_headers).status_code == 403


def test_free_text_model_is_not_used_as_instrument_filter(
    api_client: TestClient, auth_headers: dict[str, str], llm_override
) -> None:
    """型号字段可能是自由文本，不能当作仪器类型去硬过滤，否则召回直接归零。"""
    equipment = api_client.post(
        "/api/v1/equipment",
        headers=auth_headers,
        json={"equipment_no": "PLT-AI-FILTER", "model": "演示样机", "status": "待命"},
    ).json()["data"]

    data = api_client.post(
        DIAGNOSIS,
        headers=auth_headers,
        json={
            "description": "下井后压力保持不住，密封面渗漏",
            "equipment_id": equipment["id"],
        },
    ).json()["data"]

    assert data["matches"], "型号不在仪器类型字典里时应退化为不过滤，而不是搜不到"
    assert data["filter_relaxed"] is False
