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

帮我编写 hooks/check_quality.py 脚本，用于给知识条目做 5 维度质量评分

需求：
1. 支持单文件和多文件（通配符 *.json）两种输入模式
2. 使用 dataclass 定义 DimensionScore 和 QualityReport 结构
3. 5 个评分维度及满分（加权总分 100 分）：
   - 摘要质量 (25 分)：>= 50 字满分，>= 20 字基本分，含技术关键词有奖励
   - 技术深度 (25 分)：基于文章 score 字段（1-10 映射到 0-25）
   - 格式规范 (20 分)：id、title、source_url、status、时间戳五项各 4 分
   - 标签精度 (15 分)：1-3 个合法标签最佳，有标准标签列表校验
   - 空洞词检测 (15 分)：不含"赋能""抓手""闭环""打通"等空洞词
4. 空洞词黑名单分中英两组：
   - 中文：赋能、抓手、闭环、打通、全链路、底层逻辑、颗粒度、对齐、拉通、沉淀、强大的、革命性的
   - 英文：groundbreaking、revolutionary、game-changing、cutting-edge 等
5. 输出可视化进度条 + 每维度得分 + 等级 A/B/C
6. 等级标准：A >= 80, B >= 60, C < 60
7. 退出码：存在 C 级返回 1，否则返回 0

编码规范：遵循 PEP 8，使用 pathlib 和 dataclass，不依赖第三方库


读取 AGENTS.md 中的「知识条目格式」，
创建一个关于 Harness Engineering 的知识条目，
保存到 knowledge/raw/hook-test.json。
所有必填字段都要有，status 设为 "draft"。


需求：
1. 监听 tool.execute.after 事件
2. 当 Agent 使用 write 或 edit 工具写入 knowledge/articles/*-enriched.json 时触发
3. 触发时调用 uv run hooks/checkQuality.py <file_path>
4. 使用 Bun Shell API（$ 模板字符串）执行命令
5. 必须使用 .nothrow() 而非 .quiet()（.quiet() 会导致 OpenCode 卡死）
6. 必须用 try/catch 包裹所有 shell 调用（未捕获异常会阻塞 Agent）