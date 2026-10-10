"""从编译好的 LangGraph 图里导出结构：ASCII（终端看）与 Mermaid（文档/画图用）。

为什么不手画：手画的图会随代码漂移，这份是**从图本身导出来的**，
节点和边就是运行时真正的那几条，改代码后重新跑一遍即可。

用法（在 backend/ 目录下）：

    .venv\\Scripts\\python.exe eval\\export_graph.py            # 打印两种格式
    .venv\\Scripts\\python.exe eval\\export_graph.py --png ..\\docs\\agent-workflow.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai import graph_agent  # noqa: E402


def export(png_path: Path | None = None) -> tuple[str, str]:
    graph = graph_agent.build_graph().get_graph()
    ascii_art = graph.draw_ascii()
    mermaid = graph.draw_mermaid()

    print("===== ASCII（终端直接看）=====")
    print(ascii_art)
    print("===== Mermaid（可粘进 README / 文档）=====")
    print(mermaid)

    if png_path is not None:
        png_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # LangGraph 自己会调用渲染服务生成图片，省得装本地渲染器
            graph.draw_mermaid_png(output_file_path=str(png_path))
            print(f"===== 图片已写入：{png_path} =====")
        except Exception as exc:  # 没网或缺少渲染器时给出 Mermaid 源码即可
            print(f"图片生成失败（可把上面的 Mermaid 粘到 mermaid.live 渲染）：{exc}")
            png_path.with_suffix(".mmd").write_text(mermaid, encoding="utf-8")
            print(f"已改为写出 Mermaid 源码：{png_path.with_suffix('.mmd')}")

    return ascii_art, mermaid


def main() -> None:
    parser = argparse.ArgumentParser(description="导出 Agent 工作流图")
    parser.add_argument("--png", type=Path, default=None, help="可选：同时导出一张 PNG")
    args = parser.parse_args()
    export(args.png)


if __name__ == "__main__":
    main()
