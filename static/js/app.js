/* ============================================================
   网易云音乐工具箱 - 前端脚本
   依赖: jQuery 3.x / Bootstrap 5.x / APlayer 1.x
   ============================================================ */
(function ($) {
  "use strict";

  // ---------- 全局状态 ----------
  var currentSong = null; // 单曲解析结果，供下载按钮使用
  var aplayer = null; // APlayer 实例

  // ---------- 轻提示（替代 alert） ----------
  function showToast(message, duration) {
    var $tip = $("#toast-tip");
    if (!$tip.length) {
      $tip = $('<div id="toast-tip" class="toast-tip"></div>').appendTo("body");
    }
    $tip.text(message).addClass("show");
    clearTimeout($tip.data("timer"));
    $tip.data(
      "timer",
      setTimeout(function () {
        $tip.removeClass("show");
      }, duration || 2200)
    );
  }

  // ---------- LRC 工具 ----------
  // 将 LRC 歌词解析为 [时间戳, 行号, 文本] 数组
  function lrctrim(lyrics) {
    var lines = lyrics.split("\n");
    var data = [];
    lines.forEach(function (line, index) {
      var matches = line.match(/\[(\d{2}):(\d{2}[\.:]?\d*)]/);
      if (matches) {
        var minutes = parseInt(matches[1], 10);
        var seconds = parseFloat(matches[2].replace(".", ":")) || 0;
        var timestamp = minutes * 60000 + seconds * 1000;
        var text = line.replace(/\[\d{2}:\d{2}[\.:]?\d*\]/g, "").trim();
        text = text.replace(/\s\s+/g, " ");
        data.push([timestamp, index, text]);
      }
    });
    data.sort(function (a, b) {
      return a[0] - b[0];
    });
    return data;
  }

  // 合并原文歌词与翻译歌词（按时间戳）
  function lrctran(lyric, tlyric) {
    lyric = lrctrim(lyric);
    tlyric = lrctrim(tlyric);
    var len1 = lyric.length;
    var len2 = tlyric.length;
    var result = "";
    for (var i = 0, j = 0; i < len1 && j < len2; i++) {
      while (lyric[i][0] > tlyric[j][0] && j + 1 < len2) {
        j++;
      }
      if (lyric[i][0] === tlyric[j][0]) {
        tlyric[j][2] = tlyric[j][2].replace("/", "");
        if (tlyric[j][2]) {
          lyric[i][2] += " (翻译：" + tlyric[j][2] + ")";
        }
        j++;
      }
    }
    for (i = 0; i < len1; i++) {
      var t = lyric[i][0];
      result +=
        "[" +
        String(Math.floor(t / 60000)).padStart(2, "0") +
        ":" +
        String(Math.floor((t % 60000) / 1000)).padStart(2, "0") +
        "." +
        String(t % 1000).padStart(3, "0") +
        "]" +
        lyric[i][2] +
        "\n";
    }
    return result;
  }

  // ---------- 链接 / ID 提取 ----------
  function extractLinks(text) {
    var regex = /https?:\/\/\S+/g;
    var matches = text.match(regex);
    return matches ? matches[0] : "";
  }

  function checkValidLink(link) {
    if (
      link.indexOf("http") === -1 ||
      (link.indexOf("music.163.com") === -1 && link.indexOf("163cn.tv") === -1)
    ) {
      return false;
    }
    return true;
  }

  function extractAndCheckId(text) {
    var link = extractLinks(text);
    if (checkValidLink(link)) {
      return link;
    }
    var ids = text.match(/\b\d+\b/g);
    return ids && ids.length > 0 ? ids[0] : "";
  }

  // ---------- 模式切换 ----------
  var MODE_AREAS = {
    search: ["search-area"],
    parse: ["parse-area"],
    playlist: ["playlist-area"],
    album: ["album-area"],
    download: ["download-area"],
  };

  function switchMode(mode) {
    // 切换功能表单区
    Object.keys(MODE_AREAS).forEach(function (key) {
      var visible = key === mode;
      MODE_AREAS[key].forEach(function (areaId) {
        $("#" + areaId).toggleClass("hidden", !visible);
      });
    });

    // Tab 高亮
    $(".mode-tab").removeClass("active");
    $('.mode-tab[data-mode="' + mode + '"]').addClass("active");

    // 隐藏不相关的结果区
    if (mode !== "search") {
      $("#search-result").addClass("hidden");
    }
    if (mode !== "parse") {
      $("#song-info-card").addClass("hidden");
    }
    if (mode !== "playlist") {
      $("#playlist-result").addClass("hidden");
    }
    if (mode !== "album") {
      $("#album-result").addClass("hidden");
    }
  }

  // ---------- 通用下载（走本地 API，写入元数据） ----------
  function downloadMusicById(musicId, quality, $btn) {
    var btnText = $btn ? $btn.text() : "";
    if ($btn) {
      $btn.prop("disabled", true).text("下载中...");
    }

    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/Download", true);
    xhr.setRequestHeader("Content-Type", "application/x-www-form-urlencoded");
    xhr.responseType = "blob";

    xhr.onload = function () {
      if (xhr.status === 200) {
        var encodedFilename = xhr.getResponseHeader("X-Download-Filename");
        var filename = encodedFilename
          ? decodeURIComponent(encodedFilename)
          : "music.mp3";
        var blob = xhr.response;
        var url = window.URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = filename || "music.mp3";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        showToast("✅ 音乐文件下载完成！");
      } else {
        showToast("下载失败，请重试");
      }
      if ($btn) {
        $btn.prop("disabled", false).text(btnText);
      }
    };

    xhr.onerror = function () {
      showToast("下载出错，请重试");
      if ($btn) {
        $btn.prop("disabled", false).text(btnText);
      }
    };

    xhr.send(
      "id=" + encodeURIComponent(musicId) + "&quality=" + encodeURIComponent(quality)
    );
  }

  // ---------- 渲染工具 ----------
  // 生成搜索/歌单/专辑通用列表项
  function buildTrackItem(song, index, showIndex) {
    var name = song.name;
    var meta = song.artists + (song.album ? "  ·  " + song.album : "");
    return (
      '<li class="track-item">' +
      '<img class="track-cover" src="' +
      (song.picUrl || "") +
      '" alt="cover" onerror="this.style.visibility=\'hidden\'">' +
      '<div class="track-info">' +
      '<div class="track-name">' +
      (showIndex ? index + ". " : "") +
      name +
      "</div>" +
      '<div class="track-meta">' +
      meta +
      "</div>" +
      "</div>" +
      '<div class="track-actions">' +
      '<button type="button" class="btn-outline btn-outline-blue btn-sm select-song" data-id="' +
      song.id +
      '" data-name="' +
      name +
      '">解析</button>' +
      '<button type="button" class="btn-solid-sm download-song" data-id="' +
      song.id +
      '" data-name="' +
      name +
      '">下载</button>' +
      "</div>" +
      "</li>"
    );
  }

  // 渲染歌词到歌词框
  function renderLyric(text) {
    var $box = $("#lyric");
    if (text && text.trim()) {
      $box.text(text).removeClass("lyric-empty");
    } else {
      $box.text("暂无歌词").addClass("lyric-empty");
    }
  }

  // ---------- 搜索 ----------
  function handleSearch() {
    var keywords = $("#search_keywords").val().trim();
    var limit = $("#search_limit").val();
    if (!keywords) {
      showToast("请输入搜索关键词");
      return;
    }
    $.ajax({
      url: "/Search",
      method: "POST",
      data: { keyword: keywords, limit: limit },
      dataType: "json",
      success: function (data) {
        var $list = $("#search-list");
        $list.empty();
        $("#search-result").removeClass("hidden");
        if (data.status === 200 && data.data && data.data.length) {
          data.data.forEach(function (song) {
            $list.append(buildTrackItem(song, 0, false));
          });
        } else {
          $list.append('<li class="empty-state">未找到相关歌曲</li>');
        }
      },
      error: function () {
        $("#search-list").html('<li class="empty-state">搜索失败，请重试</li>');
        $("#search-result").removeClass("hidden");
      },
    });
  }

  // ---------- 单曲解析 ----------
  function handleParse() {
    var songIds = $("#song_ids").val().trim();
    var level = $("#level").val();
    if (!songIds) {
      showToast("请输入歌曲ID或URL");
      return;
    }
    $.post(
      "/Song_V1",
      { url: songIds, level: level, type: "json" },
      function (data) {
        if (data.status === 200) {
          var d = data.data;
          $("#song_name").text(d.name);
          $("#artist_names").text(d.ar_name);
          $("#song_alname").text(d.al_name);
          $("#song_level").text(d.level);
          $("#song_size").text(d.size);
          $("#song_cover").attr("src", d.pic || "");

          var processedLyrics = d.lyric;
          if (d.tlyric) {
            processedLyrics = lrctran(d.lyric, d.tlyric);
          }
          renderLyric(processedLyrics);

          currentSong = { id: d.id, level: d.level || level };
          $("#song-info-card").removeClass("hidden");
          $("#show-big-pic").data("pic", d.pic);

          // 重建播放器（避免重复实例）
          if (aplayer) {
            aplayer.destroy();
            aplayer = null;
          }
          aplayer = new APlayer({
            container: document.getElementById("aplayer"),
            lrcType: 1,
            audio: [
              {
                name: d.name,
                artist: d.ar_name,
                url: d.url,
                cover: d.pic,
                lrc: processedLyrics,
              },
            ],
          });
        } else {
          showToast(data.data && data.data.msg ? data.data.msg : "解析失败");
        }
      },
      "json"
    );
  }

  // ---------- 歌单解析 ----------
  function handlePlaylist() {
    var pid = $("#playlist_id").val().trim();
    if (!pid) {
      showToast("请输入歌单ID或链接");
      return;
    }
    var idMatch = pid.match(/playlist\?id=(\d+)/);
    if (idMatch) pid = idMatch[1];
    $.get("/Playlist", { id: pid }, function (data) {
      $("#playlist-result").removeClass("hidden");
      if (data.status === 200) {
        var pl = data.data.playlist;
        $("#playlist-cover").attr("src", pl.coverImgUrl || "");
        $("#playlist-name").text(pl.name);
        $("#playlist-creator").text("by " + (pl.creator || ""));
        $("#playlist-desc").text(pl.description || "").toggleClass("hidden", !pl.description);
        $("#playlist-count").html("<b>" + pl.trackCount + "</b> 首歌");
        var $list = $("#playlist-tracks").empty();
        (pl.tracks || []).forEach(function (song, idx) {
          $list.append(buildTrackItem(song, idx + 1, true));
        });
      } else {
        $("#playlist-tracks").html(
          '<li class="empty-state">歌单解析失败：' + (data.data && data.data.msg) + "</li>"
        );
      }
    }, "json");
  }

  // ---------- 专辑解析 ----------
  function handleAlbum() {
    var aid = $("#album_id").val().trim();
    if (!aid) {
      showToast("请输入专辑ID或链接");
      return;
    }
    var idMatch = aid.match(/album\?id=(\d+)/);
    if (idMatch) aid = idMatch[1];
    $.get("/Album", { id: aid }, function (data) {
      $("#album-result").removeClass("hidden");
      if (data.status === 200) {
        var al = data.data.album;
        $("#album-cover").attr("src", al.coverImgUrl || "");
        $("#album-name").text(al.name);
        $("#album-artist").text(al.artist);
        $("#album-desc").text(al.description || "").toggleClass("hidden", !al.description);
        $("#album-count").html("<b>" + (al.songs || []).length + "</b> 首歌");
        var $list = $("#album-tracks").empty();
        (al.songs || []).forEach(function (song, idx) {
          $list.append(buildTrackItem(song, idx + 1, true));
        });
      } else {
        $("#album-tracks").html(
          '<li class="empty-state">专辑解析失败：' + (data.data && data.data.msg) + "</li>"
        );
      }
    }, "json");
  }

  // ---------- 独立下载区 ----------
  function handleDownload() {
    var musicId = $("#download_id").val().trim();
    var quality = $("#download_quality").val();
    if (!musicId) {
      showToast("请输入音乐ID或URL");
      return;
    }
    var processedId = musicId;
    var idMatch = musicId.match(/song\?id=(\d+)/);
    if (idMatch) processedId = idMatch[1];

    $("#download-progress").removeClass("hidden");
    $("#download-btn").prop("disabled", true).text("下载中...");

    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/Download", true);
    xhr.setRequestHeader("Content-Type", "application/x-www-form-urlencoded");
    xhr.responseType = "blob";

    xhr.onload = function () {
      if (xhr.status === 200) {
        var encodedFilename = xhr.getResponseHeader("X-Download-Filename");
        var filename = encodedFilename
          ? decodeURIComponent(encodedFilename)
          : "music.flac";
        var blob = xhr.response;
        var url = window.URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = filename || "music.flac";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        showToast("✅ 音乐文件下载完成！");
      } else {
        showToast("下载失败，请重试");
      }
      $("#download-progress").addClass("hidden");
      $("#download-btn").prop("disabled", false).text("下载音乐");
    };

    xhr.onerror = function () {
      showToast("下载出错，请重试");
      $("#download-progress").addClass("hidden");
      $("#download-btn").prop("disabled", false).text("下载音乐");
    };

    xhr.send(
      "id=" + encodeURIComponent(processedId) + "&quality=" + encodeURIComponent(quality)
    );
  }

  // ---------- 事件绑定 ----------
  $(document).ready(function () {
    // 模式切换（Tab 点击）
    $(document).on("click", ".mode-tab", function () {
      switchMode($(this).data("mode"));
    });

    // 搜索
    $("#search-btn").on("click", handleSearch);
    $("#search_keywords").on("keydown", function (e) {
      if (e.key === "Enter") handleSearch();
    });

    // 单曲解析
    $("#parse-btn").on("click", handleParse);
    $("#song_ids").on("keydown", function (e) {
      if (e.key === "Enter") handleParse();
    });

    // 歌单 / 专辑
    $("#playlist-btn").on("click", handlePlaylist);
    $("#album-btn").on("click", handleAlbum);

    // 独立下载
    $("#download-btn").on("click", handleDownload);
    $("#download_id").on("keydown", function (e) {
      if (e.key === "Enter") handleDownload();
    });

    // 搜索结果点击"解析"：跳转到单曲解析
    $(document).on("click", ".select-song", function () {
      var songId = $(this).data("id");
      $("#song_ids").val(songId);
      switchMode("parse");
      $("html, body").animate(
        { scrollTop: $("#main-form").offset().top - 20 },
        300
      );
    });

    // 列表"下载"：跳转到下载区
    $(document).on("click", ".download-song", function () {
      var musicId = $(this).data("id");
      if (!musicId) {
        showToast("无法获取音乐ID");
        return;
      }
      $("#download_id").val(musicId);
      switchMode("download");
      $("html, body").animate(
        { scrollTop: $("#main-form").offset().top - 20 },
        300
      );
    });

    // 单曲信息卡"下载到本地"
    $(document).on("click", "#song-download-btn", function () {
      if (!currentSong || !currentSong.id) {
        showToast("请先解析歌曲再下载");
        return;
      }
      downloadMusicById(currentSong.id, currentSong.level, $(this));
    });

    // 显示大图
    $(document).on("click", "#show-big-pic", function () {
      var picUrl = $(this).data("pic");
      if (!picUrl) {
        showToast("暂无封面大图");
        return;
      }
      $("#big-pic-img").attr("src", picUrl);
      var modal = new bootstrap.Modal(document.getElementById("bigPicModal"));
      modal.show();
    });

    // 默认进入搜索模式
    switchMode("search");
  });
})(jQuery);
