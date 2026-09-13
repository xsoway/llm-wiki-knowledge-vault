---
title: LLM Wiki Knowledge Vault
aliases: [LLM Wiki, Knowledge Compiler Vault]
category: OpenSource
created: 2026-09-13 00:00
updated: 2026-09-13 00:00
tags: [KnowledgeBase, Wiki, LLM, Obsidian, Agent]
---

# LLM Wiki Knowledge Vault

把 Markdown 当作源代码，把 LLM/规则当作编译器，把可浏览、可检索、可回溯的 Wiki 当作产物。

这个项目提供一套轻量、可本地运行的知识库工作台：原始资料进入 `71-01-raw/`，编译器生成文章页、概念页、索引和健康报告。它适合 AI、LLM、测试开发、自动化测试、Agent、评测、Skill、Harness 与开源工具等持续增长的技术资料。

> 方法论参考：[Andrej Karpathy on LLM Wiki](https://x.com/karpathy/status/2039805659525644595)。本仓库是独立实现，并非其官方项目。

## 能做什么

- 增量编译 Markdown，避免每次全量重建。
- 从标题关键词、frontmatter 标签和正文词频提取概念。
- 当两篇文章共享至少两个概念时，自动生成同主题互链。
- 生成全量索引、主题摘要、统计和结构健康报告。
- 通过问答归档，把确认有价值的答案回写为新的知识源。
- 提供本地全文关键词搜索；语义质检可按需接入自己的 LLM 环境。

## 目录

```text
.
├── 71-01-raw/public-samples/  # 可公开、可编译的示例原料
├── 71-02-wiki/                # 本地生成产物，默认不提交
├── 71-03-output/              # 本地状态、报告、日志，默认不提交
├── 71-04-scripts/             # 编译、索引、检查、搜索、归档脚本
├── docs/                      # 内容边界与同步说明
└── scripts/                   # 本机定时同步脚本
```

## 快速开始

要求：Python 3.11+。项目仅使用标准库。

```bash
git clone https://github.com/xsoway/llm-wiki-knowledge-vault.git
cd llm-wiki-knowledge-vault

# 编译仓库内公开示例
python3 71-04-scripts/wiki-compile.py --full

# 搜索生成的 Wiki
python3 71-04-scripts/wiki-search.py "Agent"

# 结构体检
python3 71-04-scripts/wiki-lint.py
```

默认只读取仓库内的 `71-01-raw/`。如果你有自己的 Obsidian/Vault 内容，显式指定来源目录：

```bash
python3 71-04-scripts/wiki-compile.py --full \
  --raw-dirs /path/to/articles /path/to/notes ./71-01-raw
```

## 内容与版权边界

代码、规则、自己原创的笔记和已获授权的示例可以公开；第三方剪藏文章不能因为被收藏而重新分发。

因此，公开仓库只包含框架与脱敏示例。个人或团队的原始资料、编译产物、日志、运行状态和任何密钥均默认忽略。详见 [内容发布边界](docs/CONTENT_POLICY.md)。

## 日常工作流

1. 把自己有权公开或私下保存的 Markdown 放到合适的源目录。
2. 执行增量编译：`python3 71-04-scripts/wiki-compile.py`。
3. 在 Obsidian 中浏览 `71-02-wiki/`，或使用 `wiki-search.py` 检索。
4. 运行 `wiki-lint.py` 检查断链、孤岛页和缺摘要。
5. 对确认有价值的问答，使用 `wiki-archive.py` 回写，然后重新编译。

## 自动同步公开仓库

`scripts/sync-public-repo.sh` 只提交 `.gitignore` 白名单内的公开文件。macOS 的 `launchd` 示例与安装步骤见 [本机定时同步](docs/LOCAL_SYNC.md)。

## License

代码以 [MIT License](LICENSE) 发布。示例内容以文件内声明为准；第三方内容不随本仓库授权。
