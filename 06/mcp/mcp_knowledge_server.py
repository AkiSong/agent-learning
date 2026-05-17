#!/usr/bin/env python3
"""MCP Knowledge Server - 本地知识库搜索服务

通过 JSON-RPC 2.0 over stdio 提供知识库搜索、文章获取和统计功能。
"""

import json
import os
import sys
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(SCRIPT_DIR, "..")
KNOWLEDGE_DIR = os.path.join(PROJECT_DIR, "knowledge")
ARTICLES_DIR = os.path.join(KNOWLEDGE_DIR, "articles")
INDEX_PATH = os.path.join(ARTICLES_DIR, "index.json")

TOOLS = [
    {
        "name": "search_articles",
        "description": "按关键词搜索文章标题和摘要，返回匹配的文章列表",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词（匹配标题、摘要、标签）",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回结果数量上限，默认5",
                    "default": 5,
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_article",
        "description": "按 ID 获取文章完整内容，返回文章的详细数据",
        "inputSchema": {
            "type": "object",
            "properties": {
                "article_id": {
                    "type": "string",
                    "description": "文章 ID，如 langgenius/dify",
                }
            },
            "required": ["article_id"],
        },
    },
    {
        "name": "knowledge_stats",
        "description": "返回知识库统计信息（文章总数、来源分布、热门标签）",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def load_index():
    if not os.path.exists(INDEX_PATH):
        return {"articles": [], "total_articles": 0, "updated_at": ""}
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def search_articles(keyword, limit=5):
    index = load_index()
    kw = keyword.lower()
    results = []
    for article in index.get("articles", []):
        searchable = " ".join(
            [
                article.get("title", ""),
                article.get("summary", ""),
                " ".join(article.get("tags", [])),
                article.get("id", ""),
            ]
        ).lower()
        if kw in searchable:
            results.append(
                {
                    "id": article["id"],
                    "title": article.get("title", ""),
                    "summary": article.get("summary", ""),
                    "tags": article.get("tags", []),
                    "relevance_score": article.get("relevance_score", 0),
                    "url": article.get("url", ""),
                    "date": article.get("date", ""),
                }
            )
    results.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    return results[:limit]


def get_article(article_id):
    index = load_index()
    article_meta = None
    for article in index.get("articles", []):
        if article["id"] == article_id:
            article_meta = article
            break
    if article_meta is None:
        return {"error": f"文章未找到: {article_id}"}
    file_rel = article_meta.get("file_path", "")
    file_abs = os.path.join(PROJECT_DIR, file_rel)
    if not os.path.exists(file_abs):
        return {"error": f"文章文件不存在: {file_rel}"}
    with open(file_abs, "r", encoding="utf-8") as f:
        raw = f.read()
    if file_abs.endswith(".json"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"raw": raw, "format": "json-parse-error"}
    else:
        data = {
            "id": article_id,
            "title": article_meta.get("title", ""),
            "url": article_meta.get("url", ""),
            "tags": article_meta.get("tags", []),
            "relevance_score": article_meta.get("relevance_score", 0),
            "date": article_meta.get("date", ""),
            "content": raw,
            "format": "markdown",
        }
    return data


def knowledge_stats():
    index = load_index()
    articles = index.get("articles", [])
    source_counter = Counter()
    tag_counter = Counter()
    date_counter = Counter()
    for article in articles:
        file_path = article.get("file_path", "")
        file_abs = os.path.join(PROJECT_DIR, file_path)
        if file_path.endswith(".json") and os.path.exists(file_abs):
            try:
                with open(file_abs, "r", encoding="utf-8") as f:
                    data = json.load(f)
                source_counter[data.get("source", "unknown")] += 1
            except (json.JSONDecodeError, OSError):
                source_counter["unknown"] += 1
        else:
            source_counter["unknown"] += 1
        date_counter[article.get("date", "unknown")] += 1
        for tag in article.get("tags", []):
            tag_counter[tag] += 1
    return {
        "total_articles": len(articles),
        "updated_at": index.get("updated_at", ""),
        "source_distribution": dict(source_counter),
        "date_distribution": dict(date_counter),
        "top_tags": [{"tag": t, "count": c} for t, c in tag_counter.most_common(30)],
    }


def handle_request(request):
    method = request.get("method", "")
    params = request.get("params", {}) or {}
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "knowledge-server",
                    "version": "1.0.0",
                    "description": "本地知识库搜索服务 - 提供 GitHub Trending 等技术趋势文章的检索与统计",
                },
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}

        if tool_name == "search_articles":
            result = search_articles(
                keyword=arguments.get("keyword", ""),
                limit=arguments.get("limit", 5),
            )
        elif tool_name == "get_article":
            result = get_article(arguments.get("article_id", ""))
        elif tool_name == "knowledge_stats":
            result = knowledge_stats()
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"未知工具: {tool_name}",
                },
            }

        text = json.dumps(result, ensure_ascii=False, indent=2)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"未知方法: {method}"},
    }


def main():
    buf = ""
    for chunk in iter(lambda: sys.stdin.read(1), ""):
        buf += chunk
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                sys.stderr.write(f"[mcp] 无效 JSON: {line[:80]}\n")
                continue
            if request.get("id") is None and request.get("method", "").startswith("notifications/"):
                continue
            try:
                response = handle_request(request)
            except Exception as e:
                response = {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {"code": -32603, "message": str(e)},
                }
            if response is None:
                continue
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()