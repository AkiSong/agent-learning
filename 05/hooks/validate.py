#!/usr/bin/env python3
"""校验知识库 JSON 文件"""

import glob as glob_module
import json
import re
import sys
from pathlib import Path

REQUIRED_REPO_FIELDS: dict[str, type] = {
    "id": str,
    "full_name": str,
    "description": str,
    "summary": str,
    "html_url": str,
    "topics": list,
    "stargazers_count": int,
}

ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})?$"
)

MIN_DESCRIPTION_LEN = 20
MIN_TOPICS_COUNT = 1
RELEVANCE_SCORE_RANGE = (1, 10)


def _check_field_type(value, expected_type: type) -> bool:
    """检查字段类型, bool 不算 int"""
    if expected_type is int and isinstance(value, bool):
        return False
    return isinstance(value, expected_type)


def validate_file(filepath: str) -> list[str]:
    """校验单个 JSON 文件, 返回错误列表"""
    errors: list[str] = []
    path = Path(filepath)

    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        errors.append(f"文件不存在: {filepath}")
        return errors

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        errors.append(f"JSON 解析失败: {e}")
        return errors

    # collected_at (ISO 8601)
    collected_at = data.get("collected_at")
    if collected_at is None:
        errors.append("缺少顶层字段: collected_at")
    elif not isinstance(collected_at, str):
        errors.append(f"collected_at 类型错误: 期望 str, 实际 {type(collected_at).__name__}")
    elif not ISO8601_RE.match(collected_at):
        errors.append(f"collected_at 格式非 ISO 8601: {collected_at}")

    # repositories
    repos = data.get("repositories")
    if repos is None:
        errors.append("缺少顶层字段: repositories")
        return errors
    if not isinstance(repos, list):
        errors.append(f"repositories 类型错误: 期望 list, 实际 {type(repos).__name__}")
        return errors

    for i, repo in enumerate(repos):
        prefix = f"repositories[{i}]"

        if not isinstance(repo, dict):
            errors.append(f"{prefix}: 期望 dict, 实际 {type(repo).__name__}")
            continue

        # 必填字段: 存在性 + 类型
        for field, expected_type in REQUIRED_REPO_FIELDS.items():
            if field not in repo:
                errors.append(f"{prefix}: 缺少必填字段 '{field}'")
            elif not _check_field_type(repo[field], expected_type):
                actual = type(repo[field]).__name__
                errors.append(
                    f"{prefix}: 字段 '{field}' 类型错误, "
                    f"期望 {expected_type.__name__}, 实际 {actual}"
                )

        # description 长度
        desc = repo.get("description")
        if isinstance(desc, str) and len(desc) < MIN_DESCRIPTION_LEN:
            errors.append(
                f"{prefix}: description 长度不足 {MIN_DESCRIPTION_LEN} 字 (当前 {len(desc)} 字)"
            )

        # topics 数量
        topics = repo.get("topics")
        if isinstance(topics, list) and len(topics) < MIN_TOPICS_COUNT:
            errors.append(f"{prefix}: topics 不能为空")

        # html_url 协议
        url = repo.get("html_url")
        if isinstance(url, str) and not url.startswith("https://"):
            errors.append(f"{prefix}: html_url 必须以 https:// 开头: {url}")

        # relevance_score 范围
        score = repo.get("relevance_score")
        if score is not None:
            if isinstance(score, bool):
                errors.append(f"{prefix}: relevance_score 类型错误, 期望 int")
            elif isinstance(score, int) and not (
                RELEVANCE_SCORE_RANGE[0] <= score <= RELEVANCE_SCORE_RANGE[1]
            ):
                errors.append(
                    f"{prefix}: relevance_score 超出范围 "
                    f"[{RELEVANCE_SCORE_RANGE[0]}, {RELEVANCE_SCORE_RANGE[1]}]: {score}"
                )

    return errors


def expand_args(args: list[str]) -> list[str]:
    """展开命令行参数中的 glob 模式"""
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
        print("用法: uv run hooks/validate.py <json_file> [json_file2 ...]", file=sys.stderr)
        sys.exit(1)

    files = expand_args(sys.argv[1:])
    total_files = 0
    failed_files = 0
    total_errors = 0

    for filepath in files:
        total_files += 1
        errors = validate_file(filepath)
        if errors:
            failed_files += 1
            total_errors += len(errors)
            print(f"\nFAIL {filepath}:")
            for err in errors:
                print(f"  - {err}")
        else:
            print(f"PASS {filepath}")

    print(f"\n{'=' * 40}")
    print(f"文件总数: {total_files}")
    print(f"通过: {total_files - failed_files}")
    print(f"失败: {failed_files}")
    print(f"错误总数: {total_errors}")

    sys.exit(1 if failed_files > 0 else 0)


if __name__ == "__main__":
    main()