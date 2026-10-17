/* ============================================================================
   MarketPulse · DOM 写入语义哨兵 · web/static/dom-write-guard.js
   ----------------------------------------------------------------------------
   目的：**检测 + 修复写入语义**（2026-10-17；方案 ③ 检测 + 方案 ① 免疫。
   背景见 tasks/2026-10-17-dom-write-hardening/{plan.md,journal.md}）。

   背景一句话：页面出现「内容重复」（同一块内容 2~5 份、后几份是**旧值**、原始占位符与骨架屏
   被顶到最后）时，根因不在本站代码 —— 是页面里的 DOM 写入语义被第三方脚本改写成了
   「前置插入、旧内容留下」（`el.innerHTML = x` 不再替换）。本站代码全仓零克隆、零原型改写，
   正常环境下渲染恒为单份（6 种浏览器配置 + 压力测试实测）⇒ 这类改写只可能来自
   **浏览器扩展 / 用户脚本 / 自动化面板注入的脚本**。

   本文件在 head 里**最先**执行，做三件事（全部 try/catch，永不把异常抛给页面）：
     ① **检测**：行为探针（游离节点连写两次，看第二次是否替换第一次）。命中 ⇒ `console.warn`
        （含被改写 API、实测行为、**当前 setter 的源码片段** ⇒ 片段通常直接点名肇事者）
        + `<html data-dom-write-patched="innerHTML,textContent">`。
     ② **修复语义**：给命中的 setter 套一层「**先清空子节点、再交给原 setter**」的包装
        ⇒ 对方是「前置插入」还是「追加」都被抹平，写回归替换语义。
        ⚠️ 为什么**不**去「取回原生 setter」：新 realm 也可能被同样改写（内容脚本 `all_frames`
        是常见配置；本仓验收里 Playwright 的 `add_init_script` 就注进了新 iframe），
        那时「从干净 realm 取原生」取回的是**同样被改写的那一个**，还会因跨 realm 节点
        把页面写崩（实测：注入层开始抛 `insertBefore: parameter 1 is not of type 'Node'`）。
        「先清空再委派」不依赖任何干净 realm，也不与改写层争「谁的原型函数是原生的」。
     ③ **重复 id 复查**：`DOMContentLoaded` +1.5s 再查一次写入语义（抓晚改写，会再修一次）
        并统计重复 id（克隆型注入的特征：同一元素被复制 ⇒ `getElementById` 只命中第一个副本，
        其余副本冻结在旧值），命中时打 `<html data-dom-write-dup-ids="N">`。

   为什么是行为探针而不是「源码里有没有 defineProperty」：任何实现方式（setter 改写 / Proxy /
   MutationObserver 里重建节点）都会在**两次连续写入**上露马脚，而源码特征会漏（压缩、间接实现）。
   探针用**游离节点**（不进文档）⇒ 不触发布局。

   已知边界：只覆盖 `innerHTML` / `textContent` 两个写入 setter（被改写的是 `insertAdjacentHTML` /
   `appendChild` 这类**方法**时看不到）；对方把描述符设成 non-configurable 时修不了，如实报
   `data-dom-write-repair-failed` 并保持页面可用（不炸）。
   ============================================================================ */
(function () {
  'use strict';

  try {
    var nativeToString = Function.prototype.toString;
    var html = document.documentElement;
    var foundReported = false;
    var outcomeReported = false;
    var prevDesc = {};                                        // API → 我们动手之前的描述符（供还原）
    var giveUp = { innerHTML: 0, textContent: 0 };            // API → 「修了更糟」次数（≥2 不再尝试）

    function isNative(fn) {
      try { return typeof fn === 'function' && nativeToString.call(fn).indexOf('[native code]') >= 0; }
      catch (e) { return false; }
    }

    /** 行为探针：对游离元素连写两次 —— 第二次**必须**替换第一次（原生语义）。 */
    function probe(name, host, write, read) {
      var el = document.createElement('div');
      try {
        write(el, 'aaa');
        write(el, 'b');
        var got = read(el);
        if (got === 'b') return null;                 // 正常：替换语义
        var desc = null;
        try { desc = Object.getOwnPropertyDescriptor(host, name); } catch (e2) {}
        var src = '';
        try { src = desc && desc.set ? nativeToString.call(desc.set) : '(无 setter)'; } catch (e3) { src = '(源码不可读)'; }
        return {
          name: name,
          host: host,
          got: String(got).slice(0, 60),
          native: isNative(desc && desc.set),
          src: String(src).replace(/\s+/g, ' ').slice(0, 240)
        };
      } catch (e4) {
        return { name: name, host: host, got: '抛错: ' + (e4 && e4.message ? e4.message : e4), native: false, src: '' };
      }
    }

    function detectBad() {
      var bad = [];
      var a = probe('innerHTML', Element.prototype,
        function (el, v) { el.innerHTML = v; }, function (el) { return el.innerHTML; });
      if (a) bad.push(a);
      var b = probe('textContent', Node.prototype,
        function (el, v) { el.textContent = v; }, function (el) { return el.textContent; });
      if (b) bad.push(b);
      return bad;
    }

    function warnFound(bad) {
      var names = bad.map(function (x) { return x.name; }).join(',');
      if (foundReported) return;
      foundReported = true;
      var lines = bad.map(function (x) {
        return '  · ' + x.name + '：连写 "aaa" → "b"，读到 "' + x.got + '"（原生应只剩 "b"）'
          + '\n      setter 是否原生: ' + (x.native ? '是' : '否')
          + (x.src ? '\n      setter 源码片段: ' + x.src : '');
      }).join('\n');
      console.warn('[dom-write] DOM 写入语义被改写（' + names + '）：每次渲染都会多留一份内容，页面看起来「重复」。\n'
        + lines
        + '\n  本站代码不含任何此类改写 ⇒ 肇事者来自浏览器扩展 / 用户脚本 / 自动化面板注入的脚本（上面那段源码片段通常直接点名）。\n'
        + '  机器可读标记：<html data-dom-write-patched="' + names + '">');
    }

    /** 方案 ①（语义修复）：先清空子节点，再交给**当前**的 setter —— 抹平「前置插入/追加」，回到替换语义。
        只用 `firstChild` / `removeChild` / `appendChild`：比 `replaceChildren` 更不容易被同族改写波及。

        ⚠️ **`<template>` 必须特判**（2026-10-17 实测）：模板的内容在 `.content` 里，元素本身 childNodes 恒为空，
        所以「清空 + 委派」对模板是错的 —— 更要命的是**改写层自己会拿当前 setter 当解析器**
        （`const t = document.createElement('template'); 当前setter.call(t, v); 用 t.content`），
        于是委派链落到模板上、对方的 `this.insertBefore(t.content, this.firstChild)` 会把内容**丢空**
        （Chromium 实测：`t.content.childNodes.length === 0`）⇒ 页面渲染成空白（比「重复」更糟）。
        故模板一律**绕开委派**：自己用 `DOMParser` 解析（不经过被改写的 `innerHTML`）再填进 `.content`。 */
    function repairWrite(entry) {
      var cur = null;
      try { cur = Object.getOwnPropertyDescriptor(entry.host, entry.name); } catch (e) {}
      if (!cur || typeof cur.set !== 'function') return false;
      var delegate = cur.set, getter = cur.get;
      prevDesc[entry.name] = cur;                 // 记下「我们动手之前」的描述符，供修不动时还原
      try {
        Object.defineProperty(entry.host, entry.name, {
          configurable: true,
          enumerable: cur.enumerable,
          get: getter,
          set: function (v) {
            var text = v == null ? '' : String(v);
            try {                                  // ① 模板：content 才是它的内容
              if (this && this.content && this.content.nodeType === 11) {
                var doc = new DOMParser().parseFromString(text, 'text/html');
                var src = doc.body ? doc.body.childNodes : null;
                while (this.content.firstChild) this.content.removeChild(this.content.firstChild);
                if (src) { while (src.length) this.content.appendChild(src[0]); }
                return;
              }
            } catch (e2) { /* 模板路径失败就退回常规委派 */ }
            try { while (this.firstChild) this.removeChild(this.firstChild); } catch (e3) { /* 清不掉就照旧委派 */ }
            return delegate.call(this, v);
          }
        });
        return true;
      } catch (e4) {
        return false;
      }
    }

    /** 不许更糟：修完复核仍不达标 ⇒ 把描述符还原成「我们动手之前」的那个，并停止再尝试该 API。 */
    function revertWrite(name) {
      var prev = prevDesc[name];
      if (!prev) return;
      try {
        Object.defineProperty(name === 'innerHTML' ? Element.prototype : Node.prototype, name, prev);
      } catch (e) { /* 还原不了就只能保持现状（页面仍可用） */ }
    }

    function warnOutcome(ok, failed, still) {
      if (outcomeReported) return;
      outcomeReported = true;
      if (ok.length && !still.length) {
        console.warn('[dom-write] 已把写入语义修回「替换」（' + ok.join(',') + '）：本次渲染不会再累积重复内容。'
          + (failed.length ? ' 未修复: ' + failed.join(',') + '。' : '')
          + '\n  标记：<html data-dom-write-repaired="' + ok.join(',') + '">');
      } else {
        console.warn('[dom-write] 写入语义修复失败' + (still.length ? '（仍被改写: ' + still.join(',') + '）' : '')
          + (failed.length ? '（' + failed.join(',') + '）' : '')
          + ' —— 页面会继续出现「重复」。'
          + '\n  常见原因：对方把描述符设成 non-configurable（改不动），或改写层在本文件之后又跑了一次。'
          + '\n  标记：<html data-dom-write-repair-failed="' + (still.join(',') || failed.join(',')) + '">');
      }
    }

    function guard() {
      var bad = detectBad().filter(function (x) { return giveUp[x.name] < 2; });   // 已证明「修了更糟」的 API 不再动
      if (!bad.length) return;
      var names = bad.map(function (x) { return x.name; }).join(',');
      var isRepeat = foundReported;               // 之前已认出过一次 ⇒ 这次是「再次覆盖」
      html.setAttribute('data-dom-write-patched', names);
      if (!isRepeat) warnFound(bad);

      var ok = [], failed = [];
      for (var i = 0; i < bad.length; i++) {
        (repairWrite(bad[i]) ? ok : failed).push(bad[i].name);
      }
      var still = detectBad().map(function (x) { return x.name; });   // 修完复核：仍被改写 ⇒ 如实报失败
      if (ok.length && !still.length) {
        html.setAttribute('data-dom-write-repaired', ok.join(','));
        for (var j = 0; j < ok.length; j++) giveUp[ok[j]] = 0;
      } else {
        /* 不许更糟：修完仍不达标（常见于「对方把当前 setter 当解析器、链到我们的包装上」这种二次覆盖）
           ⇒ 把描述符还原成动手前的那个（页面继续「重复」但不再被我们弄坏），并停止再尝试该 API。 */
        for (var k = 0; k < ok.length; k++) { giveUp[ok[k]] = giveUp[ok[k]] + 1; revertWrite(ok[k]); }
        html.removeAttribute('data-dom-write-repaired');
        html.setAttribute('data-dom-write-repair-failed', (still.length ? still : failed).join(','));
      }
      if (isRepeat) {
        if (extraReports < 3) {
          extraReports++;
          console.warn('[dom-write] 改写层**再次**覆盖写入语义（' + names + '）—— 已' + (still.length ? '尝试' : '') + '再次修回'
            + (still.length ? '但失败' : '') + '。\n  说明对方会周期性重装钩子；上面第一次输出里的 setter 源码片段即肇事者。');
        }
      } else {
        warnOutcome(ok, failed, still);
      }
    }

    function dupIdReport() {
      var seen = Object.create(null), dup = 0, all = document.querySelectorAll('[id]');
      for (var i = 0; i < all.length; i++) {
        var id = all[i].id;
        if (seen[id]) dup++; else seen[id] = 1;
      }
      if (!dup) return;
      html.setAttribute('data-dom-write-dup-ids', String(dup));
      if (dup === lastDupCount) return;            // 同一批重复不重复刷屏（心跳会周期性调用本函数）
      lastDupCount = dup;
      console.warn('[dom-write] 检测到 ' + dup + ' 个重复 id（正常应为 0）——典型来源：第三方脚本克隆节点并插进文档。'
        + '\n  后果：document.getElementById 命中的是**第一个**副本 ⇒ 页面脚本的更新只写进那个副本，'
        + '其余副本冻结在旧值（表现即「同一块内容重复出现、且后几份是旧数据」）。');
    }

    /* ── 持续复核（2026-10-17 线上补）─────────────────────────────────────────
       为什么必须持续复核：改写层不一定在首帧前跑 —— 实测（验收 C5）**idle 阶段才跑的注入**
       会让首帧检查完全扑空，之后每轮渲染都「前置插入」（连点 3 次刷新：概览 6 → 24 小卡，
       与线上截图同形）；对方也可能在我们修回之后**再次**覆盖（C6）。
       廉价判据 = **setter 身份比对**（2 次 `getOwnPropertyDescriptor`，不做 toString）；身份变了
       才跑完整行为探针 + 重新修回。三路触发：3s 心跳（抓 idle 才跑的改写）、DOM 变化（前 90s，
       400ms 节流）、切回标签页（visibilitychange）。 */
    var lastSeen = { innerHTML: null, textContent: null };   // 上一次评估后的 setter 身份（= 我们自己装的包装）
    var extraReports = 0;                                    // 「再次覆盖」告警次数上限
    var lastDupCount = -1;                                   // 重复 id 上次上报值（同值不刷屏）

    function currentSetter(host, name) {
      try { var d = Object.getOwnPropertyDescriptor(host, name); return (d && d.set) || null; } catch (e) { return null; }
    }
    function remember() {
      lastSeen.innerHTML = currentSetter(Element.prototype, 'innerHTML');
      lastSeen.textContent = currentSetter(Node.prototype, 'textContent');
    }
    function recheck(force) {
      var a = currentSetter(Element.prototype, 'innerHTML');
      var b = currentSetter(Node.prototype, 'textContent');
      if (force || a !== lastSeen.innerHTML || b !== lastSeen.textContent) guard();
      remember();
      dupIdReport();
    }

    guard();                            // ① + ②：首帧前 —— 在 document_start 改写的注入脚本，这里就能认出并修回
    remember();
    dupIdReport();

    setInterval(function () { recheck(false); }, 3000);

    var lastTick = 0;
    function throttled() {              // MutationObserver 在每轮渲染时都会触发 ⇒ 400ms 节流
      var now = Date.now();
      if (now - lastTick < 400) return;
      lastTick = now;
      recheck(false);
    }

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () { recheck(true); });
    }
    document.addEventListener('visibilitychange', function () { if (!document.hidden) recheck(true); });
    try {
      var obs = new MutationObserver(throttled);
      obs.observe(document.documentElement || document, { childList: true, subtree: true });
      setTimeout(function () { try { obs.disconnect(); } catch (e) {} }, 90000);   // 之后交给心跳
    } catch (e) { /* 观察不到也不影响心跳那条路 */ }
  } catch (e) {
    /* 哨兵自身绝不把异常抛给页面；但**必须留痕** —— 静默失败会让「没认出改写」与「自己坏了」
       无法区分。2026-10-17 实测踩过：watch 状态漏声明 ⇒ strict 模式抛 ReferenceError ⇒
       整段持续复核被这层 catch 吞掉，验收表现为 C3/C5/C6 红而页面零报错（最难查的一种）。 */
    try {
      document.documentElement.setAttribute('data-dom-write-guard-error',
        String(e && e.message ? e.message : e).slice(0, 140));
      console.error('[dom-write] 哨兵自身出错（已降级为不干预）: ' + (e && e.message ? e.message : e));
    } catch (e2) { /* 连留痕都失败就彻底放弃 */ }
  }
})();
