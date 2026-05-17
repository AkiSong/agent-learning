"""知识库四步自动化流水线

Step 1: Collect  — 从 GitHub Search API 采集 AI 相关内容
Step 2: Analyze  — 调用 LLM 对每条内容进行摘要/评分/标签分析
Step 3: Organize — 去重 + 格式标准化 + 校验
Step 4: Save     — 将文章保存为独立 JSON 文件到 knowledge/articles/

用法:
    python pipeline/pipeline.py --limit 20           # 完整采集
    python pipeline/pipeline.py --limit 5            # 只采集 5 条
    python pipeline/pipeline.py --limit 5 --dry-run  # 干跑模式
    python pipeline/pipeline.py --verbose            # 详细日志
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from model_client import chat_with_retry

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "knowledge" / "raw"
ARTICLES_DIR = PROJECT_ROOT / "knowledge" / "articles"

GITHUB_API_URL = "https://api.github.com/search/repositories"

AI_TOPIC_QUERIES = [
    "topic:ai topic:agent stars:>5",
    "topic:llm stars:>10",
    "topic:mcp topic:agent stars:>3",
    "topic:large-language-model stars:>10",
    "topic:ai-agent stars:>5",
    "topic:model-context-protocol stars:>3",
]

logger = logging.getLogger("pipeline")


def _build_date_filter() -> str:
    now = datetime.now(timezone.utc)
    seven_days_ago = (now - __import__("datetime").timedelta(days=7)).strftime("%Y-%m-%d")
    return f"pushed:>{seven_days_ago}"


def collect(
    limit: int = 20,
    github_token: str | None = None,
) -> list[dict[str, Any]]:
    """Step 1: 从 GitHub Search API 采集最近 7 天内 AI 相关的开源仓库

    在每个 topic 查询中附加 pushed:>YYYY-MM-DD 日期过滤条件，
    合并去重后按 stars 降序排序，取 top limit 条。
    """
    logger.info("Step 1: 采集开始 (limit=%d, 最近7天)", limit)

    date_filter = _build_date_filter()
    logger.info("  日期过滤: %s", date_filter)

    headers: dict[str, str] = {
        "Accept": "application/vnd.github.v3+json",
    }
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    all_repos: dict[str, dict[str, Any]] = {}

    with httpx.Client(timeout=30.0) as client:
        for base_query in AI_TOPIC_QUERIES:
            if len(all_repos) >= limit * 2:
                break

            query = f"{base_query} {date_filter}"
            params = {
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": min(30, limit),
            }
            logger.debug("搜索: %s", query)

            try:
                resp = client.get(GITHUB_API_URL, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as exc:
                logger.warning("GitHub API 请求失败 (%d): %s", exc.response.status_code, query)
                continue
            except httpx.TimeoutException:
                logger.warning("GitHub API 请求超时: %s", query)
                continue

            items = data.get("items", [])
            logger.info("  查询 '%s' 返回 %d 条", base_query, len(items))

            for repo in items:
                repo_id = repo["full_name"]
                if repo_id in all_repos:
                    continue
                all_repos[repo_id] = {
                    "id": repo_id,
                    "full_name": repo_id,
                    "description": repo.get("description") or "",
                    "html_url": repo["html_url"],
                    "stargazers_count": repo.get("stargazers_count", 0),
                    "language": repo.get("language") or "Unknown",
                    "topics": repo.get("topics", []),
                    "created_at": repo.get("created_at", ""),
                    "pushed_at": repo.get("pushed_at", ""),
                }

            time.sleep(0.5)

    repos = sorted(all_repos.values(), key=lambda r: r["stargazers_count"], reverse=True)
    repos = repos[:limit]

    logger.info("Step 1 完成: 采集到 %d 个仓库", len(repos))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw_file = RAW_DIR / f"github-trending-{today}.json"
    raw_data = {
        "date": today,
        "source": "github-trending",
        "collected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repositories": repos,
    }
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_file.write_text(
        json.dumps(raw_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("原始数据已保存到 %s", raw_file)

    return repos


def _build_analysis_prompt(repo: dict[str, Any]) -> str:
    description = repo.get("description") or repo.get("summary") or "无描述"
    topics = repo.get("topics") or repo.get("tags", [])
    topics_str = ", ".join(topics) if topics else "无"
    language = repo.get("language", "Unknown")
    stars = repo.get("stargazers_count", 0)
    return f"""请分析以下 GitHub 仓库，返回 JSON 格式的分析结果。

仓库信息:
- 名称: {repo['full_name']}
- 描述: {description}
- 语言: {language}
- Stars: {stars}
- 话题: {topics_str}

请返回以下 JSON 格式（不要包含其他文字）:
{{
    "summary": "一句话中文摘要，格式：项目名 — 做什么 + 为什么值得关注",
    "highlights": ["亮点1", "亮点2", "亮点3"],
    "score": 1到10的整数评分,
    "score_reason": "评分理由（中文）",
    "tags": ["tag1", "tag2", "tag3"]
}}

评分标准:
- 9-10: 生产级工具，解决重要痛点
- 7-8: 有价值，通用性较好
- 5-6: 有参考价值但适用范围窄
- 3-4: 信息不足或差异化不明确
- 1-2: 与 AI/LLM/Agent 无关

tags 要求:
- 使用英文小写，连字符分隔
- 3-5 个标签
- 优先使用已有标准标签

注意：只返回 JSON，不要包含 markdown 代码块标记或其他文字。"""


_ANALYSIS_SYSTEM_PROMPT = (
    "你是一个技术分析助手，擅长分析开源项目的价值。"
    "请严格按照要求的 JSON 格式返回结果，不要添加任何额外文字。"
)


def analyze(repos: list[dict[str, Any]], dry_run: bool = False) -> list[dict[str, Any]]:
    """Step 2: 调用 LLM 对每条内容进行摘要/评分/标签分析"""
    logger.info("Step 2: 分析开始 (%d 个仓库, dry_run=%s)", len(repos), dry_run)

    analyzed_items: list[dict[str, Any]] = []

    for i, repo in enumerate(repos, 1):
        logger.info("  [%d/%d] 分析 %s", i, len(repos), repo["full_name"])

        if dry_run:
            summary = (
                repo.get("summary")
                or repo.get("description")
                or f"{repo['full_name']} — AI/LLM related project"
            )
            tags = repo.get("tags") or repo.get("topics", [])
            analyzed_items.append({
                "id": repo["id"],
                "full_name": repo["full_name"],
                "summary": summary,
                "highlights": repo.get("highlights", []),
                "score": repo.get("score", repo.get("relevance_score", 5)),
                "score_reason": repo.get("score_reason", "干跑模式，使用默认评分"),
                "tags": [t.lower().replace("_", "-").replace(" ", "-") for t in tags[:5]],
                "html_url": repo["html_url"],
                "language": repo.get("language", "Unknown"),
                "stargazers_count": repo.get("stargazers_count", 0),
            })
            continue

        prompt = _build_analysis_prompt(repo)

        try:
            response = chat_with_retry(
                messages=[
                    {"role": "system", "content": _ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=1024,
            )

            content = response.content.strip()
            content = re.sub(r"^```json\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

            analysis = json.loads(content)

            item = {
                "id": repo["id"],
                "full_name": repo["full_name"],
                "summary": analysis.get("summary", repo.get("description", "")),
                "highlights": analysis.get("highlights", []),
                "score": int(analysis.get("score", 5)),
                "score_reason": analysis.get("score_reason", ""),
                "tags": [t.lower().replace("_", "-").replace(" ", "-") for t in analysis.get("tags", [])],
                "html_url": repo["html_url"],
                "language": repo.get("language", "Unknown"),
                "stargazers_count": repo.get("stargazers_count", 0),
            }
            analyzed_items.append(item)
            logger.debug("  评分: %d, 摘要: %s", item["score"], item["summary"][:50])

        except json.JSONDecodeError as exc:
            logger.warning("  %s: JSON 解析失败 — %s", repo["full_name"], exc)
            analyzed_items.append(_fallback_item(repo))
        except Exception as exc:
            logger.warning("  %s: LLM 分析失败 — %s", repo["full_name"], exc)
            analyzed_items.append(_fallback_item(repo))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    enriched_file = RAW_DIR / f"github-trending-{today}-enriched.json"
    enriched_data = {
        "date": today,
        "source": "pipeline",
        "analyzed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": analyzed_items,
    }
    enriched_file.write_text(
        json.dumps(enriched_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("分析数据已保存到 %s", enriched_file)
    logger.info("Step 2 完成: 分析了 %d 个仓库", len(analyzed_items))

    return analyzed_items


def _fallback_item(repo: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": repo["id"],
        "full_name": repo["full_name"],
        "summary": repo.get("description", ""),
        "highlights": [],
        "score": 5,
        "score_reason": "LLM 分析失败，使用默认评分",
        "tags": [t.lower().replace("_", "-").replace(" ", "-") for t in repo.get("topics", [])[:5]],
        "html_url": repo["html_url"],
        "language": repo.get("language", "Unknown"),
        "stargazers_count": repo.get("stargazers_count", 0),
    }


_REQUIRED_FIELDS = ("id", "full_name", "summary", "score", "tags", "html_url")


def organize(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Step 3: 去重 + 格式标准化 + 校验"""
    logger.info("Step 3: 整理开始 (%d 条)", len(items))

    seen_ids: set[str] = set()
    deduped: list[dict[str, Any]] = []
    duplicates = 0

    for item in items:
        if item["id"] in seen_ids:
            duplicates += 1
            continue
        seen_ids.add(item["id"])
        deduped.append(item)

    organized: list[dict[str, Any]] = []
    skipped = 0

    for item in deduped:
        missing = [f for f in _REQUIRED_FIELDS if f not in item or not item[f]]
        if missing:
            logger.warning("  %s: 缺少必填字段 %s，已跳过", item.get("full_name", "?"), missing)
            skipped += 1
            continue

        item["score"] = max(1, min(10, int(item.get("score", 5))))
        item["relevance_score"] = item["score"]

        tags = item.get("tags", [])
        if isinstance(tags, list):
            item["tags"] = [t.lower().replace("_", "-").replace(" ", "-") for t in tags if isinstance(t, str)][:5]

        organized.append(item)

    logger.info(
        "Step 3 完成: 输入 %d → 去重 %d → 校验后 %d (跳过 %d)",
        len(items),
        len(deduped),
        len(organized),
        skipped + duplicates,
    )
    return organized


def save(items: list[dict[str, Any]], dry_run: bool = False) -> None:
    """Step 4: 将文章保存为独立 JSON 文件到 knowledge/articles/"""
    logger.info("Step 4: 保存开始 (%d 条, dry_run=%s)", len(items), dry_run)

    if not items:
        logger.info("没有文章需要保存")
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_dir = ARTICLES_DIR / today

    if dry_run:
        for item in items:
            slug = item["full_name"].replace("/", "-").lower()
            file_path = date_dir / f"{today}-{slug}.json"
            logger.info("  [DRY-RUN] 将保存: %s", file_path)
        logger.info("Step 4 (dry-run) 完成")
        return

    date_dir.mkdir(parents=True, exist_ok=True)

    index_file = ARTICLES_DIR / "index.json"
    index: dict[str, Any] = {"updated_at": "", "total_articles": 0, "articles": []}
    if index_file.exists():
        try:
            index = json.loads(index_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("无法读取索引文件，将创建新索引")

    existing_ids = {a["id"] for a in index.get("articles", [])}
    articles_list: list[dict[str, Any]] = index.get("articles", [])

    for item in items:
        slug = item["full_name"].replace("/", "-").lower()
        file_name = f"{today}-{slug}.json"
        file_path = date_dir / file_name

        article_data = {
            "id": item["id"],
            "full_name": item["full_name"],
            "source": "github-trending",
            "html_url": item["html_url"],
            "collected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "summary": item["summary"],
            "highlights": item.get("highlights", []),
            "relevance_score": item["relevance_score"],
            "score": item.get("score", 5),
            "score_reason": item.get("score_reason", ""),
            "tags": item.get("tags", []),
            "language": item.get("language", "Unknown"),
            "stargazers_count": item.get("stargazers_count", 0),
            "status": "published",
        }

        file_path.write_text(
            json.dumps(article_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("  已保存: %s", file_path)

        index_entry = {
            "id": item["id"],
            "title": item["full_name"],
            "slug": slug,
            "url": item["html_url"],
            "date": today,
            "file_path": f"knowledge/articles/{today}/{file_name}",
            "relevance_score": item["relevance_score"],
            "tags": item.get("tags", []),
            "summary": item["summary"],
        }

        if item["id"] not in existing_ids:
            articles_list.append(index_entry)
            existing_ids.add(item["id"])
        else:
            for i, a in enumerate(articles_list):
                if a["id"] == item["id"]:
                    articles_list[i] = index_entry
                    break

    index_data = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_articles": len(articles_list),
        "articles": articles_list,
    }
    index_file.write_text(
        json.dumps(index_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("索引已更新: %s (共 %d 篇)", index_file, len(articles_list))
    logger.info("Step 4 完成: 保存了 %d 篇文章", len(items))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="知识库四步自动化流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  python pipeline/pipeline.py --limit 20           # 完整采集
  python pipeline/pipeline.py --limit 5            # 只采集 5 条
  python pipeline/pipeline.py --limit 5 --dry-run  # 干跑模式
  python pipeline/pipeline.py --verbose            # 详细日志
  python pipeline/pipeline.py --input knowledge/raw/github-trending-2026-05-12.json
""",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="采集仓库数量上限 (默认: 20)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="干跑模式，不写入文件",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="输出详细日志",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="跳过采集步骤，使用指定的原始数据 JSON 文件",
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("=== 知识库流水线启动 ===")
    logger.info("参数: limit=%d, dry_run=%s, input=%s", args.limit, args.dry_run, args.input)

    github_token = os.getenv("GITHUB_TOKEN")

    # ── Step 1: Collect ──
    if args.input:
        input_path = Path(args.input)
        if not input_path.is_absolute():
            input_path = PROJECT_ROOT / input_path
        logger.info("使用输入文件: %s", input_path)
        raw_data = json.loads(input_path.read_text(encoding="utf-8"))
        repos = raw_data.get("repositories", raw_data.get("items", []))
        logger.info("从文件读取 %d 个仓库", len(repos))
    else:
        repos = collect(limit=args.limit, github_token=github_token)
        if not repos:
            logger.error("采集失败: 未获取到任何仓库")
            sys.exit(1)

    # ── Step 2: Analyze ──
    analyzed = analyze(repos, dry_run=args.dry_run)

    # ── Step 3: Organize ──
    organized = organize(analyzed)

    # ── Step 4: Save ──
    save(organized, dry_run=args.dry_run)

    logger.info("=== 流水线执行完毕 ===")


if __name__ == "__main__":
    main()