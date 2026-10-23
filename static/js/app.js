/* ============================================================
   云音盒子 - 前端脚本（全新版）
   原生 JS，无外部依赖
   功能：搜索 / 解析 / 歌单 / 专辑 / 下载 / 播放器模式
   ============================================================ */
(function () {
  "use strict";

  /* ================= 工具 ================= */

  const $ = (sel, parent) => (parent || document).querySelector(sel);
  const $$ = (sel, parent) => Array.prototype.slice.call((parent || document).querySelectorAll(sel));

  function escapeHtml(str) {
    return String(str == null ? "" : str)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function fmtTime(sec) {
    if (!isFinite(sec) || sec < 0) sec = 0;
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return m + ":" + String(s).padStart(2, "0");
  }

  // 全局 toast 提示
  const toast = (function () {
    let timer = null;
    return function (msg) {
      const el = $("#toast");
      el.textContent = msg;
      el.classList.add("show");
      clearTimeout(timer);
      timer = setTimeout(function () { el.classList.remove("show"); }, 2400);
    };
  })();

  // 按钮 loading 态（spinner + 禁用，防重复点击）
  function setBtnLoading(btn, on, loadingText) {
    if (!btn) return;
    const label = btn.querySelector(".btn-label");
    if (on) {
      if (!btn.dataset.origText && label) btn.dataset.origText = label.textContent;
      if (label && loadingText) label.textContent = loadingText;
      btn.classList.add("is-loading");
      btn.disabled = true;
    } else {
      btn.classList.remove("is-loading");
      btn.disabled = false;
      if (label && btn.dataset.origText) label.textContent = btn.dataset.origText;
    }
  }

  // 请求封装（后端 _safe_get_request_data 同时接受 JSON 与表单）
  async function apiJSON(url, opts) {
    opts = opts || {};
    const method = opts.method || "GET";
    let full = url;
    if (method === "GET" && opts.data) {
      full += "?" + new URLSearchParams(opts.data).toString();
    }
    const init = { method: method };
    if (method === "POST") {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(opts.data || {});
    }
    const res = await fetch(full, init);
    let body = null;
    try { body = await res.json(); } catch (e) { /* 非 JSON 响应 */ }
    if (!res.ok) {
      // 会话失效时重置本地登录态
      if (res.status === 401 && Auth.user) {
        Auth.user = null;
        Auth.renderUI();
      }
      throw new Error((body && body.message) || ("HTTP " + res.status));
    }
    return body;
  }

  // 列表骨架屏
  function showSkeleton(listEl, rows) {
    let html = "";
    for (let i = 0; i < rows; i++) {
      html += '<li class="skeleton-item">' +
        '<div class="sk sk-cover"></div>' +
        '<div class="sk-lines"><div class="sk sk-line w60"></div><div class="sk sk-line w40"></div></div>' +
        "</li>";
    }
    listEl.innerHTML = html;
  }

  /* ================= LRC 歌词 ================= */

  // 解析 LRC -> [{t(ms), text}]
  function parseLrc(lyrics) {
    if (!lyrics) return [];
    const out = [];
    lyrics.split("\n").forEach(function (line) {
      const m = line.match(/\[(\d{2}):(\d{2}[\.:]?\d*)]/g);
      const text = line.replace(/\[\d{2}:\d{2}[\.:]?\d*\]/g, "").trim();
      if (!m || !text) return;
      m.forEach(function (tag) {
        const t = tag.match(/\[(\d{2}):(\d{2}[\.:]?\d*)]/);
        const min = parseInt(t[1], 10);
        const sec = parseFloat(t[2].replace(".", ":")) || 0;
        out.push({ t: min * 60000 + sec * 1000, text: text });
      });
    });
    out.sort(function (a, b) { return a.t - b.t; });
    return out;
  }

  // 原文 + 翻译合并 -> [{t, text, trans}]
  function mergeLyric(lrc, tlyric) {
    const base = parseLrc(lrc);
    if (!tlyric) return base.map(function (l) { return { t: l.t, text: l.text, trans: "" }; });
    const trans = parseLrc(tlyric);
    let j = 0;
    base.forEach(function (line) {
      while (j < trans.length - 1 && trans[j].t < line.t - 300) j++;
      if (Math.abs(trans[j] ? trans[j].t - line.t : 1e9) < 500) {
        line.trans = trans[j].text;
      }
    });
    return base;
  }

  /* ================= 模式切换 ================= */

  const MODE_PANELS = {
    search: "panel-search",
    parse: "panel-parse",
    playlist: "panel-playlist",
    album: "panel-album",
    download: "panel-download",
    player: "panel-player",
    favorites: "panel-favorites",
  };
  const RESULT_IDS = ["search-result", "song-info-card", "playlist-result", "album-result"];
  const RESULT_OWNER = { "search-result": "search", "song-info-card": "parse", "playlist-result": "playlist", "album-result": "album" };

  // 页签滑动玻璃指示器：定位到当前激活页签下方
  function updateTabsIndicator() {
    const bar = $(".mode-tabs");
    const ind = $("#tabs-indicator");
    const tab = $(".mode-tab.active");
    if (!bar || !ind || !tab || !tab.offsetParent) { if (ind) ind.classList.remove("ready"); return; }
    ind.style.left = tab.offsetLeft + "px";
    ind.style.width = tab.offsetWidth + "px";
    ind.classList.add("ready");
  }

  function switchMode(mode) {
    Object.keys(MODE_PANELS).forEach(function (key) {
      $("#" + MODE_PANELS[key]).classList.toggle("hidden", key !== mode);
    });
    $$(".mode-tab").forEach(function (tab) {
      tab.classList.toggle("active", tab.dataset.mode === mode);
    });
    // 非本模式时隐藏对应结果
    RESULT_IDS.forEach(function (id) {
      if (RESULT_OWNER[id] !== mode) $("#" + id).classList.add("hidden");
    });
    if (mode === "favorites") loadFavorites();
    window.scrollTo({ top: 0, behavior: "smooth" });
    updateTabsIndicator();
  }

  /* ================= 应用模式（听音乐 / 下音乐） ================= */

  function setAppMode(m) {
    document.body.dataset.appmode = m;
    try { localStorage.setItem("appmode", m); } catch (e) { /* 忽略 */ }
    $$(".appmode-btn").forEach(function (b) {
      b.classList.toggle("active", b.dataset.app === m);
    });
    // 切换模式后若当前页签被隐藏（scope 不符），回退到搜索页
    const cur = $(".mode-tab.active");
    if (cur && !cur.offsetParent) switchMode("search");
    updateTabsIndicator();
  }

  /* ================= ID / 链接处理 ================= */

  function extractIdFromLink(text) {
    const m = text.match(/song\?id=(\d+)/);
    if (m) return m[1];
    const ids = text.match(/\b\d+\b/g);
    return ids ? ids[0] : "";
  }
  function extractPlaylistId(text) {
    const m = text.match(/playlist\?id=(\d+)/);
    if (m) return m[1];
    const ids = text.match(/\b\d+\b/g);
    return ids ? ids[0] : "";
  }
  function extractAlbumId(text) {
    const m = text.match(/album\?id=(\d+)/);
    if (m) return m[1];
    const ids = text.match(/\b\d+\b/g);
    return ids ? ids[0] : "";
  }

  /* ================= 下载 ================= */

  function downloadMusicById(musicId, quality, btn) {
    setBtnLoading(btn, true, "下载中…");
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/Download", true);
    xhr.setRequestHeader("Content-Type", "application/x-www-form-urlencoded");
    xhr.responseType = "blob";
    xhr.onload = function () {
      if (xhr.status === 200) {
        const encoded = xhr.getResponseHeader("X-Download-Filename");
        const filename = encoded ? decodeURIComponent(encoded) : "music.mp3";
        const url = window.URL.createObjectURL(xhr.response);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        toast("音乐文件下载完成");
      } else {
        toast("下载失败，请重试");
      }
      setBtnLoading(btn, false);
    };
    xhr.onerror = function () {
      toast("下载出错，请重试");
      setBtnLoading(btn, false);
    };
    xhr.send("id=" + encodeURIComponent(musicId) + "&quality=" + encodeURIComponent(quality));
  }

  /* ================= 列表渲染 ================= */

  const ICON_PLAY = '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>';

  function buildTrackItem(song, index, showIndex, extraBtn) {
    const name = song.name || "未知歌曲";
    const artist = song.artists || song.artist || "";
    const meta = artist + (song.album ? "  ·  " + song.album : "");
    return '<li class="track-item">' +
      (showIndex ? '<span class="track-index">' + (index + 1) + "</span>" : "") +
      '<img class="track-cover" src="' + escapeHtml(song.picUrl || song.pic || "") + '" alt="" loading="lazy" onerror="this.style.visibility=\'hidden\'">' +
      '<div class="track-info">' +
      '<div class="track-name">' + escapeHtml(name) + "</div>" +
      '<div class="track-meta">' + escapeHtml(meta) + "</div>" +
      "</div>" +
      '<div class="track-actions">' +
      '<button type="button" class="icon-btn act-play" data-id="' + escapeHtml(song.id) + '" data-name="' + escapeHtml(name) + '" data-artist="' + escapeHtml(artist) + '" data-pic="' + escapeHtml(song.picUrl || song.pic || "") + '" title="播放">' + ICON_PLAY + "</button>" +
      '<button type="button" class="pill-btn act-parse" data-id="' + escapeHtml(song.id) + '" data-name="' + escapeHtml(name) + '">解析</button>' +
      '<button type="button" class="pill-btn act-dl" data-id="' + escapeHtml(song.id) + '">下载</button>' +
      (extraBtn || "") +
      "</div>" +
      "</li>";
  }

  function renderTrackList(listEl, songs, showIndex) {
    if (songs && songs.length) {
      listEl.innerHTML = songs.map(function (s, i) {
        return buildTrackItem(s, i, showIndex);
      }).join("");
    } else {
      listEl.innerHTML = '<li class="empty-state">未找到相关内容</li>';
    }
  }

  // 收集某列表内所有歌曲（用于全部播放）
  function collectListSongs(listEl) {
    return $$(".act-play", listEl).map(function (btn) {
      return {
        id: btn.dataset.id,
        name: btn.dataset.name,
        artist: btn.dataset.artist,
        pic: btn.dataset.pic,
      };
    });
  }

  /* ================= 播放器 ================= */

  const ICON_PAUSE = '<svg viewBox="0 0 24 24"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>';
  const ICON_PLAY_SM = '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>';
  const ICON_LOOP_LIST = '<svg viewBox="0 0 24 24"><path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/></svg>';
  const ICON_SHUFFLE = '<svg viewBox="0 0 24 24"><path d="M16 3h5v5"/><path d="M4 20 21 3"/><path d="M21 16v5h-5"/><path d="m15 15 6 6"/><path d="M4 4l5 5"/></svg>';

  /* ---- 封面占位图（无封面 / 加载失败时的兜底，避免破图） ---- */
  const PLACEHOLDER = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">' +
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">' +
    '<stop offset="0" stop-color="#2a2d3f"/><stop offset="1" stop-color="#17181f"/></linearGradient></defs>' +
    '<rect width="200" height="200" fill="url(#g)"/>' +
    '<path d="M82 138V76l48-10v62" fill="none" stroke="rgba(255,255,255,0.4)" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>' +
    '<ellipse cx="72" cy="140" rx="14" ry="10" fill="rgba(255,255,255,0.4)"/>' +
    '<ellipse cx="120" cy="130" rx="14" ry="10" fill="rgba(255,255,255,0.4)"/>' +
    "</svg>"
  );

  // 给关键封面 img 挂载 onerror 兜底（加载失败自动换成占位图）
  window.__PLACEHOLDER__ = PLACEHOLDER;
  function installCoverFallback() {
    ["#pl-cover", "#pb-cover", "#fs-cover", "#fs-bg", "#fs2-cover", "#song_cover"].forEach(function (sel) {
      const img = $(sel);
      if (!img) return;
      img.addEventListener("error", function () {
        if (img.src !== PLACEHOLDER) img.src = PLACEHOLDER;
      });
    });
  }

  /* ---- 歌词平滑滚动（lerp 逼近目标位置，比 scrollTo(smooth) 更顺滑） ----
     支持多个歌词容器（播放器页 / 全屏歌词视图），各自独立动画队列 */
  function createLerpScroller(el) {
    let target = 0;
    let raf = null;
    function step() {
      const diff = target - el.scrollTop;
      if (Math.abs(diff) < 0.5) {
        el.scrollTop = target;
        raf = null;
        return;
      }
      el.scrollTop += diff * 0.13;
      raf = requestAnimationFrame(step);
    }
    return {
      scrollTo: function (top) {
        target = top;
        if (raf === null) raf = requestAnimationFrame(step);
      },
      // 立即终止进行中的动画（用户手动滚动时调用，避免与手滚动互相拉扯产生"反弹"）
      cancel: function () {
        if (raf !== null) {
          cancelAnimationFrame(raf);
          raf = null;
        }
      },
    };
  }

  // 歌词容器注册表：[{el, lines, scroller}]
  const LyricViews = [];
  function registerLyricBox(el) {
    if (!el) return null;
    const box = { el: el, lines: [], scroller: createLerpScroller(el) };
    LyricViews.push(box);
    return box;
  }

  // 用户手动滚动歌词后暂停自动跟随；3 秒无操作平滑复位回当前播放行
  let userScrollHold = 0;
  let holdingForResume = false;
  function holdAutoScroll(e) {
    // 终止被滚动容器正在进行的 lerp 动画，消除与手动滚动的拉扯（反弹感）
    LyricViews.forEach(function (box) {
      if (!e || box.el.contains(e.target)) box.scroller.cancel();
    });
    userScrollHold = Date.now() + 3000;
    holdingForResume = true;
  }

  /* ---- 播放进度 rAF 驱动（播放时逐帧刷新进度条与歌词，暂停时停止省电） ---- */
  let rafId = null;
  function startRaf() {
    if (rafId === null) {
      const loop = function () {
        Player.syncProgress();
        rafId = requestAnimationFrame(loop);
      };
      rafId = requestAnimationFrame(loop);
    }
  }
  function stopRaf() {
    if (rafId !== null) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
  }

  const Player = {
    audio: new Audio(),
    queue: [],
    index: -1,
    loop: "list", // list | one | shuffle
    lyrics: [],
    lyricIdx: -1,
    loadingTrack: false,

    current: function () { return this.queue[this.index] || null; },

    // 加入队列；replace=true 时替换整个队列并立即播放
    add: function (meta, replace) {
      const item = {
        id: meta.id, name: meta.name || "", artist: meta.artist || "",
        pic: meta.pic || "", pending: true, url: "", lyric: [],
      };
      if (replace) {
        this.queue = [item];
        this.playAt(0);
      } else {
        this.queue.push(item);
        if (this.index === -1) this.playAt(this.queue.length - 1);
        else { this.renderQueue(); this.updateCount(); }
      }
      this.syncBarVisibility();
    },

    // 解析真实音源并播放
    playAt: async function (i) {
      if (i < 0 || i >= this.queue.length || this.loadingTrack) return;
      this.loadingTrack = true;
      this.index = i;
      const item = this.queue[i];
      this.renderQueue();
      this.setMeta(item, "加载中…");
      this.buildLyrics([]);
      this.updatePlayIcons();

      try {
        if (item.pending) {
          const data = await apiJSON("/Song_V1", {
            method: "POST",
            data: { url: item.id, level: "lossless", type: "json" },
          });
          if (data.status !== 200 || !data.data) throw new Error(data.message || "解析失败");
          const d = data.data;
          item.name = item.name || d.name;
          item.artist = item.artist || d.ar_name;
          item.pic = item.pic || d.pic;
          item.url = d.url || "";
          item.level = d.level || "";
          item.lyric = mergeLyric(d.lyric, d.tlyric);
          item.pending = false;
          if (!item.url) throw new Error("暂无可播放音源（可能受版权限制）");
        }
        this.audio.src = item.url;
        this.audio.play().catch(function () { /* 自动播放被拦截时由用户手动点击 */ });
        this.buildLyrics(item.lyric);
        this.setMeta(item, null);
        refreshPlayerFav();
      } catch (e) {
        toast(e.message || "播放失败");
        this.setMeta(item, null);
      } finally {
        this.loadingTrack = false;
        this.renderQueue();
      }
    },

    playPause: function () {
      if (!this.current()) return;
      if (this.audio.paused) this.audio.play().catch(function () {});
      else this.audio.pause();
    },

    next: function (auto) {
      if (!this.queue.length) return;
      if (auto && this.loop === "one") {
        this.audio.currentTime = 0;
        this.audio.play().catch(function () {});
        return;
      }
      let i;
      if (this.loop === "shuffle") {
        i = Math.floor(Math.random() * this.queue.length);
        if (this.queue.length > 1 && i === this.index) i = (i + 1) % this.queue.length;
      } else {
        i = this.index + 1;
        if (i >= this.queue.length) i = 0;
      }
      this.playAt(i);
    },

    prev: function () {
      if (!this.queue.length) return;
      const i = this.index - 1 < 0 ? this.queue.length - 1 : this.index - 1;
      this.playAt(i);
    },

    clear: function () {
      this.queue = [];
      this.index = -1;
      this.audio.pause();
      this.audio.removeAttribute("src");
      this.lyrics = [];
      this.buildLyrics([]);
      this.renderQueue();
      this.updateCount();
      this.syncBarVisibility();
      this.setMeta(null, null);
      this.updatePlayIcons();
      refreshPlayerFav();
      toast("播放队列已清空");
    },

    removeAt: function (i) {
      if (i < 0 || i >= this.queue.length) return;
      this.queue.splice(i, 1);
      if (i < this.index) this.index--;
      else if (i === this.index) {
        this.index = Math.min(this.index, this.queue.length - 1);
        if (this.queue.length && this.index >= 0) this.playAt(this.index);
        else this.clear();
        return;
      }
      this.renderQueue();
      this.updateCount();
      this.syncBarVisibility();
    },

    cycleLoop: function () {
      const order = ["list", "one", "shuffle"];
      this.loop = order[(order.indexOf(this.loop) + 1) % order.length];
      this.renderLoopIcon();
      const names = { list: "列表循环", one: "单曲循环", shuffle: "随机播放" };
      toast(names[this.loop]);
    },

    renderLoopIcon: function () {
      const self = this;
      $$(".loop-btn").forEach(function (btn) {
        if (self.loop === "shuffle") {
          btn.innerHTML = ICON_SHUFFLE + '<span class="loop-one hidden">1</span>';
        } else {
          btn.innerHTML = ICON_LOOP_LIST +
            '<span class="loop-one' + (self.loop === "one" ? "" : " hidden") + '">1</span>';
        }
        const names = { list: "列表循环", one: "单曲循环", shuffle: "随机播放" };
        btn.title = "播放模式：" + names[self.loop] + "（点击切换）";
      });
    },

    /* ---- UI 同步 ---- */

    setMeta: function (item, hint) {
      const name = item ? item.name || "加载中…" : "未在播放";
      const artist = hint || (item ? item.artist || "" : "从任意列表点 ▶ 开始播放");
      $("#pl-name").textContent = name;
      $("#pl-artist").textContent = artist;
      $("#fs-name").textContent = name;
      $("#fs-artist").textContent = artist;
      $("#fs2-name").textContent = name;
      $("#fs2-artist").textContent = artist;
      $("#pb-name").textContent = name;
      $("#pb-artist").textContent = item ? item.artist || "" : "";
      const levelEl = $("#pl-level");
      if (item && item.level) {
        levelEl.textContent = item.level;
        levelEl.classList.remove("hidden");
      } else {
        levelEl.classList.add("hidden");
      }
      // 无封面或为空时使用占位图，避免显示破图
      const cover = item && item.pic ? item.pic : PLACEHOLDER;
      ["#pl-cover", "#pb-cover", "#fs-cover", "#fs-bg", "#fs2-cover"].forEach(function (sel) {
        const img = $(sel);
        if (img.src !== cover) img.src = cover;
      });
      const playing = !!(item && !this.audio.paused);
      $("#pl-cover").classList.toggle("pf-playing", playing);
      $("#pb-cover").classList.toggle("spinning", playing);
      $("#fs-cover").classList.toggle("fs-playing", playing);
      $("#fs2-cover").classList.toggle("fs-playing", playing);
      // 系统媒体控制（任务栏 / 锁屏 / 蓝牙耳机）显示歌曲与封面
      if ("mediaSession" in navigator && item) {
        try {
          navigator.mediaSession.metadata = new MediaMetadata({
            title: item.name || "",
            artist: item.artist || "",
            album: item.album || "",
            artwork: item.pic ? [{ src: item.pic, sizes: "512x512" }] : [],
          });
        } catch (e) { /* 忽略 */ }
      }
    },

    updateCount: function () {
      $("#pl-queue-count").textContent = this.queue.length ? "（" + this.queue.length + "）" : "";
    },

    syncBarVisibility: function () {
      $("#player-bar").classList.toggle("hidden", this.queue.length === 0);
    },

    updatePlayIcons: function () {
      const playing = !this.audio.paused && !!this.current();
      ["#pl-play", "#pb-play", "#fs-play", "#fs2-play"].forEach(function (sel) {
        const btn = $(sel);
        btn.querySelector(".ic-play").classList.toggle("hidden", playing);
        btn.querySelector(".ic-pause").classList.toggle("hidden", !playing);
      });
      $("#pl-cover").classList.toggle("pf-playing", playing);
      $("#pb-cover").classList.toggle("spinning", playing);
      $("#fs-cover").classList.toggle("fs-playing", playing);
      $("#fs2-cover").classList.toggle("fs-playing", playing);
    },

    buildLyrics: function (lines) {
      this.lyrics = lines || [];
      this.lyricIdx = -1;
      const html = this.lyrics.length
        ? this.lyrics.map(function (l) {
            const trans = l.trans ? '<span class="lrc-trans">' + escapeHtml(l.trans) + "</span>" : "";
            return '<p class="lrc-line" data-t="' + l.t + '">' + escapeHtml(l.text) + trans + "</p>";
          }).join("")
        : "";
      LyricViews.forEach(function (box) {
        box.el.innerHTML = html || '<p class="lyric-hint">暂无歌词</p>';
        box.lines = $$(".lrc-line", box.el);
      });
    },

    syncLyric: function (curMs) {
      // 手动滚动暂停期结束后：平滑复位回当前播放行（不瞬跳）
      if (holdingForResume && Date.now() > userScrollHold) {
        holdingForResume = false;
        const idxNow = this.lyricIdx;
        LyricViews.forEach(function (box) {
          const active = box.lines[idxNow];
          if (active) {
            box.scroller.scrollTo(active.offsetTop - box.el.clientHeight / 2 + active.offsetHeight / 2);
          }
        });
      }
      if (!this.lyrics.length) { $("#pb-lyric").textContent = ""; return; }
      let idx = -1;
      for (let i = 0; i < this.lyrics.length; i++) {
        if (this.lyrics[i].t <= curMs) idx = i; else break;
      }
      // 底部播放栏歌词行（每帧更新，低成本）
      const line = idx >= 0 ? this.lyrics[idx] : null;
      const text = line ? line.text + (line.trans ? " / " + line.trans : "") : "";
      const pbLyric = $("#pb-lyric");
      if (pbLyric.textContent !== text) pbLyric.textContent = text;
      const fsLyric = $("#fs-lyric");
      const fsText = line ? line.text : "";
      if (fsLyric.textContent !== fsText) {
        fsLyric.textContent = fsText;
        fsLyric.classList.toggle("show", !!fsText);
      }

      if (idx === this.lyricIdx) return;
      this.lyricIdx = idx;
      // 用户手动滚动期间暂停自动跟随，但高亮照常
      const autoOk = Date.now() > userScrollHold;
      LyricViews.forEach(function (box) {
        box.lines.forEach(function (el, i) {
          el.classList.toggle("active", i === idx);
        });
        const active = box.lines[idx];
        if (active && autoOk) {
          // 目标位置交给 lerp 动画器平滑逼近，避免 scrollTo 抖动
          box.scroller.scrollTo(active.offsetTop - box.el.clientHeight / 2 + active.offsetHeight / 2);
        }
      });
    },

    syncProgress: function () {
      const dur = this.audio.duration || 0;
      const cur = this.audio.currentTime || 0;
      const pct = dur ? (cur / dur) * 1000 : 0;
      ["#pl-seek", "#pb-seek", "#fs-seek", "#fs2-seek"].forEach(function (sel) {
        const input = $(sel);
        if (!input.matches(":active")) {
          input.value = pct;
          input.style.setProperty("--fill", (pct / 10) + "%");
        }
      });
      const t1 = fmtTime(cur), t2 = fmtTime(dur);
      $("#pl-cur").textContent = t1;
      $("#pl-dur").textContent = t2;
      $("#pb-cur").textContent = t1;
      $("#pb-dur").textContent = t2;
      $("#fs-cur").textContent = t1;
      $("#fs-dur").textContent = t2;
      $("#fs2-cur").textContent = t1;
      $("#fs2-dur").textContent = t2;
      this.syncLyric(cur * 1000);
    },

    renderQueue: function () {
      const list = $("#pl-queue");
      if (!this.queue.length) {
        list.innerHTML = '<li class="empty-state">队列空空如也，去添加几首歌吧</li>';
        return;
      }
      const self = this;
      list.innerHTML = this.queue.map(function (item, i) {
        const isCur = i === self.index;
        const indicator = isCur
          ? (self.loadingTrack ? '<span class="eq"><i></i><i></i><i></i></span>' : '<span class="eq"><i></i><i></i><i></i></span>')
          : '<span class="q-index">' + (i + 1) + "</span>";
        return '<li class="queue-item' + (isCur ? " playing" : "") + '" data-i="' + i + '">' +
          indicator +
          '<div class="q-info">' +
          '<div class="q-name">' + escapeHtml(item.name || item.id) + "</div>" +
          '<div class="q-artist">' + escapeHtml(item.artist || " ") + "</div>" +
          "</div>" +
          '<button type="button" class="q-remove" data-i="' + i + '" title="移除">×</button>' +
          "</li>";
      }).join("");
      this.updateCount();
    },
  };

  /* ================= 各功能处理 ================= */

  // 搜索
  async function handleSearch() {
    const kw = $("#search_keywords").value.trim();
    if (!kw) { toast("请输入搜索关键词"); return; }
    const btn = $("#search-btn");
    if (btn.disabled) return;
    setBtnLoading(btn, true, "搜索中…");
    const listEl = $("#search-list");
    showSkeleton(listEl, 6);
    $("#search-result").classList.remove("hidden");
    try {
      const data = await apiJSON("/Search", { method: "POST", data: { keyword: kw, limit: $("#search_limit").value || 10 } });
      renderTrackList(listEl, data.status === 200 ? data.data : null, false);
    } catch (e) {
      listEl.innerHTML = '<li class="empty-state">搜索失败，请重试</li>';
    } finally {
      setBtnLoading(btn, false);
    }
  }

  // 单曲解析
  let currentParse = null;

  async function handleParse() {
    const input = $("#song_ids").value.trim();
    if (!input) { toast("请输入歌曲ID或URL"); return; }
    const btn = $("#parse-btn");
    if (btn.disabled) return;
    setBtnLoading(btn, true, "解析中…");
    $("#parse-loading").classList.remove("hidden");
    $("#song-info-card").classList.add("hidden");
    try {
      const data = await apiJSON("/Song_V1", {
        method: "POST",
        data: { url: input, level: $("#level").value, type: "json" },
      });
      if (data.status !== 200 || !data.data) {
        toast(data.message || "解析失败，可能是版权限制");
        return;
      }
      const d = data.data;
      currentParse = d;
      $("#song_name").textContent = d.name || "未知歌曲";
      $("#artist_names").textContent = d.ar_name || "";
      $("#song_alname").textContent = d.al_name || "";
      $("#song_level").textContent = d.level || "";
      $("#song_size").textContent = d.size || "";
      $("#song_cover").src = d.pic || "";
      const lyricText = d.tlyric ? mergeLyric(d.lyric, d.tlyric)
        .map(function (l) { return l.text + (l.trans ? "（" + l.trans + "）" : ""); }).join("\n")
        : (d.lyric || "");
      const box = $("#lyric");
      if (lyricText.trim()) { box.textContent = lyricText; box.classList.remove("hidden"); }
      else { box.textContent = "暂无歌词"; }
      $("#show-big-pic").dataset.pic = d.pic || "";
      $("#song-info-card").classList.remove("hidden");
      refreshFavState();
    } catch (e) {
      toast("解析失败：" + e.message);
    } finally {
      setBtnLoading(btn, false);
      $("#parse-loading").classList.add("hidden");
    }
  }

  // 歌单解析
  async function handlePlaylist() {
    const input = $("#playlist_id").value.trim();
    if (!input) { toast("请输入歌单ID或链接"); return; }
    const btn = $("#playlist-btn");
    if (btn.disabled) return;
    setBtnLoading(btn, true, "解析中…");
    const listEl = $("#playlist-tracks");
    showSkeleton(listEl, 6);
    $("#playlist-result").classList.remove("hidden");
    try {
      const data = await apiJSON("/Playlist", { data: { id: extractPlaylistId(input) } });
      if (data.status !== 200 || !data.data || !data.data.playlist) {
        listEl.innerHTML = '<li class="empty-state">歌单解析失败：' + escapeHtml(data.message || "") + "</li>";
        return;
      }
      const pl = data.data.playlist;
      $("#playlist-cover").src = pl.coverImgUrl || "";
      $("#playlist-name").textContent = pl.name || "";
      $("#playlist-creator").textContent = "by " + (pl.creator || "");
      $("#playlist-desc").textContent = pl.description || "";
      $("#playlist-desc").classList.toggle("hidden", !pl.description);
      $("#playlist-count").innerHTML = "<b>" + (pl.trackCount || (pl.tracks || []).length) + "</b> 首歌";
      renderTrackList(listEl, pl.tracks, true);
    } catch (e) {
      listEl.innerHTML = '<li class="empty-state">歌单解析失败，请重试</li>';
    } finally {
      setBtnLoading(btn, false);
    }
  }

  // 专辑解析
  async function handleAlbum() {
    const input = $("#album_id").value.trim();
    if (!input) { toast("请输入专辑ID或链接"); return; }
    const btn = $("#album-btn");
    if (btn.disabled) return;
    setBtnLoading(btn, true, "解析中…");
    const listEl = $("#album-tracks");
    showSkeleton(listEl, 6);
    $("#album-result").classList.remove("hidden");
    try {
      const data = await apiJSON("/Album", { data: { id: extractAlbumId(input) } });
      if (data.status !== 200 || !data.data || !data.data.album) {
        listEl.innerHTML = '<li class="empty-state">专辑解析失败：' + escapeHtml(data.message || "") + "</li>";
        return;
      }
      const al = data.data.album;
      $("#album-cover").src = al.coverImgUrl || "";
      $("#album-name").textContent = al.name || "";
      $("#album-artist").textContent = al.artist || "";
      $("#album-desc").textContent = al.description || "";
      $("#album-desc").classList.toggle("hidden", !al.description);
      $("#album-count").innerHTML = "<b>" + (al.songs || []).length + "</b> 首歌";
      renderTrackList(listEl, al.songs, true);
    } catch (e) {
      listEl.innerHTML = '<li class="empty-state">专辑解析失败，请重试</li>';
    } finally {
      setBtnLoading(btn, false);
    }
  }

  // 独立下载
  function handleDownload() {
    const input = $("#download_id").value.trim();
    if (!input) { toast("请输入音乐ID或URL"); return; }
    const btn = $("#download-btn");
    if (btn.disabled) return;
    $("#download-progress").classList.remove("hidden");
    setBtnLoading(btn, true, "下载中…");
    const finish = function () {
      $("#download-progress").classList.add("hidden");
      setBtnLoading(btn, false);
    };
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/Download", true);
    xhr.setRequestHeader("Content-Type", "application/x-www-form-urlencoded");
    xhr.responseType = "blob";
    xhr.onload = function () {
      if (xhr.status === 200) {
        const encoded = xhr.getResponseHeader("X-Download-Filename");
        const filename = encoded ? decodeURIComponent(encoded) : "music.flac";
        const url = window.URL.createObjectURL(xhr.response);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        toast("音乐文件下载完成");
      } else {
        toast("下载失败，请重试");
      }
      finish();
    };
    xhr.onerror = function () { toast("下载出错，请重试"); finish(); };
    xhr.send("id=" + encodeURIComponent(extractIdFromLink(input)) + "&quality=" + encodeURIComponent($("#download_quality").value));
  }

  /* ================= 账号（登录 / 注册 / 收藏） ================= */

  const Auth = {
    user: null,
    tab: "login",

    refresh: async function () {
      try {
        const d = await apiJSON("/auth/me");
        this.user = d.data && d.data.login ? d.data : null;
      } catch (e) {
        this.user = null;
      }
      this.renderUI();
      if (this.user) loadFavorites();
    },

    renderUI: function () {
      // 站点账号状态仅在"我的收藏"页签体现（顶栏按钮已改为网易云账号）
    },

    openModal: function (tab) {
      this.tab = tab || "login";
      this.renderTabs();
      $("#auth-msg").textContent = "";
      $("#auth-password").value = "";
      $("#auth-modal").classList.remove("hidden");
      $("#auth-username").focus();
    },

    closeModal: function () { $("#auth-modal").classList.add("hidden"); },

    renderTabs: function () {
      $$(".auth-tab").forEach(function (t) {
        t.classList.toggle("active", t.dataset.authTab === Auth.tab);
      });
      $("#auth-submit .btn-label").textContent = Auth.tab === "login" ? "登录" : "注册";
    },

    submit: async function (e) {
      e.preventDefault();
      const btn = $("#auth-submit");
      if (btn.disabled) return;
      const username = $("#auth-username").value.trim();
      const password = $("#auth-password").value;
      const msg = $("#auth-msg");
      msg.classList.remove("ok");
      msg.textContent = "";
      setBtnLoading(btn, true);
      try {
        const url = this.tab === "login" ? "/auth/login" : "/auth/register";
        const d = await apiJSON(url, { method: "POST", data: { username: username, password: password } });
        if (this.tab === "register") {
          // 注册成功后自动登录
          const ld = await apiJSON("/auth/login", { method: "POST", data: { username: username, password: password } });
          this.user = ld.data;
        } else {
          this.user = d.data;
        }
        msg.classList.add("ok");
        toast("欢迎，" + this.user.username);
        this.closeModal();
        this.renderUI();
        loadFavorites();
        refreshPlayerFav();
      } catch (err) {
        msg.textContent = err.message;
      } finally {
        setBtnLoading(btn, false);
      }
    },

    logout: async function () {
      try { await apiJSON("/auth/logout", { method: "POST" }); } catch (e) { /* 忽略 */ }
      this.user = null;
      this.renderUI();
      loadFavorites();
      refreshPlayerFav();
      toast("已退出登录");
    },
  };

  // apiJSON 已统一处理 401：这里移除旧包装

  /* ---- 收藏 ---- */

  async function loadFavorites() {
    const tip = $("#fav-login-tip");
    const content = $("#fav-content");
    if (!Auth.user) {
      tip.classList.remove("hidden");
      content.classList.add("hidden");
      return;
    }
    tip.classList.add("hidden");
    content.classList.remove("hidden");
    const listEl = $("#fav-list");
    showSkeleton(listEl, 4);
    try {
      const d = await apiJSON("/favorites");
      const songs = (d.data && d.data.songs) || [];
      $("#fav-count").textContent = songs.length ? "（" + songs.length + "）" : "";
      if (songs.length) {
        listEl.innerHTML = songs.map(function (s, i) {
          return buildTrackItem(s, i, true,
            '<button type="button" class="pill-btn act-unfav act-unfav-btn" data-id="' + escapeHtml(s.id) + '">取消收藏</button>');
        }).join("");
      } else {
        listEl.innerHTML = '<li class="empty-state">还没有收藏，解析歌曲后点"收藏"试试</li>';
      }
    } catch (e) {
      listEl.innerHTML = '<li class="empty-state">收藏加载失败，请刷新重试</li>';
    }
  }

  // 播放器页 / 全屏歌词视图收藏红心状态（跟随当前播放歌曲）
  async function refreshPlayerFav() {
    const btns = [$("#pl-fav"), $("#fs2-fav")];
    const cur = Player.current();
    if (!Auth.user || !cur || !cur.id) {
      btns.forEach(function (btn) {
        btn.classList.remove("fav-active");
        btn.title = Auth.user ? "收藏当前歌曲" : "登录后可收藏当前歌曲";
      });
      return;
    }
    try {
      const d = await apiJSON("/favorites/contains/" + cur.id);
      const fav = !!(d.data && d.data.fav);
      btns.forEach(function (btn) {
        btn.classList.toggle("fav-active", fav);
        btn.title = fav ? "取消收藏当前歌曲" : "收藏当前歌曲";
      });
    } catch (e) { /* 忽略 */ }
  }

  // 单曲卡收藏红心状态
  async function refreshFavState() {
    const btn = $("#song-fav-btn");
    if (!Auth.user || !currentParse || !currentParse.id) {
      btn.classList.remove("fav-active");
      btn.querySelector(".btn-label").textContent = "收藏";
      return;
    }
    try {
      const d = await apiJSON("/favorites/contains/" + currentParse.id);
      const fav = d.data && d.data.fav;
      btn.classList.toggle("fav-active", fav);
      btn.querySelector(".btn-label").textContent = fav ? "已收藏" : "收藏";
    } catch (e) { /* 忽略 */ }
  }

  async function toggleFavorite() {
    if (!currentParse || !currentParse.id) { toast("请先解析歌曲"); return; }
    if (!Auth.user) {
      toast("请先登录后再收藏");
      Auth.openModal("login");
      return;
    }
    const btn = $("#song-fav-btn");
    const active = btn.classList.contains("fav-active");
    btn.disabled = true;
    try {
      if (active) {
        await apiJSON("/favorites/" + currentParse.id, { method: "DELETE" });
        btn.classList.remove("fav-active");
        btn.querySelector(".btn-label").textContent = "收藏";
        toast("已取消收藏");
      } else {
        await apiJSON("/favorites", {
          method: "POST",
          data: {
            song_id: currentParse.id,
            name: currentParse.name,
            artist: currentParse.ar_name,
            album: currentParse.al_name,
            pic: currentParse.pic,
          },
        });
        btn.classList.add("fav-active");
        btn.querySelector(".btn-label").textContent = "已收藏";
        toast("已加入收藏");
      }
    } catch (e) {
      toast(e.message.indexOf("HTTP") !== -1 ? "操作失败，请重试" : e.message);
    } finally {
      btn.disabled = false;
    }
  }

  /* ---- 首页小卡片网格（每日推荐 / 我喜欢的音乐） ---- */

  function buildSongCard(song) {
    const name = song.name || "未知歌曲";
    const artist = song.artists || song.artist || "";
    const pic = song.picUrl || song.pic || PLACEHOLDER;
    return '<div class="song-card" data-id="' + escapeHtml(song.id) + '" data-name="' + escapeHtml(name) +
      '" data-artist="' + escapeHtml(artist) + '" data-pic="' + escapeHtml(pic) + '" title="播放 ' + escapeHtml(name) + '">' +
      '<div class="sc-cover-wrap"><img class="sc-cover" src="' + escapeHtml(pic) + '" alt="" loading="lazy" onerror="this.src=window.__PLACEHOLDER__">' +
      '<span class="sc-play">' + ICON_PLAY + "</span></div>" +
      '<div class="sc-name">' + escapeHtml(name) + "</div>" +
      '<div class="sc-artist">' + escapeHtml(artist) + "</div>" +
      "</div>";
  }

  function renderCardGrid(gridEl, songs, limit) {
    const list = (songs || []).slice(0, limit || 12);
    if (!list.length) {
      gridEl.innerHTML = '<p class="grid-empty">暂无内容</p>';
      return;
    }
    gridEl.innerHTML = list.map(buildSongCard).join("");
  }

  /* ---- 网易云账号（Cookie 登录） ---- */

  const Ncm = {
    profile: null,

    refresh: async function () {
      try {
        const d = await apiJSON("/netease/profile");
        this.profile = d.data && d.data.login ? d.data : null;
      } catch (e) {
        this.profile = null;
      }
      this.renderTop();
      if (this.profile) loadHomeCards();
      else renderLoggedOutHome();
    },

    renderTop: function () {
      const text = $("#ncm-btn-text");
      const avatar = $("#ncm-top-avatar");
      const icon = $("#ncm-top-icon");
      if (this.profile) {
        text.textContent = this.profile.nickname || "网易云用户";
        if (this.profile.avatarUrl) {
          avatar.src = this.profile.avatarUrl;
          avatar.classList.remove("hidden");
          icon.classList.add("hidden");
        }
        $("#ncm-btn").title = "网易云账号：" + (this.profile.nickname || "") + "（点击管理）";
      } else {
        text.textContent = "网易云登录";
        avatar.classList.add("hidden");
        icon.classList.remove("hidden");
        $("#ncm-btn").title = "网易云账号登录";
      }
    },

    openModal: function () {
      // 网易云 Cookie 与站点账号一一绑定：未登录站点账号时引导先登录
      if (!Auth.user) {
        toast("请先登录站点账号，再绑定网易云 Cookie");
        Auth.openModal("login");
        return;
      }
      $("#ncm-msg").textContent = "";
      $("#ncm-cookie-input").value = "";
      if (this.profile) {
        $("#ncm-avatar").src = this.profile.avatarUrl || PLACEHOLDER;
        $("#ncm-nickname").textContent = this.profile.nickname || "网易云用户";
        $("#ncm-sign").textContent = this.profile.signature || "";
        $("#ncm-login-view").classList.add("hidden");
        $("#ncm-logged-view").classList.remove("hidden");
      } else {
        $("#ncm-login-view").classList.remove("hidden");
        $("#ncm-logged-view").classList.add("hidden");
      }
      $("#ncm-modal").classList.remove("hidden");
    },

    closeModal: function () { $("#ncm-modal").classList.add("hidden"); },

    login: async function () {
      const btn = $("#ncm-login-btn");
      const msg = $("#ncm-msg");
      const raw = $("#ncm-cookie-input").value.trim();
      msg.classList.remove("ok");
      if (!Auth.user) { msg.textContent = "请先登录站点账号，再绑定网易云 Cookie"; return; }
      if (!raw) { msg.textContent = "请先粘贴 Cookie 或 MUSIC_U 值"; return; }
      setBtnLoading(btn, true, "验证中…");
      try {
        const d = await apiJSON("/netease/login", { method: "POST", data: { cookie: raw } });
        this.profile = d.data;
        msg.classList.add("ok");
        toast("欢迎，" + (this.profile.nickname || "网易云用户"));
        this.closeModal();
        this.renderTop();
        loadHomeCards();
      } catch (e) {
        msg.textContent = e.message;
      } finally {
        setBtnLoading(btn, false);
      }
    },

    logout: async function () {
      try { await apiJSON("/netease/logout", { method: "POST" }); } catch (e) { /* 忽略 */ }
      this.profile = null;
      this.renderTop();
      this.closeModal();
      renderLoggedOutHome();
      toast("已退出网易云登录");
    },
  };

  async function loadHomeCards() {
    $("#home-sections").classList.remove("hidden");
    $("#home-login-hint").classList.add("hidden");
    loadDailyGrid();
    loadLikeGrid();
  }

  function renderLoggedOutHome() {
    $("#home-sections").classList.add("hidden");
    $("#home-login-hint").classList.remove("hidden");
  }

  async function loadDailyGrid() {
    const grid = $("#daily-grid");
    grid.innerHTML = '<p class="grid-empty">加载中…</p>';
    try {
      const d = await apiJSON("/netease/daily");
      const songs = (d.data && d.data.songs) || [];
      $("#daily-count").textContent = songs.length ? songs.length + " 首" : "";
      renderCardGrid(grid, songs, 12);
    } catch (e) {
      grid.innerHTML = '<p class="grid-empty">每日推荐加载失败：' + escapeHtml(e.message) + "</p>";
    }
  }

  async function loadLikeGrid() {
    const grid = $("#like-grid");
    grid.innerHTML = '<p class="grid-empty">加载中…</p>';
    try {
      const d = await apiJSON("/netease/likes");
      const songs = (d.data && d.data.songs) || [];
      $("#like-count").textContent = songs.length ? songs.length + " 首" : "";
      renderCardGrid(grid, songs, 12);
    } catch (e) {
      grid.innerHTML = '<p class="grid-empty">我喜欢的音乐加载失败：' + escapeHtml(e.message) + "</p>";
    }
  }

  /* ================= 全屏播放界面 ================= */

  const FsPlayer = {
    open: function () {
      if (!Player.current()) { toast("先播放一首歌再来全屏体验吧"); return; }
      const el = $("#fs-player");
      el.classList.remove("hidden");
      // 每次打开回到中央封面视图
      this.exitLyrics();
      document.body.classList.add("fs-open");
      Player.syncProgress();
      Player.updatePlayIcons();
    },
    close: function () {
      $("#fs-player").classList.add("hidden");
      document.body.classList.remove("fs-open");
    },
    toggle: function () {
      if ($("#fs-player").classList.contains("hidden")) this.open();
      else this.close();
    },
    // 中央视图 <-> 歌词视图（CSS transition 平滑过渡）
    toggleLyrics: function () {
      const el = $("#fs-player");
      const on = el.classList.toggle("fs-mode-lyrics");
      const btn = $("#fs-lyric-toggle");
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.title = on ? "返回封面" : "歌词";
      if (on) Player.syncProgress();
    },
    exitLyrics: function () {
      $("#fs-player").classList.remove("fs-mode-lyrics");
      const btn = $("#fs-lyric-toggle");
      btn.setAttribute("aria-pressed", "false");
      btn.title = "歌词";
    },
  };

  /* ================= 事件绑定 ================= */

  function bindRangeFill(input) {
    const update = function () {
      input.style.setProperty("--fill", ((input.value - input.min) / (input.max - input.min) * 100) + "%");
    };
    input.addEventListener("input", update);
    update();
  }

  document.addEventListener("DOMContentLoaded", function () {
    // 模式切换
    $$(".mode-tab").forEach(function (tab) {
      tab.addEventListener("click", function () { switchMode(tab.dataset.mode); });
    });

    // 搜索
    $("#search-btn").addEventListener("click", handleSearch);
    $("#search_keywords").addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !$("#search-btn").disabled) handleSearch();
    });

    // 单曲解析
    $("#parse-btn").addEventListener("click", handleParse);
    $("#song_ids").addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !$("#parse-btn").disabled) handleParse();
    });

    // 歌单 / 专辑 / 下载
    $("#playlist-btn").addEventListener("click", handlePlaylist);
    $("#playlist_id").addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !$("#playlist-btn").disabled) handlePlaylist();
    });
    $("#album-btn").addEventListener("click", handleAlbum);
    $("#album_id").addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !$("#album-btn").disabled) handleAlbum();
    });
    $("#download-btn").addEventListener("click", handleDownload);
    $("#download_id").addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !$("#download-btn").disabled) handleDownload();
    });

    // 列表事件委托（播放 / 解析 / 下载 / 全部播放）
    document.addEventListener("click", function (e) {
      // 歌词行点击：跳转到该行播放时间
      const lrcLine = e.target.closest(".lrc-line");
      if (lrcLine && lrcLine.dataset.t && Player.audio.duration) {
        Player.audio.currentTime = parseFloat(lrcLine.dataset.t) / 1000;
        userScrollHold = 0;
        return;
      }
      const playBtn = e.target.closest(".act-play");
      if (playBtn) {
        Player.add({
          id: playBtn.dataset.id, name: playBtn.dataset.name,
          artist: playBtn.dataset.artist, pic: playBtn.dataset.pic,
        }, false);
        toast("已加入播放队列");
        return;
      }
      const parseBtn = e.target.closest(".act-parse");
      if (parseBtn) {
        $("#song_ids").value = parseBtn.dataset.id;
        switchMode("parse");
        return;
      }
      const dlBtn = e.target.closest(".act-dl");
      if (dlBtn) {
        $("#download_id").value = dlBtn.dataset.id;
        switchMode("download");
        return;
      }
      const playAll = e.target.closest(".act-play-all");
      if (playAll) {
        const songs = collectListSongs($("#" + playAll.dataset.from));
        if (!songs.length) { toast("列表为空，无法播放"); return; }
        Player.add(songs[0], true);
        songs.slice(1).forEach(function (s) { Player.add(s, false); });
        switchMode("player");
        return;
      }
      // 首页小卡片：点击直接播放
      const card = e.target.closest(".song-card");
      if (card) {
        Player.add({
          id: card.dataset.id, name: card.dataset.name,
          artist: card.dataset.artist, pic: card.dataset.pic,
        }, false);
        toast("已加入播放队列");
        return;
      }
      // 队列项点击播放 / 移除
      const removeBtn = e.target.closest(".q-remove");
      if (removeBtn) {
        e.stopPropagation();
        Player.removeAt(parseInt(removeBtn.dataset.i, 10));
        return;
      }
      // 取消收藏
      const unfavBtn = e.target.closest(".act-unfav-btn");
      if (unfavBtn) {
        apiJSON("/favorites/" + unfavBtn.dataset.id, { method: "DELETE" })
          .then(function () { toast("已取消收藏"); loadFavorites(); })
          .catch(function (err) { toast(err.message); });
        return;
      }
      const queueItem = e.target.closest(".queue-item");
      if (queueItem) {
        Player.playAt(parseInt(queueItem.dataset.i, 10));
        return;
      }
    });

    // ===== 网易云账号（Cookie 登录） =====
    $("#ncm-btn").addEventListener("click", function () { Ncm.openModal(); });
    $("#ncm-close").addEventListener("click", function () { Ncm.closeModal(); });
    $("#ncm-modal").addEventListener("click", function (e) {
      if (e.target === this) Ncm.closeModal();
    });
    $("#ncm-login-btn").addEventListener("click", function () { Ncm.login(); });
    $("#ncm-cookie-input").addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey && !$("#ncm-login-btn").disabled) {
        e.preventDefault();
        Ncm.login();
      }
    });
    $("#ncm-logout-btn").addEventListener("click", function () { Ncm.logout(); });

    // ===== 应用模式（听音乐 / 下音乐） =====
    $$(".appmode-btn").forEach(function (b) {
      b.addEventListener("click", function () { setAppMode(b.dataset.app); });
    });
    $("#auth-form").addEventListener("submit", function (e) { Auth.submit(e); });
    $("#auth-close").addEventListener("click", function () { Auth.closeModal(); });
    $("#auth-modal").addEventListener("click", function (e) {
      if (e.target === this) Auth.closeModal();
    });
    $$(".auth-tab").forEach(function (t) {
      t.addEventListener("click", function () {
        Auth.tab = t.dataset.authTab;
        Auth.renderTabs();
        $("#auth-msg").textContent = "";
      });
    });

    // ===== 收藏 =====
    $("#fav-login-btn").addEventListener("click", function () { Auth.openModal("login"); });
    $$(".act-fav-refresh").forEach(function (b) {
      b.addEventListener("click", loadFavorites);
    });
    $("#song-fav-btn").addEventListener("click", toggleFavorite);

    // 播放器页 / 全屏歌词视图收藏红心（共用逻辑，两处状态同步）
    [$("#pl-fav"), $("#fs2-fav")].forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const cur = Player.current();
        if (!cur || !cur.id) { toast("当前没有播放中的歌曲"); return; }
        if (!Auth.user) {
          toast("请先登录后再收藏");
          Auth.openModal("login");
          return;
        }
        const active = btn.classList.contains("fav-active");
        btn.disabled = true;
        try {
          if (active) {
            await apiJSON("/favorites/" + cur.id, { method: "DELETE" });
            btn.classList.remove("fav-active");
            btn.title = "收藏当前歌曲";
            toast("已取消收藏");
          } else {
            await apiJSON("/favorites", {
              method: "POST",
              data: { song_id: cur.id, name: cur.name, artist: cur.artist, pic: cur.pic },
            });
            btn.classList.add("fav-active");
            btn.title = "取消收藏当前歌曲";
            toast("已加入收藏");
          }
          // 同步另一处红心状态
          const other = btn === $("#pl-fav") ? $("#fs2-fav") : $("#pl-fav");
          other.classList.toggle("fav-active", btn.classList.contains("fav-active"));
          other.title = btn.title;
        } catch (e) {
          toast(e.message.indexOf("HTTP") !== -1 ? "操作失败，请重试" : e.message);
        } finally {
          btn.disabled = false;
        }
      });
    });

    // 单曲卡操作
    $("#show-big-pic").addEventListener("click", function () {
      const pic = this.dataset.pic;
      if (!pic) { toast("暂无封面大图"); return; }
      $("#lightbox-img").src = pic;
      $("#lightbox").classList.remove("hidden");
    });
    $("#song_cover").addEventListener("click", function () {
      if (this.src) { $("#lightbox-img").src = this.src; $("#lightbox").classList.remove("hidden"); }
    });
    $("#lightbox").addEventListener("click", function (e) {
      if (e.target === this || e.target.id === "lightbox-close") this.classList.add("hidden");
    });

    $("#song-play-btn").addEventListener("click", function () {
      if (!currentParse) { toast("请先解析歌曲"); return; }
      Player.add({
        id: currentParse.id, name: currentParse.name,
        artist: currentParse.ar_name, pic: currentParse.pic,
      }, false);
      switchMode("player");
    });

    // 底部播放栏歌词行点击 -> 打开播放器
    $("#pb-lyric").addEventListener("click", function () { switchMode("player"); });

    // 底部播放栏封面点击 -> 全屏播放界面
    $("#pb-cover-btn").addEventListener("click", function () { FsPlayer.open(); });

    $("#song-download-btn").addEventListener("click", function () {
      if (!currentParse || !currentParse.id) { toast("请先解析歌曲"); return; }
      downloadMusicById(currentParse.id, currentParse.level || "lossless", this);
    });

    // ===== 播放器控制 =====
    $("#pl-play").addEventListener("click", function () { Player.playPause(); });
    $("#pb-play").addEventListener("click", function () { Player.playPause(); });
    $("#fs-play").addEventListener("click", function () { Player.playPause(); });
    $("#fs2-play").addEventListener("click", function () { Player.playPause(); });
    $("#pl-prev").addEventListener("click", function () { Player.prev(); });
    $("#pb-prev").addEventListener("click", function () { Player.prev(); });
    $("#fs-prev").addEventListener("click", function () { Player.prev(); });
    $("#fs2-prev").addEventListener("click", function () { Player.prev(); });
    $("#pl-next").addEventListener("click", function () { Player.next(false); });
    $("#pb-next").addEventListener("click", function () { Player.next(false); });
    $("#fs-next").addEventListener("click", function () { Player.next(false); });
    $("#fs2-next").addEventListener("click", function () { Player.next(false); });
    $("#pl-loop").addEventListener("click", function () { Player.cycleLoop(); });
    $("#fs-loop").addEventListener("click", function () { Player.cycleLoop(); });
    $("#fs2-loop").addEventListener("click", function () { Player.cycleLoop(); });
    $("#pl-clear").addEventListener("click", function () { Player.clear(); });

    // ===== 全屏播放界面 =====
    $("#fs-close").addEventListener("click", function () { FsPlayer.close(); });
    $("#fs-lyric-toggle").addEventListener("click", function () { FsPlayer.toggleLyrics(); });
    // 点击中央大封面同样进入歌词视图
    $("#fs-cover").addEventListener("click", function () {
      if (!$("#fs-player").classList.contains("fs-mode-lyrics")) FsPlayer.toggleLyrics();
    });
    $("#fs-player").addEventListener("click", function (e) {
      if (e.target === this || e.target.classList.contains("fs-shade")) FsPlayer.close();
    });
    document.addEventListener("keydown", function (e) {
      const fsOpen = !$("#fs-player").classList.contains("hidden");
      if (e.key === "Escape") {
        if (fsOpen) { FsPlayer.close(); return; }
        if (!$("#ncm-modal").classList.contains("hidden")) { Ncm.closeModal(); return; }
        if (!$("#auth-modal").classList.contains("hidden")) { Auth.closeModal(); return; }
        if (!$("#lightbox").classList.contains("hidden")) { $("#lightbox").classList.add("hidden"); return; }
        return;
      }
      // 输入框 / 按钮聚焦时不接管按键
      if (e.target.matches("input, textarea, select") || e.target.closest("button")) return;
      if (e.key === " " && Player.current()) {
        e.preventDefault();
        Player.playPause();
        return;
      }
      if (fsOpen) {
        if (e.key === "ArrowRight") Player.next(false);
        else if (e.key === "ArrowLeft") Player.prev();
        else if (e.key.toLowerCase() === "l") FsPlayer.toggleLyrics();
      }
    });

    // 进度拖动（播放器页 / 底部栏 / 全屏中央 / 全屏歌词视图）
    ["#pl-seek", "#pb-seek", "#fs-seek", "#fs2-seek"].forEach(function (sel) {
      const input = $(sel);
      input.addEventListener("input", function () {
        const dur = Player.audio.duration || 0;
        input.style.setProperty("--fill", (input.value / 10) + "%");
        const txt = fmtTime(input.value / 1000 * dur);
        $("#pl-cur").textContent = txt;
        $("#pb-cur").textContent = txt;
        $("#fs-cur").textContent = txt;
        $("#fs2-cur").textContent = txt;
      });
      input.addEventListener("change", function () {
        const dur = Player.audio.duration || 0;
        if (dur) Player.audio.currentTime = input.value / 1000 * dur;
      });
    });

    // 音量（播放器页 / 全屏中央 / 全屏歌词视图三路同步）
    const volInputs = [$("#pl-vol"), $("#fs-vol"), $("#fs2-vol")];
    Player.audio.volume = 1;
    volInputs.forEach(function (input) {
      input.addEventListener("input", function () {
        Player.audio.volume = input.value / 100;
        volInputs.forEach(function (v) {
          v.value = input.value;
          v.style.setProperty("--fill", input.value + "%");
        });
      });
    });

    // audio 事件
    Player.audio.addEventListener("play", function () {
      Player.updatePlayIcons();
      startRaf();
      if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "playing";
    });
    Player.audio.addEventListener("pause", function () {
      Player.updatePlayIcons();
      stopRaf();
      if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "paused";
    });
    Player.audio.addEventListener("ended", function () { Player.next(true); });
    Player.audio.addEventListener("error", function () {
      if (Player.current() && Player.current().url) toast("音频加载失败，可能已过期，请重新播放");
    });

    // ===== 系统媒体键 / 锁屏控制（Windows / macOS / iOS / Android） =====
    if ("mediaSession" in navigator) {
      const ms = navigator.mediaSession;
      const safeHandler = function (name, fn) {
        try { ms.setActionHandler(name, fn); } catch (e) { /* 该动作不支持时忽略 */ }
      };
      safeHandler("play", function () { Player.audio.play(); });
      safeHandler("pause", function () { Player.audio.pause(); });
      safeHandler("previoustrack", function () { Player.prev(); });
      safeHandler("nexttrack", function () { Player.next(false); });
      safeHandler("seekto", function (d) {
        if (d.seekTime != null && Player.audio.duration) Player.audio.currentTime = d.seekTime;
      });
      safeHandler("seekbackward", function (d) {
        Player.audio.currentTime = Math.max(0, Player.audio.currentTime - (d.seekOffset || 10));
      });
      safeHandler("seekforward", function (d) {
        Player.audio.currentTime = Math.min(Player.audio.duration || 0, Player.audio.currentTime + (d.seekOffset || 10));
      });
      safeHandler("stop", function () { Player.audio.pause(); });
    }

    // 初始化
    installCoverFallback();
    // 注册歌词容器（播放器页 + 全屏歌词视图），并监听手动滚动以暂停自动跟随
    [$("#pl-lyrics"), $("#fs-lyrics")].forEach(function (el) {
      registerLyricBox(el);
      el.addEventListener("wheel", holdAutoScroll, { passive: true });
      el.addEventListener("touchstart", holdAutoScroll, { passive: true });
    });
    Player.renderLoopIcon();
    Player.renderQueue();
    Player.updateCount();
    Player.syncBarVisibility();
    Player.setMeta(null, null);
    bindRangeFill($("#pl-seek"));
    bindRangeFill($("#pb-seek"));
    bindRangeFill($("#fs-seek"));
    bindRangeFill($("#fs2-seek"));
    volInputs.forEach(bindRangeFill);
    // 恢复上次的应用模式（默认听音乐）
    let savedMode = "player";
    try { savedMode = localStorage.getItem("appmode") || "player"; } catch (e) { /* 忽略 */ }
    setAppMode(savedMode === "download" ? "download" : "player");
    // 页签指示器初始化与自适应（字体加载 / 窗口缩放后重定位）
    updateTabsIndicator();
    window.addEventListener("resize", updateTabsIndicator);
    window.addEventListener("load", updateTabsIndicator);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(updateTabsIndicator);
    Auth.refresh();
    Ncm.refresh();
    switchMode("search");
  });
})();
