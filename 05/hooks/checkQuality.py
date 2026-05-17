#!/usr/bin/env python3
"""知识条目五维度质量评分脚本"""

import glob as glob_module
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

BUZZWORD_ZH = [
    "赋能", "抓手", "闭环", "打通", "全链路",
    "底层逻辑", "颗粒度", "对齐", "拉通", "沉淀",
    "强大的", "革命性的",
]

BUZZWORD_EN = [
    "groundbreaking", "revolutionary", "game-changing", "cutting-edge",
    "industry-leading", "world-class", "next-generation",
    "best-in-class", "seamless", "disruptive",
]

SUMMARY_MIN_FULL = 50
SUMMARY_MIN_BASIC = 20
SUMMARY_FULL_SCORE = 25
SUMMARY_BASIC_SCORE = 15
SUMMARY_KEYWORD_BONUS = 5

TECH_KEYWORDS = [
    "agent", "llm", "mcp", "rag", "api", "sdk", "ml", "ai",
    "transformer", "embedding", "token", "inference", "fine-tun",
    "model", "neural", "gpu", "cpu", "docker", "kubernetes",
    "serverless", "microserv", "pipeline", "orchestrat",
    "framework", "runtime", "compiler", "interpreters",
    "protocol", "schema", "vector", "memori", "context",
    "circuit-break", "cache", "queue", "stream",
]

STANDARD_TAG_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")

FIELD_ALIASES: dict[str, list[str]] = {
    "id": ["id"],
    "title": ["title", "full_name", "name"],
    "source_url": ["source_url", "html_url", "url"],
    "status": ["status", "state"],
    "timestamp": [
        "collected_at", "analyzed_at", "created_at",
        "updated_at", "pushed_at", "date", "timestamp",
    ],
}

MAX_WEIGHT = {
    "summary_quality": 25,
    "technical_depth": 25,
    "format_compliance": 20,
    "tag_precision": 15,
    "buzzword_free": 15,
}

GRADE_A_THRESHOLD = 80
GRADE_B_THRESHOLD = 60


@dataclass
class DimensionScore:
    name: str
    score: float
    max_score: float
    detail: str


@dataclass
class QualityReport:
    file_path: str
    item_id: str
    dimensions: list[DimensionScore] = field(default_factory=list)

    @property
    def total_score(self) -> float:
        return sum(d.score for d in self.dimensions)

    @property
    def max_score(self) -> float:
        return sum(d.max_score for d in self.dimensions)

    @property
    def grade(self) -> str:
        pct = (self.total_score / self.max_score * 100) if self.max_score > 0 else 0
        if pct >= GRADE_A_THRESHOLD:
            return "A"
        if pct >= GRADE_B_THRESHOLD:
            return "B"
        return "C"


def _get_field(item: dict, canonical: str):
    for alias in FIELD_ALIASES.get(canonical, [canonical]):
        if alias in item:
            return item[alias]
    return None


def _score_summary_quality(item: dict) -> DimensionScore:
    summary = _get_field(item, "title") or ""
    desc = _get_field(item, "source_url")
    raw_summary = (
        item.get("summary")
        or item.get("description")
        or item.get("desc")
        or ""
    )
    text = raw_summary if raw_summary else summary

    length = len(text)
    score = 0.0
    detail_parts: list[str] = []

    if length >= SUMMARY_MIN_FULL:
        score = SUMMARY_FULL_SCORE
        detail_parts.append(f"长度 {length} 字 (>= {SUMMARY_MIN_FULL})")
    elif length >= SUMMARY_MIN_BASIC:
        score = SUMMARY_BASIC_SCORE
        detail_parts.append(f"长度 {length} 字 (>= {SUMMARY_MIN_BASIC})")
    else:
        detail_parts.append(f"长度 {length} 字 (< {SUMMARY_MIN_BASIC})")

    text_lower = text.lower()
    hits = [kw for kw in TECH_KEYWORDS if kw in text_lower]
    if hits:
        bonus = min(SUMMARY_KEYWORD_BONUS, len(hits) * 2)
        score = min(score + bonus, SUMMARY_FULL_SCORE)
        detail_parts.append(f"技术关键词 x{len(hits)}: +{bonus}")

    return DimensionScore(
        name="摘要质量",
        score=score,
        max_score=MAX_WEIGHT["summary_quality"],
        detail="; ".join(detail_parts),
    )


def _score_technical_depth(item: dict) -> DimensionScore:
    raw = item.get("score") or item.get("relevance_score")
    if raw is None:
        return DimensionScore(
            name="技术深度", score=0, max_score=MAX_WEIGHT["technical_depth"],
            detail="缺少 score/relevance_score 字段",
        )

    try:
        val = int(raw)
    except (ValueError, TypeError):
        return DimensionScore(
            name="技术深度", score=0, max_score=MAX_WEIGHT["technical_depth"],
            detail=f"score 值无效: {raw!r}",
        )

    val = max(1, min(10, val))
    score = round((val / 10) * MAX_WEIGHT["technical_depth"], 1)
    return DimensionScore(
        name="技术深度",
        score=score,
        max_score=MAX_WEIGHT["technical_depth"],
        detail=f"score={val}/10 → {score}/{MAX_WEIGHT['technical_depth']}",
    )


def _score_format_compliance(item: dict) -> DimensionScore:
    fields = ["id", "title", "source_url", "status", "timestamp"]
    found = 0
    missing: list[str] = []

    for f in fields:
        val = _get_field(item, f)
        if val is not None and val != "":
            found += 1
        else:
            missing.append(f)

    score = found * 4
    detail = f"命中 {found}/5"
    if missing:
        detail += f" (缺: {', '.join(missing)})"

    return DimensionScore(
        name="格式规范",
        score=float(score),
        max_score=MAX_WEIGHT["format_compliance"],
        detail=detail,
    )


def _score_tag_precision(item: dict) -> DimensionScore:
    tags = item.get("tags") or item.get("topics") or []
    count = len(tags)

    if count == 0:
        return DimensionScore(
            name="标签精度", score=0, max_score=MAX_WEIGHT["tag_precision"],
            detail="无标签",
        )

    valid = sum(1 for t in tags if STANDARD_TAG_RE.match(str(t)))
    invalid = count - valid

    if 1 <= count <= 3:
        base = 15
    elif count <= 5:
        base = 10
    elif count <= 8:
        base = 6
    else:
        base = 3

    penalty = invalid * 2
    score = max(0, base - penalty)
    detail = f"标签数={count}, 合法={valid}, 非法={invalid}"
    return DimensionScore(
        name="标签精度",
        score=float(score),
        max_score=MAX_WEIGHT["tag_precision"],
        detail=detail,
    )


def _score_buzzword_free(item: dict) -> DimensionScore:
    summary = (
        item.get("summary")
        or item.get("description")
        or item.get("desc")
        or ""
    )
    text = (summary + " " + (item.get("title") or "")).lower()

    found: list[str] = []
    for word in BUZZWORD_ZH:
        if word in text:
            found.append(word)
    for word in BUZZWORD_EN:
        if word in text:
            found.append(word)

    penalty = min(len(found) * 5, MAX_WEIGHT["buzzword_free"])
    score = MAX_WEIGHT["buzzword_free"] - penalty
    detail = f"空洞词 x{len(found)}"
    if found:
        detail += f": {', '.join(found)}"

    return DimensionScore(
        name="空洞词检测",
        score=float(score),
        max_score=MAX_WEIGHT["buzzword_free"],
        detail=detail,
    )


def score_item(item: dict) -> QualityReport:
    report = QualityReport(
        file_path="",
        item_id=str(item.get("id", item.get("full_name", "unknown"))),
    )
    report.dimensions = [
        _score_summary_quality(item),
        _score_technical_depth(item),
        _score_format_compliance(item),
        _score_tag_precision(item),
        _score_buzzword_free(item),
    ]
    return report


def _progress_bar(current: int, total: int, width: int = 30) -> str:
    filled = int(width * current / total) if total > 0 else 0
    bar = "█" * filled + "░" * (width - filled)
    pct = (current / total * 100) if total > 0 else 0
    return f"[{bar}] {pct:5.1f}% ({current}/{total})"


def extract_items(data: dict) -> list[dict]:
    for key in ("repositories", "items", "entries", "data"):
        if key in data and isinstance(data[key], list):
            return data[key]
    return []


def process_file(filepath: str) -> list[QualityReport]:
    path = Path(filepath)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"文件不存在: {filepath}", file=sys.stderr)
        return []

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败 {filepath}: {e}", file=sys.stderr)
        return []

    items = extract_items(data)
    if not items and isinstance(data, list):
        items = data

    if not items:
        print(f"未找到条目: {filepath}", file=sys.stderr)
        return []

    reports: list[QualityReport] = []
    total = len(items)
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        report = score_item(item)
        report.file_path = filepath
        reports.append(report)

        print(f"  {_progress_bar(i, total)} {report.item_id}")

    return reports


def format_report(report: QualityReport) -> str:
    lines = [
        f"  [{report.grade}] {report.item_id}  "
        f"总分 {report.total_score:.0f}/{report.max_score:.0f}",
    ]
    for d in report.dimensions:
        bar_len = 20
        filled = int(bar_len * d.score / d.max_score) if d.max_score > 0 else 0
        bar = "■" * filled + "□" * (bar_len - filled)
        lines.append(
            f"    {d.name:8s} {bar} {d.score:5.1f}/{d.max_score:.0f}  {d.detail}"
        )
    return "\n".join(lines)


GRADE_STYLES = {"A": "\033[32m", "B": "\033[33m", "C": "\033[31m"}
RESET = "\033[0m"


def format_grade(grade: str) -> str:
    color = GRADE_STYLES.get(grade, "")
    return f"{color}{grade}{RESET}"


def expand_args(args: list[str]) -> list[str]:
    result: list[str] = []
    for arg in args:
        matches = glob_module.glob(arg)
        if matches:
            result.extend(sorted(matches))
        else:
            result.append(arg)
    return result


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "用法: uv run hooks/check_quality.py <json_file> [json_file2 ...]",
            file=sys.stderr,
        )
        print(
            "支持通配符: uv run hooks/check_quality.py 'knowledge/raw/*.json'",
            file=sys.stderr,
        )
        sys.exit(1)

    files = expand_args(sys.argv[1:])
    all_reports: list[QualityReport] = []

    for filepath in files:
        print(f"\n{'─' * 50}")
        print(f"文件: {filepath}")
        reports = process_file(filepath)
        all_reports.extend(reports)

    if not all_reports:
        print("\n无可用条目", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'═' * 50}")
    print("质量评分汇总")
    print(f"{'═' * 50}")

    for report in all_reports:
        grade_str = format_grade(report.grade)
        lines = [
            f"  [{grade_str}] {report.item_id}  "
            f"总分 {report.total_score:.0f}/{report.max_score:.0f}",
        ]
        for d in report.dimensions:
            bar_len = 20
            filled = int(bar_len * d.score / d.max_score) if d.max_score > 0 else 0
            bar = "■" * filled + "□" * (bar_len - filled)
            lines.append(
                f"    {d.name:8s} {bar} {d.score:5.1f}/{d.max_score:.0f}  {d.detail}"
            )
        print("\n".join(lines))

    grade_counts = {"A": 0, "B": 0, "C": 0}
    for r in all_reports:
        grade_counts[r.grade] += 1

    print(f"\n{'─' * 50}")
    print(
        f"条目总数: {len(all_reports)}  "
        f"A={grade_counts['A']}  B={grade_counts['B']}  C={grade_counts['C']}"
    )

    avg = sum(r.total_score for r in all_reports) / len(all_reports)
    print(f"平均分: {avg:.1f}/{all_reports[0].max_score:.0f}")

    if grade_counts["C"] > 0:
        print(f"\n存在 C 级条目 ({grade_counts['C']} 个)，质量不达标")
        sys.exit(1)
    else:
        print("\n所有条目质量达标")
        sys.exit(0)


if __name__ == "__main__":
    main()