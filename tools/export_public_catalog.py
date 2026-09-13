#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
# @Time     : 2026/09/13 12:21
# @Filename : export_public_catalog.py
# @Author   : Alan_Hsu

"""从本地剪藏导出不含正文的公开文章目录。"""

from __future__ import annotations

import argparse
import csv
import logging
import re
from dataclasses import dataclass
from pathlib import Path


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(module)s.%(funcName)s:%(lineno)d - %(message)s",
)
logger = logging.getLogger(__name__)

WIKI_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = WIKI_ROOT / "71-01-raw"
DEFAULT_OUTPUT_PATH = WIKI_ROOT / "catalog" / "articles.csv"
HTTP_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


@dataclass(frozen=True)
class CatalogRecord:
    """公开文章目录的一行元数据。"""

    title: str
    tags: str
    source: str
    created: str


def clean_scalar(value: str) -> str:
    """清洗 frontmatter 的单行标量，移除 YAML 引号。"""
    return value.strip().strip('"\'').strip()


def parse_frontmatter(path: Path) -> dict[str, object]:
    """读取 Markdown frontmatter 中目录所需字段，不读取正文。

    Args:
        path: 待解析 Markdown 文件路径。

    Returns:
        仅包含 title、source、created、tags 等头部字段的字典。
    """
    with path.open(encoding="utf-8", errors="replace") as handle:
        lines = []
        first_line = handle.readline()
        if first_line.strip() != "---":
            return {}
        for line in handle:
            if line.strip() == "---":
                break
            lines.append(line.rstrip("\n"))
        else:
            return {}

    result: dict[str, object] = {}
    active_list_key: str | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line.startswith((" ", "\t")) and stripped.startswith("-") and active_list_key:
            values = result.setdefault(active_list_key, [])
            if isinstance(values, list):
                values.append(clean_scalar(stripped[1:]))
            continue
        if ":" not in stripped:
            active_list_key = None
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        active_list_key = None
        if value.startswith("[") and value.endswith("]"):
            result[key] = [clean_scalar(item) for item in value[1:-1].split(",") if item.strip()]
        elif value:
            result[key] = clean_scalar(value)
        else:
            result[key] = []
            active_list_key = key
    return result


def record_from_file(path: Path) -> CatalogRecord | None:
    """将单个 Markdown 的公开元数据转换为目录记录。

    没有 HTTP/HTTPS 原文链接的文件不导出，防止公开本地路径或其他私有引用。
    """
    metadata = parse_frontmatter(path)
    source = str(metadata.get("source", "")).strip()
    if not HTTP_URL_RE.match(source):
        return None

    raw_tags = metadata.get("tags", [])
    tags = raw_tags if isinstance(raw_tags, list) else [str(raw_tags)]
    return CatalogRecord(
        title=str(metadata.get("title") or path.stem).strip(),
        tags=" | ".join(tag for tag in tags if tag),
        source=source,
        created=str(metadata.get("created", "")).strip(),
    )


def escape_markdown_cell(value: str) -> str:
    """转义 Markdown 表格单元格中的分隔符，保持一条记录只占一行。"""
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def write_markdown_catalog(records: list[CatalogRecord], output_path: Path) -> None:
    """将公开元数据写成可直接点击原文的 Markdown 表格。"""
    lines = [
        "# 公开文章目录",
        "",
        "> 仅包含标题、个人标签、原文链接和收藏时间；不包含正文、摘要或图片。",
        "",
        "| 标题 | 标签 | 原文链接 | 收藏时间 |",
        "| --- | --- | --- | --- |",
    ]
    for record in records:
        title = escape_markdown_cell(record.title)
        tags = escape_markdown_cell(record.tags)
        created = escape_markdown_cell(record.created)
        lines.append(
            f"| {title} | {tags} | [打开原文]({record.source}) | {created} |"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_catalog(source_dir: Path, output_path: Path) -> int:
    """导出标题、标签、原文链接和创建时间到 CSV 与 Markdown 表格。

    Args:
        source_dir: 本地剪藏 Markdown 根目录。
        output_path: 公开 CSV 文件输出路径。

    Returns:
        已导出的记录数。
    """
    records = [
        record
        for path in source_dir.rglob("*.md")
        if path.name != "README.md"
        if (record := record_from_file(path)) is not None
    ]
    records.sort(key=lambda record: (record.created, record.title), reverse=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["title", "tags", "source", "created"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(record.__dict__ for record in records)
    write_markdown_catalog(records, output_path.with_suffix(".md"))
    logger.info("公开目录已生成: records=%d output=%s", len(records), output_path)
    return len(records)


def main() -> None:
    """解析参数并生成公开目录。"""
    parser = argparse.ArgumentParser(description="导出不含正文的公开文章目录")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR, help="剪藏目录")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="CSV 输出路径")
    args = parser.parse_args()
    export_catalog(args.source_dir, args.output)


if __name__ == "__main__":
    main()
