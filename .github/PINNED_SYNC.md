# 精选项目自动同步

工作流：`.github/workflows/sync-pinned.yml`（Actions 中显示为 **Sync pinned repositories**）。

- 每天 UTC 07:23 运行；也可以在 Actions 页面选择 **Run workflow** 手动运行。
- 以仓库所有者资料页的公开 Pinned 仓库为数据源，按 GitHub GraphQL 返回的顺序生成卡片；不处理 Gist，不展示私有仓库。
- 仅管理 `README.md` 中 `## 精选项目` 到下一个一级或二级标题之间的内容，保留现有卡片主题与其他章节。不要在该区域添加需手动保留的内容。
- 内容相同时不写 README、不创建提交；仓库增删、顺序或名称变化时更新卡片，由 `github-actions[bot]` 提交到默认分支。
- 查询成功且没有公开 Pinned 仓库时清空卡片；API 错误、数据不完整、精选项目标题缺失或重复时失败退出，不提交更改。
- 同步摘要记录在 Actions Summary；推送失败以最后一个步骤的日志为准。推送不使用 force，远端并发更新导致冲突时可重新运行。

## 启用条件

将工作流、脚本和测试文件提交到默认分支，并启用仓库 Actions。工作流使用内置 `GITHUB_TOKEN`，声明 `contents: write`，无需额外配置 PAT。仓库策略和默认分支规则需要允许该工作流推送；如果禁止直接推送，任务会失败，不会绕过保护规则。

定时任务由 GitHub 调度，可能延迟；公共仓库长期没有活动时，定时工作流可能被自动禁用，可在 Actions 页面重新启用。

## 本地测试

仅依赖 Python 3.10+ 标准库，无需安装额外包：

```bash
python -B -m unittest discover -s .github/scripts -p 'test_*.py' -v
```

实际同步命令如下（会修改当前目录的 README）：

```bash
python -B .github/scripts/sync_pinned.py
```

需通过环境变量提供 `GITHUB_REPOSITORY_OWNER` 和可访问 GitHub GraphQL 的 `GITHUB_TOKEN`。不要将 token 写入文件或提交到仓库。
