# LangChain RAG 电商知识库问答系统

基于 LangChain 的 RAG 企业级知识库问答系统（毕业设计）。用户在浏览器中对电商商品知识库提问，回答引用知识库片段并支持溯源查看。

## 技术栈

| 层 | 选型 |
|---|---|
| AI 框架 | LangChain 0.3.x（Python，LCEL） |
| 后端 | Python 3.12 + FastAPI + SQLAlchemy 2.x（异步）+ MySQL 8 |
| LLM | 阿里云百炼 qwen3.8-flash（OpenAI 兼容模式，可切换） |
| Embedding / Rerank | BGE-M3 / bge-reranker-v2-m3（本地 GPU） |
| 向量库 | Chroma（内嵌持久化） |
| 前端 | Vue3 + Vite + Element Plus + Pinia |

## 环境要求

- Python 3.12+、Node.js 24+、MySQL 8.0（本机运行，不用 Docker）
- 可选：NVIDIA GPU（本地 Embedding/Rerank 加速）

## 快速启动

**一键启动（推荐）**：双击项目根目录 `start.bat`，会自动打开两个窗口分别运行后端与前端；停止服务时关闭两个窗口即可。

手动启动（两个终端分别执行）：

### 1. 后端

```bash
cd backend
pip install -r requirements.txt        # 核心依赖（M3 再装 requirements-ai.txt）
python -m uvicorn app.main:app --reload --port 8000
```

启动时自动建表并写入管理员种子。验证：http://127.0.0.1:8000/api/v1/health
Swagger 文档：http://127.0.0.1:8000/docs

### 2. 前端

```bash
cd frontend
npm install
npm run dev
```

访问：http://localhost:5173

## 配置

复制 `.env.example` 为 `.env` 并填写（`.env` 已被 `.gitignore` 排除，勿提交）：

| 变量 | 说明 |
|---|---|
| `DASHSCOPE_API_KEY` | 阿里云百炼 API Key |
| `LLM_BASE_URL` / `LLM_MODEL` | OpenAI 兼容接口地址 / 模型名 |
| `LLM_ENABLE_THINKING` | 思考模式（默认 false，保证首字延迟） |
| `MYSQL_*` | MySQL 连接信息 |
| `SECRET_KEY` | JWT 签名密钥 |

## 默认账号

| 账号 | 密码 | 权限 |
|---|---|---|
| admin | 123456 | 管理员（知识库管理 + 仪表盘） |

> 演示初始密码，答辩后请修改。

## 目录结构

```
LangchainRAG项目/
├── backend/               # FastAPI 后端
│   ├── app/
│   │   ├── api/v1/        # 路由（health → M1 起陆续加 auth/sessions/chat/documents）
│   │   ├── core/          # 配置 / 日志 / 异常
│   │   ├── db/            # ORM 模型 / 连接池 / 种子
│   │   ├── schemas/       # Pydantic 模型
│   │   └── services/      # 业务服务（rag/ 为 RAG 核心链路）
│   ├── tests/             # 单元测试
│   └── data/              # 上传文件 / Chroma / 模型缓存
├── frontend/              # Vue3 前端
├── docs/                  # 项目文档（01-项目方案计划.md 等）
├── .env                   # 本地配置（不进 git）
└── .env.example           # 配置模板
```

## 测试与实验

```bash
# 单元测试（27 个用例）
cd backend && python -m pytest tests/ -q

# 检索对比实验（论文/答辩数据，输出 docs/07-检索对比实验报告.md）
cd backend && python -m experiments.eval_retrieval
```

## 文档索引

| 文档 | 内容 |
|---|---|
| `docs/01-项目方案计划.md` | 技术选型、架构、功能、里程碑（v0.3） |
| `docs/05-测试报告.md` | 单元测试/功能验收/性能压测结果 |
| `docs/07-检索对比实验报告.md` | 检索模式对比 + 查询改写对比（实验脚本自动产出） |
| `docs/08-答辩演示脚本.md` | 5 分钟演示流程 + 预设 Q&A |

## 开发里程碑

M0 脚手架 ✅ → M1 用户体系 ✅ → M2 文档入库 ✅ → M3 向量化/索引 ✅ → M4 问答闭环 ✅ → M5 性能套件 ✅ → M6 扩展功能+质量 ✅ → M7 收尾 ✅

详见 `docs/01-项目方案计划.md`。
