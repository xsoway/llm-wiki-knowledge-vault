#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
# @Time     : 2026/09/13 12:20
# @Filename : test_export_public_catalog.py
# @Author   : Alan_Hsu

"""公开目录导出器的回归测试。"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from tools.export_public_catalog import export_catalog


class ExportPublicCatalogTests(unittest.TestCase):
    """验证仅导出标题、标签、链接和创建时间。"""

    def test_exports_only_records_with_http_source(self) -> None:
        """具有 HTTP 原文链接的笔记应被导出，正文和无链接笔记不应导出。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "raw"
            source_dir.mkdir()
            (source_dir / "included.md").write_text(
                "---\n"
                "title: 示例文章\n"
                "source: https://example.com/article\n"
                "created: 2026-09-13\n"
                "tags:\n"
                "  - clippings\n"
                "  - Agent\n"
                "---\n"
                "这段第三方正文绝不能出现在公开目录中。\n",
                encoding="utf-8",
            )
            (source_dir / "excluded.md").write_text(
                "---\ntitle: 无链接文章\ntags: [LLM]\n---\n正文\n",
                encoding="utf-8",
            )
            output_path = Path(temp_dir) / "articles.csv"

            exported = export_catalog(source_dir, output_path)

            self.assertEqual(exported, 1)
            with output_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows, [{
                "title": "示例文章",
                "tags": "clippings | Agent",
                "source": "https://example.com/article",
                "created": "2026-09-13",
            }])


if __name__ == "__main__":
    unittest.main()
