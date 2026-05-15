# suganami_mirei_twitter_backup

这是一个把 `gallery-dl` 抓下来的 X/Twitter 归档生成为静态时间线页面的小工具。

## 本地使用

拉取/更新归档数据：

```bash
bash backup.sh
```

生成静态页面：

```bash
bash gen.sh
```

默认会生成到：

```text
output/suganami_mirei/timeline.html
```

## GitHub Pages 发布

仓库里已经包含了 `.github/workflows/deploy-pages.yml`：

- 每次推送到默认分支时，GitHub Actions 会自动执行 `gen.sh`
- 工作流会把 `output/` 和 `gallery-dl/` 打包成 Pages artifact 后直接部署
- 根目录 `index.html` 会自动跳转到 `output/suganami_mirei/timeline.html`

你还需要在 GitHub 仓库设置里手动确认一次：

1. 打开 `Settings`
2. 进入 `Pages`
3. 将 Source 设为 `GitHub Actions`
