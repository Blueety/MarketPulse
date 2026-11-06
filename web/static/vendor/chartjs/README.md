# vendored · Chart.js v4.4.1 + chartjs-plugin-zoom v2.0.1

出图页面的图表引擎（均 MIT）。本目录是 **vendored 快照**：文件原样入库，**禁止改写 / 内联 / 重新压缩**。

| 文件 | 来源 | 说明 |
| --- | --- | --- |
| `chart.umd.min.js` | `https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js` | UMD 构建，挂到 `window.Chart`；上游 [chartjs/Chart.js](https://github.com/chartjs/Chart.js) tag `v4.4.1` |
| `chartjs-plugin-zoom.min.js` | `https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js` | 缩放/平移插件（首页用）；上游 [chartjs/chartjs-plugin-zoom](https://github.com/chartjs/chartjs-plugin-zoom) tag `v2.0.1` |
| `LICENSE-chartjs.txt` | 包内 `LICENSE.md` | MIT 文本（分发义务） |
| `LICENSE-chartjs-plugin-zoom.txt` | 包内 `LICENSE.md` | MIT 文本（分发义务） |

- 版本锁定：`4.4.1` / `2.0.1`（模板里的 `?v={{ asset_v }}` 由 `web/app.py` 的 `_ASSET_FILES` 取 mtime）。
- 为什么自托管：`cdn.jsdelivr.net` 在部分移动网络不可达 ⇒ `window.__chartFailed` ⇒ 图表恒空白
  （2026-11-06 实测，见 `docs/pitfalls.md`「静态库一律自托管」）。禁止改回第三方 CDN。
- 刷新方法（升级时）：从上面两个 URL 原样下载覆盖，再核对首行 banner 版本号与 `LICENSE-*`。
