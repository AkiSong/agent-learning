# GitHub Trending Knowledge Base System

## 项目概述

构建一个自动从 GitHub 获取每日/每周热门仓库（Trending）信息，并生成中文趋势摘要的知识库系统。

## 核心功能

1. **数据采集**：调用 GitHub API 获取 GitHub Trending 
2. **智能摘要**：为热门仓库生成中文描述和趋势分析
3. **知识存储**：结构化存储仓库元数据、摘要、趋势历史
4. **质量审核**：审核知识条目质量，确保格式、内容、数据一致性合规

## 项目结构

```
.
├── AGENTS.md                 # OPENCODE Mem
├── README.md                 # 面向人类用户的说明
├── .env.example              # 环境变量模板
└── knowledge/
    ├── raw                   # 原始信息（json）
    ├── quality-report        # 审核报告（md）
    └── articles              # 整理后的信息（md）
```

## 编码规范

### 文件命名
- 原始数据：`knowledge/raw/{source}-{YYYY-MM-DD}.json`
  - 例：`knowledge/raw/github-trending-2026-03-17.json`
- 知识条目：`knowledge/articles/{YYYY-MM-DD}/{YYYY-MM-DD}-{slug}.md`
  - 例：`knowledge/articles/2026-03-17/2026-03-17-openai-agents-sdk.md`
- 索引文件：`knowledge/articles/index.json`
- 审核报告：`knowledge/quality-report/{YYYY-MM-DD}.md`

### JSON 格式
- 使用 2 空格缩进
- 日期格式：ISO 8601（`YYYY-MM-DDTHH:mm:ssZ`）
- 字符编码：UTF-8
- 每个知识条目必须包含：`id`, `title`, `source`, `url`, `collected_at`, `summary`, `tags`, `relevance_score`

### 语言约定
- 代码、JSON 键名、文件名：英文
- 摘要、分析、注释、正文：中文
- 标签（tags）：英文小写，用连字符分隔（如 `large-language-model`）

## 工作流规则

### 四阶段流水线

```
[Collector] ──采集──→ knowledge/raw/
                          │
[Analyzer]  ──分析──→ knowledge/raw/ (enriched)
                          │
[Organizer] ──整理──→ knowledge/articles/
                          │
[Reviewer]  ──审核──→ knowledge/quality-report/
```

**阶段说明**：

| 阶段 | Agent | 职责 | 持久化时机 |
|------|-------|------|-----------|
| 1 | Collector | 从 GitHub API 采集原始数据 | 对话中返回给主 Agent |
| 1.5 | Organizer | 将原始数据写入 `knowledge/raw/` | **立即写入** |
| 2 | Analyzer | 读取原始数据，生成中文摘要和趋势分析 | 对话中返回给主 Agent |
| 2.5 | Organizer | 将 enriched 数据写入 `knowledge/raw/`，生成文章和索引 | **立即写入** |
| 3 | Reviewer | 审核文章、索引、enriched 数据的质量和一致性 | 输出审核报告 |

### Agent 协作规则

1. **单向数据流**：Collector → Analyzer → Organizer → Reviewer，不可反向
2. **职责隔离**：每个 Agent 只操作自己权限范围内的文件
3. **幂等性**：重复运行同一天的采集不应产生重复条目
4. **质量门控**：
   - Analyzer 评分低于 6 的条目，Organizer 应丢弃
   - Reviewer 审核为 `rejected` 的批次，需由 Organizer 修正后重新审核
5. **可追溯**：每个条目保留 `source_url` 和 `collected_at` 用于溯源
6. **阶段内即时持久化**：Collector 和 Analyzer 产出后，主 Agent 应立即委派 Organizer 写入文件，避免上下文过长丢失数据

### Agent 调用方式

在 OpenCode 中使用 `@` 语法调用特定 Agent：

```
@collector 采集今天的 GitHub Trending 数据
@organizer 将采集结果写入 knowledge/raw/
@analyzer 分析 knowledge/raw/github-trending-2026-03-17.json
@organizer 将分析结果写入 knowledge/raw/ 并生成文章
@reviewer 审核今天生成的所有知识条目 审核结果写入 knowledge/quality-report
```

也可以在对话中要求主 Agent 依次委派子 Agent，实现流水线作业。**流水线作业在每个阶段结束后立即调用 organizer 写入文件**

### 错误处理
- 网络请求失败时，记录错误并跳过该条目，不中断整体流程
- API 限流时，等待后重试，最多 3 次
- 数据格式异常时，写入 `knowledge/raw/errors-{date}.json` 供人工排查

## 技术栈
- **运行时**：OpenCode + LLM（DeepSeek / Qwen）
- **数据源**：GitHub API v3、Hacker News API (firebase)
- **输出格式**：JSON
- **版本管理**：Git

