"""网易云音乐API服务主程序

提供网易云音乐相关API服务，包括：
- 歌曲信息获取
- 音乐搜索
- 歌单和专辑详情
- 音乐下载
- 健康检查
"""

import json
import logging
import os
import re
import secrets
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from urllib.parse import quote
from flask import Flask, request, send_file, render_template, Response, session

try:
    from music_api import (
        NeteaseAPI, APIException, QualityLevel,
        url_v1, name_v1, lyric_v1, search_music,
        playlist_detail, album_detail,
        account_profile, daily_recommend_songs, like_list_songs,
        parse_cookie_string,
    )
    from music_downloader import MusicDownloader, DownloadException, AudioFormat, clean_song_name, strip_hashtags
    from auth_service import AuthService
except ImportError as e:
    print(f"导入模块失败: {e}")
    print("请确保所有依赖模块存在且可用")
    sys.exit(1)


@dataclass
class APIConfig:
    """API配置类"""
    host: str = '0.0.0.0'
    port: int = 5000
    debug: bool = False
    downloads_dir: str = 'downloads'
    max_file_size: int = 500 * 1024 * 1024  # 500MB
    request_timeout: int = 30
    log_level: str = 'INFO'
    cors_origins: str = '*'
    # 下载文件名是否附加音质标记（如 [lossless]）。默认 False：文件名保持
    # "歌曲名.扩展名" 的简洁格式，音质信息通过元数据/API 响应获取。
    # 仅当显式开启时，浏览器下载名才附加 [quality] 后缀。
    filename_include_quality: bool = False
    # downloads 缓存目录大小上限（字节），超过后按时间从旧到新删除文件，默认 200MB
    cache_max_size: int = 200 * 1024 * 1024


class RateLimiter:
    """进程内滑动窗口限流器（按 key 计数，线程安全）"""

    def __init__(self, max_keys: int = 5000):
        self._buckets: Dict[str, list] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def allow(self, key: str, limit: int, window: int = 60) -> bool:
        now = time.time()
        with self._lock:
            if len(self._buckets) > self._max_keys:
                # 淘汰过期 key，防止内存无限增长
                self._buckets = {
                    k: ts for k, ts in self._buckets.items()
                    if ts and ts[-1] > now - window
                }
            bucket = [t for t in self._buckets.get(key, []) if t > now - window]
            if len(bucket) >= limit:
                self._buckets[key] = bucket
                return False
            bucket.append(now)
            self._buckets[key] = bucket
            return True


limiter = RateLimiter()
auth_service = AuthService()

# ============ 网易云 Cookie 存储（按站点账号隔离绑定） ============
# 安全模型：网易云 Cookie 即账号身份凭证，必须与站点账号一一绑定。
# data/cookie.json 结构为 { "<站点uid>": {cookie名: 值} }，游客与
# 其他用户均无法读取他人绑定；未登录站点账号时不携带任何网易云登录态。

COOKIE_STORE_FILE = Path("data") / "cookie.json"


def _first_site_user_id() -> Optional[int]:
    """查询站点账号库中最早注册的用户 id（用于旧数据迁移归属）"""
    try:
        row = auth_service._db.execute(
            "SELECT id FROM users ORDER BY id ASC LIMIT 1"
        ).fetchone()
        return int(row["id"]) if row else None
    except Exception:
        return None


def load_cookie_store() -> Dict[str, Dict[str, str]]:
    """读取网易云 Cookie 存储（data/cookie.json），返回 {uid(str): {cookie名: 值}}"""
    try:
        with open(COOKIE_STORE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        out: Dict[str, Dict[str, str]] = {}
        for uid, cookies in data.items():
            if isinstance(cookies, dict) and cookies:
                out[str(uid)] = {str(k): str(v) for k, v in cookies.items() if k and v}
        return out
    except (OSError, ValueError):
        return {}


def save_user_cookies(uid: int, cookies: Dict[str, str]) -> None:
    """将网易云 Cookie 绑定保存到指定站点账号名下（合并写入，不影响其他用户）"""
    store = load_cookie_store()
    if cookies:
        store[str(uid)] = {str(k): str(v) for k, v in cookies.items() if k and v}
    else:
        store.pop(str(uid), None)
    COOKIE_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(COOKIE_STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def clear_user_cookies(uid: int) -> None:
    """清除指定站点账号绑定的网易云 Cookie（不影响其他账号）"""
    store = load_cookie_store()
    if str(uid) in store:
        store.pop(str(uid), None)
        COOKIE_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(COOKIE_STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)


def migrate_legacy_cookie() -> None:
    """旧版全局共享 Cookie（cookie.txt 或旧 flat 格式 cookie.json）迁移：
    归属给站点账号库中最早注册的用户；无任何站点账号时直接丢弃。"""
    legacy_text = ""
    legacy = Path("cookie.txt")
    if legacy.exists():
        try:
            legacy_text = legacy.read_text(encoding="utf-8").strip()
        except OSError:
            legacy_text = ""

    legacy_cookies: Dict[str, str] = {}
    if COOKIE_STORE_FILE.exists():
        try:
            with open(COOKIE_STORE_FILE, "r", encoding="utf-8") as f:
                old = json.load(f)
            # 旧 flat 格式：顶层值是字符串（cookie名 -> 值）
            if isinstance(old, dict) and old and all(isinstance(v, str) for v in old.values()):
                legacy_cookies = {str(k): str(v) for k, v in old.items() if k and v}
        except (OSError, ValueError):
            pass

    if legacy_text and not legacy_cookies:
        legacy_cookies = parse_cookie_string(legacy_text)

    migrated_to = None
    if legacy_cookies:
        owner = _first_site_user_id()
        if owner is not None:
            store = load_cookie_store()
            store[str(owner)] = legacy_cookies
            COOKIE_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(COOKIE_STORE_FILE, "w", encoding="utf-8") as f:
                json.dump(store, f, ensure_ascii=False, indent=2)
            migrated_to = owner
        else:
            print("检测到旧版全局 Cookie，但站点无注册账号，已丢弃（请登录站点账号后重新绑定网易云）")

    if legacy.exists():
        try:
            legacy.unlink()
            print("已删除旧版 cookie.txt")
        except OSError:
            pass
    if migrated_to is not None:
        print(f"已将旧版全局 Cookie 迁移绑定至站点账号 uid={migrated_to}（网易云 Cookie 现按账号隔离）")


def rate_limit(limit: int, window: int = 60):
    """按 IP 限流的接口装饰器"""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = f"rl:{request.path}:{request.remote_addr}"
            if not limiter.allow(key, limit, window):
                return APIResponse.error("请求过于频繁，请稍后再试", 429, "rate_limited")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def login_required(fn):
    """要求已登录的装饰器"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("uid"):
            return APIResponse.error("请先登录", 401, "unauthorized")
        return fn(*args, **kwargs)
    return wrapper


def validate_music_id(raw_id: Any) -> Optional[str]:
    """校验音乐 ID：仅允许 1-20 位纯数字，防止注入与异常输入"""
    text = str(raw_id or "").strip()
    return text if re.fullmatch(r"\d{1,20}", text) else None


def validate_netease_id_param(raw_id: Any) -> Optional[str]:
    """校验歌单 / 专辑 ID：允许纯数字或包含 id= 的链接，返回纯数字 ID"""
    text = str(raw_id or "").strip()[:500]
    match = re.search(r"[?&]id=(\d{1,20})", text)
    if match:
        return match.group(1)
    return text if re.fullmatch(r"\d{1,20}", text) else None


def get_json_body() -> Dict[str, Any]:
    """安全读取 JSON 请求体（限制为对象类型）"""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


class APIResponse:
    """API响应工具类"""
    
    @staticmethod
    def success(data: Any = None, message: str = 'success', status_code: int = 200) -> Tuple[Dict[str, Any], int]:
        """成功响应"""
        response = {
            'status': status_code,
            'success': True,
            'message': message
        }
        if data is not None:
            response['data'] = data
        return response, status_code
    
    @staticmethod
    def error(message: str, status_code: int = 400, error_code: str = None) -> Tuple[Dict[str, Any], int]:
        """错误响应"""
        response = {
            'status': status_code,
            'success': False,
            'message': message
        }
        if error_code:
            response['error_code'] = error_code
        return response, status_code


class MusicAPIService:
    """音乐API服务类"""
    
    def __init__(self, config: APIConfig):
        self.config = config
        self.logger = self._setup_logger()
        self.netease_api = NeteaseAPI()
        self.downloader = MusicDownloader(cache_max_size=config.cache_max_size)

        # 创建下载目录
        self.downloads_path = Path(config.downloads_dir)
        self.downloads_path.mkdir(exist_ok=True)

        self.logger.info(f"音乐API服务初始化完成，下载目录: {self.downloads_path.absolute()}")
    
    def _setup_logger(self) -> logging.Logger:
        """设置日志记录器"""
        logger = logging.getLogger('music_api')
        logger.setLevel(getattr(logging, self.config.log_level.upper()))
        
        if not logger.handlers:
            # 控制台处理器
            console_handler = logging.StreamHandler()
            console_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            console_handler.setFormatter(console_formatter)
            logger.addHandler(console_handler)
            
            # 文件处理器
            try:
                file_handler = logging.FileHandler('music_api.log', encoding='utf-8')
                file_formatter = logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
                )
                file_handler.setFormatter(file_formatter)
                logger.addHandler(file_handler)
            except Exception as e:
                logger.warning(f"无法创建日志文件: {e}")
        
        return logger
    
    def _get_cookies(self) -> Dict[str, str]:
        """读取当前站点登录用户绑定的网易云 Cookie（游客与其他用户互不可见）"""
        try:
            uid = session.get("uid")
            if not uid:
                return {}
            return load_cookie_store().get(str(uid), {})
        except Exception as e:
            self.logger.error(f"读取 Cookie 存储异常: {e}")
            return {}
    
    def _extract_music_id(self, id_or_url: str) -> Optional[str]:
        """提取音乐ID（仅返回纯数字 ID，非法输入返回 None）"""
        try:
            text = str(id_or_url or "").strip()[:500]

            # 处理短链接
            if '163cn.tv' in text:
                import requests
                response = requests.get(text, allow_redirects=False, timeout=10)
                text = response.headers.get('Location', text)

            # 处理网易云链接
            if 'music.163.com' in text:
                index = text.find('id=') + 3
                if index > 2:
                    text = text[index:].split('&')[0]

            return validate_music_id(text)

        except Exception as e:
            self.logger.error(f"提取音乐ID失败: {e}")
            return None
    
    def _format_file_size(self, size_bytes: int) -> str:
        """格式化文件大小"""
        if size_bytes == 0:
            return "0B"
        
        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(size_bytes)
        unit_index = 0
        
        while size >= 1024.0 and unit_index < len(units) - 1:
            size /= 1024.0
            unit_index += 1
        
        return f"{size:.2f}{units[unit_index]}"
    
    def _get_quality_display_name(self, quality: str) -> str:
        """获取音质显示名称"""
        quality_names = {
            'standard': "标准音质",
            'exhigh': "极高音质", 
            'lossless': "无损音质",
            'hires': "Hi-Res音质",
            'sky': "沉浸环绕声",
            'jyeffect': "高清环绕声",
            'jymaster': "超清母带",
            'dolby': "杜比全景声"
        }
        return quality_names.get(quality, f"未知音质({quality})")
    
    def _validate_request_params(self, required_params: Dict[str, Any]) -> Optional[Tuple[Dict[str, Any], int]]:
        """验证请求参数"""
        for param_name, param_value in required_params.items():
            if not param_value:
                return APIResponse.error(f"参数 '{param_name}' 不能为空", 400)
        return None
    
    def _safe_get_request_data(self) -> Dict[str, Any]:
        """安全获取请求数据"""
        try:
            if request.method == 'GET':
                return dict(request.args)
            else:
                # 优先使用JSON数据，然后是表单数据
                json_data = request.get_json(silent=True) or {}
                form_data = dict(request.form)
                # 合并数据，JSON优先
                return {**form_data, **json_data}
        except Exception as e:
            self.logger.error(f"获取请求数据失败: {e}")
            return {}


# 创建Flask应用和服务实例
config = APIConfig()
app = Flask(__name__)
api_service = MusicAPIService(config)

# ---- 会话与请求体安全配置 ----
_SECRET_KEY_FILE = os.path.join("data", "secret_key")
os.makedirs("data", exist_ok=True)
if not os.path.isfile(_SECRET_KEY_FILE):
    with open(_SECRET_KEY_FILE, "w", encoding="utf-8") as f:
        f.write(secrets.token_hex(32))
with open(_SECRET_KEY_FILE, "r", encoding="utf-8") as f:
    app.secret_key = f.read().strip()
app.config.update(
    MAX_CONTENT_LENGTH=64 * 1024,  # 请求体上限 64KB，防御超大包攻击
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=7 * 24 * 3600,
)


@app.before_request
def before_request():
    """请求前处理"""
    # 记录请求信息
    api_service.logger.info(
        f"{request.method} {request.path} - IP: {request.remote_addr} - "
        f"User-Agent: {request.headers.get('User-Agent', 'Unknown')}"
    )


@app.after_request
def after_request(response: Response) -> Response:
    """请求后处理 - 安全响应头与CORS"""
    # 安全响应头：防点击劫持 / MIME 嗅探 / 限制资源加载来源
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' https: http: data:; "
        "media-src 'self' https: http:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'"
    )
    if request.path.startswith("/api/") or request.path in {"/", "/health"}:
        # 页面与公开信息接口保持开放 CORS；业务接口同样开放以兼容既有调用方
        response.headers.add("Access-Control-Allow-Origin", config.cors_origins)
        response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
        response.headers.add("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        response.headers.add("Access-Control-Max-Age", "3600")

    # 记录响应信息
    api_service.logger.info(f"响应状态: {response.status_code}")
    return response


@app.errorhandler(400)
def handle_bad_request(e):
    """处理400错误"""
    return APIResponse.error("请求参数错误", 400)


@app.errorhandler(404)
def handle_not_found(e):
    """处理404错误"""
    return APIResponse.error("请求的资源不存在", 404)


@app.errorhandler(500)
def handle_internal_error(e):
    """处理500错误"""
    api_service.logger.error(f"服务器内部错误: {e}")
    return APIResponse.error("服务器内部错误", 500)


@app.route('/')
def index() -> str:
    """首页路由"""
    return render_template('index.html')


@app.route('/health', methods=['GET'])
def health_check():
    """健康检查API"""
    try:
        # 检查 Cookie 状态：统计已绑定网易云账号的站点用户数
        cookies = load_cookie_store()
        cookie_status = 'valid' if cookies else 'invalid'

        health_info = {
            'service': 'running',
            'timestamp': int(time.time()) if 'time' in sys.modules else None,
            'cookie_status': cookie_status,
            'cookie_count': len(cookies),
            'downloads_dir': str(api_service.downloads_path.absolute()),
            'version': '2.0.0'
        }

        return APIResponse.success(health_info, "API服务运行正常")
        
    except Exception as e:
        api_service.logger.error(f"健康检查失败: {e}")
        return APIResponse.error(f"健康检查失败: {str(e)}", 500)


@app.route('/song', methods=['GET', 'POST'])
@app.route('/Song_V1', methods=['GET', 'POST'])  # 向后兼容
@rate_limit(limit=60, window=60)
def get_song_info():
    """获取歌曲信息API"""
    try:
        # 获取请求参数
        data = api_service._safe_get_request_data()
        song_ids = data.get('ids') or data.get('id')
        url = data.get('url')
        level = data.get('level', 'lossless')
        info_type = data.get('type', 'url')

        # 参数验证
        if not song_ids and not url:
            return APIResponse.error("必须提供 'ids'、'id' 或 'url' 参数")

        # 提取音乐ID（含合法性校验）
        music_id = api_service._extract_music_id(song_ids or url)
        if not music_id:
            return APIResponse.error("无效的歌曲 ID 或链接", 400)

        # 验证音质参数
        valid_levels = ['standard', 'exhigh', 'lossless', 'hires', 'sky', 'jyeffect', 'jymaster', 'dolby']
        if level not in valid_levels:
            return APIResponse.error(f"无效的音质参数，支持: {', '.join(valid_levels)}")
        
        # 验证类型参数
        valid_types = ['url', 'name', 'lyric', 'json']
        if info_type not in valid_types:
            return APIResponse.error(f"无效的类型参数，支持: {', '.join(valid_types)}")
        
        cookies = api_service._get_cookies()
        
        # 根据类型获取不同信息
        if info_type == 'url':
            result = url_v1(music_id, level, cookies)
            if result and result.get('data') and len(result['data']) > 0:
                song_data = result['data'][0]
                response_data = {
                    'id': song_data.get('id'),
                    'url': song_data.get('url'),
                    'level': song_data.get('level'),
                    'quality_name': api_service._get_quality_display_name(song_data.get('level', level)),
                    'size': song_data.get('size'),
                    'size_formatted': api_service._format_file_size(song_data.get('size', 0)),
                    'type': song_data.get('type'),
                    'bitrate': song_data.get('br')
                }
                return APIResponse.success(response_data, "获取歌曲URL成功")
            else:
                return APIResponse.error("获取音乐URL失败，可能是版权限制或音质不支持", 404)
        
        elif info_type == 'name':
            result = name_v1(music_id)
            return APIResponse.success(result, "获取歌曲信息成功")
        
        elif info_type == 'lyric':
            result = lyric_v1(music_id, cookies)
            return APIResponse.success(result, "获取歌词成功")
        
        elif info_type == 'json':
            # 获取完整的歌曲信息（用于前端解析）
            song_info = name_v1(music_id)
            url_info = url_v1(music_id, level, cookies)
            lyric_info = lyric_v1(music_id, cookies)
            
            if not song_info or 'songs' not in song_info or not song_info['songs']:
                return APIResponse.error("未找到歌曲信息", 404)
            
            song_data = song_info['songs'][0]
            
            # 构建前端期望的响应格式
            response_data = {
                'id': music_id,
                'name': clean_song_name(song_data.get('name', '')),
                'ar_name': strip_hashtags(', '.join(artist['name'] for artist in song_data.get('ar', []))),
                'al_name': strip_hashtags(song_data.get('al', {}).get('name', '')),
                'pic': song_data.get('al', {}).get('picUrl', ''),
                'level': level,
                'lyric': lyric_info.get('lrc', {}).get('lyric', '') if lyric_info else '',
                'tlyric': lyric_info.get('tlyric', {}).get('lyric', '') if lyric_info else ''
            }
            
            # 添加URL和大小信息
            if url_info and url_info.get('data') and len(url_info['data']) > 0:
                url_data = url_info['data'][0]
                response_data.update({
                    'url': url_data.get('url', ''),
                    'size': api_service._format_file_size(url_data.get('size', 0)),
                    'level': url_data.get('level', level)
                })
            else:
                response_data.update({
                    'url': '',
                    'size': '获取失败'
                })
            
            return APIResponse.success(response_data, "获取歌曲信息成功")
            
    except APIException as e:
        api_service.logger.error(f"API调用失败: {e}")
        return APIResponse.error(f"API调用失败: {str(e)}", 500)
    except Exception as e:
        api_service.logger.error(f"获取歌曲信息异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error(f"服务器错误: {str(e)}", 500)


@app.route('/search', methods=['GET', 'POST'])
@app.route('/Search', methods=['GET', 'POST'])  # 向后兼容
@rate_limit(limit=30, window=60)
def search_music_api():
    """搜索音乐API"""
    try:
        # 获取请求参数
        data = api_service._safe_get_request_data()
        keyword = str(data.get('keyword') or data.get('keywords') or data.get('q') or '').strip()[:64]
        limit = min(max(int(data.get('limit', 30)), 1), 100)
        search_type = '1'
        
        # 参数验证
        validation_error = api_service._validate_request_params({'keyword': keyword})
        if validation_error:
            return validation_error
        
        # 限制搜索数量
        if limit > 100:
            limit = 100
        
        cookies = api_service._get_cookies()
        result = search_music(keyword, cookies, limit)
        
        # search_music返回的是歌曲列表，需要包装成前端期望的格式
        if result:
            for song in result:
                # 清洗歌曲元素（移除"(有字幕)"、"#"等多余内容）
                if 'name' in song:
                    song['name'] = clean_song_name(song['name'])
                if 'artists' in song:
                    song['artists'] = strip_hashtags(song['artists'])
                    song['artist_string'] = song['artists']
                if 'album' in song:
                    song['album'] = strip_hashtags(song['album'])
        
        return APIResponse.success(result, "搜索完成")
        
    except ValueError as e:
        return APIResponse.error(f"参数格式错误: {str(e)}")
    except Exception as e:
        api_service.logger.error(f"搜索音乐异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error(f"搜索失败: {str(e)}", 500)


@app.route('/playlist', methods=['GET', 'POST'])
@app.route('/Playlist', methods=['GET', 'POST'])  # 向后兼容
@rate_limit(limit=20, window=60)
def get_playlist():
    """获取歌单详情API"""
    try:
        # 获取请求参数
        data = api_service._safe_get_request_data()
        playlist_id = validate_netease_id_param(data.get('id'))

        # 参数验证
        validation_error = api_service._validate_request_params({'playlist_id': playlist_id})
        if validation_error:
            return APIResponse.error("无效的歌单 ID 或链接", 400)
        
        cookies = api_service._get_cookies()
        result = playlist_detail(playlist_id, cookies)

        # 清洗歌曲列表中的元素（移除"(有字幕)"、"#"等多余内容）
        for track in result.get('tracks', []):
            if 'name' in track:
                track['name'] = clean_song_name(track['name'])
            if 'artists' in track:
                track['artists'] = strip_hashtags(track['artists'])
            if 'album' in track:
                track['album'] = strip_hashtags(track['album'])
        
        # 适配前端期望的响应格式
        response_data = {
            'status': 'success',
            'playlist': result
        }
        
        return APIResponse.success(response_data, "获取歌单详情成功")
        
    except Exception as e:
        api_service.logger.error(f"获取歌单异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error(f"获取歌单失败: {str(e)}", 500)


@app.route('/album', methods=['GET', 'POST'])
@app.route('/Album', methods=['GET', 'POST'])  # 向后兼容
@rate_limit(limit=20, window=60)
def get_album():
    """获取专辑详情API"""
    try:
        # 获取请求参数
        data = api_service._safe_get_request_data()
        album_id = validate_netease_id_param(data.get('id'))

        # 参数验证
        validation_error = api_service._validate_request_params({'album_id': album_id})
        if validation_error:
            return APIResponse.error("无效的专辑 ID 或链接", 400)
        
        cookies = api_service._get_cookies()
        result = album_detail(album_id, cookies)

        # 清洗歌曲列表中的元素（移除"(有字幕)"、"#"等多余内容）
        for song in result.get('songs', []):
            if 'name' in song:
                song['name'] = clean_song_name(song['name'])
            if 'artists' in song:
                song['artists'] = strip_hashtags(song['artists'])
            if 'album' in song:
                song['album'] = strip_hashtags(song['album'])
        
        # 适配前端期望的响应格式
        response_data = {
            'status': 200,
            'album': result
        }
        
        return APIResponse.success(response_data, "获取专辑详情成功")
        
    except Exception as e:
        api_service.logger.error(f"获取专辑异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error(f"获取专辑失败: {str(e)}", 500)


@app.route('/download', methods=['GET', 'POST'])
@app.route('/Download', methods=['GET', 'POST'])  # 向后兼容
@rate_limit(limit=10, window=60)
def download_music_api():
    """下载音乐API"""
    try:
        # 获取请求参数
        data = api_service._safe_get_request_data()
        music_id = validate_music_id(data.get('id'))
        quality = data.get('quality', 'lossless')
        return_format = data.get('format', 'file')  # file 或 json

        # 参数验证
        if not music_id:
            return APIResponse.error("无效的音乐 ID 或链接", 400)
        
        # 验证音质参数
        valid_qualities = ['standard', 'exhigh', 'lossless', 'hires', 'sky', 'jyeffect', 'jymaster', 'dolby']
        if quality not in valid_qualities:
            return APIResponse.error(f"无效的音质参数，支持: {', '.join(valid_qualities)}")
        
        # 验证返回格式
        if return_format not in ['file', 'json']:
            return APIResponse.error("返回格式只支持 'file' 或 'json'")

        # 统一通过下载器处理：内部包含文件去重、安全文件名生成（"歌手 - 歌曲名.扩展名"）、
        # ffmpeg 元数据写入（歌词/封面/歌手/专辑等）
        download_result = api_service.downloader.download_music_file(music_id, quality)

        if not download_result.success:
            return APIResponse.error(f"下载失败: {download_result.error_message}", 500)

        if not download_result.file_path or not download_result.music_info:
            return APIResponse.error("下载结果缺少文件路径或音乐信息", 500)

        file_path = Path(download_result.file_path)
        music_info = download_result.music_info

        # 元数据写入警告（不阻断下载，仅记录）
        if download_result.warning:
            api_service.logger.warning(f"元数据写入警告 [{file_path.name}]: {download_result.warning}")

        # 文件名规则：默认与磁盘文件名一致（"歌手 - 歌曲名.扩展名"，无音质后缀）
        # 仅当配置 filename_include_quality 开启时，浏览器下载名才附加 [quality] 标记
        if config.filename_include_quality:
            raw_name = f"{music_info.name} [{quality}]"
            safe_name = api_service.downloader._sanitize_filename(raw_name)
            filename = f"{safe_name}.{music_info.file_type}"
        else:
            filename = file_path.name

        # 根据返回格式返回结果
        if return_format == 'json':
            response_data = {
                'music_id': music_id,
                'name': music_info.name,
                'artist': music_info.artists,
                'album': music_info.album,
                'quality': quality,
                'quality_name': api_service._get_quality_display_name(quality),
                'file_type': music_info.file_type,
                'file_size': music_info.file_size,
                'file_size_formatted': api_service._format_file_size(music_info.file_size),
                'file_path': str(file_path.absolute()),
                'filename': filename,
                'duration': music_info.duration,
                'metadata_warning': download_result.warning or None
            }
            return APIResponse.success(response_data, "下载完成")
        else:
            # 返回文件下载
            if not file_path.exists():
                return APIResponse.error("文件不存在", 404)

            try:
                response = send_file(
                    str(file_path),
                    as_attachment=True,
                    download_name=filename,
                    mimetype=f"audio/{music_info.file_type}"
                )
                response.headers['X-Download-Message'] = 'Download completed successfully'
                response.headers['X-Download-Filename'] = quote(filename, safe='')
                if download_result.warning:
                    response.headers['X-Download-Warning'] = quote(download_result.warning, safe='')
                return response
            except Exception as e:
                api_service.logger.error(f"发送文件失败: {e}")
                return APIResponse.error(f"文件发送失败: {str(e)}", 500)

    except DownloadException as e:
        api_service.logger.error(f"下载异常: {e}")
        return APIResponse.error(f"下载失败: {str(e)}", 500)
    except Exception as e:
        api_service.logger.error(f"下载音乐异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error(f"下载异常: {str(e)}", 500)


@app.route('/auth/register', methods=['POST'])
@rate_limit(limit=5, window=3600)
def auth_register():
    """注册新用户"""
    try:
        data = get_json_body()
        ok, message = auth_service.create_user(data.get('username'), data.get('password'))
        if not ok:
            return APIResponse.error(message, 400)
        return APIResponse.success(None, message)
    except Exception as e:
        api_service.logger.error(f"注册异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error("注册失败，请稍后重试", 500)


@app.route('/auth/login', methods=['POST'])
@rate_limit(limit=10, window=300)
def auth_login():
    """用户登录（失败达到阈值触发阶梯封禁）"""
    try:
        data = get_json_body()
        ok, message, user = auth_service.verify_user(data.get('username'), data.get('password'))
        if not ok:
            return APIResponse.error(message, 401, "login_failed")
        session.clear()
        session["uid"] = user["id"]
        session["username"] = user["username"]
        session.permanent = True
        return APIResponse.success({"username": user["username"]}, message)
    except Exception as e:
        api_service.logger.error(f"登录异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error("登录失败，请稍后重试", 500)


@app.route('/auth/logout', methods=['POST'])
def auth_logout():
    """退出登录"""
    session.clear()
    return APIResponse.success(None, "已退出登录")


@app.route('/auth/me', methods=['GET'])
def auth_me():
    """查询当前登录状态"""
    uid = session.get("uid")
    if not uid:
        return APIResponse.success({"login": False}, "未登录")
    return APIResponse.success({"login": True, "username": session.get("username")}, "已登录")


@app.route('/favorites', methods=['GET'])
@login_required
def favorites_list():
    """获取当前用户收藏列表"""
    try:
        songs = auth_service.list_favorites(session["uid"])
        return APIResponse.success({"songs": songs, "total": len(songs)}, "获取收藏成功")
    except Exception as e:
        api_service.logger.error(f"获取收藏异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error("获取收藏失败", 500)


@app.route('/favorites', methods=['POST'])
@rate_limit(limit=60, window=60)
@login_required
def favorites_add():
    """添加收藏"""
    try:
        data = get_json_body()
        ok, message = auth_service.add_favorite(session["uid"], data)
        if not ok:
            return APIResponse.error(message, 400)
        return APIResponse.success(None, message)
    except Exception as e:
        api_service.logger.error(f"添加收藏异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error("添加收藏失败", 500)


@app.route('/favorites/<song_id>', methods=['DELETE'])
@login_required
def favorites_remove(song_id):
    """移除收藏"""
    try:
        ok, message = auth_service.remove_favorite(session["uid"], song_id)
        if not ok:
            return APIResponse.error(message, 404)
        return APIResponse.success(None, message)
    except Exception as e:
        api_service.logger.error(f"移除收藏异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error("移除收藏失败", 500)


@app.route('/favorites/contains/<song_id>', methods=['GET'])
@login_required
def favorites_contains(song_id):
    """查询单曲是否已收藏"""
    return APIResponse.success({"fav": auth_service.has_favorite(session["uid"], song_id)}, "查询成功")


@app.route('/netease/login', methods=['POST'])
@rate_limit(limit=10, window=300)
@login_required
def netease_login():
    """绑定网易云 Cookie 到当前站点账号（接受完整 Cookie 串或仅 MUSIC_U 值）"""
    try:
        data = api_service._safe_get_request_data()
        raw = str(data.get('cookie') or '').strip()
        if not raw:
            return APIResponse.error('请输入 Cookie 或 MUSIC_U 值')
        if len(raw) > 4096:
            return APIResponse.error('Cookie 内容过长')

        cookies = parse_cookie_string(raw)
        if not cookies.get('MUSIC_U'):
            token = raw.strip().strip('"').strip("'")
            if re.fullmatch(r'[A-Za-z0-9%_-]{16,}', token):
                cookies = {'MUSIC_U': token}
        if not cookies.get('MUSIC_U'):
            return APIResponse.error('未在输入中找到 MUSIC_U 登录态，请复制包含 MUSIC_U 的 Cookie')

        profile = account_profile(cookies)
        if not profile.get('login'):
            return APIResponse.error('Cookie 无效或已过期，请重新复制最新的网易云 Cookie')

        save_user_cookies(session["uid"], cookies)
        api_service.logger.info(f"网易云 Cookie 绑定成功: uid={session['uid']} -> {profile.get('nickname', 'unknown')}")
        return APIResponse.success(profile, '网易云账号绑定成功（仅当前站点账号可用）')
    except APIException as e:
        return APIResponse.error(f"Cookie 校验失败: {str(e)}", 502)
    except Exception as e:
        api_service.logger.error(f"网易云登录异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error("登录失败，请稍后重试", 500)


@app.route('/netease/logout', methods=['POST'])
def netease_logout():
    """退出网易云登录（仅清除当前站点账号绑定的 Cookie，不影响其他账号）"""
    uid = session.get("uid")
    if uid:
        clear_user_cookies(uid)
    return APIResponse.success({'login': False}, '已退出网易云登录')


@app.route('/netease/profile', methods=['GET'])
@rate_limit(limit=10, window=60)
def netease_profile():
    """获取网易云账号资料（头像/昵称，基于网页输入的 Cookie）"""
    try:
        cookies = api_service._get_cookies()
        if not cookies.get('MUSIC_U'):
            return APIResponse.success({'login': False}, '尚未绑定网易云（请先登录站点账号，再在右上角绑定 Cookie）')
        return APIResponse.success(account_profile(cookies), '获取账号资料成功')
    except APIException as e:
        return APIResponse.error(f"获取账号资料失败: {str(e)}", 502)
    except Exception as e:
        api_service.logger.error(f"获取账号资料异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error("获取账号资料失败", 500)


@app.route('/netease/daily', methods=['GET'])
@rate_limit(limit=10, window=60)
def netease_daily():
    """获取网易云每日推荐歌曲（需要 MUSIC_U 登录态）"""
    try:
        cookies = api_service._get_cookies()
        if not cookies.get('MUSIC_U'):
            return APIResponse.error('每日推荐需要先登录站点账号并绑定网易云 Cookie（右上角操作）', 401)
        songs = daily_recommend_songs(cookies, limit=30)
        for s in songs:
            s['name'] = clean_song_name(s['name'])
            s['artists'] = strip_hashtags(s['artists'])
            s['album'] = strip_hashtags(s['album'])
        return APIResponse.success({'songs': songs}, '获取每日推荐成功')
    except APIException as e:
        return APIResponse.error(str(e), 502)
    except Exception as e:
        api_service.logger.error(f"获取每日推荐异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error("获取每日推荐失败", 500)


@app.route('/netease/likes', methods=['GET'])
@rate_limit(limit=10, window=60)
def netease_likes():
    """获取网易云"我喜欢的音乐"列表（需要 MUSIC_U 登录态）"""
    try:
        cookies = api_service._get_cookies()
        if not cookies.get('MUSIC_U'):
            return APIResponse.error('"我喜欢的音乐"需要先登录站点账号并绑定网易云 Cookie（右上角操作）', 401)
        profile = account_profile(cookies)
        if not profile.get('login'):
            return APIResponse.error('Cookie 已失效，请重新输入 Cookie 登录网易云', 401)
        songs = like_list_songs(cookies, profile['userId'])
        for s in songs:
            s['name'] = clean_song_name(s['name'])
            s['artists'] = strip_hashtags(s['artists'])
            s['album'] = strip_hashtags(s['album'])
        return APIResponse.success({'songs': songs}, '获取我喜欢的音乐成功')
    except APIException as e:
        return APIResponse.error(str(e), 502)
    except Exception as e:
        api_service.logger.error(f"获取我喜欢的音乐异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error("获取我喜欢的音乐失败", 500)


@app.route('/api/info', methods=['GET'])
def api_info():
    """API信息接口"""
    try:
        info = {
            'name': '网易云音乐API服务',
            'version': '2.0.0',
            'description': '提供网易云音乐相关API服务',
            'endpoints': {
                '/health': 'GET - 健康检查',
                '/song': 'GET/POST - 获取歌曲信息',
                '/search': 'GET/POST - 搜索音乐',
                '/playlist': 'GET/POST - 获取歌单详情',
                '/album': 'GET/POST - 获取专辑详情',
                '/download': 'GET/POST - 下载音乐',
                '/api/info': 'GET - API信息'
            },
            'supported_qualities': [
                'standard', 'exhigh', 'lossless', 
                'hires', 'sky', 'jyeffect', 'jymaster'
            ],
            'config': {
                'downloads_dir': str(api_service.downloads_path.absolute()),
                'max_file_size': f"{config.max_file_size // (1024*1024)}MB",
                'request_timeout': f"{config.request_timeout}s",
                'cache_max_size': f"{config.cache_max_size // (1024*1024)}MB"
            }
        }
        
        return APIResponse.success(info, "API信息获取成功")
        
    except Exception as e:
        api_service.logger.error(f"获取API信息异常: {e}")
        return APIResponse.error(f"获取API信息失败: {str(e)}", 500)


def start_api_server():
    """启动API服务器"""
    try:
        migrate_legacy_cookie()
        print("\n" + "=" * 60)
        print("网易云音乐API服务启动中")
        print("=" * 60)
        print(f"服务地址: http://{config.host}:{config.port}")
        print(f"下载目录: {api_service.downloads_path.absolute()}")
        print(f"日志级别: {config.log_level}")
        print("\nAPI端点:")
        print("  GET  /health          - 健康检查")
        print("  POST /song            - 获取歌曲信息")
        print("  POST /search          - 搜索音乐")
        print("  POST /playlist        - 获取歌单详情")
        print("  POST /album           - 获取专辑详情")
        print("  POST /download        - 下载音乐")
        print("  POST /auth/register   - 注册账号")
        print("  POST /auth/login      - 用户登录")
        print("  POST /auth/logout     - 退出登录")
        print("  GET  /auth/me         - 登录状态")
        print("  GET  /favorites       - 收藏列表")
        print("  POST /favorites       - 添加收藏")
        print("  DEL  /favorites/<id>  - 移除收藏")
        print("  POST /netease/login   - 网易云 Cookie 登录（网页输入）")
        print("  POST /netease/logout  - 退出网易云登录")
        print("  GET  /netease/profile - 网易云账号资料（头像/昵称，需 MUSIC_U）")
        print("  GET  /netease/daily   - 网易云每日推荐（需 MUSIC_U）")
        print("  GET  /netease/likes   - 网易云我喜欢的音乐（需 MUSIC_U）")
        print("  GET  /api/info        - API信息")
        print("\n支持的音质:")
        print("  standard, exhigh, lossless, hires, sky, jyeffect, jymaster, dolby")
        print("=" * 60)
        print(f"启动时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("服务已就绪，等待请求\n")

        # 启动Flask应用
        app.run(
            host=config.host,
            port=config.port,
            debug=config.debug,
            threaded=True
        )

    except KeyboardInterrupt:
        print("\n服务已停止")
    except Exception as e:
        api_service.logger.error(f"启动服务失败: {e}")
        print(f"启动失败: {e}")
        sys.exit(1)


if __name__ == '__main__':
    start_api_server()

