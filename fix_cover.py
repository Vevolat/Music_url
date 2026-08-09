"""修复下载目录中缺失封面的音频文件

扫描 downloads 目录，对没有内嵌封面的音频文件，按文件名搜索网易云
获取封面并写入（使用 mutagen，不依赖 ffmpeg）。

用法:
    python fix_cover.py              # 修复 downloads 目录
    python fix_cover.py <目录路径>    # 修复指定目录

说明:
    - 已有封面的文件会跳过
    - 按文件主名搜索网易云，取第一个带封面的结果写入
    - 封面下载/写入失败不影响其他文件
"""

import os
import sys
import base64
from pathlib import Path
from typing import Optional

import requests

from music_api import load_cookies, search_music
from mutagen import File
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, APIC
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus

# 支持的音频扩展名
AUDIO_EXTS = {".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus"}


def has_cover(path: Path) -> bool:
    """检查文件是否已有内嵌封面"""
    try:
        audio = File(str(path))
        if audio is None:
            return False
        if hasattr(audio, "pictures"):
            return len(audio.pictures) > 0
        ext = path.suffix.lower()
        if ext == ".mp3":
            return any(isinstance(v, APIC) for v in audio.tags.values()) if audio.tags else False
        if ext in (".m4a", ".mp4"):
            return "covr" in audio
        return False
    except Exception:
        return False


def download_cover(url: str, timeout: int = 15) -> Optional[bytes]:
    """下载封面图片到内存"""
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        print(f"    封面下载失败: {e}")
        return None


def write_cover(path: Path, data: bytes) -> bool:
    """使用 mutagen 写入封面"""
    ext = path.suffix.lower()
    try:
        if ext == ".flac":
            audio = FLAC(str(path))
            audio.clear_pictures()
            pic = Picture()
            pic.type = 3
            pic.mime = "image/jpeg"
            pic.desc = "Cover"
            pic.data = data
            audio.add_picture(pic)
            audio.save()

        elif ext == ".mp3":
            try:
                audio = ID3(str(path))
            except Exception:
                audio = ID3()
            audio.delall("APIC")
            audio.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=data))
            audio.save(str(path), v2_version=3)

        elif ext in (".m4a", ".mp4"):
            audio = MP4(str(path))
            audio["covr"] = [MP4Cover(data, imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()

        elif ext in (".ogg", ".opus"):
            try:
                audio = OggOpus(str(path))
            except Exception:
                audio = OggVorbis(str(path))
            pic = Picture()
            pic.type = 3
            pic.mime = "image/jpeg"
            pic.desc = "Cover"
            pic.data = data
            audio["metadata_block_picture"] = [
                base64.b64encode(pic.write()).decode("ascii")
            ]
            audio.save()

        else:
            return False

        print(f"    ✅ 封面已写入 ({len(data) / 1024:.0f}KB)")
        return True

    except Exception as e:
        print(f"    封面写入失败: {e}")
        return False


def find_cover_url(song_name: str) -> Optional[str]:
    """按歌名搜索网易云，返回第一个带封面的结果 URL"""
    try:
        cookies = load_cookies()
        songs = search_music(song_name, cookies, 5)
        for s in songs:
            pic = s.get("picUrl")
            if pic:
                return pic
    except Exception as e:
        print(f"    搜索失败: {e}")
    return None


def fix_dir(directory: Path) -> None:
    """修复指定目录中缺失封面的文件"""
    if not directory.exists():
        print(f"目录不存在: {directory}")
        return

    files = [f for f in sorted(directory.iterdir()) if f.is_file() and f.suffix.lower() in AUDIO_EXTS]
    if not files:
        print("目录中没有音频文件")
        return

    fixed, skipped, failed = 0, 0, 0
    print(f"扫描 {directory}，共 {len(files)} 个音频文件\n")

    for f in files:
        print(f"▶ {f.name}")
        if has_cover(f):
            print("    已有封面，跳过")
            skipped += 1
            continue

        # 用文件主名搜索（去掉扩展名和可能的序号后缀）
        song_name = f.stem
        url = find_cover_url(song_name)
        if not url:
            print("    ❌ 未找到匹配封面")
            failed += 1
            continue

        data = download_cover(url)
        if not data:
            failed += 1
            continue

        if write_cover(f, data):
            fixed += 1
        else:
            failed += 1

    print(f"\n=== 完成: 补写 {fixed} 个, 跳过 {skipped} 个, 失败 {failed} 个 ===")


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "downloads"
    fix_dir(Path(target))


if __name__ == "__main__":
    main()
