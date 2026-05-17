---
name: github-trending
description: 当需要采集 GitHub 热门开源项目的时候使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# GitHub Trending 采集技能

## 使用场景

- 需要采集 GitHub 每周热门开源项目信息
- 需要生成结构化的趋势摘要供知识库使用
- 需要关注 AI / LLM / Agent 方向的热门项目动态

## 执行步骤

### 1. 搜索热门仓库（GitHub API）

使用 WebFetch 调用 GitHub Search API，获取近期 stars 增长最多的仓库：

```
https://api.github.com/search/repositories?q=created:>2026-05-05&sort=stars&order=desc&per_page=100
```

可针对不同时间范围多次搜索，扩大覆盖面。

### 2. 提取信息

从 API 返回结果中提取每个仓库的以下字段：

| 字段 | 说明 |
|------|------|
| `full_name` | 仓库全名（owner/repo） |
| `description` | 仓库描述 |
| `html_url` | 仓库地址 |
| `stargazers_count` | 当前 star 数 |
| `language` | 主要编程语言 |
| `topics` | 仓库标签 |
| `created_at` | 创建时间 |
| `pushed_at` | 最近推送时间 |

### 3. 过滤

保留与 **AI / LLM / Agent** 相关的项目，丢弃以下类型：

- awesome 列表（仓库名以 `awesome-` 开头）
- 纯教程 / 学习资源仓库
- 无实质代码的资源合集

判断依据：topics 包含 `ai`、`llm`、`large-language-model`、`agent`、`machine-learning`、`deep-learning`、`nlp` 等标签，或 description 中含有关键词。

### 4. 去重

多次搜索可能返回相同仓库，按 `full_name` 去重，仅保留一条记录。

### 5. 撰写一句话中文摘要

为每个保留的项目撰写中文摘要，遵循公式：

> **项目名 + 做什么 + 为什么关注**

示例："OpenAI Agents SDK — 构建多 Agent 应用的 Python 框架，低价门槛和官方支持使其成为 Agent 开发首选"

### 6. 按 star 排序提取 Top 15

将项目按 `stargazers_count` 降序排列，取前 15 个。

### 7. 输出 JSON

将结果写入 `knowledge/raw/github-trending-YYYY-MM-DD.json`，格式如下：

```json
{
  "date": "2026-05-12",
  "source": "github-trending",
  "collected_at": "2026-05-12T12:00:00Z",
  "repositories": [
    {
      "id": "",
      "full_name": "owner/repo",
      "description": "原始英文描述",
      "summary": "一句话中文摘要",
      "html_url": "https://github.com/owner/repo",
      "stargazers_count": 12345,
      "language": "Python",
      "topics": ["ai", "agent"],
      "created_at": "2026-01-01T00:00:00Z",
      "pushed_at": "2026-05-10T00:00:00Z",
      "relevance_score": 9
    }
  ]
}
```

## 注意事项

- GitHub API 有速率限制（未认证 60 次/小时），如遇 403 响应，等待后重试，最多 3 次
- `relevance_score` 取值 1-10，基于项目与 AI/LLM/Agent 的相关程度评分
- 确保 JSON 使用 2 空格缩进，UTF-8 编码
- 幂等性：重复运行同一天的采集应覆盖同一文件，而非创建新文件
- 网络请求失败时记录错误并跳过，不中断整体流程
- 数据格式异常时，写入 `knowledge/raw/errors-{date}.json` 供人工排查

## 输出格式

文件路径：`knowledge/raw/github-trending-YYYY-MM-DD.json`

见步骤 7 中的 JSON 结构。

## 质量检查清单

采集完成后，逐条检查：

- [ ] 每个条目都有非空的 `id`、`title`、`url`
- [ ] `collected_at` 时间戳为当前采集时间，格式为 ISO 8601
- [ ] `url` 格式正确，以 `https://` 开头
- [ ] GitHub 数据的 `stars` 为数字类型
- [ ] 无重复条目（同一个 `id` 不出现两次）
- [ ] JSON 格式正确，可通过 `JSON.parse()` 校验
- [ ] 文件名包含当天日期