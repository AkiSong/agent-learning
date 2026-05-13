---
name: hn-digest
description: 当需要对分析结果整理成结构化的知识库文章时使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - Write
---

# HN Digest 知识库文章生成技能

## 使用场景

- 需要将采集的分析结果整理成结构化的知识库文章
- 需要筛选高质量条目并生成 Markdown 文档
- 需要维护知识库索引文件

## 执行步骤

### 1. 读取最新分析文件

使用 Glob 查找 `knowledge/raw/` 目录下最新的 enriched 文件：

```
knowledge/raw/github-trending-*-enriched.json
```

选取日期最新（文件名中日期最大）的文件，使用 Read 读取其内容。

### 2. 筛选高质量条目

从 JSON 数组中筛选 **`relevance_score` >= 7.0** 的条目，作为文章生成候选。

### 3. 为每个条目创建文档

为每个筛选出的条目生成 Markdown 文件，路径规则：

- **日期子目录**: `knowledge/articles/{date}/`，date 从条目的 `collected_at` 中提取（`YYYY-MM-DD`）
- **slug 生成规则**:
  - 从仓库名（`owner/repo-name`）转换
  - 将 `/` 替换为 `-`
  - 全部小写
  - 例: `openai/agents-sdk` → `openai-agents-sdk`

最终路径: `knowledge/articles/{date}/{date}-{slug}.md`

### 4. 按 Markdown 模板生成文章内容

模板如下：

```markdown
# {title}

## 基本信息

- **仓库地址**: [{id}]({url})
- **主要语言**: {language}
- **Stars**: {stars}
- **相关度评分**: {relevance_score}/10
- **采集时间**: {collected_at}

## 技术摘要

{summary}

## 趋势分析

{trend_analysis}

## 标签

{tags}
```

字段映射说明：

| 模板占位符 | JSON 字段 | 说明 |
|-----------|----------|------|
| `{title}` | `full_name` 或 `id` | 文章标题 |
| `{id}` | `id` | 仓库全名，作为链接文字 |
| `{url}` | `html_url` | 仓库地址 |
| `{language}` | `language` | 主要编程语言 |
| `{stars}` | `stargazers_count` | Star 数 |
| `{relevance_score}` | `relevance_score` | 相关度评分 |
| `{collected_at}` | `collected_at` | 采集时间 |
| `{summary}` | `summary` | 中文摘要 |
| `{trend_analysis}` | `trend_analysis` | 趋势分析内容 |
| `{tags}` | `topics` | 标签，每行一个，格式为 `- tag-name` |

### 5. 更新索引文件

索引文件路径: `knowledge/articles/index.json`

- 若文件不存在，新建并初始化
- 若文件已存在，使用 Read 读取现有内容
- 新增或更新文章条目，条目格式：

```json
{
  "articles": [
    {
      "id": "openai-agents-sdk",
      "title": "openai/agents-sdk",
      "date": "2026-05-12",
      "slug": "openai-agents-sdk",
      "path": "2026-05-12/2026-05-12-openai-agents-sdk.md",
      "relevance_score": 9,
      "collected_at": "2026-05-12T12:00:00Z"
    }
  ]
}
```

- 按 `id` 去重：若已有相同 `id` 的条目，更新其内容；否则追加
- 写入时保持 JSON 2 空格缩进，UTF-8 编码

## 注意事项

- 写入文章前确保 `knowledge/articles/{date}/` 目录存在，不存在时先创建
- 文件名和路径中的日期必须与条目的 `collected_at` 日期一致
- 文件命名严格遵循 `{YYYY-MM-DD}-{slug}.md` 格式
- 所有文本保持 UTF-8，中文内容不要转义
- `relevance_score` 低于 7.0 的条目不生成文章
- 幂等性：同一天同一仓库的文章可覆盖更新，不同日期的文章独立存在
- `trend_analysis` 字段在 enriched 数据中可能为空，为空时输出「暂无趋势分析」
- JSON 索引文件中的 `articles` 数组按 `date` 降序排列，新增文章时追加到索引，已有文章（相同 `id` + `date`）时更新信息，不要删除历史条目
- 语言约定：正文、摘要使用中文；标签、文件名、JSON 键名、技术术语保留英文

## 质量检查清单

生成完成后，逐条检查：

- [ ] 每个 Markdown 文件包含完整的章节（基本信息、技术摘要、趋势分析、标签）
- [ ] `relevance_score` 均为 >= 7.0 的条目
- [ ] 文件路径符合 `knowledge/articles/{date}/{date}-{slug}.md` 规则
- [ ] slug 全部小写，`/` 已替换为 `-`
- [ ] `index.json` 格式正确，可通过 `JSON.parse()` 校验
- [ ] 所有链接（`url`）以 `https://` 开头