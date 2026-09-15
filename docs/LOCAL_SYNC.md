# macOS 本机定时同步

本项目的源资料在本机，GitHub Actions 无法读取它们；因此使用 macOS `launchd` 触发本机同步。

同步脚本只会执行 `git add -A`。由于根目录 `.gitignore` 是白名单策略，私有 raw、生成页、状态、日志和通知脚本不会被加入提交。

## 手动验证

```bash
./scripts/sync-public-repo.sh
```

确认首次推送成功后，安装 LaunchAgent：

```bash
cp scripts/com.xsoway.llm-wiki-knowledge-vault.sync.plist \
  ~/Library/LaunchAgents/com.xsoway.llm-wiki-knowledge-vault.sync.plist
launchctl bootstrap "gui/$(id -u)" \
  ~/Library/LaunchAgents/com.xsoway.llm-wiki-knowledge-vault.sync.plist
```

默认每天 09:15 执行一次。日志写入 `71-03-output/`，不会提交。

已安装任务更新后，重载以使新时间生效：

```bash
launchctl bootout "gui/$(id -u)/com.xsoway.llm-wiki-knowledge-vault.sync"
cp scripts/com.xsoway.llm-wiki-knowledge-vault.sync.plist \
  ~/Library/LaunchAgents/com.xsoway.llm-wiki-knowledge-vault.sync.plist
launchctl bootstrap "gui/$(id -u)" \
  ~/Library/LaunchAgents/com.xsoway.llm-wiki-knowledge-vault.sync.plist
```

卸载任务：

```bash
launchctl bootout "gui/$(id -u)/com.xsoway.llm-wiki-knowledge-vault.sync"
rm ~/Library/LaunchAgents/com.xsoway.llm-wiki-knowledge-vault.sync.plist
```
