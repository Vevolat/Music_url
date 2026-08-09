"""网易云音乐下载器（适配 ffmpeg 写入元数据）

提供功能：
- 同步 / 异步下载（本地落盘 / 内存返回）
- 批量并发下载
- 进度查询
- 基于 ffmpeg 的元数据 + 封面写入（MP3/FLAC/M4A/MP4/OGG/Opus）

设计要点：
1. ffmpeg 路径懒加载：每次写入前重新检测，支持服务启动后中途安装
2. 显式 -f 指定输出格式 + 临时文件保留原扩展名在最后，双保险
3. MP4（杜比全景声 EAC3）单独分支，启用 +faststart
4. 扩展名优先使用 API 返回的 type 字段，URL/Content-Type 兜底
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiofiles
import aiohttp
import requests

from music_api import APIException, NeteaseAPI, load_cookies


# ============ 类型定义 ============

class AudioFormat(Enum):
    """音频格式枚举"""
    MP3 = "mp3"
    FLAC = "flac"
    M4A = "m4a"
    MP4 = "mp4"
    UNKNOWN = "unknown"


class QualityLevel(Enum):
    """音质等级枚举"""
    STANDARD = "standard"
    EXHIGH = "exhigh"
    LOSSLESS = "lossless"
    HIRES = "hires"
    SKY = "sky"
    JYEFFECT = "jyeffect"
    JYMASTER = "jymaster"
    DOLBY = "dolby"


@dataclass
class MusicInfo:
    """音乐信息数据类"""
    id: int
    name: str
    artists: str
    album: str
    pic_url: str
    duration: int
    track_number: int
    download_url: str
    file_type: str
    file_size: int
    quality: str
    lyric: str = ""
    tlyric: str = ""


@dataclass
class DownloadResult:
    """下载结果数据类"""
    success: bool
    file_path: Optional[str] = None
    file_size: int = 0
    error_message: str = ""
    warning: str = ""  # 非致命警告（如元数据写入失败），不阻断下载
    music_info: Optional[MusicInfo] = None


class DownloadException(Exception):
    """下载异常类"""
    pass


# ============ 工具映射表 ============

# API 返回的 type -> 文件扩展名
API_TYPE_TO_EXT = {
    "mp3": ".mp3",
    "flac": ".flac",
    "m4a": ".m4a",
    "mp4": ".mp4",
    "ogg": ".ogg",
    "opus": ".opus",
}

# 文件扩展名 -> ffmpeg 输出 muxer 名称
EXT_TO_FFMPEG_FORMAT = {
    ".mp3": "mp3",
    ".flac": "flac",
    ".m4a": "mp4",
    ".mp4": "mp4",
    ".ogg": "ogg",
    ".opus": "opus",
}

# 支持元数据写入的扩展名
METADATA_FORMATS = {".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus"}


def strip_hashtags(text: Any) -> str:
    """移除文本中的 "#" 与全角 "＃" 符号

    应用于歌手名、专辑名等歌曲元素，避免下载列表与元数据中出现 "#"。
    """
    if not text:
        return text
    return str(text).replace('#', '').replace('＃', '').strip()


def clean_song_name(name: Any) -> str:
    """清洗歌曲名：移除多余修饰词与符号

    网易云部分歌曲名自带 "(有字幕)" 等修饰后缀或 "#" 标记，
    这些会污染文件名、元数据 title 与网页显示，统一在此移除。

    处理:
    - 移除 "(有字幕)" / "（有字幕）" / "[有字幕]" / "【有字幕】" 等变体（半角/全角括号）
    - 移除 "#" 与全角 "＃" 符号

    Returns:
        清洗后的歌曲名（无匹配内容时原样返回）
    """
    if not name:
        return name
    name = str(name)
    # 移除 (有字幕) 等修饰后缀（兼容半角/全角/方括号/书名号）
    name = re.sub(r'[\(（\[【]\s*有字幕\s*[\)）\]】]', '', name)
    # 移除 # 符号（半角 + 全角）
    return strip_hashtags(name)


# ============ 核心实现 ============

class MusicDownloader:
    """网易云音乐下载器

    用法:
        downloader = MusicDownloader(download_dir="downloads")
        result = downloader.download_music_file(music_id, quality="lossless")
    """

    def __init__(
        self,
        download_dir: str = "downloads",
        max_concurrent: int = 3,
        ffmpeg_path: Optional[str] = None,
        cache_max_size: int = 200 * 1024 * 1024,  # 缓存目录大小上限，默认 200MB
    ):
        """
        Args:
            download_dir: 下载目录
            max_concurrent: 最大并发下载数
            ffmpeg_path: ffmpeg 可执行文件路径，为 None 时启动时检测一次
            cache_max_size: 缓存目录总大小上限（字节），超过后按时间从旧到新删除文件
        """
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True)
        self.max_concurrent = max_concurrent
        self.cache_max_size = max(cache_max_size, 0)

        # 正在写入/使用的文件路径集合，缓存清理时跳过，避免误删并发下载中的文件
        self._active_files: set[str] = set()

        self.api = NeteaseAPI()

        # ffmpeg 路径缓存：启动时检测一次，写入时还会再懒加载一次
        self.ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg")
        if not self.ffmpeg_path:
            print("警告: 未检测到 ffmpeg，写入元数据功能将不可用")

    # ----------- 工具方法 -----------

    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名非法字符"""
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filename = filename.strip(' .')
        if len(filename) > 200:
            filename = filename[:200]
        return filename or "unknown"

    def _determine_file_extension(
        self,
        url: str,
        content_type: str = "",
        api_type: str = "",
    ) -> str:
        """确定文件扩展名

        优先级: API 返回的 type > URL 后缀 > HTTP Content-Type > 默认 mp3
        """
        api_type = (api_type or "").lower()
        if api_type in API_TYPE_TO_EXT:
            return API_TYPE_TO_EXT[api_type]

        url_lower = url.lower()
        if ".flac" in url_lower:
            return ".flac"
        if ".mp3" in url_lower:
            return ".mp3"
        if ".m4a" in url_lower or ".mp4" in url_lower:
            return ".m4a"

        content_type = (content_type or "").lower()
        if "flac" in content_type:
            return ".flac"
        if "mpeg" in content_type or "mp3" in content_type:
            return ".mp3"
        if "mp4" in content_type or "m4a" in content_type:
            return ".m4a"

        return ".mp3"

    def _resolve_ffmpeg(self) -> Optional[str]:
        """懒加载解析 ffmpeg 路径

        每次写入前调用一次：若启动时未检测到，但中途已安装，下一次就能用。
        """
        if self.ffmpeg_path:
            return self.ffmpeg_path
        path = shutil.which("ffmpeg")
        if path:
            self.ffmpeg_path = path  # 回写缓存
        return path

    # ----------- 歌词处理 -----------

    def _merge_lyrics(self, lyric: str, tlyric: str) -> str:
        """合并原文歌词与翻译歌词

        策略:
        - 仅有原文 → 返回原文
        - 仅有翻译 → 返回翻译
        - 两者都有 → 按时间戳逐行合并为 "原文 / 翻译" 格式
        - 都为空 → 返回空字符串

        合并后保留 LRC 时间戳，兼容大多数播放器的歌词显示。
        """
        lyric = (lyric or "").strip()
        tlyric = (tlyric or "").strip()

        if not lyric and not tlyric:
            return ""
        if not tlyric:
            return lyric
        if not lyric:
            return tlyric

        # 解析 LRC：将 [mm:ss.xx]文本 解析为 {timestamp: text}
        def parse_lrc(lrc_text: str) -> Dict[str, str]:
            """解析 LRC 格式歌词为 {时间戳: 文本} 字典"""
            result: Dict[str, str] = {}
            for line in lrc_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                # 匹配 [mm:ss.xx] 或 [mm:ss] 前缀
                m = re.match(r'\[(\d+:\d+(?:\.\d+)?)\](.*)', line)
                if m:
                    timestamp = m.group(1)
                    text = m.group(2).strip()
                    if text:
                        result[timestamp] = text
                else:
                    # 无时间戳的行（如歌曲信息），保留
                    if line and not line.startswith('['):
                        result[f'_info_{len(result)}'] = line
            return result

        orig = parse_lrc(lyric)
        transl = parse_lrc(tlyric)

        if not orig:
            return lyric
        if not transl:
            return lyric

        # 按时间戳合并
        merged_lines: List[str] = []
        all_timestamps = list(orig.keys())
        for ts in all_timestamps:
            orig_text = orig.get(ts, "")
            transl_text = transl.get(ts, "")
            if transl_text and orig_text:
                merged_lines.append(f"[{ts}]{orig_text} / {transl_text}")
            elif orig_text:
                merged_lines.append(f"[{ts}]{orig_text}")
            elif transl_text:
                merged_lines.append(f"[{ts}]{transl_text}")

        return "\n".join(merged_lines) if merged_lines else lyric

    # ----------- 信息获取 -----------

    def get_music_info(self, music_id: int, quality: str = "standard") -> MusicInfo:
        """获取音乐详细信息（同步）"""
        try:
            cookies = load_cookies()

            url_result = self.api.get_song_url(music_id, quality, cookies)
            if not url_result.get("data") or not url_result["data"]:
                raise DownloadException(f"无法获取音乐ID {music_id} 的播放链接")

            song_data = url_result["data"][0]
            download_url = song_data.get("url", "")
            if not download_url:
                raise DownloadException(f"音乐ID {music_id} 无可用的下载链接")

            detail_result = self.api.get_song_detail(music_id)
            if not detail_result.get("songs") or not detail_result["songs"]:
                raise DownloadException(f"无法获取音乐ID {music_id} 的详细信息")

            song_detail = detail_result["songs"][0]

            lyric_result = self.api.get_lyric(music_id, cookies)
            lyric = lyric_result.get("lrc", {}).get("lyric", "") if lyric_result else ""
            tlyric = lyric_result.get("tlyric", {}).get("lyric", "") if lyric_result else ""

            artists = "/".join(a["name"] for a in song_detail.get("ar", []))

            # 字段空值兜底：API 可能返回 null/None，避免下游拼接或计算时报错
            raw_type = (song_data.get("type") or "mp3").lower()
            file_type = raw_type if raw_type in API_TYPE_TO_EXT else "mp3"
            file_size = song_data.get("size") or 0
            duration_ms = song_detail.get("dt") or 0

            return MusicInfo(
                id=music_id,
                name=clean_song_name(song_detail.get("name") or "未知歌曲"),
                artists=strip_hashtags(artists) or "未知艺术家",
                album=strip_hashtags(song_detail.get("al", {}).get("name")) or "未知专辑",
                pic_url=song_detail.get("al", {}).get("picUrl") or "",
                duration=duration_ms // 1000,
                track_number=song_detail.get("no") or 0,
                download_url=download_url,
                file_type=file_type,
                file_size=file_size,
                quality=quality,
                lyric=lyric,
                tlyric=tlyric,
            )

        except APIException as e:
            raise DownloadException(f"API调用失败: {e}")
        except Exception as e:
            raise DownloadException(f"获取音乐信息时发生错误: {e}")

    # ----------- 文件路径 -----------

    def _build_file_path(self, music_info: MusicInfo) -> Path:
        """根据 MusicInfo 生成下载文件路径

        文件名规则："歌曲名.扩展名"（不含歌手前缀、不含音质后缀）。
        歌曲名为空时回退为歌曲 ID。
        """
        filename = music_info.name or str(music_info.id) or "unknown"
        safe = self._sanitize_filename(filename)
        ext = self._determine_file_extension(
            music_info.download_url,
            api_type=music_info.file_type,
        )
        return self.download_dir / f"{safe}{ext}"

    # ----------- 缓存清理 -----------

    def cleanup_cache(self, max_size: Optional[int] = None) -> List[Path]:
        """清理下载缓存目录

        当目录内音乐文件总大小超过上限时，按文件修改时间从旧到新删除，
        直到总大小不超过上限为止。

        安全策略:
        - 只清理音乐文件（含 ffmpeg 残留的 .tagging 临时文件）
        - 跳过正在写入/使用的文件（self._active_files），避免误删并发下载中的文件

        Args:
            max_size: 缓存大小上限（字节），默认使用初始化时的 cache_max_size

        Returns:
            被删除的文件路径列表
        """
        limit = max_size if max_size is not None else self.cache_max_size
        if limit <= 0 or not self.download_dir.exists():
            return []

        # 收集目录内所有音乐文件（含正在使用的，用于正确计算总大小）
        all_music: List[Path] = []
        for f in self.download_dir.iterdir():
            if not f.is_file():
                continue
            # 音乐文件或 ffmpeg 残留的临时输出文件
            if f.suffix.lower() in METADATA_FORMATS or ".tagging" in f.name:
                all_music.append(f)

        if not all_music:
            return []

        # 计算总大小（包含所有文件，被保护文件也占空间）
        total = sum(f.stat().st_size for f in all_music)
        if total <= limit:
            return []

        # 可删除的候选：排除正在写入/使用的文件
        candidates = [f for f in all_music if str(f) not in self._active_files]
        if not candidates:
            return []

        # 按修改时间从旧到新排序（最老的优先删除）
        candidates.sort(key=lambda f: f.stat().st_mtime)

        deleted: List[Path] = []
        for f in candidates:
            if total <= limit:
                break
            try:
                size = f.stat().st_size
                f.unlink()
                deleted.append(f)
                total -= size
                print(f"[缓存清理] 删除 {f.name} ({size / 1024 / 1024:.1f}MB)")
            except Exception as e:
                print(f"[缓存清理] 删除失败 {f.name}: {e}")

        if deleted:
            print(
                f"[缓存清理] 完成: 删除 {len(deleted)} 个文件, "
                f"剩余约 {total / 1024 / 1024:.1f}MB"
            )
        return deleted

    # ----------- 下载（同步） -----------

    def download_music_file(
        self,
        music_id: int,
        quality: str = "standard",
    ) -> DownloadResult:
        """同步下载音乐到本地"""
        try:
            music_info = self.get_music_info(music_id, quality)
            file_path = self._build_file_path(music_info)

            # 注册为"正在使用"，缓存清理时跳过，避免误删
            self._active_files.add(str(file_path))
            try:
                # 已存在则直接返回
                if file_path.exists():
                    return DownloadResult(
                        success=True,
                        file_path=str(file_path),
                        file_size=file_path.stat().st_size,
                        music_info=music_info,
                    )

                # 流式下载
                response = requests.get(music_info.download_url, stream=True, timeout=30)
                response.raise_for_status()
                with open(file_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                # 写入元数据（失败不阻断主流程，但记录警告供上层感知）
                metadata_ok = self._write_metadata(file_path, music_info)
                warning = ""
                if not metadata_ok:
                    warning = (
                        "元数据写入失败（歌词/封面/歌手/专辑可能缺失），"
                        "请安装 ffmpeg 或 mutagen"
                    )

                # 缓存清理：总大小超过上限时按时间从旧到新删除
                self.cleanup_cache()

                return DownloadResult(
                    success=True,
                    file_path=str(file_path),
                    file_size=file_path.stat().st_size,
                    warning=warning,
                    music_info=music_info,
                )
            finally:
                self._active_files.discard(str(file_path))

        except DownloadException:
            raise
        except requests.RequestException as e:
            return DownloadResult(success=False, error_message=f"下载请求失败: {e}")
        except Exception as e:
            return DownloadResult(success=False, error_message=f"下载过程中发生错误: {e}")

    # ----------- 下载（异步） -----------

    async def download_music_file_async(
        self,
        music_id: int,
        quality: str = "standard",
    ) -> DownloadResult:
        """异步下载音乐到本地"""
        try:
            music_info = self.get_music_info(music_id, quality)
            file_path = self._build_file_path(music_info)

            # 注册为"正在使用"，缓存清理时跳过，避免误删并发下载中的文件
            self._active_files.add(str(file_path))
            try:
                if file_path.exists():
                    return DownloadResult(
                        success=True,
                        file_path=str(file_path),
                        file_size=file_path.stat().st_size,
                        music_info=music_info,
                    )

                async with aiohttp.ClientSession() as session:
                    async with session.get(music_info.download_url) as resp:
                        resp.raise_for_status()
                        async with aiofiles.open(file_path, "wb") as f:
                            async for chunk in resp.content.iter_chunked(8192):
                                await f.write(chunk)

                # 写入元数据（失败不阻断主流程，但记录警告供上层感知）
                metadata_ok = self._write_metadata(file_path, music_info)
                warning = ""
                if not metadata_ok:
                    warning = (
                        "元数据写入失败（歌词/封面/歌手/专辑可能缺失），"
                        "请安装 ffmpeg 或 mutagen"
                    )

                # 缓存清理：总大小超过上限时按时间从旧到新删除
                self.cleanup_cache()

                return DownloadResult(
                    success=True,
                    file_path=str(file_path),
                    file_size=file_path.stat().st_size,
                    warning=warning,
                    music_info=music_info,
                )
            finally:
                self._active_files.discard(str(file_path))

        except DownloadException:
            raise
        except aiohttp.ClientError as e:
            return DownloadResult(success=False, error_message=f"异步下载请求失败: {e}")
        except Exception as e:
            return DownloadResult(success=False, error_message=f"异步下载过程中发生错误: {e}")

    # ----------- 下载到内存 -----------

    def download_music_to_memory(
        self,
        music_id: int,
        quality: str = "standard",
    ) -> Tuple[bool, BytesIO, MusicInfo]:
        """下载音乐到内存"""
        try:
            music_info = self.get_music_info(music_id, quality)
            resp = requests.get(music_info.download_url, timeout=30)
            resp.raise_for_status()
            return True, BytesIO(resp.content), music_info

        except DownloadException:
            raise
        except requests.RequestException as e:
            raise DownloadException(f"下载到内存失败: {e}")
        except Exception as e:
            raise DownloadException(f"内存下载过程中发生错误: {e}")

    # ----------- 批量下载 -----------

    async def download_batch_async(
        self,
        music_ids: List[int],
        quality: str = "standard",
    ) -> List[DownloadResult]:
        """批量并发下载"""
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def _one(music_id: int) -> DownloadResult:
            async with semaphore:
                return await self.download_music_file_async(music_id, quality)

        tasks = [_one(mid) for mid in music_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed: List[DownloadResult] = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                processed.append(DownloadResult(
                    success=False,
                    error_message=f"下载音乐ID {music_ids[i]} 时发生异常: {r}",
                ))
            else:
                processed.append(r)
        return processed

    # ----------- 进度查询 -----------

    def get_download_progress(
        self,
        music_id: int,
        quality: str = "standard",
    ) -> Dict[str, Any]:
        """查询下载进度"""
        try:
            music_info = self.get_music_info(music_id, quality)
            file_path = self._build_file_path(music_info)

            if file_path.exists():
                current_size = file_path.stat().st_size
                progress = (
                    current_size / music_info.file_size * 100
                    if music_info.file_size > 0
                    else 0
                )
                return {
                    "music_id": music_id,
                    "filename": file_path.name,
                    "total_size": music_info.file_size,
                    "current_size": current_size,
                    "progress": min(progress, 100),
                    "completed": current_size >= music_info.file_size,
                }

            return {
                "music_id": music_id,
                "filename": file_path.name,
                "total_size": music_info.file_size,
                "current_size": 0,
                "progress": 0,
                "completed": False,
            }

        except Exception as e:
            return {
                "music_id": music_id,
                "error": str(e),
                "progress": 0,
                "completed": False,
            }

    # ============ 元数据写入（统一入口） ============

    def _write_metadata(self, file_path: Path, music_info: MusicInfo) -> bool:
        """写入音频元数据（统一入口）

        策略:
        1. 优先使用 ffmpeg（封面嵌入对杜比 MP4 等更健壮）
        2. ffmpeg 不可用或写入失败 → 回退 mutagen（纯 Python，不依赖外部程序）
        3. 两者都失败 → 返回 False，由上层记录警告

        Returns:
            是否写入成功
        """
        if self._resolve_ffmpeg():
            if self._write_metadata_with_ffmpeg(file_path, music_info):
                return True
            print("ffmpeg 元数据写入失败，回退 mutagen")
        return self._write_metadata_with_mutagen(file_path, music_info)

    def _download_cover(self, pic_url: str) -> Optional[bytes]:
        """下载封面图片到内存（供 mutagen 使用）"""
        if not pic_url:
            return None
        try:
            resp = requests.get(pic_url, timeout=10)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            print(f"封面下载失败: {e}")
            return None

    def _write_metadata_with_mutagen(
        self,
        file_path: Path,
        music_info: MusicInfo,
    ) -> bool:
        """使用 mutagen（纯 Python）写入音频元数据

        不依赖外部 ffmpeg，支持:
        - MP3  : ID3v2.3（title/artist/album/USLT 歌词/APIC 封面）
        - FLAC : VorbisComment（title/artist/album/lyrics + picture 封面）
        - M4A/MP4: MP4 atom（©nam/©ART/©alb/©lyr 歌词/covr 封面）
        - OGG/Opus: VorbisComment（title/artist/album/lyrics + 封面）

        Returns:
            是否写入成功
        """
        try:
            import mutagen
            from mutagen.id3 import ID3, TIT2, TPE1, TALB, TPE2, USLT, APIC, COMM
            from mutagen.flac import FLAC, Picture
            from mutagen.mp4 import MP4, MP4Cover
            from mutagen.oggvorbis import OggVorbis
            from mutagen.oggopus import OggOpus
        except ImportError:
            print("mutagen 未安装，无法写入元数据 (pip install mutagen)")
            return False

        ext = file_path.suffix.lower()
        combined_lyric = self._merge_lyrics(music_info.lyric, music_info.tlyric)
        cover_data = self._download_cover(music_info.pic_url) if music_info.pic_url else None

        # 需移除的曲目号类字段（Windows 属性"曲目号"会显示为 #N，用户不需要）
        TRACK_FIELDS = ("tracknumber", "tracktotal", "track", "discnumber", "disknumber")

        try:
            if ext == ".mp3":
                try:
                    audio = ID3(str(file_path))
                except Exception:
                    # 无 ID3 头的 MP3：创建空标签再写入
                    audio = ID3()
                audio.delall("TRCK")  # 移除曲目号帧
                audio.add(TIT2(encoding=3, text=music_info.name))
                audio.add(TPE1(encoding=3, text=music_info.artists))
                audio.add(TALB(encoding=3, text=music_info.album))
                audio.add(TPE2(encoding=3, text=music_info.artists))
                audio.add(COMM(encoding=3, lang="eng", desc="", text="Downloaded from Netease Cloud Music"))
                if combined_lyric:
                    audio.add(USLT(encoding=3, lang="chi", desc="", text=combined_lyric))
                if cover_data:
                    audio.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover_data))
                audio.save(str(file_path), v2_version=3)

            elif ext == ".flac":
                audio = FLAC(str(file_path))
                for k in TRACK_FIELDS:
                    try:
                        del audio[k]
                    except Exception:
                        pass
                audio["title"] = music_info.name
                audio["artist"] = music_info.artists
                audio["album"] = music_info.album
                audio["albumartist"] = music_info.artists
                audio["comment"] = "Downloaded from Netease Cloud Music"
                if combined_lyric:
                    audio["lyrics"] = combined_lyric
                if cover_data:
                    pic = Picture()
                    pic.type = 3
                    pic.mime = "image/jpeg"
                    pic.desc = "Cover"
                    pic.data = cover_data
                    audio.add_picture(pic)
                audio.save()

            elif ext in (".m4a", ".mp4"):
                audio = MP4(str(file_path))
                for k in ("trkn", "disk", "disc"):
                    try:
                        del audio[k]
                    except Exception:
                        pass
                audio["\xa9nam"] = music_info.name
                audio["\xa9ART"] = music_info.artists
                audio["\xa9alb"] = music_info.album
                audio["aART"] = music_info.artists
                audio["\xa9cmt"] = "Downloaded from Netease Cloud Music"
                if combined_lyric:
                    audio["\xa9lyr"] = combined_lyric
                if cover_data:
                    audio["covr"] = [MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)]
                audio.save()

            elif ext in (".ogg", ".opus"):
                try:
                    audio = OggOpus(str(file_path))
                except Exception:
                    audio = OggVorbis(str(file_path))
                for k in TRACK_FIELDS:
                    try:
                        del audio[k]
                    except Exception:
                        pass
                audio["title"] = music_info.name
                audio["artist"] = music_info.artists
                audio["album"] = music_info.album
                audio["albumartist"] = music_info.artists
                if combined_lyric:
                    audio["lyrics"] = combined_lyric
                if cover_data:
                    pic = Picture()
                    pic.type = 3
                    pic.mime = "image/jpeg"
                    pic.desc = "Cover"
                    pic.data = cover_data
                    audio["metadata_block_picture"] = [
                        base64.b64encode(pic.write()).decode("ascii")
                    ]
                audio.save()

            else:
                print(f"mutagen 不支持的格式: {ext}")
                return False

            print(f"mutagen 元数据写入成功: {file_path.name}")
            return True

        except Exception as e:
            print(f"mutagen 元数据写入失败: {e}")
            return False

    # ============ ffmpeg 元数据写入（核心） ============

    def _write_metadata_with_ffmpeg(
        self,
        file_path: Path,
        music_info: MusicInfo,
    ) -> bool:
        """使用 ffmpeg 写入音频元数据

        处理: title/artist/album/track/lyrics + 封面（mp3/flac/m4a/mp4 等）

        写入策略（分级回退，确保数据不丢失）:
        1. 先尝试"完整元数据"（含歌词）
        2. 若因歌词超长/特殊字符导致失败，自动回退为"基础元数据"（不含歌词），
           保证 title/artist/album/封面 等核心信息一定写入
        3. 基础元数据也失败时，返回 False 由上层记录警告

        Returns:
            是否写入成功（失败不影响主流程）
        """
        ffmpeg_path = self._resolve_ffmpeg()
        if not ffmpeg_path:
            print("跳过元数据写入: ffmpeg 不可用")
            return False

        file_ext = file_path.suffix.lower()
        if file_ext not in METADATA_FORMATS:
            print(f"跳过元数据写入: 不支持的格式 {file_ext}")
            return False

        if not file_path.exists():
            print(f"跳过元数据写入: 文件不存在 {file_path}")
            return False

        # 临时输出文件：保留原扩展名在最后，便于 ffmpeg 识别 muxer
        # 例: 艾辰 - 错位时空.tagging.flac
        tmp_output = file_path.with_name(
            file_path.stem + ".tagging" + file_path.suffix
        )
        # 临时封面文件
        cover_tmp: Optional[str] = None

        try:
            # 下载封面到临时文件
            if music_info.pic_url:
                try:
                    pic_resp = requests.get(music_info.pic_url, timeout=10)
                    pic_resp.raise_for_status()
                    fd, cover_tmp = tempfile.mkstemp(suffix=".jpg", dir=str(self.download_dir))
                    os.close(fd)
                    with open(cover_tmp, "wb") as cf:
                        cf.write(pic_resp.content)
                except Exception as e:
                    print(f"封面下载失败，跳过封面写入: {e}")
                    cover_tmp = None

            # 合并歌词（原文 + 翻译，按时间戳逐行合并）
            combined_lyric = self._merge_lyrics(music_info.lyric, music_info.tlyric)

            # 基础元数据（不含歌词）
            base_meta = {
                "title": music_info.name,
                "artist": music_info.artists,
                "album": music_info.album,
                "album_artist": music_info.artists,
                "comment": "Downloaded from Netease Cloud Music",
            }
            # 注意：不写入 track/tracktotal（Windows 属性"曲目号"会显示为 #N，
            # 用户不需要该标记，故从元数据中移除）

            # 构造 ffmpeg 命令
            # 顺序: global opts -> -i input1 -> -i input2 -> metadata -> mapping -> -f format -> output
            def build_cmd(meta: Dict[str, str]) -> List[str]:
                cmd: List[str] = [
                    ffmpeg_path, "-y", "-loglevel", "error",
                    "-i", str(file_path),
                ]
                if cover_tmp:
                    cmd += ["-i", cover_tmp]
                for k, v in meta.items():
                    if v is not None and str(v).strip():
                        cmd += ["-metadata", f"{k}={v}"]
                cmd += self._build_format_args(file_ext, has_cover=bool(cover_tmp))
                output_format = EXT_TO_FFMPEG_FORMAT.get(file_ext, "")
                if output_format:
                    cmd += ["-f", output_format]
                cmd.append(str(tmp_output))
                return cmd

            def run_ffmpeg(cmd: List[str]) -> bool:
                """执行 ffmpeg 并原子替换原文件，成功返回 True"""
                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=120,
                        encoding="utf-8",
                        errors="ignore",
                    )
                    if result.returncode == 0 and tmp_output.exists():
                        shutil.move(str(tmp_output), str(file_path))
                        return True
                    print(
                        f"ffmpeg 写入元数据失败: "
                        f"{(result.stderr or result.stdout or '').strip()}"
                    )
                    return False
                except subprocess.TimeoutExpired:
                    print("ffmpeg 执行超时")
                    return False
                except FileNotFoundError:
                    print(f"ffmpeg 可执行文件未找到: {ffmpeg_path}")
                    return False
                except Exception as e:
                    print(f"ffmpeg 写入元数据异常: {e}")
                    return False

            # 1. 尝试完整元数据（含歌词）
            if combined_lyric:
                full_meta = dict(base_meta)
                full_meta["lyrics"] = combined_lyric
                if run_ffmpeg(build_cmd(full_meta)):
                    return True
                # 2. 歌词导致失败 → 回退为基础元数据，保证核心信息不丢失
                print("完整元数据写入失败（可能因歌词超长/特殊字符），回退为基础元数据")
                if run_ffmpeg(build_cmd(base_meta)):
                    return True
                return False

            # 无歌词时直接写入基础元数据
            return run_ffmpeg(build_cmd(base_meta))

        finally:
            # 清理封面临时文件
            if cover_tmp and os.path.exists(cover_tmp):
                try:
                    os.unlink(cover_tmp)
                except OSError:
                    pass
            # 清理可能残留的临时输出
            if tmp_output.exists():
                try:
                    tmp_output.unlink()
                except OSError:
                    pass

    def _build_format_args(self, file_ext: str, has_cover: bool) -> List[str]:
        """根据文件格式构造 mapping / 编码参数"""
        if file_ext == ".mp3":
            # MP3: 封面通过 ID3v2 APIC 帧写入
            if has_cover:
                return [
                    "-map", "0:a", "-map", "1:v",
                    "-c:a", "copy", "-c:v", "copy",
                    "-id3v2_version", "3",
                    "-metadata:s:v", "title=Album cover",
                    "-metadata:s:v", "comment=Cover (front)",
                ]
            return ["-map", "0:a", "-c:a", "copy", "-id3v2_version", "3"]

        if file_ext == ".flac":
            # FLAC: 原生支持封面
            if has_cover:
                return [
                    "-map", "0", "-map", "1",
                    "-c", "copy",
                    "-disposition:v:0", "attached_pic",
                ]
            return ["-map", "0", "-c", "copy"]

        if file_ext == ".m4a":
            # M4A: AAC 音频 + mp4 容器
            if has_cover:
                return [
                    "-map", "0:a", "-map", "1:v",
                    "-c", "copy",
                    "-disposition:v:0", "attached_pic",
                    "-metadata:s:v", "title=Album cover",
                    "-metadata:s:v", "comment=Cover (front)",
                ]
            return ["-map", "0:a", "-c:a", "copy"]

        if file_ext == ".mp4":
            # MP4 (杜比全景声 EAC3 / 其它 mp4 容器音频)
            # 杜比文件通常无视频流，封面作为 video stream 注入；+faststart 让 moov 在文件头
            if has_cover:
                return [
                    "-map", "0", "-map", "1:v",
                    "-c", "copy",
                    "-disposition:v:0", "attached_pic",
                    "-metadata:s:v", "title=Album cover",
                    "-metadata:s:v", "comment=Cover (front)",
                    "-movflags", "+faststart",
                ]
            return ["-map", "0", "-c", "copy", "-movflags", "+faststart"]

        if file_ext in (".ogg", ".opus"):
            if has_cover:
                return [
                    "-map", "0:a", "-map", "1:v",
                    "-c:a", "copy", "-c:v", "copy",
                ]
            return ["-map", "0:a", "-c:a", "copy"]

        # 默认
        if has_cover:
            return ["-map", "0:a", "-map", "1:v", "-c", "copy"]
        return ["-map", "0:a", "-c:a", "copy"]


# ============ CLI 入口 ============

if __name__ == "__main__":
    import sys
    from dataclasses import asdict

    downloader = MusicDownloader()

    # 无参数：打印模块信息
    if len(sys.argv) < 2:
        print("网易云音乐下载器")
        print(f"ffmpeg 路径: {downloader.ffmpeg_path or '未找到'}")
        print("支持的音质: standard / exhigh / lossless / hires / sky / jyeffect / jymaster / dolby")
        print("支持的功能: 同步/异步/批量下载、内存下载、进度查询、ffmpeg 元数据写入")
        print()
        print("用法:")
        print("  python music_downloader.py <music_id> [quality]            # 仅打印信息")
        print("  python music_downloader.py <music_id> [quality] --download # 打印并下载")
        print()
        print("示例:")
        print("  python music_downloader.py 123456")
        print("  python music_downloader.py 123456 lossless")
        print("  python music_downloader.py 123456 hires --download")
        sys.exit(0)

    # 解析参数
    try:
        music_id = int(sys.argv[1])
    except ValueError:
        print(f"错误: music_id 必须是整数，收到: {sys.argv[1]!r}")
        sys.exit(1)

    quality = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else "lossless"
    do_download = "--download" in sys.argv

    # 打印音乐信息
    try:
        info = downloader.get_music_info(music_id, quality)
    except DownloadException as e:
        print(f"获取音乐信息失败: {e}")
        sys.exit(1)

    print()
    print("=" * 70)
    print(f"音乐信息  (ID={info.id}, quality={info.quality})")
    print("=" * 70)

    info_dict = asdict(info)
    for key, value in info_dict.items():
        # 歌词太长，只显示行数
        if key in ("lyric", "tlyric"):
            lines = [ln for ln in (value or "").splitlines() if ln.strip()]
            preview = " | ".join(lines[:2])[:80] if lines else "(空)"
            print(f"  {key:<14}: {len(lines)} 行  预览: {preview}{'...' if len(lines) > 2 else ''}")
            continue
        # URL 类字段：完整展示（如果终端窄可换行）
        if key in ("download_url", "pic_url"):
            print(f"  {key:<14}: {value}")
            continue
        print(f"  {key:<14}: {value}")

    print("=" * 70)

    # 可选：触发下载
    if do_download:
        print()
        print("开始下载...")
        result = downloader.download_music_file(music_id, quality)
        if result.success:
            print(f"下载完成: {result.file_path}  ({result.file_size} 字节)")
        else:
            print(f"下载失败: {result.error_message}")
            sys.exit(1)
