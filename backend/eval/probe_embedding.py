"""向量接口自检：验证 key、模型名、维度与延迟是否可用。

用法（在 backend/ 目录下）：

    .venv\\Scripts\\python.exe eval\\probe_embedding.py

读取 backend/.env 里的 EMBEDDING_* 配置，发一条真实请求并打印结果。
换模型、换提供方、怀疑 key 失效时先跑这个，比在诊断链路里排查快得多。
不会打印密钥本身。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.embedding import build_embedder  # noqa: E402
from app.core.config import get_settings  # noqa: E402

SAMPLES = [
    "下井后压力保持不住，密封面渗漏",
    "地面解码误码率偏高，波形畸变",
    # 与第一条语义无关，用来确认向量不是退化的常量
    "食堂午餐菜单这周有调整吗",
]


def main() -> None:
    settings = get_settings()
    embedder = build_embedder(settings)

    if embedder is None:
        print("当前未启用向量检索：请把 EMBEDDING_PROVIDER 设为 api 或 local 再跑。")
        return

    print(f"提供方：{settings.embedding_provider}")
    print(f"模型：{settings.embedding_model}　维度配置：{settings.embedding_dimensions or '模型默认'}")
    print(f"接口：{settings.embedding_base_url}")

    started = time.perf_counter()
    try:
        vectors = embedder.embed(SAMPLES)
    except Exception as exc:
        print(f"调用失败：{exc}")
        return
    elapsed = int((time.perf_counter() - started) * 1000)

    print(f"成功：{len(vectors)} 条，维度 {len(vectors[0])}，耗时 {elapsed} ms")
    for index, sample in enumerate(SAMPLES):
        head = ", ".join(f"{value:.3f}" for value in vectors[index][:5])
        print(f"  第{index + 1}条前 5 维：{head}")

    def cosine(left: list[float], right: list[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right))
        norm = (sum(a * a for a in left) ** 0.5) * (sum(b * b for b in right) ** 0.5)
        return dot / norm if norm else 0.0

    # 前两条都是设备故障，第三条是无关话题：相似度应当明显更低
    print(f"  相似度（故障 vs 故障）：{cosine(vectors[0], vectors[1]):.4f}")
    print(f"  相似度（故障 vs 无关）：{cosine(vectors[0], vectors[2]):.4f}")


if __name__ == "__main__":
    main()
