#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
# @Time     : 2026/05/01 06:28
# @Filename : wiki-compile.py
# @Author   : Alan_Hsu

"""一键编译 71-Wiki raw 资料到 wiki（多源目录 + 增量模式）。

支持从多个源目录收集 Markdown 原始资料，增量编译到 wiki。
未编译或修改过的文件才会被处理，已编译且未变更的自动跳过。

Usage:
    # 全量编译（默认增量，跳过已编译且未变的文件）
    python3 wiki-compile.py

    # 只编译指定文件
    python3 wiki-compile.py --target "某篇文章.md"

    # 强制全量重编译（忽略增量状态）
    python3 wiki-compile.py --full

    # 自定义源目录（覆盖默认三目录）
    python3 wiki-compile.py --raw-dirs /path/a /path/b
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

# ── 日志 ──────────────────────────────────────────────────────────────────────

def setup_logging() -> None:
    """初始化日志配置。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(module)s.%(funcName)s:%(lineno)d - %(message)s",
    )


# ── 路径常量 ──────────────────────────────────────────────────────────────────

WIKI_ROOT = Path(__file__).resolve().parents[1]

# 开源仓库默认只读取自身的公开原料。完整 Vault 的其他资料目录需要
# 通过 --raw-dirs 显式传入，避免误把本地私有笔记或未授权剪藏带入产物。
DEFAULT_RAW_DIRS: list[Path] = [WIKI_ROOT / "71-01-raw"]

DEFAULT_WIKI_DIR = WIKI_ROOT / "71-02-wiki"
DEFAULT_OUTPUT_DIR = WIKI_ROOT / "71-03-output"
STATE_FILE = DEFAULT_OUTPUT_DIR / "compile-state.json"


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class ArticleMeta:
    """编译输入文章的基础元数据。"""

    source_path: Path
    title: str
    created: str
    summary: str
    concepts: list[str]
    body: str


@dataclass
class CompileState:
    """增量编译状态，记录已编译文件及其 mtime。"""

    compiled: dict[str, float] = field(default_factory=dict)  # key=源文件绝对路径, value=mtime
    last_run: str = ""

    @classmethod
    def load(cls, path: Path) -> CompileState:
        """从 JSON 加载状态。"""
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                compiled=data.get("compiled", {}),
                last_run=data.get("last_run", ""),
            )
        except (json.JSONDecodeError, OSError):
            logging.warning("状态文件损坏，将重新编译全部: %s", path)
            return cls()

    def save(self, path: Path) -> None:
        """保存状态到 JSON。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"compiled": self.compiled, "last_run": self.last_run},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def is_compiled(self, file_path: Path) -> bool:
        """判断文件是否已编译且未变更。"""
        key = str(file_path.resolve())
        if key not in self.compiled:
            return False
        try:
            current_mtime = file_path.stat().st_mtime
        except OSError:
            return False
        return self.compiled[key] >= current_mtime

    def mark_compiled(self, file_path: Path) -> None:
        """标记文件为已编译。"""
        key = str(file_path.resolve())
        try:
            self.compiled[key] = file_path.stat().st_mtime
        except OSError:
            self.compiled[key] = datetime.now().timestamp()


# ── NLP 工具 ─────────────────────────────────────────────────────────────────

STOPWORDS = {
    "the", "and", "for", "that", "with", "this", "from", "have", "into", "your",
    "karpathy", "agent", "wiki", "llm", "obsidian", "文章", "一个", "我们", "他们",
    "因为", "可以", "不是", "就是", "什么", "这样", "这个", "进行", "工作", "知识",
    "资料", "系统", "自己", "如果", "以及", "通过", "时候", "需要", "做到", "已经",
    "不是", "没有", "不是", "不会", "但是", "所以", "还是", "或者", "之后", "之后",
    "一下", "一些", "那些", "这些", "这种", "那种", "如何", "为什么", "怎么", "什么",
}

IGNORED_TAGS = {"clippings", "clip", "raw", "draft", "inbox"}

# 标题中常见的关键词 → 概念映射
TITLE_KEYWORD_MAP = {
    r"llm\s*wiki": "LLM Wiki",
    r"obsidian": "Obsidian",
    r"\bagent\b": "Agent 知识编译",
    r"harness\s*engineering": "Harness Engineering",
    r"vibe\s*coding": "Vibe Coding",
    r"skill\s*creator": "Skill Creator",
    r"openclaw": "OpenClaw",
    r"andrej|karpathy": "Andrej Karpathy",
    r"知识库|知识管理": "知识管理",
    r"自动化测试|软件测试": "软件测试",
}


def strip_frontmatter(content: str) -> str:
    """移除 frontmatter，避免污染摘要和关键词提取。"""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].lstrip()
    return content


def slugify(text: str) -> str:
    """把标题转成相对稳定的文件名片段。"""
    normalized = re.sub(r"[：:·•丨|/]+", "-", text)
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff\-]+", "", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized[:80] or "untitled"


def extract_frontmatter_value(content: str, key: str) -> str | None:
    """从 frontmatter 提取单值字段。"""
    match = re.search(rf"^{re.escape(key)}:\s*[\"']?(.*?)[\"']?\s*$", content, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return None


def extract_title(content: str, fallback: str) -> str:
    """提取文章标题，优先 frontmatter，其次一级标题。"""
    title = extract_frontmatter_value(content, "title")
    if title:
        # 清理 frontmatter 中的引号包裹和 markdown 加粗标记
        title = title.strip("'\"")
        title = re.sub(r"\*{1,2}(.*?)\*{1,2}", r"\1", title)  # 去掉 **bold** 和 *italic*
        if title:
            return title
    heading = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if heading:
        return heading.group(1).strip()
    return fallback


def clean_markdown(text: str) -> str:
    """清理 markdown 标记，便于做摘要和关键词提取。"""
    # 用逐行状态机清理 fenced code，避免 ``` 不闭合时正则失效或误吞正文
    cleaned_lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)
    text = re.sub(r"`[^`]+`", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^\)]+\)", " ", text)
    text = re.sub(r"\[[^\]]+\]\([^\)]+\)", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[#>*_~\-]{1,}", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_summary(content: str) -> str:
    """提取摘要。优先使用文章首个有效段落。"""
    content = strip_frontmatter(content)
    # 优先找 ## 摘要 / Summary / 概述 段落
    summary_heading = re.search(
        r"^#{1,3}\s+(?:摘要|Summary|概述)\s*\n+(.+?)(?=\n#{1,3}\s+|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if summary_heading:
        line = clean_markdown(summary_heading.group(1)).split("。", 1)[0].strip()
        if line:
            return line[:180]
    # 退而求其次：第一个有效段落
    paragraphs = re.split(r"\n{2,}", content)
    for paragraph in paragraphs:
        plain = clean_markdown(paragraph)
        if len(plain) >= 40:
            return plain[:180]
    return "(no summary)"


def tokenize(text: str) -> list[str]:
    """分词，兼顾中英文。"""
    return re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}|[\u4e00-\u9fff]{2,}", text)


def extract_concepts(content: str, title: str) -> list[str]:
    """基于标题关键词映射、标签和词频提取概念。"""
    # 分桶收集：显式 wikilink（作者意图）优先级最高，其次标题映射与 tags，最后才用词频补足。
    wikilink_concepts: list[str] = []
    mapped_concepts: list[str] = []
    tag_concepts: list[str] = []
    freq_concepts: list[str] = []

    # 1) 标题关键词映射
    title_lower = title.lower()
    for pattern, concept_name in TITLE_KEYWORD_MAP.items():
        if re.search(pattern, title_lower):
            mapped_concepts.append(concept_name)

    # 2) frontmatter tags
    tags_line = extract_frontmatter_value(content, "tags")
    if tags_line:
        tags = re.findall(r"[A-Za-z0-9\-\u4e00-\u9fff]+", tags_line)
        for tag in tags:
            lowered = tag.lower()
            if lowered in STOPWORDS or lowered in IGNORED_TAGS:
                continue
            if lowered == "llm-wiki":
                tag_concepts.append("LLM Wiki")
                continue
            tag_concepts.append(tag)

    # 2.5) 显式 wikilink 目标（[[概念]]）——把“作者明确标注的概念”优先纳入概念池
    # 说明：当前 Wiki 产物中存在大量 [[Skill]] / [[Token]] / [[Karpathy]] 这类显式互链，
    # 如果不把这些目标纳入 concepts，则会出现大量“断链/孤岛”的假阳性，并且概念页无法覆盖作者意图。
    # 仅从“非代码区域”抽取，避免把教程里的 `[[示例]]` / `![[示例]]` 写法当成真实概念导致污染
    # 注意：raw 资料里可能存在不规范的 ``` fence（比如拷贝网页导致 fence 不闭合），
    # 用正则跨段删除会误吞后续正文；这里用逐行状态机更稳。
    out_lines: list[str] = []
    in_fence = False
    for line in content.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out_lines.append(line)
    content_no_code = "\n".join(out_lines)
    content_no_code = re.sub(r"`[^`]+`", "", content_no_code)  # inline code
    for raw in re.findall(r"\[\[(.+?)\]\]", content_no_code):
        target = raw.split("|", 1)[0].strip()
        if not target:
            continue
        # 排除显然不是“概念页”的目标：路径、URL、附件
        if any(sep in target for sep in ("/", "\\")):
            continue
        if target.startswith(("http://", "https://")):
            continue
        if re.search(r"\.(png|jpg|jpeg|gif|svg|webp|bmp|tiff|pdf)$", target, re.IGNORECASE):
            continue
        if target.lower().startswith("image "):
            continue
        # 过滤明显异常的目标（半截 markdown / 代码片段）
        if any(ch in target for ch in ("[", "]", "(", ")", "`")):
            continue
        if len(target) > 80:
            continue
        lowered = target.lower()
        if lowered in IGNORED_TAGS:
            continue
        # STOPWORDS 不在这里拦截：显式 wikilink 的优先级高于 stopwords（作者意图优先）
        wikilink_concepts.append(target)

    # 3) 正文词频（仅在前两步未产出足够概念时启用）
    if len(mapped_concepts) + len(tag_concepts) + len(wikilink_concepts) < 3:
        plain_body = clean_markdown(strip_frontmatter(content))
        token_counter = Counter(
            token for token in tokenize(plain_body) if token.lower() not in STOPWORDS
        )
        for token, count in token_counter.most_common(12):
            if count < 2:
                continue
            if re.fullmatch(r"[A-F0-9]{4,}", token):  # 过滤 SVG/HTML 碎片
                continue
            if len(token) <= 1:
                continue
            freq_concepts.append(token)
            if len(freq_concepts) >= 8:
                break

    def _dedup_and_clean(items: list[str]) -> list[str]:
        out: list[str] = []
        seen_local: set[str] = set()
        for concept in items:
            key = concept.lower()
            if key in seen_local:
                continue
            if concept.strip("- ") == "":
                continue
            if re.fullmatch(r"[A-F0-9]{4,}", concept):
                continue
            seen_local.add(key)
            out.append(concept)
        return out

    wikilink_concepts = _dedup_and_clean(wikilink_concepts)
    mapped_concepts = _dedup_and_clean(mapped_concepts)
    tag_concepts = _dedup_and_clean(tag_concepts)
    freq_concepts = _dedup_and_clean(freq_concepts)

    # 组合策略：
    # - 显式 wikilink（作者意图）尽量不丢：最多保留 24 个（避免极端爆炸）
    # - 其余概念用于补充语义聚类：最多 12 个
    result: list[str] = []
    seen: set[str] = set()

    for concept in wikilink_concepts[:24]:
        key = concept.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(concept)

    for concept in (mapped_concepts + tag_concepts + freq_concepts):
        if len(result) >= 36:
            break
        key = concept.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(concept)

    return result


def extract_body(content: str) -> str:
    """提取正文片段，避免整篇原文直接复制。"""
    content = strip_frontmatter(content)
    # 避免把代码块里的 “## 标题” 当成正文结构（常见于 Obsidian 教程/模板示例）
    non_code_lines: list[str] = []
    in_fence = False
    for line in content.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            non_code_lines.append(line)
    content_no_code = "\n".join(non_code_lines)

    sections = re.findall(r"^##\s+(.+)$", content_no_code, re.MULTILINE)
    lines = [f"- {section.strip()}" for section in sections[:8]]
    if lines:
        return "\n".join(lines)

    plain = clean_markdown(content_no_code)
    sentences = re.split(r"[。！？.!?]", plain)
    bullet_lines = [f"- {sentence.strip()}" for sentence in sentences if len(sentence.strip()) > 20]
    return "\n".join(bullet_lines[:8])


# ── 编译管线 ──────────────────────────────────────────────────────────────────

def parse_article(md_path: Path) -> ArticleMeta:
    """解析 raw 文章。"""
    content = md_path.read_text(encoding="utf-8")
    title = extract_title(content, md_path.stem)
    created = extract_frontmatter_value(content, "created") or datetime.now().strftime("%Y-%m-%d")
    # created 可能是 "2026-04-13 14:30" 格式，只取日期部分做前缀
    return ArticleMeta(
        source_path=md_path,
        title=title,
        created=created[:10] if len(created) >= 10 else created,
        summary=extract_summary(content),
        concepts=extract_concepts(content, title),
        body=extract_body(content),
    )


def article_output_path(wiki_dir: Path, article: ArticleMeta) -> Path:
    """返回文章输出路径。"""
    date_prefix = article.created[:10]
    filename = f"{date_prefix}-{slugify(article.title)}.md"
    return wiki_dir / "articles" / filename


def render_article(article: ArticleMeta, output_path: Path, peer_articles: list[tuple[str, Path]] | None = None) -> str:
    """渲染 article 页面。

    Args:
        article: 文章元数据
        output_path: 输出路径
        peer_articles: 共享概念的其他文章列表 [(title, relative_path), ...]
    """
    updated = datetime.now().strftime("%Y-%m-%d %H:%M")
    # 概念链接
    related_lines = [f"- [[{concept}]]" for concept in article.concepts[:5]]
    # 同概念文章互链（实现 backlinks）
    if peer_articles:
        related_lines.append("")  # 空行分隔
        related_lines.append("## 同主题文章")
        for peer_title, peer_rel in peer_articles[:8]:
            related_lines.append(f"- [[{peer_rel.with_suffix('').as_posix()}|{peer_title}]]")
    related = "\n".join(related_lines) or "- 暂无"
    # 来源用纯文本路径，不用 wikilink（避免 lint 误报断裂链接）
    source_str = str(article.source_path.resolve())
    try:
        source_str = str(article.source_path.relative_to(VAULT_ROOT))
    except ValueError:
        pass
    return f"""---
title: {article.title}
aliases: []
category: Wiki
created: {updated}
updated: {updated}
tags: [KnowledgeBase, Wiki, Article]
---

# {article.title}

## 摘要

{article.summary}

## 核心概念

{', '.join(article.concepts) if article.concepts else '待补充'}

## 内容拆解

{article.body or '- 待补充'}

## 来源

- `{source_str}`

## 相关页面

{related}
"""


def concept_output_path(wiki_dir: Path, concept: str) -> Path:
    """返回概念页路径。"""
    return wiki_dir / "concepts" / f"{concept}.md"


def render_concept(concept: str, related_articles: list[tuple[str, Path, str]]) -> str:
    """渲染概念页。如果已有内容则追加新来源，否则新建。"""
    updated = datetime.now().strftime("%Y-%m-%d %H:%M")
    source_lines = "\n".join(
        f"- [[{path.with_suffix('').as_posix()}|{title}]]：{summary}"
        for title, path, summary in related_articles
    )
    return f"""---
title: {concept}
aliases: []
category: Wiki
created: {updated}
updated: {updated}
tags: [KnowledgeBase, Wiki, Concept]
---

# {concept}

## 摘要

{concept} 是从当前 raw 资料中抽取出的核心主题，后续可继续随着更多文章摄入迭代定义。

## 当前语境

- 该概念由自动编译脚本从 raw 资料的标题、标签和正文高频词中提取
- 当前定义偏"工作索引"，适合后续人工再精炼

## 相关来源

{source_lines}
"""


# ── 文件收集 ──────────────────────────────────────────────────────────────────

def collect_raw_files(raw_dirs: list[Path], target: str | None, state: CompileState, full: bool) -> list[Path]:
    """收集所有源目录中待编译的 Markdown 文件。

    增量模式：跳过已编译且未变更的文件。
    full 模式：不跳过任何文件。
    """
    if target:
        # 指定了单文件目标，在各源目录中查找
        for raw_dir in raw_dirs:
            candidate = (raw_dir / target).resolve()
            if candidate.exists():
                return [candidate]
            # 也尝试直接按绝对路径
            if Path(target).resolve().exists():
                return [Path(target).resolve()]
        raise FileNotFoundError(f"指定文件在所有源目录中均不存在: {target}")

    all_files: list[Path] = []
    for raw_dir in raw_dirs:
        if not raw_dir.exists():
            logging.warning("源目录不存在，跳过: %s", raw_dir)
            continue
        for md_file in sorted(raw_dir.rglob("*.md")):
            # 跳过 README、隐藏文件、.venv、.obsidian 等
            if md_file.name == "README.md":
                continue
            rel_parts = md_file.relative_to(raw_dir).parts
            if any(part.startswith(".") for part in rel_parts):
                continue
            if any(part == ".venv" or part == ".obsidian" or part == "node_modules" for part in rel_parts):
                continue

            # 增量判断
            if not full and state.is_compiled(md_file):
                continue

            all_files.append(md_file)

    return all_files


# ── 后处理 ────────────────────────────────────────────────────────────────────

def write_compile_report(output_dir: Path, compiled: list[dict], skipped: int) -> None:
    """写入编译结果报告。"""
    report_path = output_dir / "compile-report.json"
    report_path.write_text(
        json.dumps(
            {
                "compiled": compiled,
                "skipped": skipped,
                "total_sources": len(compiled) + skipped,
                "updated_at": datetime.now().isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def run_followup_script(script_path: Path, *args: str) -> None:
    """执行后续脚本并在失败时记录。"""
    command = [sys.executable, str(script_path), *args]
    logging.info("执行后处理脚本: %s", " ".join(command))
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        logging.error("后处理脚本失败 (%s): %s", script_path.name, result.stderr)
    else:
        if result.stdout:
            for line in result.stdout.splitlines()[:10]:
                logging.info("[followup] %s", line)


# ── 主编译流程 ────────────────────────────────────────────────────────────────

def compile_wiki(
    raw_dirs: list[Path],
    wiki_dir: Path,
    output_dir: Path,
    target: str | None,
    full: bool,
) -> None:
    """编译 raw 到 wiki，并刷新索引/健康报告。"""
    # 全量编译时先清空产物目录，避免“旧概念页/旧文章页”残留造成断链与噪声。
    if full:
        for sub in ("articles", "concepts"):
            p = wiki_dir / sub
            if p.exists():
                shutil.rmtree(p)
    ensure_dirs([wiki_dir / "articles", wiki_dir / "concepts", output_dir])

    # 加载增量状态
    state = CompileState.load(STATE_FILE) if not full else CompileState()

    raw_files = collect_raw_files(raw_dirs, target, state, full)
    if not raw_files:
        logging.info("无新增或变更的文件需要编译（已全部同步）")
        # 仍然刷新索引
        script_dir = Path(__file__).resolve().parent
        run_followup_script(script_dir / "wiki-index.py", "--wiki-dir", str(wiki_dir))
        run_followup_script(script_dir / "wiki-lint.py", "--wiki-dir", str(wiki_dir))
        return

    logging.info("待编译文件数: %s", len(raw_files))
    concept_map: dict[str, list[tuple[str, Path, str]]] = {}
    compiled: list[dict] = []

    # ── 第一轮：解析所有文章，建立概念图 ──────────────────────────────────
    # 概念名大小写归一化：小写 key → 首次出现的原始大小写（display name）
    concept_display: dict[str, str] = {}  # lowercase_key → original_case_name

    articles_meta: list[tuple[ArticleMeta, Path, Path]] = []  # (meta, source, output)
    for raw_file in raw_files:
        logging.info("开始解析: %s", raw_file)
        try:
            article = parse_article(raw_file)
        except Exception:
            logging.warning("解析失败，跳过: %s", raw_file, exc_info=True)
            continue

        out_path = article_output_path(wiki_dir, article)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        article_rel = out_path.relative_to(wiki_dir)

        articles_meta.append((article, raw_file, out_path))

        for concept in article.concepts:
            lc = concept.lower()
            if lc not in concept_display:
                concept_display[lc] = concept  # 保留首次出现的原始大小写
            concept_map.setdefault(lc, []).append((article.title, article_rel, article.summary))

        # 记录编译结果
        compiled.append(
            {
                "source": str(raw_file),
                "article": str(article_rel),
                "concepts": article.concepts,
            }
        )

    # ── 第二轮：渲染文章页（此时已知道完整的概念图，可计算 peer） ──────
    # 构建反向索引：概念 → [(title, rel_path), ...]（用 display name 做 key）
    concept_to_articles: dict[str, list[tuple[str, Path]]] = {}
    for lc_key, arts in concept_map.items():
        display = concept_display.get(lc_key, lc_key)
        concept_to_articles[display] = [(t, p) for t, p, _ in arts]

    for article, raw_file, out_path in articles_meta:
        # 将 article.concepts 中的概念名归一化到 display name
        article.concepts = [concept_display.get(c.lower(), c) for c in article.concepts]
        # 收集同概念文章，统计共享概念数（排除自身）
        peer_shared_count: dict[str, int] = {}  # key=title, value=共享概念数
        peer_path_map: dict[str, Path] = {}      # key=title, value=rel_path
        for concept in article.concepts:
            for peer_title, peer_rel in concept_to_articles.get(concept, []):
                if peer_title == article.title:
                    continue
                peer_shared_count[peer_title] = peer_shared_count.get(peer_title, 0) + 1
                peer_path_map[peer_title] = peer_rel
        # 过滤：至少共享 2 个概念才算同主题（降低噪声）
        peer_articles = sorted(
            [(t, peer_path_map[t]) for t, cnt in peer_shared_count.items() if cnt >= 2],
            key=lambda x: x[0],
        )

        out_path.write_text(render_article(article, out_path, peer_articles), encoding="utf-8")
        logging.info("渲染文章页: %s (peers=%d)", out_path.name, len(peer_articles))

        # 标记已编译
        state.mark_compiled(raw_file)

    # ── 渲染概念页 ───────────────────────────────────────────────────────────
    for lc_key, related_articles in concept_map.items():
        display = concept_display.get(lc_key, lc_key)
        concept_path = concept_output_path(wiki_dir, display)
        concept_path.parent.mkdir(parents=True, exist_ok=True)
        concept_path.write_text(render_concept(display, related_articles), encoding="utf-8")
        logging.info("更新概念页: %s", concept_path)

    # 保存增量状态
    state.last_run = datetime.now().isoformat()
    state.save(STATE_FILE)

    # 后处理：刷新索引 + 健康检查
    script_dir = Path(__file__).resolve().parent
    run_followup_script(script_dir / "wiki-index.py", "--wiki-dir", str(wiki_dir))
    run_followup_script(script_dir / "wiki-lint.py", "--wiki-dir", str(wiki_dir))

    # 编译报告
    # 计算跳过数
    all_count = 0
    for raw_dir in raw_dirs:
        if raw_dir.exists():
            all_count += sum(
                1 for f in raw_dir.rglob("*.md")
                if f.name != "README.md"
                and not any(p.startswith(".") for p in f.relative_to(raw_dir).parts)
            )
    skipped = max(0, all_count - len(compiled))
    write_compile_report(output_dir, compiled, skipped)

    logging.info("编译完成，新增/更新 %s 篇文章，跳过 %s 篇已编译", len(compiled), skipped)


def ensure_dirs(paths: Iterable[Path]) -> None:
    """确保目录存在。"""
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数。"""
    parser = argparse.ArgumentParser(
        description="71-Wiki 一键编译（多源目录 + 增量模式）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python3 wiki-compile.py                    # 增量编译（默认）
  python3 wiki-compile.py --full             # 强制全量重编译
  python3 wiki-compile.py --target "xxx.md"  # 只编译指定文件
  python3 wiki-compile.py --raw-dirs /a /b   # 自定义源目录""",
    )
    parser.add_argument(
        "--raw-dirs",
        nargs="+",
        default=[str(p) for p in DEFAULT_RAW_DIRS],
        help="源资料目录（默认: 仓库内 71-01-raw；可显式传入多个目录）",
    )
    parser.add_argument(
        "--wiki-dir",
        default=str(DEFAULT_WIKI_DIR),
        help="Wiki 输出目录",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="输出/报告目录",
    )
    parser.add_argument(
        "--target",
        help="只编译指定文件（在各源目录中查找）",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="强制全量重编译（忽略增量状态）",
    )
    return parser


def main() -> None:
    """CLI 入口。"""
    setup_logging()
    parser = build_parser()
    args = parser.parse_args()

    raw_dirs = [Path(p) for p in args.raw_dirs]
    wiki_dir = Path(args.wiki_dir)
    output_dir = Path(args.output_dir)

    logging.info("源目录: %s", [str(p) for p in raw_dirs])
    logging.info("Wiki 目录: %s", wiki_dir)
    logging.info("增量模式: %s", "否（全量）" if args.full else "是")

    try:
        compile_wiki(
            raw_dirs=raw_dirs,
            wiki_dir=wiki_dir,
            output_dir=output_dir,
            target=args.target,
            full=args.full,
        )
    except Exception as exc:
        logging.error("wiki 编译失败: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
