"""检索质量评测：40 条口语描述查规范案例，输出 Recall@K 与故障类型命中率。

用法（在 backend/ 目录下）：

    .venv\\Scripts\\python.exe eval\\retrieval_eval.py            # 行业词典 + 同义词扩展
    .venv\\Scripts\\python.exe eval\\retrieval_eval.py --plain    # 基线：不加词典、不做扩展

评测集来自仿真案例自带的「口语表述」——每条案例的规范表述进语料库，口语表述
当查询，标准答案就是它自己。真实故障数据迁移到位后，把评测集换成留出的历史
记录即可，指标口径不变。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许直接以脚本方式运行，而不必先安装成包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai import lexicon, retriever  # noqa: E402
from app.ai.retriever import BM25Index  # noqa: E402
from app.ai.synthetic_cases import build_synthetic_case_documents, synthetic_cases  # noqa: E402

TOP_K = 5


def evaluate(index: BM25Index, top_k: int = TOP_K) -> dict[str, float]:
    cases = synthetic_cases()
    hits_at_1 = hits_at_3 = hits_at_k = 0
    type_at_3 = 0

    for case in cases:
        hits = index.search(case.colloquial, top_k=top_k)
        doc_ids = [hit.document.doc_id for hit in hits]
        if doc_ids[:1] == [case.doc_id] or case.doc_id in doc_ids[:1]:
            hits_at_1 += 1
        if case.doc_id in doc_ids[:3]:
            hits_at_3 += 1
        if case.doc_id in doc_ids:
            hits_at_k += 1
        if any(hit.document.payload.get("fault_type") == case.fault_type for hit in hits[:3]):
            type_at_3 += 1

    total = len(cases)
    return {
        "queries": total,
        "recall@1": hits_at_1 / total,
        "recall@3": hits_at_3 / total,
        f"recall@{top_k}": hits_at_k / total,
        "type@3": type_at_3 / total,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="检索质量评测")
    parser.add_argument("--plain", action="store_true", help="基线：不加载行业词典、不做同义词扩展")
    args = parser.parse_args()

    if args.plain:
        lexicon.unload_lexicon()
        retriever.lexicon.expand_query = lambda text: text or ""  # type: ignore[assignment]

    label = "基线（无词典、无扩展）" if args.plain else "当前（行业词典 + 同义词扩展）"
    metrics = evaluate(BM25Index(build_synthetic_case_documents()))

    print(f"配置　　：{label}")
    print(f"查询条数：{metrics['queries']}")
    for key in ("recall@1", "recall@3", f"recall@{TOP_K}", "type@3"):
        print(f"{key:<10}{metrics[key] * 100:.1f}%")


if __name__ == "__main__":
    main()
