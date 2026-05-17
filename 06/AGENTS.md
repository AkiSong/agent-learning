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
- 每个知识条目必须包含：`id`, `full_name`, `source`, `html_url`, `collected_at`, `summary`, `topics`, `relevance_score`

### 语言约定
- 代码、JSON 键名、文件名：英文
- 摘要、分析、注释、正文：中文
- 标签（tags）：英文小写，用连字符分隔（如 `large-language-model`）

## 技术栈
- **运行时**：OpenCode + LLM（DeepSeek / Qwen）
- **数据源**：GitHub API v3、Hacker News API (firebase)
- **输出格式**：JSON
- **版本管理**：Git

