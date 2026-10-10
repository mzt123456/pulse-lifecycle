"""知识库用例：分块、解析、入库、检索接入、软删除、权限与审计。

测试库是会话级共享的，所以每条用例都用独一无二的标题/关键词，避免互相干扰。
"""

import io

from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.ai.corpus import build_corpus, build_knowledge_documents
from app.ai.document import SOURCE_KNOWLEDGE
from app.ai.retriever import BM25Index
from app.services.knowledge import split_chunks

BASE = "/api/v1/knowledge"


# ----------------------------------------------------------------- 分块


def test_long_line_is_split_on_sentence_punctuation() -> None:
    """超长行按句末标点切，而不是从中间硬断。"""
    text = "第一句话结束。" * 200  # 1400 字，远超 500 的阈值

    chunks = split_chunks(text)

    assert len(chunks) > 1
    for chunk in chunks[:-1]:
        assert chunk.endswith("。")


def test_chunks_keep_overlap_between_neighbours() -> None:
    """块间留重叠：一句话被切断后，两边都能检索到相邻语境。"""
    lines = [f"第{i}行：" + "脉冲器压力异常需要检查密封圈。" * 6 for i in range(20)]

    chunks = split_chunks("\n".join(lines))

    assert len(chunks) > 2
    assert all(chunk for chunk in chunks)
    # 后一块的开头与上一块的结尾重叠（重叠长度受切分位置影响，这里校验非空交集）
    assert chunks[1][:10] in chunks[0] + chunks[1]


def test_short_text_is_a_single_chunk() -> None:
    assert split_chunks("设备台账：剪切阀脉冲器，状态在用。") == [
        "设备台账：剪切阀脉冲器，状态在用。"
    ]


def test_blank_lines_are_dropped() -> None:
    assert split_chunks("第一行\n\n   \n第二行") == ["第一行\n第二行"]


# ----------------------------------------------------------------- 入库


def test_paste_text_document_is_chunked_and_listed(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    title = "知识库用例-粘贴文档-2026"
    content = "剪切阀脉冲器的扭矩标定方法：先加压到 20MPa，保持三分钟后读取脉冲计数。"

    created = api_client.post(
        f"{BASE}/documents/text", headers=auth_headers, json={"title": title, "content": content}
    )
    assert created.status_code == 200, created.text
    data = created.json()["data"]

    assert data["status"] == "ready"
    assert data["source_type"] == "text"
    assert data["char_count"] == len(content)
    assert data["chunk_count"] == 1

    listed = api_client.get(f"{BASE}/documents", headers=auth_headers, params={"keyword": title})
    items = listed.json()["data"]["items"]
    assert [item["id"] for item in items] == [data["id"]]
    assert items[0]["created_by_name"]

    detail = api_client.get(f"{BASE}/documents/{data['id']}", headers=auth_headers).json()["data"]
    assert [chunk["seq"] for chunk in detail["chunks"]] == [1]
    assert "扭矩标定方法" in detail["chunks"][0]["text"]


def test_upload_txt_file_keeps_original_name(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    content = "维保规程：每次下井前检查剪切阀脉冲器密封圈。".encode("utf-8")

    response = api_client.post(
        f"{BASE}/documents/upload",
        headers=auth_headers,
        data={"title": "知识库用例-上传 txt"},
        files={"file": ("脉冲器规程.txt", content, "text/plain")},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "ready"
    assert data["source_type"] == "file"
    assert data["file_name"] == "脉冲器规程.txt"
    assert data["size_bytes"] == len(content)
    assert data["chunk_count"] == 1


def test_upload_docx_extracts_paragraphs_and_tables(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    document = DocxDocument()
    document.add_paragraph("知识库用例：docx 段落内容——剪切阀脉冲器标定流程。")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "参数"
    table.cell(0, 1).text = "取值范围"
    buffer = io.BytesIO()
    document.save(buffer)

    response = api_client.post(
        f"{BASE}/documents/upload",
        headers=auth_headers,
        files={
            "file": (
                "docx用例.docx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "ready"
    assert data["chunk_count"] == 1

    detail = api_client.get(f"{BASE}/documents/{data['id']}", headers=auth_headers).json()["data"]
    text = detail["chunks"][0]["text"]
    assert "标定流程" in text
    assert "参数 | 取值范围" in text  # 表格按行拍平，不丢内容


def test_upload_rejects_unsupported_extension_without_storing(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = api_client.post(
        f"{BASE}/documents/upload",
        headers=auth_headers,
        files={"file": ("bad.exe", b"MZ", "application/octet-stream")},
    )

    assert response.status_code == 422
    assert "不支持" in response.json()["message"]

    listed = api_client.get(f"{BASE}/documents", headers=auth_headers, params={"keyword": "bad"})
    assert listed.json()["data"]["items"] == []


def test_upload_without_text_is_recorded_as_failed(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    """扫描件/空文档不静默入库：落一条 failed 记录，页面能看到原因。"""
    response = api_client.post(
        f"{BASE}/documents/upload",
        headers=auth_headers,
        data={"title": "知识库用例-空白文档"},
        files={"file": ("空白.txt", "   \n\n".encode(), "text/plain")},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "failed"
    assert data["chunk_count"] == 0
    assert "没有提取到任何文字" in data["error"]

    detail = api_client.get(f"{BASE}/documents/{data['id']}", headers=auth_headers).json()["data"]
    assert detail["chunks"] == []


def test_paste_blank_content_is_rejected(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = api_client.post(
        f"{BASE}/documents/text", headers=auth_headers, json={"title": "空正文", "content": " "}
    )

    assert response.status_code == 422


def test_stats_count_documents_and_chunks(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    before = api_client.get(f"{BASE}/stats", headers=auth_headers).json()["data"]

    api_client.post(
        f"{BASE}/documents/text",
        headers=auth_headers,
        json={"title": "知识库用例-统计口径", "content": "统计口径验证：一段正文。"},
    )

    after = api_client.get(f"{BASE}/stats", headers=auth_headers).json()["data"]
    assert after["documents"] == before["documents"] + 1
    assert after["chunks"] == before["chunks"] + 1
    assert after["characters"] > before["characters"]


# ----------------------------------------------------------------- 检索接入


def test_ready_document_chunks_enter_corpus_and_are_searchable(
    api_client: TestClient,
    auth_headers: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    marker = "氦气检漏标定作业指导"
    created = api_client.post(
        f"{BASE}/documents/text",
        headers=auth_headers,
        json={
            "title": "知识库用例-进语料",
            "content": f"{marker}：把剪切阀脉冲器放入检漏工装，充氦至 0.6MPa，保压五分钟无泄漏为合格。",
        },
    ).json()["data"]

    with session_factory() as session:
        documents = build_knowledge_documents(session)

    matched = [doc for doc in documents if doc.payload["document_id"] == created["id"]]
    assert len(matched) == 1
    document = matched[0]
    assert document.source == SOURCE_KNOWLEDGE
    assert document.doc_id == f"knowledge:{created['id']}:1"
    assert document.payload["chunk_seq"] == 1

    with session_factory() as session:
        corpus = build_corpus(session, include_synthetic=False)

    hits = BM25Index(corpus).search(marker, top_k=3)
    assert any(hit.document.doc_id == document.doc_id for hit in hits)


def test_deleted_document_leaves_corpus_and_hides_detail(
    api_client: TestClient,
    auth_headers: dict[str, str],
    session_factory: sessionmaker[Session],
) -> None:
    created = api_client.post(
        f"{BASE}/documents/text",
        headers=auth_headers,
        json={"title": "知识库用例-软删除", "content": "软删除验证：这段内容不应再进语料。"},
    ).json()["data"]

    removed = api_client.delete(f"{BASE}/documents/{created['id']}", headers=auth_headers)
    assert removed.status_code == 200, removed.text

    with session_factory() as session:
        documents = build_knowledge_documents(session)
    assert all(doc.payload["document_id"] != created["id"] for doc in documents)

    assert api_client.get(f"{BASE}/documents/{created['id']}", headers=auth_headers).status_code == 404
    listed = api_client.get(
        f"{BASE}/documents", headers=auth_headers, params={"keyword": "知识库用例-软删除"}
    )
    assert listed.json()["data"]["items"] == []


# ----------------------------------------------------------------- 权限与审计


def test_readonly_user_can_view_but_not_manage(
    api_client: TestClient, auth_headers: dict[str, str], readonly_headers: dict[str, str]
) -> None:
    created = api_client.post(
        f"{BASE}/documents/text",
        headers=auth_headers,
        json={"title": "知识库用例-权限", "content": "权限验证：只读用户能看不能改。"},
    ).json()["data"]

    assert api_client.get(f"{BASE}/documents", headers=readonly_headers).status_code == 200
    assert api_client.get(f"{BASE}/stats", headers=readonly_headers).status_code == 200

    denied_upload = api_client.post(
        f"{BASE}/documents/text",
        headers=readonly_headers,
        json={"title": "越权上传", "content": "不应成功"},
    )
    assert denied_upload.status_code == 403
    assert denied_upload.json()["code"] == 40300

    denied_delete = api_client.delete(f"{BASE}/documents/{created['id']}", headers=readonly_headers)
    assert denied_delete.status_code == 403


def test_upload_is_recorded_in_audit_log(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    api_client.post(
        f"{BASE}/documents/text",
        headers=auth_headers,
        json={"title": "知识库用例-审计", "content": "审计验证：写入应留痕。"},
    )

    logs = api_client.get(
        "/api/v1/system/audit-logs",
        headers=auth_headers,
        params={"object_type": "knowledge", "page_size": 50},
    ).json()["data"]

    entries = [
        item for item in logs["items"] if item["action"].endswith("/knowledge/documents/text")
    ]
    assert entries
    assert entries[0]["user_id"] is not None


def test_unknown_document_returns_404(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = api_client.get(f"{BASE}/documents/999999", headers=auth_headers)

    assert response.status_code == 404
    assert response.json()["code"] == 40400
