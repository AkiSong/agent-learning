创建 .opencode/skills/github-trending/SKILL.md 文件

格式要求:
- 头部用YAML frontmatter (name,description,allow-tools)
- 正文使用markdown格式,包含:使用场景,执行步骤,注意事项,输出格式

内容要求:
- name: github-trending
- description:当需要采集github 每周热门开源项目的时候使用此技能
- allowed-tools: Read,Grep,Glob,WebFecth
- 7个执行步骤:
    1. 搜索热门仓库(github api)  
    2. 提取信息 
    3. 过滤(保留和AI/LLM/AGENT有关项目,丢弃awesome列/教程) 
    4. 去重(多次搜索的重复项目只保留一条) 
    5. 撰写一句话中文摘要(公式: 项目名+做什么+为什么关注)
    6. 按star排序提取top15
    7. 输出JSON到knowledge/raw/github-trending-YYYY-MM-DD.json


参考 .opencode/skills/github-trending/SKILL.md 的格式，
帮我创建 .opencode/skills/hn-digest/SKILL.md。

- name: hn-digest
- description: 当需要对分析结果整理成结构化的知识库文章时使用此技能
- allowed-tools: Read, Grep, Glob, Write
- 5个执行步骤：
  1. 读取 knowledge/raw/github-trending-{YYYY-MM-DD}-enriched.json 最新分析文件
  2. 筛选 **评分 >= 7.0** 的条目
  3. 为每个筛选出的条目创建文档`knowledge/articles/{date}/{date}-{slug}.md`，**date**：日期子目录 ， **slug 生成规则**: a. 从仓库名（`owner/repo-name`）转换， b. 将 `/` 替换为 `-` ， c. 全部小写。 例：`openai/agents-sdk` → `openai-agents-sdk`
  4. 按 Markdown 模板生成文章内容
  5. 索引文件`knowledge/articles/index.json`(不存在就新建)，读取现有索引（如果存在），新增或更新文章条目。
    
- **Markdown 模板**:

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