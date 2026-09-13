#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
# @Time     : 2026/05/07 13:35
# @Filename : wiki-archive.py
# @Author   : Alan_HSU

"""Wiki Query 归档脚本 — 将优质问答 / 探索成果归档回 Wiki。

好的查询答案不应该只停留在对话里。这个脚本将问答对归档为
源文件，下次编译时自动变成新的 Wiki 页面，探索和提问也在
不断丰富知识库。

支持两种模式：
1. 交互式：从 .specs/wiki-archive/ 下的待归档文件处理
2. 命令行：直接传入问题和答案

归档产物写入 71-Wiki/71-01-raw/（源③），编译后自动进入 71-02-wiki/。

Usage:
    # 交互模式：处理待归档文件
    python3 wiki-archive.py

    # 命令行：直接归档一条问答
    python3 wiki-archive.py --question "X和Y有什么关系？" --answer "根据分析..."

    # 从文件读取
    python3 wiki-archive.py --from-file qa.md

    # 查看待归档列表
    python3 wiki-archive.py --list

    # 归档并触发编译
    python3 wiki-archive.py --question "..." --answer "..." --compile
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── 日志 ──────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(module)s.%(funcName)s:%(lineno)d - %(message)s",
)
logger = logging.getLogger(__name__)

# ── 路径常量 ──────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
WIKI_ROOT = SCRIPT_DIR.parent
RAW_DIR = WIKI_ROOT / "71-01-raw"          # 归档目标（源③）
ARCHIVE_QUEUE = WIKI_ROOT / "71-03-output" / "archive-queue"  # 待归档队列
COMPILE_SCRIPT = SCRIPT_DIR / "wiki-compile.py"


# ── 归档文件生成 ──────────────────────────────────────────────────────────────

def generate_archive_filename(question: str) -> str:
    """根据问题生成文件名：日期 + 问题关键词。"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    # 提取问题中的核心关键词（前20字，去标点）
    keywords = re.sub(r"[？?！!。，,、：:；;\"'《》\[\]【】()（）\s]+", "-", question[:40])
    keywords = re.sub(r"-+", "-", keywords).strip("-")
    if not keywords:
        keywords = "query-archive"
    return f"{date_str}-QA-{keywords}.md"


def build_archive_content(question: str, answer: str, source: str = "对话归档") -> str:
    """构建归档 Markdown 文件内容。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    # 从问题提取候选 tags
    tags = extract_tags_from_question(question)

    content = f"""---
title: "Q&A: {question[:50]}"
aliases: []
category: Wiki-Archive
created: {now}
updated: {now}
tags: [{', '.join(tags)}]
source: "{source}"
---

# Q&A: {question}

## 问题

{question}

## 回答

{answer}

## 来源

{source}
"""
    return content


def extract_tags_from_question(question: str) -> list[str]:
    """从问题中提取候选标签。"""
    tags = ["KnowledgeBase", "QA-Archive"]

    # 检测常见技术关键词
    tech_keywords = {
        "openclaw": "OpenClaw",
        "obsidian": "Obsidian",
        "agent": "Agent",
        "llm": "LLM",
        "wiki": "Wiki",
        "rag": "RAG",
        "mcp": "MCP",
        "claude": "Claude",
        "hermes": "Hermes",
        "skill": "Skill",
        "cron": "Cron",
        "telegram": "Telegram",
        "cursor": "Cursor",
        "codex": "Codex",
        "知识库": "知识管理",
        "知识管理": "知识管理",
        "自动化": "自动化",
        "编译": "编译",
        "测试": "测试",
        "部署": "部署",
        "微服务": "微服务",
        "前端": "前端",
        "后端": "后端",
    }

    q_lower = question.lower()
    for keyword, tag in tech_keywords.items():
        if keyword in q_lower and tag not in tags:
            tags.append(tag)
        if len(tags) >= 8:
            break

    return tags


# ── 归档执行 ──────────────────────────────────────────────────────────────────

def archive_qa(question: str, answer: str, source: str = "对话归档") -> Path:
    """归档一条问答，写入 71-01-raw/，返回文件路径。"""
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    filename = generate_archive_filename(question)
    filepath = RAW_DIR / filename

    # 避免重名
    counter = 1
    while filepath.exists():
        stem = filepath.stem
        filepath = RAW_DIR / f"{stem}-{counter}.md"
        counter += 1

    content = build_archive_content(question, answer, source)
    filepath.write_text(content, encoding="utf-8")
    logger.info("归档文件已写入: %s", filepath)

    return filepath


def trigger_compile() -> int:
    """触发增量编译。"""
    logger.info("触发 Wiki 增量编译...")
    result = subprocess.run(
        [sys.executable, str(COMPILE_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        logger.error("编译失败: %s", result.stderr[:500])
    else:
        logger.info("编译完成")
    return result.returncode


# ── 队列处理 ──────────────────────────────────────────────────────────────────

def list_pending_archives() -> list[Path]:
    """列出待归档队列中的文件。"""
    if not ARCHIVE_QUEUE.exists():
        return []
    return sorted(ARCHIVE_QUEUE.glob("*.md"))


def process_queue() -> list[Path]:
    """处理待归档队列，将所有文件移入 71-01-raw/。"""
    pending = list_pending_archives()
    if not pending:
        logger.info("待归档队列为空")
        return []

    archived = []
    for src_file in pending:
        # 读取内容，提取 Q&A
        content = src_file.read_text(encoding="utf-8")

        # 尝试解析问答格式
        question, answer = parse_qa_content(content)

        if question and answer:
            dest = archive_qa(question, answer, source="队列归档")
            # 删除已处理的队列文件
            src_file.unlink()
            archived.append(dest)
            logger.info("队列文件 %s → %s", src_file.name, dest.name)
        else:
            # 无法解析则直接复制
            dest = RAW_DIR / src_file.name
            dest.write_text(content, encoding="utf-8")
            src_file.unlink()
            archived.append(dest)
            logger.warning("队列文件 %s 格式无法解析，已直接复制", src_file.name)

    return archived


def parse_qa_content(content: str) -> tuple[str, str]:
    """从 Markdown 内容中解析问题和答案。"""
    question = ""
    answer = ""

    # 尝试匹配 ## 问题 / ## 回答 格式
    q_match = re.search(r"^##\s*(?:问题|Question)\s*\n+(.*?)(?=\n##\s)", content, re.DOTALL | re.MULTILINE)
    a_match = re.search(r"^##\s*(?:回答|Answer)\s*\n+(.*)", content, re.DOTALL | re.MULTILINE)

    if q_match:
        question = q_match.group(1).strip()
    if a_match:
        answer = a_match.group(1).strip()

    # 兜底：用标题当问题，正文当答案
    if not question:
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if title_match:
            question = title_match.group(1).strip()

    if not answer:
        # 去掉 frontmatter 和标题，剩余当答案
        body = re.sub(r"^---.*?---\s*", "", content, flags=re.DOTALL)
        body = re.sub(r"^#\s+.+$", "", body, flags=re.MULTILINE).strip()
        if body:
            answer = body

    return question, answer


# ── 主函数 ────────────────────────────────────────────────────────────────────

def main() -> None:
    """主入口。"""
    parser = argparse.ArgumentParser(description="Wiki query 归档工具")
    parser.add_argument("--question", "-q", help="问题内容")
    parser.add_argument("--answer", "-a", help="回答内容")
    parser.add_argument("--from-file", "-f", type=Path, help="从文件读取问答内容")
    parser.add_argument("--source", "-s", default="对话归档", help="来源标注")
    parser.add_argument("--compile", action="store_true", help="归档后触发编译")
    parser.add_argument("--list", action="store_true", help="列出待归档队列")
    parser.add_argument("--process-queue", action="store_true", help="处理待归档队列")
    args = parser.parse_args()

    if args.list:
        pending = list_pending_archives()
        if pending:
            print(f"待归档文件 ({len(pending)} 个)：")
            for f in pending:
                print(f"  - {f.name}")
        else:
            print("待归档队列为空")
        return

    if args.process_queue:
        archived = process_queue()
        print(f"已归档 {len(archived)} 个文件")
        if args.compile and archived:
            trigger_compile()
        return

    # 命令行直接归档
    question = args.question or ""
    answer = args.answer or ""

    if args.from_file:
        content = args.from_file.read_text(encoding="utf-8")
        q, a = parse_qa_content(content)
        question = question or q
        answer = answer or a

    if not question:
        logger.error("缺少问题内容，请使用 --question 或 --from-file")
        sys.exit(1)

    if not answer:
        logger.error("缺少回答内容，请使用 --answer 或 --from-file")
        sys.exit(1)

    filepath = archive_qa(question, answer, args.source)
    print(f"归档完成: {filepath}")

    if args.compile:
        rc = trigger_compile()
        if rc == 0:
            print("编译完成，新页面已生成")
        else:
            print(f"编译失败 (rc={rc})，请手动执行 wiki-compile.py")


if __name__ == "__main__":
    main()
