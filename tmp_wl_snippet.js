      // 自选股实时取数：hidden=false（有配置）才显示卡片；取数失败/超时占位可见，不静默
      var wlTimer = null;
      var wlFetch = fetch("/api/watchlist").then(function (r) { return r.json(); });
      var wlTimeout = new Promise(function (_, reject) {
        wlTimer = setTimeout(function () { reject(new Error("watchlist 取数超时（12s）")); }, 12000);
      });
      Promise.race([wlFetch, wlTimeout])
        .then(function (data) {
          clearTimeout(wlTimer);
          var sec = document.getElementById("watchlist-section");
          if (!sec) return;
          if (data && data.hidden) { sec.style.display = "none"; return; }
          sec.style.display = "";
          if (!data || !data.stocks || !data.stocks.length) {
            var b = document.getElementById("watchlist-body");
            if (b) b.innerHTML = '<tr><td colspan="4" class="empty">数据暂缺（实时取数失败）</td></tr>';
            return;
          }
          renderWatchlist(data);
        })
        .catch(function (err) {
          console.error("[watchlist] fetch failed:", err);
          var sec = document.getElementById("watchlist-section");
          if (!sec) return;
          sec.style.display = "";
          var b = document.getElementById("watchlist-body");
          if (b) b.innerHTML = '<tr><td colspan="4" class="empty">数据暂缺（取数失败）</td></tr>';
        });
