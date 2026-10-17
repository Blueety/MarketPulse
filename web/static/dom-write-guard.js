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
        只用 `firstChild` / `removeChild`：比 `replaceChildren` 更不容易被同族改写波及。 */
    function repairWrite(entry) {
      var cur = null;
      try { cur = Object.getOwnPropertyDescriptor(entry.host, entry.name); } catch (e) {}
      if (!cur || typeof cur.set !== 'function') return false;
      var delegate = cur.set, getter = cur.get;
      try {
        Object.defineProperty(entry.host, entry.name, {
          configurable: true,
          enumerable: cur.enumerable,
          get: getter,
          set: function (v) {
            try { while (this.firstChild) this.removeChild(this.firstChild); } catch (e2) { /* 清不掉就照旧委派 */ }
            return delegate.call(this, v);
          }
        });
        return true;
      } catch (e3) {
        return false;
      }
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
      var bad = detectBad();
      if (!bad.length) return;
      var names = bad.map(function (x) { return x.name; }).join(',');
      html.setAttribute('data-dom-write-patched', names);
      warnFound(bad);

      var ok = [], failed = [];
      for (var i = 0; i < bad.length; i++) {
        (repairWrite(bad[i]) ? ok : failed).push(bad[i].name);
      }
      var still = detectBad().map(function (x) { return x.name; });   // 修完复核：仍被改写 ⇒ 如实报失败
      if (ok.length && !still.length) {
        html.setAttribute('data-dom-write-repaired', ok.join(','));
      } else {
        html.removeAttribute('data-dom-write-repaired');
        html.setAttribute('data-dom-write-repair-failed', (still.length ? still : failed).join(','));
      }
      warnOutcome(ok, failed, still);
    }

    function dupIdReport() {
      var seen = Object.create(null), dup = 0, all = document.querySelectorAll('[id]');
      for (var i = 0; i < all.length; i++) {
        var id = all[i].id;
        if (seen[id]) dup++; else seen[id] = 1;
      }
      if (!dup) return;
      html.setAttribute('data-dom-write-dup-ids', String(dup));
      console.warn('[dom-write] 检测到 ' + dup + ' 个重复 id（正常应为 0）——典型来源：第三方脚本克隆节点并插进文档。'
        + '\n  后果：document.getElementById 命中的是**第一个**副本 ⇒ 页面脚本的更新只写进那个副本，'
        + '其余副本冻结在旧值（表现即「同一块内容重复出现、且后几份是旧数据」）。');
    }

    guard();                            // ① + ②：首帧前 —— 在 document_start 改写的注入脚本，这里就能认出并修回

    function lateCheck() {              // ③：晚改写 / 克隆型
      guard();
      dupIdReport();
    }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () { setTimeout(lateCheck, 1500); });
    } else {
      setTimeout(lateCheck, 1500);
    }
  } catch (e) {
    /* 哨兵自身绝不把异常抛给页面 */
  }
})();
