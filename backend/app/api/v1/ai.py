"""智能运维助手接口：故障案例诊断与语料概览。

诊断接口复用现有的 JWT 鉴权与 fault.view 权限点，工具层调用现有服务函数，
不在 AI 模块里另写查询——权限不能因为套了一层模型就被绕过。
POST 请求由审计中间件自动留痕，与其它写操作一致。
"""

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.ai import corpus as corpus_module
from app.ai import agent
from app.ai import diagnosis
from app.ai import graph_agent
from app.ai.embedding import build_embedder
from app.ai.llm import build_chat_client
from app.ai.memory import get_memory
from app.ai.rerank import build_reranker
from app.core.config import get_settings
from app.core.deps import get_current_user, require_permission
from app.core.response import ApiResponse, ok
from app.db.session import get_db
from app.models.user import User
from app.schemas.ai import AskOut, AskRequest, CorpusStatsOut, DiagnosisOut, DiagnosisRequest
from app.services.auth import load_roles_and_permissions

router = APIRouter(prefix="/ai", tags=["智能运维助手"])


def get_chat_client() -> Any:
    """大模型客户端依赖。

    注册成依赖而不是在路由里直接构造，是为了让测试替换成假客户端，
    避免用例打到真实模型服务；换成内网模型时也只需要改这一处。
    """
    return build_chat_client(get_settings())


def get_embedder() -> Any:
    """向量化器依赖。

    同样做成依赖而不是在路由里直接构造：测试替换成假向量化器，
    切换 API / 本地模型时也只改配置。
    """
    return build_embedder(get_settings())


@router.post(
    "/diagnosis",
    response_model=ApiResponse,
    summary="故障案例智能诊断（检索增强）",
)
def diagnose_fault(
    payload: DiagnosisRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("fault.view")),
    llm: Any = Depends(get_chat_client),
    embedder: Any = Depends(get_embedder),
) -> dict:
    settings = get_settings()
    reranker = build_reranker(
        llm, enabled=settings.ai_rerank, min_score=settings.ai_rerank_min_score
    )
    result = diagnosis.diagnose(
        db,
        description=payload.description,
        fault_type=payload.fault_type,
        instrument_type=payload.instrument_type,
        equipment_id=payload.equipment_id,
        top_k=payload.top_k or settings.ai_top_k,
        include_synthetic=settings.ai_include_synthetic,
        llm=llm,
        reranker=reranker,
        embedder=embedder,
    )
    return ok(DiagnosisOut.model_validate(result).model_dump(mode="json"))


@router.get(
    "/corpus/stats",
    response_model=ApiResponse,
    summary="语料规模与来源构成",
)
def corpus_stats(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system.settings")),
) -> dict:
    settings = get_settings()
    stats = corpus_module.corpus_stats(db, include_synthetic=settings.ai_include_synthetic)
    return ok(CorpusStatsOut.model_validate(stats).model_dump(mode="json"))


@router.post(
    "/ask",
    response_model=ApiResponse,
    summary="设备数据问答（Agent 工具调用）",
)
def ask_question(
    payload: AskRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    llm: Any = Depends(get_chat_client),
) -> dict:
    """登录即可提问，具体能看到哪些数据由工具层的权限点决定。

    这里只做登录校验、不挂单一权限点：一个账号可能只能查设备、不能查耗材，
    所以权限要在工具粒度上判断，并把无权限的工具整体隐藏掉。
    """
    _, permissions = load_roles_and_permissions(db, user)

    # 短期记忆：会话内容在 LangGraph 的检查点里，这里先取到本次要用的会话 ID
    memory = get_memory()
    conversation_id = memory.register(
        payload.conversation_id if memory.owns(payload.conversation_id, user.id) else None,
        user.id,
    )
    # 检查点里有上下文就用它（server）；没有（新会话或服务刚重启）就退回请求体带来的历史
    prior_turns, _ = graph_agent.prior_context(conversation_id)
    if prior_turns:
        memory_source, seed = "server", []
    else:
        seed = [item.model_dump() for item in payload.history]
        memory_source = "client" if seed else "none"

    result = agent.answer(
        db,
        question=payload.question,
        user=user,
        permissions=frozenset(permissions),
        llm=llm,
        client_ip=request.client.host if request.client else None,
        max_steps=payload.max_steps,
        history=seed,
        thread_id=conversation_id,
    )
    data = AskOut.model_validate(
        {**result, "conversation_id": conversation_id, "memory_source": memory_source}
    )
    return ok(data.model_dump(mode="json"))


@router.delete(
    "/conversations/{conversation_id}",
    response_model=ApiResponse,
    summary="忘记一个会话（清空短期记忆）",
)
def forget_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    """只删自己的会话；不存在或不属于当前用户时返回 removed=false，天然幂等。"""
    removed = get_memory().clear(conversation_id, user.id)
    return ok({"conversation_id": conversation_id, "removed": removed})
