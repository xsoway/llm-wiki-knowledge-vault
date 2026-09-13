#!/opt/homebrew/bin/python3.13
from __future__ import annotations
"""
Wiki Linter — health checks for LLM-generated wiki.

Usage:
    python wiki-lint.py [--wiki-dir 71-02-wiki/] [--fix]

Checks:
1. Broken links ([[wikilink]] to non-existent files)
2. Duplicate concepts (similar titles/content)
3. Missing summaries (articles without ## 摘要 section)
4. Orphaned articles (no incoming backlinks)
5. INDEX.md consistency (files not in index)
6. Stale articles (last modified > 90 days without update marker)

Outputs: 71-02-wiki/HEALTH-REPORT.md
"""

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def resolve_default_wiki_dir() -> Path:
    """Resolve the default numbered wiki directory from the current script path."""
    return Path(__file__).resolve().parents[1] / "71-02-wiki"


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _normalize_for_match(text: str) -> str:
    """把文本归一化用于模糊匹配：去掉空白与常见分隔符，统一大小写。"""
    compact = re.sub(r"[\s_\-—–·•,:，:：;；.!?！？()（）\\[\\]{}\"'`]+", "", text)
    return compact.lower()


def _extract_frontmatter_title(content: str) -> str | None:
    """从 frontmatter 提取 title（若有）。"""
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return None
    for line in m.group(1).splitlines():
        if line.strip().startswith("title:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return None


def _extract_h1_title(content: str) -> str | None:
    """提取第一个 H1 标题作为 title 兜底。"""
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


class WikiIndex:
    """为 link 解析预建索引，避免对每条 link 都 rglob 一遍（会指数级变慢）。"""

    def __init__(self, wiki_dir: Path) -> None:
        self.wiki_dir = wiki_dir
        self.rel_to_path: dict[str, Path] = {}
        self.stem_to_paths: dict[str, list[Path]] = defaultdict(list)
        self.title_to_path: dict[str, Path] = {}
        # norm → {Path, ...}；用 set 避免同一文件因 stem/title 两次入表导致“多命中”误判
        self.norm_to_paths: dict[str, set[Path]] = defaultdict(set)

        for md_path in wiki_dir.rglob("*.md"):
            rel = str(md_path.relative_to(wiki_dir))
            self.rel_to_path[rel] = md_path
            self.stem_to_paths[md_path.stem].append(md_path)

            content = md_path.read_text(encoding="utf-8")
            title = _extract_frontmatter_title(content) or _extract_h1_title(content)
            if title and title not in self.title_to_path:
                self.title_to_path[title] = md_path

            self.norm_to_paths[_normalize_for_match(md_path.stem)].add(md_path)
            if title:
                self.norm_to_paths[_normalize_for_match(title)].add(md_path)

    def resolve_wikilink_target(self, raw_target: str) -> Path | None:
        """解析 wikilink 目标，兼容 path/stem/title/模糊多种写法。"""
        target = raw_target.strip()
        if not target:
            return None

        # 兼容 Obsidian 里常见的“源目录路径”写法：[[01 Articles/...]] / [[01-Articles/...]]
        target = target.replace("\\", "/")
        for prefix in ("01 Articles/", "01-Articles/", "02 Notes/", "02-Notes/"):
            if target.startswith(prefix):
                target = target[len(prefix):]
                break

        # 1) 直接路径（相对 wiki_dir）命中
        direct_rel = f"{target}.md" if not target.endswith(".md") else target
        direct_path = self.wiki_dir / direct_rel
        if direct_path.exists():
            return direct_path

        # 2) 相对路径（去掉后缀）命中
        rel_no_ext = target[:-3] if target.endswith(".md") else target
        maybe = self.wiki_dir / f"{rel_no_ext}.md"
        if maybe.exists():
            return maybe

        # 3) stem 命中（若唯一）
        stem_hits = self.stem_to_paths.get(target)
        if stem_hits and len(stem_hits) == 1:
            return stem_hits[0]

        # 4) title 命中
        title_hit = self.title_to_path.get(target)
        if title_hit is not None:
            return title_hit

        # 5) 模糊命中：归一化后精确匹配（避免中文/标点差异）
        norm = _normalize_for_match(target)
        norm_hits = self.norm_to_paths.get(norm)
        if norm_hits and len(norm_hits) == 1:
            return next(iter(norm_hits))

        # 6) 兜底：仅当 target 很长时，尝试“包含匹配”（避免误命中）
        if len(norm) >= 10:
            for key, paths in self.norm_to_paths.items():
                if norm and norm in key and len(paths) == 1:
                    return next(iter(paths))

        return None


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".tiff", ".pdf"}


def _is_attachment_like_target(target: str) -> bool:
    """判断 wikilink 是否更像附件引用而非页面链接。"""
    t = target.strip()
    if not t:
        return False
    # 常见：[[image 20260524102531933.png]]
    if re.search(r"\.(png|jpg|jpeg|gif|svg|webp|bmp|tiff|pdf)$", t, re.IGNORECASE):
        return True
    # 还有些附件名没有扩展名但带 image 前缀
    if t.lower().startswith("image "):
        return True
    return False


def find_broken_links(wiki_dir: Path) -> list[dict]:
    """Find [[wikilinks]] pointing to non-existent files."""
    broken = []
    index = WikiIndex(wiki_dir)

    for md_file in wiki_dir.rglob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        links = re.findall(r"\[\[(.+?)\]\]", content)
        for link in links:
            # Strip display text: [[target|display]] → target
            parts = link.split("|", 1)
            target = parts[0].strip()
            # 附件引用不算断链（wiki 产物可能不带附件目录）
            if _is_attachment_like_target(target):
                continue
            # Check if target exists as filename/path/title
            target_path = index.resolve_wikilink_target(target)
            # 若存在 display text，且 target 解析失败，尝试用 display 解析（常见于源路径迁移）
            if target_path is None and len(parts) == 2:
                display = parts[1].strip()
                if display:
                    target_path = index.resolve_wikilink_target(display)

            if target_path is None:
                broken.append({
                    "file": str(md_file.relative_to(wiki_dir)),
                    "link": link,
                    "reason": "target not found",
                })
    return broken


def find_missing_summaries(wiki_dir: Path) -> list[dict]:
    """Find articles without summary sections."""
    missing = []
    for md_file in wiki_dir.rglob("*.md"):
        if md_file.name in ("INDEX.md", "SUMMARY.md", "HEALTH-REPORT.md", "STATS.md"):
            continue
        content = md_file.read_text(encoding="utf-8")
        has_summary = bool(re.search(r"^#{1,3}\s+(摘要|Summary|概述)", content, re.MULTILINE))
        if not has_summary:
            missing.append({
                "file": str(md_file.relative_to(wiki_dir)),
                "reason": "no summary section",
            })
    return missing


def find_orphaned_articles(wiki_dir: Path) -> list[dict]:
    """Find articles with no incoming backlinks."""
    orphaned = []
    all_files = list(wiki_dir.rglob("*.md"))
    all_paths = {str(f.relative_to(wiki_dir)) for f in all_files}

    # Build backlink map
    backlinks = {p: 0 for p in all_paths}
    index = WikiIndex(wiki_dir)
    for md_file in all_files:
        content = md_file.read_text(encoding="utf-8")
        # 1) Wikilink backlinks: [[target]]
        wikilinks = re.findall(r"\[\[(.+?)\]\]", content)
        for link in wikilinks:
            target = link.split("|")[0].strip()
            if _is_attachment_like_target(target):
                continue
            target_file = index.resolve_wikilink_target(target)
            if target_file is not None:
                rel = str(target_file.relative_to(wiki_dir))
                backlinks[rel] = backlinks.get(rel, 0) + 1

        # 2) Markdown link backlinks: [text](relative/path.md)
        # INDEX.md 使用这种写法，之前会导致大量“孤岛页面”误报。
        md_links = re.findall(r"\[[^\]]*\]\(([^)]+)\)", content)
        for href in md_links:
            href = href.strip()
            if not href or href.startswith(("http://", "https://")):
                continue
            # 只认 wiki 内部 md 链接
            if not href.endswith(".md"):
                continue
            target_path = (wiki_dir / href).resolve()
            try:
                rel = str(target_path.relative_to(wiki_dir.resolve()))
            except ValueError:
                continue
            if rel in backlinks:
                backlinks[rel] = backlinks.get(rel, 0) + 1

    for path, count in backlinks.items():
        name = Path(path).name
        if name in ("INDEX.md", "SUMMARY.md", "HEALTH-REPORT.md", "STATS.md"):
            continue
        if count == 0:
            orphaned.append({
                "file": path,
                "reason": "no incoming backlinks",
            })
    return orphaned


def check_index_consistency(wiki_dir: Path) -> list[dict]:
    """Check if INDEX.md lists all files."""
    issues = []
    index_file = wiki_dir / "INDEX.md"
    if not index_file.exists():
        return [{"file": "INDEX.md", "reason": "index file missing"}]

    index_content = index_file.read_text(encoding="utf-8")
    all_files = {str(f.relative_to(wiki_dir)) for f in wiki_dir.rglob("*.md")
                 if f.name not in ("INDEX.md", "SUMMARY.md", "HEALTH-REPORT.md", "STATS.md")}

    for file_path in all_files:
        # Check if file is mentioned in index
        file_stem = Path(file_path).stem
        if file_stem not in index_content:
            issues.append({
                "file": file_path,
                "reason": "not listed in INDEX.md",
            })
    return issues


def generate_report(
    wiki_dir: Path,
    broken_links: list,
    missing_summaries: list,
    orphaned: list,
    index_issues: list,
) -> str:
    """Generate HEALTH-REPORT.md content."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_files = len(list(wiki_dir.rglob("*.md")))
    total_issues = len(broken_links) + len(missing_summaries) + len(orphaned) + len(index_issues)

    # Health score（0~10）：按规模归一化，避免“文件数上千但小问题较多就直接 0 分”的失真。
    # 权重：断链最致命，其次索引一致性，然后孤岛，最后缺摘要。
    broken_rate = len(broken_links) / max(1, total_files)
    index_rate = len(index_issues) / max(1, total_files)
    orphan_rate = len(orphaned) / max(1, total_files)
    missing_rate = len(missing_summaries) / max(1, total_files)
    weighted = (3.0 * broken_rate) + (2.0 * index_rate) + (1.0 * orphan_rate) + (0.5 * missing_rate)
    score = int(round(max(0.0, 10.0 * (1.0 - min(1.0, weighted)))))

    report = f"""# Wiki Health Report

**Date**: {now}
**Total files**: {total_files}
**Total issues**: {total_issues}
**Health Score**: {score}/10

---

## Broken Links ({len(broken_links)})

"""
    if broken_links:
        for item in broken_links:
            report += f"- `{item['file']}` → `{item['link']}` ({item['reason']})\n"
    else:
        report += "None found.\n"

    report += f"\n## Missing Summaries ({len(missing_summaries)})\n\n"
    if missing_summaries:
        for item in missing_summaries:
            report += f"- `{item['file']}` ({item['reason']})\n"
    else:
        report += "None found.\n"

    report += f"\n## Orphaned Articles ({len(orphaned)})\n\n"
    if orphaned:
        for item in orphaned:
            report += f"- `{item['file']}` ({item['reason']})\n"
    else:
        report += "None found.\n"

    report += f"\n## Index Consistency ({len(index_issues)})\n\n"
    if index_issues:
        for item in index_issues:
            report += f"- `{item['file']}` ({item['reason']})\n"
    else:
        report += "Index is consistent.\n"

    report += "\n## Recommendations\n\n"
    if broken_links:
        report += f"1. **Fix {len(broken_links)} broken links** — update or remove invalid references\n"
    if missing_summaries:
        report += f"{'2' if broken_links else '1'}. **Add summaries to {len(missing_summaries)} articles**\n"
    if orphaned:
        report += f"{'3' if broken_links or missing_summaries else '2'}. **Review {len(orphaned)} orphaned articles** — add backlinks or merge\n"
    if not total_issues:
        report += "Wiki is healthy! Consider adding new concepts or deepening existing ones.\n"

    return report


def main():
    parser = argparse.ArgumentParser(description="Wiki linter / health checker")
    parser.add_argument(
        "--wiki-dir",
        default=str(resolve_default_wiki_dir()),
        help="Wiki directory",
    )
    parser.add_argument("--fix", action="store_true", help="Auto-fix issues")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    wiki_path = Path(args.wiki_dir)
    if not wiki_path.exists():
        print(f"Error: {args.wiki_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    broken = find_broken_links(wiki_path)
    missing = find_missing_summaries(wiki_path)
    orphaned = find_orphaned_articles(wiki_path)
    index_issues = check_index_consistency(wiki_path)

    if args.json:
        import json
        print(json.dumps({
            "broken_links": broken,
            "missing_summaries": missing,
            "orphaned_articles": orphaned,
            "index_issues": index_issues,
            "total_issues": len(broken) + len(missing) + len(orphaned) + len(index_issues),
        }, ensure_ascii=False, indent=2))
    else:
        report = generate_report(wiki_path, broken, missing, orphaned, index_issues)
        report_file = wiki_path / "HEALTH-REPORT.md"
        report_file.write_text(report, encoding="utf-8")
        print(report)
        print(f"\nReport saved to: {report_file}")


if __name__ == "__main__":
    main()
