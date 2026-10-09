"""端到端诊断评测：原因匹配率、无结果准确率、P95 延迟与单次成本。

用法（在 backend/ 目录下）：

    .venv\\Scripts\\python.exe eval\\diagnosis_eval.py                # 全量 40 条 + 10 条域外问题（消耗模型额度）
    .venv\\Scripts\\python.exe eval\\diagnosis_eval.py --limit 10     # 先小样本试跑
    .venv\\Scripts\\python.exe eval\\diagnosis_eval.py --no-model     # 只跑无结果准确率，不调用模型
    .venv\\Scripts\\python.exe eval\\diagnosis_eval.py --price-in 1 --price-out 2   # 单价（元/百万 token）用于折算成本

评测集来自仿真案例自带的「口语表述」，标准答案就是该案例的规范原因。
这条设计让"原因匹配率"可以自动判定，而不用人工标注——这也是当初把
「口语表述」和「规范表述」都写进案例的原因。

**注意口径**：查询与知识库同源（同一批仿真案例），所以数字偏乐观；
真实故障数据迁移到位后要换成留出法重测，指标口径不变。
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai import diagnosis  # noqa: E402
from app.ai.llm import build_chat_client  # noqa: E402
from app.ai.synthetic_cases import synthetic_cases  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402

# 与设备运维无关的问题：知识库里没有相似案例，正确行为是明确回答"未找到"
OUT_OF_SCOPE_QUERIES = (
    "食堂午餐菜单这周有调整吗",
    "差旅费报销标准是多少",
    "今天天气怎么样要不要带伞",
    "昨天那场篮球比赛谁赢了",
    "英语六级报名什么时候截止",
    "毕业论文查重率多少算合格",
    "手机话费充值什么时候到账",
    "电影票过期了还能退吗",
    "地铁末班车几点停运",
    "如何申请软件著作权登记",
)

PUNCTUATION = re.compile(r"[\s，。、；：,!.;:（）()【】\[\]“”\"'—\-—]+")


def normalize(text: str | None) -> str:
    """去掉空白与标点，便于判定"同一个意思"在字面上是否对得上。"""
    return PUNCTUATION.sub("", text or "")


def cause_matches(predicted: str | None, truth: str | None) -> bool:
    """判定原因是否命中：互为子串即算命中（模型常把原因写得更长或更短）。

    例：标准「密封圈老化」对上模型「密封圈老化导致密封失效」→ 命中；
    标准「泥浆含砂量大导致阀芯磨粒磨损」对上「阀芯磨粒磨损」→ 命中。
    """
    left, right = normalize(predicted), normalize(truth)
    if not left or not right:
        return False
    return left in right or right in left


def percentile(values: list[float], ratio: float) -> float:
    """给定分位数；样本为空返回 0。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(round(ratio * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[index]


def evaluate_diagnosis(limit: int | None, llm, session) -> dict[str, float]:
    cases = synthetic_cases()[:limit] if limit else synthetic_cases()
    first_hits = top3_hits = found_any = 0
    latencies: list[float] = []
    prompt_tokens = completion_tokens = 0

    for case in cases:
        result = diagnosis.diagnose(
            session,
            description=case.colloquial,
            top_k=5,
            llm=llm,
        )
        if result["found"]:
            found_any += 1
        latencies.append(float(result["elapsed_ms"]))

        causes = [item["text"] for item in result["causes"]]
        if causes and cause_matches(causes[0], case.cause):
            first_hits += 1
        if any(cause_matches(text, case.cause) for text in causes[:3]):
            top3_hits += 1

        usage = result.get("usage") or {}
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)

    total = len(cases)
    return {
        "queries": total,
        "found_rate": found_any / total,
        "cause@1": first_hits / total,
        "cause@3": top3_hits / total,
        "p50_ms": statistics.median(latencies) if latencies else 0.0,
        "p95_ms": percentile(latencies, 0.95),
        "prompt_tokens_avg": prompt_tokens / total,
        "completion_tokens_avg": completion_tokens / total,
        "prompt_tokens_total": prompt_tokens,
        "completion_tokens_total": completion_tokens,
    }


def evaluate_no_result(llm, session, *, verbose: bool = False) -> dict[str, float]:
    """无结果准确率：知识库里没有的东西，系统必须说没有，而不是编一个。"""
    correct = 0
    for query in OUT_OF_SCOPE_QUERIES:
        result = diagnosis.diagnose(session, description=query, top_k=5, llm=llm)
        # usage 为空说明压根没调用模型，这正是"检索为空不调模型"的硬约束
        ok = result["found"] is False and result.get("usage") is None
        if ok:
            correct += 1
        elif verbose:
            hit = result["matches"][0] if result["matches"] else {}
            print(f"    × {query} → 误召回「{hit.get('title')}」命中词={hit.get('matched_terms')}")
    return {
        "queries": len(OUT_OF_SCOPE_QUERIES),
        "accuracy": correct / len(OUT_OF_SCOPE_QUERIES),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="端到端诊断评测")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条案例（试跑用）")
    parser.add_argument("--no-model", action="store_true", help="不调用模型，只跑无结果准确率")
    parser.add_argument("--price-in", type=float, default=0.0, help="输入单价（元/百万 token）")
    parser.add_argument("--price-out", type=float, default=0.0, help="输出单价（元/百万 token）")
    parser.add_argument("--verbose", action="store_true", help="打印域外问题的误召回明细")
    args = parser.parse_args()

    settings = get_settings()
    llm = None if args.no_model else build_chat_client(settings)
    if not args.no_model and llm is None:
        print("未配置 DEEPSEEK_API_KEY，无法跑端到端指标；可先用 --no-model。")
        return

    factory = get_session_factory()
    with factory() as session:
        no_result = evaluate_no_result(llm, session, verbose=args.verbose)
        print("【无结果准确率】")
        print(f"  域外问题 {no_result['queries']} 条，正确回答未找到 {no_result['accuracy'] * 100:.1f}%")

        if args.no_model:
            return

        metrics = evaluate_diagnosis(args.limit, llm, session)
        print("\n【原因匹配率】")
        print(f"  查询条数        {metrics['queries']}")
        print(f"  检索到案例比例  {metrics['found_rate'] * 100:.1f}%")
        print(f"  首位原因命中    {metrics['cause@1'] * 100:.1f}%")
        print(f"  前三位原因覆盖  {metrics['cause@3'] * 100:.1f}%")

        print("\n【延迟与成本】")
        print(f"  P50 延迟        {metrics['p50_ms']:.0f} ms")
        print(f"  P95 延迟        {metrics['p95_ms']:.0f} ms")
        print(
            "  token 均值      输入 {:.0f} / 输出 {:.0f}".format(
                metrics["prompt_tokens_avg"], metrics["completion_tokens_avg"]
            )
        )
        if args.price_in or args.price_out:
            cost = (
                metrics["prompt_tokens_total"] * args.price_in
                + metrics["completion_tokens_total"] * args.price_out
            ) / 1_000_000
            print(f"  总成本          {cost:.4f} 元（{metrics['queries']} 次调用）")
            print(f"  单次成本        {cost / metrics['queries']:.5f} 元")
        else:
            print("  成本            未提供单价；用 --price-in / --price-out 折算")


if __name__ == "__main__":
    main()
