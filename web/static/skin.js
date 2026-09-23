/* ============================================================================
   MarketPulse 液态玻璃皮肤 · 运行时（ESM）· web/static/skin.js
   ----------------------------------------------------------------------------
   套件（skin-kit）给不了、必须宿主自补的 4 件事（plan §2.4）：
     ① 引擎分流 `data-glass-engine` 的**首帧前**落定 + 用引擎真实探测复核；
     ② `scheduleGlass` 分帧挂载（实测 13 个宿主同步挂载 188.8ms / 单面 7–32.3ms
        ⇒ 一帧一个，首屏先画静态壳）；
     ③ `html.is-scrolling` 滚动降级（套件 CSS 里有这条钩子，JS 由宿主提供）；
     ④ `window.mpSkin.remount(el)`：`innerHTML` 重建区（KPI 卡 / 自选表 …）渲染后再挂一次
        —— 引擎按元素的 `_lgInit` 标记幂等，重复调用安全。
   ----------------------------------------------------------------------------
   加载顺序（硬契约，见 mp-skin.css 文件头）：引擎 CSS → tokens → liquid-skin → motion →
   style.css → mp-skin.css，**再**执行本文件；`<head>` 里另有一段**经典内联脚本**
   在首帧前写一次 `data-glass-engine`（classic 脚本不能 import，故用 UA + CSSOM 假性判定，
   真实判定在这里用引擎的 `supportsBackdropFilter()` 复核，不一致时 console.warn 并改正）。
   ----------------------------------------------------------------------------
   引擎是 **vendored** 的（`/static/vendor/liquid-glass/`），用**动态 import** 引入 ——
   零构建页面没有 import map，裸 specifier `@avenra/liquid-glass` 会解析失败。
   ============================================================================ */
const ENGINE_URL = '/static/vendor/liquid-glass/liquid-glass.esm.js';
const HOST_SEL = '[data-liquid-glass]';
const BUDGET_MS = 12;          // 每帧建材质的**时间**预算（单实例 ≈18ms ⇒ 实际「一帧一个」）

/* ── 分帧队列（逐行移植 skin-kit/js/queue.js 的 `scheduleGlass`）─────────────────
   ⚠️ 必须让出一整帧：rAF 回调仍在 paint **之前**执行，单层挡不住；用双层 rAF 保证
   第一次 drain 发生在「没有玻璃的首屏」画完之后。 */
const queue = [];
let scheduled = false;
function pump() {
  scheduled = false;
  const start = performance.now();
  while (queue.length) {
    const job = queue.shift();
    try {
      job();
    } catch (err) {
      console.warn('[mp-skin] 建材质失败（已跳过该面）:', err);
    }
    if (performance.now() - start >= BUDGET_MS) break;
  }
  if (queue.length) {
    scheduled = true;
    requestAnimationFrame(pump);
  }
}
function scheduleGlass(job) {
  queue.push(job);
  if (!scheduled) {
    scheduled = true;
    requestAnimationFrame(() => requestAnimationFrame(pump));
  }
  return () => {
    const i = queue.indexOf(job);
    if (i >= 0) queue.splice(i, 1);
  };
}

/* ── 引擎与状态 ─────────────────────────────────────────────────────────────── */
let engine = null;
const state = { mounted: 0, pending: 0, mode: null, ms: 0 };

function hosts(root) {
  return [...(root || document).querySelectorAll(HOST_SEL)];
}

/**
 * 只给**一个**宿主排队建材质。
 *
 * 为什么先摘属性再挂：引擎的 `init({ root })` 是 `root.querySelectorAll(sel).forEach(...)`，
 * 一次调用会把 root 子树里**所有**宿主都挂上（KPI 行有 4 张卡 ⇒ 一帧 4×18ms）。
 * 摘掉属性后其余宿主不匹配，逐帧只挂一个；`init` 内部按 `_lgInit` 幂等，重复调用安全。
 */
function mountOne(el) {
  if (!engine || !el || el._lgMounted) return;
  const raw = el.getAttribute('data-liquid-glass');
  el.removeAttribute('data-liquid-glass');
  state.pending += 1;
  scheduleGlass(() => {
    if (!el.isConnected) {          // 排队期间被卸载（innerHTML 重建）→ 什么都不做
      state.pending -= 1;
      return;
    }
    el.setAttribute('data-liquid-glass', raw == null ? '' : raw);
    const t0 = performance.now();
    try {
      engine.init({ root: el.parentElement || document });
      el._lgMounted = true;
      state.mounted += 1;
      state.ms += performance.now() - t0;
      document.documentElement.dataset.skinMounted = String(state.mounted);
    } catch (err) {
      console.warn('[mp-skin] init 失败:', err);
    } finally {
      state.pending -= 1;
      // 「挂载完毕」只在**最后一个任务真的出队之后**成立（本任务此刻还没出队 ⇒ 不能放在 try 里判）
      if (!state.pending && !queue.length) {
        document.documentElement.dataset.skinReady = '1';   // 验收等待点（I13：玻璃是异步出现的）
      }
    }
  });
}

function mountAll(root) {
  hosts(root).forEach(mountOne);
}

/* ── 滚动降级：滚动期间给 <html> 加 .is-scrolling（套件 CSS 借此再降一档）──
   套件只提供 CSS 钩子（`html.is-scrolling [data-liquid-skin] .lg-inner`），JS 由宿主补；
   停止滚动 200ms 后摘掉，避免长期停在被降级的材质上。 */
function bindScrollDegrade() {
  const html = document.documentElement;
  let timer = 0;
  window.addEventListener('scroll', () => {
    if (!html.classList.contains('is-scrolling')) html.classList.add('is-scrolling');
    clearTimeout(timer);
    timer = setTimeout(() => html.classList.remove('is-scrolling'), 200);
  }, { passive: true });
}

window.mpSkin = {
  state,
  /** 渲染批次后重挂（`innerHTML` 重建的容器：KPI 卡 / 自选表 / 概览迷你卡 …） */
  remount(root) {
    mountAll(root);
    return state;
  },
};

/* ── 启动 ─────────────────────────────────────────────────────────────────── */
import(ENGINE_URL)
  .then((mod) => {
    engine = mod;
    const html = document.documentElement;
    const forced = window.__MP_FORCE_ENGINE;
    const real = forced === 'frost' || forced === 'refract'
      ? forced
      : (mod.supportsBackdropFilter() ? 'refract' : 'frost');
    const prev = html.dataset.glassEngine;
    html.dataset.glassEngine = real;
    state.mode = real;
    if (prev && prev !== real) {
      // 内联首帧判定与引擎真实探测不一致 ⇒ 以引擎为准（首帧可能闪一次，属预期代价）
      console.warn(`[mp-skin] data-glass-engine ${prev} → ${real}（引擎真实探测为准）`);
    }
    const start = () => {
      mountAll();
      bindScrollDegrade();
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
  })
  .catch((err) => {
    // 引擎加载失败 ⇒ 不能让 JS 抛错把 app.js 带走；并把**宿主旧玻璃装回去**
    // （`mp-skin.css §7` 的 `html[data-skin-degraded='1']` 规则），否则页面只剩「透明卡片」。
    console.error('[mp-skin] 引擎加载失败，回退到宿主玻璃:', err);
    document.documentElement.dataset.glassEngine = 'frost';
    document.documentElement.dataset.skinDegraded = '1';
  });
