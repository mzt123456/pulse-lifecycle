# 剪切阀脉冲器全生命周期管理系统（网络版）

某能源装备企业维保管理系统的网络版。单机版用 tkinter 加 SQLite、装在每台电脑上；
这一版把数据集中到服务器，改成浏览器访问，设备台账、使用记录、维保工单、故障记录与耗材库存
由各岗位共用同一份数据，并增加权限控制与审计日志。

## 目录结构

| 路径 | 内容 |
| --- | --- |
| `docs/` | 方案文档，见下表 |
| `dev/` | 开发环境编排，只跑 MySQL，后端与前端在本机运行 |
| `开发日志/` | 每个阶段的开发日志，按天或按提交追加 |

后端与前端目录尚未创建，结构见 `docs/` 里编写报告第九章。

`docs/` 中的文档：

| 文档 | 用途 |
| --- | --- |
| 编写报告（网络版） | 系统建成后的完整形态：需求、架构、数据库、接口、界面、部署与验收 |
| 分阶段实施计划 | 八个阶段的顺序、交付物、验收标准与工作量 |
| 阶段进度看板 | 当前处在哪个阶段、检查项进度、待决事项、变更记录 |
| 开发规范与避坑清单 | 踩过的坑、必须走的流程、提交与上线前自检清单、配置与密钥约定 |
| 首批上线范围确认表 | 供现场岗位与甲方确认正式上线时必须包含的模块 |

## 开发环境

需要 Python 3.10 以上、Node、Git 和 Docker Desktop（WSL2 后端）。

开发数据库是容器里的 MySQL 8.0，映射到宿主机 3307：

```
docker compose -f dev/docker-compose.dev.yml up -d      # 起库
docker compose -f dev/docker-compose.dev.yml logs -f    # 看日志
docker compose -f dev/docker-compose.dev.yml down       # 停库
```

连接信息：`127.0.0.1:3307`，库 `pulse_lifecycle_dev`，用户 `pulse_dev`。
本机若另装了 MySQL 8.4，它占用 3306，两者互不干扰。

## 后端

后端在 `backend/` 目录，FastAPI + SQLAlchemy 2.x + Alembic，要求 Python 3.10 以上。

首次准备（在 `backend/` 目录下执行）：

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
copy .env.example .env
```

启动开发服务与运行测试：

```
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
.venv\Scripts\python.exe -m pytest
```

接口文档在 `http://127.0.0.1:8000/docs`，健康检查在 `http://127.0.0.1:8000/api/v1/health`。

## 智能运维助手（RAG）

在既有业务系统上增加故障案例检索与诊断，代码在 `backend/app/ai/`（语料、检索、生成层）。

| 接口 | 说明 | 权限 |
| --- | --- | --- |
| `POST /api/v1/ai/diagnosis` | 输入故障现象，返回可能原因、建议处置与引用案例 | `fault.view` |
| `POST /api/v1/ai/ask` | 自然语言数据问答，模型自己决定调哪些工具 | 登录即可，数据按工具粒度鉴权 |
| `GET /api/v1/ai/corpus/stats` | 语料规模与来源构成 | `system.settings` |

链路是「结构化预过滤 → BM25 检索 → 大模型归纳 → 引用校验」，两条抗幻觉约束：
检索为空时不调用模型，直接回答未找到；模型给出的引用必须能在本次检索结果里对上，
对不上的引用一律丢弃，一条不剩时置信度强制降为「低」。

生成层走 OpenAI 兼容协议，默认 DeepSeek，Key 放在 `backend/.env`（不入库）。
**没有 Key 或模型超时、报错时接口自动降级为只返回相似案例列表**，不影响页面可用。

检索质量可以用 40 条口语描述评测（在 `backend/` 下执行）：

```
.venv\Scripts\python.exe eval\retrieval_eval.py          # 行业词典 + 同义词扩展
.venv\Scripts\python.exe eval\retrieval_eval.py --plain  # 基线，用于对比
.venv\Scripts\python.exe eval\diagnosis_eval.py          # 端到端：原因匹配率、无结果准确率、延迟、token
.venv\Scripts\python.exe eval\diagnosis_eval.py --no-model   # 不调用模型，只跑无结果准确率
```

### 指标（2026-10-09，开发库 + 仿真语料）

| 指标 | 数值 | 口径 |
| --- | --- | --- |
| Recall@1 / @3 / @5 | 92.5% / 97.5% / 97.5% | 40 条口语描述查规范案例，标准答案即案例自身 |
| 故障类型命中@3 | 97.5% | Top-3 里出现同类型案例 |
| 原因匹配率（首位 / 前三位） | 92.5% / 97.5% | 端到端，模型给出的原因与标准原因一致 |
| 无结果准确率 | 90.0% | 10 条域外问题，正确回答"未找到"且不调用模型 |
| P50 / P95 延迟 | 1.81s / 2.44s | 端到端，含模型调用 |
| token 用量（均值） | 输入 341 / 输出 123 | 单次诊断 |

两条口径说明，写在文档里比藏着强：**评测集与行业词典同源**（同一批仿真案例），数字偏乐观，
真实故障数据迁移到位后要改用留出法重测；**残留误差**是域外问题里"如何申请软件著作权登记"
因"软件"同词异义被误召回——纯字面检索的天花板，也是引入向量检索的理由。

### Agent 工具与技能

`/ai/ask` 走手写的工具调用循环（最多 5 步）：模型决定调哪个工具、结果回灌、信息够了再作答。
工具全部复用现有 service，**用户没有权限的工具根本不会出现在模型可见的清单里**，每次调用都写审计日志
（`object_type=ai_tool`）。

技能按需加载，避免把全部指令塞进提示词：

```
app/ai/skills/<技能名>/SKILL.md      # frontmatter 声明用途与触发词，正文是流程与约束
app/ai/skills/<技能名>/references/   # 参考资料，被显式引用时才读入上下文
```

常驻提示词里只有一行一个的技能索引，命中触发词才展开正文；返回体里的 `context_chars` 可以看到省了多少。

### MCP Server

同一套工具定义还有第二个出口：MCP。外部客户端（Claude Code、Codex、Cursor 等）可以直接挂载。

```
cd backend
.venv\Scripts\python.exe -m app.mcp.server                              # stdio
set MCP_TRANSPORT=streamable-http && .venv\Scripts\python.exe -m app.mcp.server   # 内网 HTTP
```

身份用服务账号（环境变量 `MCP_USERNAME`，默认 `admin`），工具层照旧按该账号的权限点过滤——
换传输方式不绕过权限。**只暴露查询类工具，写操作不开放**；另有两个只读资源
`pulse://corpus/stats` 与 `pulse://audit/recent`。

## 配置与密钥

仓库只提交 `.env.example`，真实的 `.env` 不进入版本库，JWT 密钥在部署时随机生成并单独保管。
完整约定见 `docs/` 里开发规范与避坑清单的 3.6 节。

## 分支约定

主分支是 `main`。一项改动从 `main` 拉一条分支，命名按改动类型带前缀：
`feat-` 是新功能，`fix-` 是修缺陷，`docs-` 是文档改动；完成后合并回 `main` 并删除该分支。

## 当前进度

处于阶段 0 准备与基线。方案文档、开发环境与代码仓库已经就绪；首批上线范围确认表待现场岗位与
甲方签字；单机版数据文件暂时拿不到，字段映射表与数据体检相应推迟。
进度以 `docs/` 里的阶段进度看板为准。
