#!/opt/homebrew/bin/python3.13
"""
Wiki Search Engine — naive full-text search over wiki markdown files.

Usage:
    python wiki-search.py <query> [--wiki-dir 71-02-wiki/] [--top N]

Searches all .md files in 71-02-wiki/ for the query terms, ranks by
term frequency, and prints the top N results with file paths
and match context.
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path


def resolve_default_wiki_dir() -> Path:
    """Resolve the default numbered wiki directory from the current script path."""
    return Path(__file__).resolve().parents[1] / "71-02-wiki"


def tokenize(text: str) -> list[str]:
    """Simple tokenization: lowercase, split on non-alphanumeric."""
    return re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", text.lower())


def build_index(wiki_dir: str) -> dict[str, dict]:
    """Build inverted index from all .md files in wiki_dir."""
    index = {}
    wiki_path = Path(wiki_dir)
    if not wiki_path.exists():
        print(f"Error: {wiki_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    for md_file in wiki_path.rglob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        tokens = tokenize(content)
        doc_freq = Counter(tokens)
        rel_path = str(md_file.relative_to(wiki_path))

        # Extract title from first heading
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        title = title_match.group(1) if title_match else rel_path

        index[rel_path] = {
            "title": title,
            "path": rel_path,
            "tokens": doc_freq,
            "total_tokens": len(tokens),
            "content": content[:500],  # preview
        }

    return index


def search(query: str, index: dict[str, dict], top_n: int = 10) -> list[dict]:
    """Search the index for query terms, rank by TF score."""
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    results = []
    for doc_path, doc_info in index.items():
        score = 0
        for token in query_tokens:
            score += doc_info["tokens"].get(token, 0)
        if score > 0:
            results.append({
                "title": doc_info["title"],
                "path": doc_info["path"],
                "score": score,
                "preview": doc_info["content"],
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]


def main():
    parser = argparse.ArgumentParser(description="Search wiki markdown files")
    parser.add_argument("query", help="Search query")
    parser.add_argument(
        "--wiki-dir",
        default=str(resolve_default_wiki_dir()),
        help="Wiki directory",
    )
    parser.add_argument("--top", type=int, default=10, help="Top N results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    index = build_index(args.wiki_dir)
    results = search(args.query, index, args.top)

    if args.json:
        import json
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif results:
        print(f"Found {len(results)} results for: {args.query}\n")
        for i, r in enumerate(results, 1):
            print(f"{i}. [{r['title']}] ({r['path']}) — score: {r['score']}")
            print(f"   Preview: {r['preview'][:120]}...")
            print()
    else:
        print(f"No results for: {args.query}")


if __name__ == "__main__":
    main()
