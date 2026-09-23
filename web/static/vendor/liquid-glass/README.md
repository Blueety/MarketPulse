# vendored · @avenra/liquid-glass v1.2.0

液态玻璃**材质引擎**（唯一第三方依赖，MIT）。本目录是 **vendored 快照**：文件原样入库，
**禁止改写 / 内联 / 丢进 `@layer`**（引擎产物的类名契约与内联样式是皮肤的覆盖前提，见下）。

| 文件 | 来源 | 说明 |
| --- | --- | --- |
| `liquid-glass.css` | 包内 `styles/liquid-glass.css` | 引擎自身样式（`.lg-inner` / `.lg-clone` / 各控件） |
| `liquid-glass.esm.js` | 包内 `dist/liquid-glass.esm.js` | 自包含 ESM（零运行时依赖）；由 `web/static/skin.js` **动态 import** |
| `LICENSE-avenra-liquid-glass.txt` | 包内 `LICENSE` | MIT 文本（分发时保留的义务）；上游作者 DevSam7t3 |

- 版本锁定：`1.2.0`（`web/static/skin/liquid-skin.css` 与 `skin-kit` 的类名契约按此版本对齐）。
- 校验：入库副本与上游**逐字节一致**（md5 见 `tasks/2026-09-23-web-liquid-glass-skin/journal.md`）。

## 刷新方法（升级引擎时）

```bash
# 1) 取包（npm 是唯一分发渠道；本仓不引入 node 工具链）
npm install --no-save @avenra/liquid-glass@<version>      # 在临时目录里执行
# 2) 覆盖本目录三个文件（styles/ · dist/ · LICENSE）
# 3) 重新取 md5 并比对（更新 journal 记录）
md5sum <pkg>/styles/liquid-glass.css <pkg>/dist/liquid-glass.esm.js
```

## 上游版本敏感面（升级前必读）

皮肤**不复制**引擎 DOM，而是靠**类名契约**覆盖它注入的节点：
`.lg-inner` / `.lg-clone` / `.lg-clone-world` / `.lg-button` / `.lg-input-field` / `.lg-switch-track` /
`.lg-switch-thumb` / `.lg-checkbox-*` / `.lg-radio-*` / `.lg-progress`。
上游若在次版本里改名或改结构，皮肤会**静默**失去覆盖（表现为「玻璃还在、皮肤没了」）。

已知的易变面/死代码（v1.2.0 实测）：

- `.lg-inner` 的 `border` / `background` / `box-shadow` 在引擎 CSS 里被**注释掉**：投影由 JS
  逐帧写成**内联样式**，只有作者 `!important` 能压过 ⇒ 面板染色由宿主补丁层给（`mp-skin.css §3`）。
- `init()` 的 `parseDataset()` **不解析** `radius` 与 `options`：圆角只能由 CSS 提供
  （`data-radius` 不存在）；`.lg-inner` 用 `border-radius: inherit` 跟随宿主。
- `createLiquidSwitch` 的 `destroy()` 不移除 `.lg-switch-track`（本页未用开关控件，暂不影响）。
- `supportsBackdropFilter()` 的实现是 `!!window.chrome && CSSOM 接受 url(#…)` —— **headless Chromium
  没有 `window.chrome`** ⇒ 无头下恒判磨砂。折射类验收必须 `--headed`（见 `verify_skin.py`）。

## 属性通道（引擎 `init({root})` 会解析的 `data-*`）

`data-bezel-width` / `data-glass-thickness` / `data-refractive-index` / `data-blur` / `data-saturation` /
`data-specular-slope` / `data-profile` / `data-filter-mode`（其余 `data-liquid-*` 选择器对应各控件工厂）。
本仓用法：宿主卡片 `data-bezel-width="20" data-glass-thickness="80" data-blur="1.5"`（topbar `blur=4`）。
