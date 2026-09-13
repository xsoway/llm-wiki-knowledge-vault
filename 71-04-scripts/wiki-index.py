#!/opt/homebrew/bin/python3.13
"""
Wiki Index Generator — auto-maintains INDEX.md and SUMMARY.md.

Usage:
    python wiki-index.py [--wiki-dir 71-02-wiki/] [--stats]

Generates:
- 71-02-wiki/INDEX.md — list of all articles with one-line summary
- 71-02-wiki/SUMMARY.md — topic-level overview
- 71-02-wiki/STATS.md — wiki statistics
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path


def resolve_default_wiki_dir() -> Path:
    """Resolve the default numbered wiki directory from the current script path."""
    return Path(__file__).resolve().parents[1] / "71-02-wiki"


def extract_summary(content: str) -> str:
    """Extract the first paragraph or ## 摘要 section as summary."""
    # Try ## 摘要 / ## Summary first
    match = re.search(r"^#{1,3}\s+(?:摘要|Summary|概述)\s*\n+(.+?)(?=\n#{1,3}\s+|\Z)",
                      content, re.MULTILINE | re.DOTALL)
    if match:
        text = match.group(1).strip()
        # Return first line or first 150 chars
        first_line = text.split("\n")[0].strip()
        if first_line:
            return first_line[:150]

    # Fall back: first paragraph after title
    paragraphs = re.split(r"\n{2,}", content)
    for p in paragraphs:
        p = p.strip()
        if p and not p.startswith("#") and len(p) > 20:
            # Clean markdown
            p = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", p)  # links
            p = re.sub(r"[#*`_]", "", p)  # formatting
            return p[:150]

    return "(no summary)"


def extract_title(content: str) -> str:
    """Extract the first # heading as title."""
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else "(untitled)"


def extract_topics(wiki_dir: Path) -> dict[str, list[dict]]:
    """Group articles by topic (subdirectory or tag)."""
    topics = {}
    for md_file in sorted(wiki_dir.rglob("*.md")):
        if md_file.name in ("INDEX.md", "SUMMARY.md", "HEALTH-REPORT.md", "STATS.md"):
            continue

        content = md_file.read_text(encoding="utf-8")
        title = extract_title(content)
        summary = extract_summary(content)

        # Topic from subdirectory
        rel_path = md_file.relative_to(wiki_dir)
        topic = str(rel_path.parent) if rel_path.parent != Path(".") else "general"

        if topic not in topics:
            topics[topic] = []
        topics[topic].append({
            "title": title,
            "summary": summary,
            "path": str(rel_path),
            "words": len(content.split()),
        })

    return topics


def generate_index(topics: dict[str, list[dict]]) -> str:
    """Generate INDEX.md content."""
    now = datetime.now().strftime("%Y-%m-%d")
    total = sum(len(arts) for arts in topics.values())

    index = f"""# Wiki Index

> Auto-generated on {now} — {total} articles

"""
    for topic, articles in sorted(topics.items()):
        index += f"## {topic}\n\n"
        for art in articles:
            index += f"- [{art['title']}]({art['path']}) — {art['summary']}\n"
        index += "\n"

    return index


def generate_summary(topics: dict[str, list[dict]]) -> str:
    """Generate SUMMARY.md content."""
    now = datetime.now().strftime("%Y-%m-%d")

    summary = f"""# Wiki Summary

> Auto-generated on {now}

"""
    for topic, articles in sorted(topics.items()):
        total_words = sum(a["words"] for a in articles)
        summary += f"## {topic}\n\n"
        summary += f"- **Articles**: {len(articles)}\n"
        summary += f"- **Words**: ~{total_words:,}\n"
        summary += f"- **Coverage**: {', '.join(a['title'] for a in articles)}\n\n"

    return summary


def generate_stats(topics: dict[str, list[dict]], wiki_dir: Path) -> str:
    """Generate STATS.md content."""
    now = datetime.now().strftime("%Y-%m-%d")
    total_articles = sum(len(arts) for arts in topics.values())
    total_words = sum(a["words"] for arts in topics.values() for a in arts)
    total_concepts = len(topics)

    # Count backlinks
    all_content = ""
    for md_file in wiki_dir.rglob("*.md"):
        all_content += md_file.read_text(encoding="utf-8")
    backlink_count = len(re.findall(r"\[\[.+?\]\]", all_content))

    stats = f"""# Wiki Stats

- **Last updated**: {now}
- **Topics**: {total_concepts}
- **Wiki articles**: {total_articles}
- **Total words**: ~{total_words:,}
- **Backlinks**: {backlink_count}
- **Health score**: _pending check_
"""
    return stats


def main():
    parser = argparse.ArgumentParser(description="Wiki index generator")
    parser.add_argument(
        "--wiki-dir",
        default=str(resolve_default_wiki_dir()),
        help="Wiki directory",
    )
    parser.add_argument("--stats", action="store_true", help="Only generate stats")
    args = parser.parse_args()

    wiki_path = Path(args.wiki_dir)
    if not wiki_path.exists():
        print(f"Error: {args.wiki_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    topics = extract_topics(wiki_path)

    if not args.stats:
        index_content = generate_index(topics)
        (wiki_path / "INDEX.md").write_text(index_content, encoding="utf-8")
        print(f"Generated INDEX.md ({sum(len(a) for a in topics.values())} articles)")

        summary_content = generate_summary(topics)
        (wiki_path / "SUMMARY.md").write_text(summary_content, encoding="utf-8")
        print(f"Generated SUMMARY.md ({len(topics)} topics)")

    stats_content = generate_stats(topics, wiki_path)
    (wiki_path / "STATS.md").write_text(stats_content, encoding="utf-8")
    print("Generated STATS.md")


if __name__ == "__main__":
    main()
