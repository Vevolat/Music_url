"""网易云音乐API模块

提供网易云音乐相关API接口的封装，包括：
- 音乐URL获取
- 歌曲详情获取
- 歌词获取
- 搜索功能
- 歌单和专辑详情
- 二维码登录
"""

import base64
import json
import os
import urllib.parse
import time
from random import randrange
from typing import Dict, List, Optional, Tuple, Any
from hashlib import md5
from enum import Enum

import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class QualityLevel(Enum):
    """音质等级枚举"""
    STANDARD = "standard"      # 标准音质
    EXHIGH = "exhigh"          # 极高音质
    LOSSLESS = "lossless"      # 无损音质
    HIRES = "hires"            # Hi-Res音质
    SKY = "sky"                # 沉浸环绕声
    JYEFFECT = "jyeffect"      # 高清环绕声
    JYMASTER = "jymaster"      # 超清母带
    DOLBY = "dolby"      # 杜比全景声


# 常量定义
class APIConstants:
    """API相关常量"""
    AES_KEY = b"e82ckenh8dichen8"
    USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36 Chrome/91.0.4472.164 NeteaseMusicDesktop/2.10.2.200154'
    REFERER = 'https://music.163.com/'
    
    # API URLs
    SONG_URL_V1 = "https://interface3.music.163.com/eapi/song/enhance/player/url/v1"
    SONG_DETAIL_V3 = "https://interface3.music.163.com/api/v3/song/detail"
    LYRIC_API = "https://interface3.music.163.com/api/song/lyric"
    SEARCH_API = 'https://music.163.com/api/cloudsearch/pc'
    PLAYLIST_DETAIL_API = 'https://music.163.com/api/v6/playlist/detail'
    ALBUM_DETAIL_API = 'https://music.163.com/api/v1/album/'
    QR_UNIKEY_API = 'https://interface3.music.163.com/eapi/login/qrcode/unikey'
    QR_LOGIN_API = 'https://interface3.music.163.com/eapi/login/qrcode/client/login'
    ACCOUNT_PROFILE_API = 'https://music.163.com/api/nuser/account/get'
    DAILY_RECOMMEND_API = 'https://music.163.com/weapi/v1/discovery/recommend/songs'
    USER_PLAYLIST_API = 'https://music.163.com/api/user/playlist'
    
    # 默认配置
    DEFAULT_CONFIG = {
        "os": "pc",
        "appver": "",
        "osver": "",
        "deviceId": "pyncm!"
    }
    
    DEFAULT_COOKIES = {
        "os": "pc",
        "appver": "",
        "osver": "",
        "deviceId": "pyncm!"
    }


class CryptoUtils:
    """加密工具类"""
    
    @staticmethod
    def hex_digest(data: bytes) -> str:
        """将字节数据转换为十六进制字符串"""
        return "".join([hex(d)[2:].zfill(2) for d in data])
    
    @staticmethod
    def hash_digest(text: str) -> bytes:
        """计算MD5哈希值"""
        return md5(text.encode("utf-8")).digest()
    
    @staticmethod
    def hash_hex_digest(text: str) -> str:
        """计算MD5哈希值并转换为十六进制字符串"""
        return CryptoUtils.hex_digest(CryptoUtils.hash_digest(text))
    
    @staticmethod
    def encrypt_params(url: str, payload: Dict[str, Any]) -> str:
        """加密请求参数"""
        url_path = urllib.parse.urlparse(url).path.replace("/eapi/", "/api/")
        digest = CryptoUtils.hash_hex_digest(f"nobody{url_path}use{json.dumps(payload)}md5forencrypt")
        params = f"{url_path}-36cd479b6b5-{json.dumps(payload)}-36cd479b6b5-{digest}"
        
        # AES加密
        padder = padding.PKCS7(algorithms.AES(APIConstants.AES_KEY).block_size).padder()
        padded_data = padder.update(params.encode()) + padder.finalize()
        cipher = Cipher(algorithms.AES(APIConstants.AES_KEY), modes.ECB())
        encryptor = cipher.encryptor()
        enc = encryptor.update(padded_data) + encryptor.finalize()
        
        return CryptoUtils.hex_digest(enc)


class HTTPClient:
    """HTTP客户端类"""
    
    @staticmethod
    def post_request(url: str, params: str, cookies: Dict[str, str]) -> str:
        """发送POST请求并返回文本响应"""
        headers = {
            'User-Agent': APIConstants.USER_AGENT,
            'Referer': APIConstants.REFERER,
        }
        
        request_cookies = APIConstants.DEFAULT_COOKIES.copy()
        request_cookies.update(cookies)
        
        try:
            response = requests.post(url, headers=headers, cookies=request_cookies, 
                                   data={"params": params}, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            raise APIException(f"HTTP请求失败: {e}")
    
    @staticmethod
    def post_request_full(url: str, params: str, cookies: Dict[str, str]) -> requests.Response:
        """发送POST请求并返回完整响应对象"""
        headers = {
            'User-Agent': APIConstants.USER_AGENT,
            'Referer': APIConstants.REFERER,
        }
        
        request_cookies = APIConstants.DEFAULT_COOKIES.copy()
        request_cookies.update(cookies)
        
        try:
            response = requests.post(url, headers=headers, cookies=request_cookies, 
                                   data={"params": params}, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            raise APIException(f"HTTP请求失败: {e}")


class APIException(Exception):
    """API异常类"""
    pass


class WeapiCrypto:
    """weapi 参数加密（用于需要登录态的 web 接口，如每日推荐）

    实测说明：随机密钥 + RSA 方案会被服务端拒绝（返回 200 空响应体），
    固定密钥对（社区通用方案）可正常工作，故采用固定密钥。
    """

    PRESET_KEY = b"0CoJUm6Qyw8W8jud"
    IV = b"0102030405060708"
    SECRET_KEY = b"TA3YiYCfY2dDJQgg"
    ENC_SEC_KEY = (
        "84ca47bca10bad09a6b04c5c927ef077d9b9f1e37098aa3eac6ea70eb59df0aa28b691b7e75e4f1f9831754919ea784c8f74fbfadf2898b0be17849fd656060162857830e241aba44991601f137624094c114ea8d17bce815b0cd4e5b8e2fbaba978c6d1d14dc3d1faf852bdd28818031ccdaaa13a6018e1024e2aae98844210"
    )

    @classmethod
    def _aes_encrypt(cls, text: str, key: bytes) -> str:
        padder = padding.PKCS7(algorithms.AES(key).block_size).padder()
        data = padder.update(text.encode("utf-8")) + padder.finalize()
        cipher = Cipher(algorithms.AES(key), modes.CBC(cls.IV))
        encryptor = cipher.encryptor()
        return base64.b64encode(encryptor.update(data) + encryptor.finalize()).decode()

    @classmethod
    def encrypt(cls, payload: Dict[str, Any]) -> Tuple[str, str]:
        """返回 (params, encSecKey) 表单字段（加密文本使用紧凑 JSON，等同 JSON.stringify）"""
        text = json.dumps(payload, separators=(",", ":"))
        params = cls._aes_encrypt(cls._aes_encrypt(text, cls.PRESET_KEY), cls.SECRET_KEY)
        return params, cls.ENC_SEC_KEY


class NeteaseAPI:
    """网易云音乐API主类"""
    
    def __init__(self):
        self.http_client = HTTPClient()
        self.crypto_utils = CryptoUtils()
    
    def get_song_url(self, song_id: int, quality: str, cookies: Dict[str, str]) -> Dict[str, Any]:
        """获取歌曲播放URL
        
        Args:
            song_id: 歌曲ID
            quality: 音质等级 (standard, exhigh, lossless, hires, sky, jyeffect, jymaster)
            cookies: 用户cookies
            
        Returns:
            包含歌曲URL信息的字典
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            config = APIConstants.DEFAULT_CONFIG.copy()
            config["requestId"] = str(randrange(20000000, 30000000))
            
            payload = {
                'ids': [song_id],
                'level': quality,
                'encodeType': 'mp4' if quality == 'dolby' else 'flac',
                'header': json.dumps(config),
            }

            if quality == 'sky':
                payload['immerseType'] = 'c51'
            
            params = self.crypto_utils.encrypt_params(APIConstants.SONG_URL_V1, payload)
            response_text = self.http_client.post_request(APIConstants.SONG_URL_V1, params, cookies)
            
            result = json.loads(response_text)
            if result.get('code') != 200:
                raise APIException(f"获取歌曲URL失败: {result.get('message', '未知错误')}")
            
            return result
        except (json.JSONDecodeError, KeyError) as e:
            raise APIException(f"解析响应数据失败: {e}")
    
    def get_song_detail(self, song_id: int) -> Dict[str, Any]:
        """获取歌曲详细信息
        
        Args:
            song_id: 歌曲ID
            
        Returns:
            包含歌曲详细信息的字典
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            data = {'c': json.dumps([{"id": song_id, "v": 0}])}
            response = requests.post(APIConstants.SONG_DETAIL_V3, data=data, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get('code') != 200:
                raise APIException(f"获取歌曲详情失败: {result.get('message', '未知错误')}")
            
            return result
        except requests.RequestException as e:
            raise APIException(f"获取歌曲详情请求失败: {e}")
        except json.JSONDecodeError as e:
            raise APIException(f"解析歌曲详情响应失败: {e}")
    
    def get_lyric(self, song_id: int, cookies: Dict[str, str]) -> Dict[str, Any]:
        """获取歌词信息
        
        Args:
            song_id: 歌曲ID
            cookies: 用户cookies
            
        Returns:
            包含歌词信息的字典
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            data = {
                'id': song_id, 
                'cp': 'false', 
                'tv': '0', 
                'lv': '0', 
                'rv': '0', 
                'kv': '0', 
                'yv': '0', 
                'ytv': '0', 
                'yrv': '0'
            }
            
            headers = {
                'User-Agent': APIConstants.USER_AGENT,
                'Referer': APIConstants.REFERER
            }
            
            response = requests.post(APIConstants.LYRIC_API, data=data, 
                                   headers=headers, cookies=cookies, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get('code') != 200:
                raise APIException(f"获取歌词失败: {result.get('message', '未知错误')}")
            
            return result
        except requests.RequestException as e:
            raise APIException(f"获取歌词请求失败: {e}")
        except json.JSONDecodeError as e:
            raise APIException(f"解析歌词响应失败: {e}")
    
    def search_music(self, keywords: str, cookies: Dict[str, str], limit: int = 10) -> List[Dict[str, Any]]:
        """搜索音乐
        
        Args:
            keywords: 搜索关键词
            cookies: 用户cookies
            limit: 返回数量限制
            
        Returns:
            歌曲信息列表
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            data = {'s': keywords, 'type': 1, 'limit': limit}
            headers = {
                'User-Agent': APIConstants.USER_AGENT,
                'Referer': APIConstants.REFERER
            }
            
            response = requests.post(APIConstants.SEARCH_API, data=data, 
                                   headers=headers, cookies=cookies, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get('code') != 200:
                raise APIException(f"搜索失败: {result.get('message', '未知错误')}")
            
            songs = []
            for item in result.get('result', {}).get('songs', []):
                song_info = {
                    'id': item['id'],
                    'name': item['name'],
                    'artists': '/'.join(artist['name'] for artist in item['ar']),
                    'album': item['al']['name'],
                    'picUrl': item['al']['picUrl']
                }
                songs.append(song_info)
            
            return songs
        except requests.RequestException as e:
            raise APIException(f"搜索请求失败: {e}")
        except (json.JSONDecodeError, KeyError) as e:
            raise APIException(f"解析搜索响应失败: {e}")
    
    def get_playlist_detail(self, playlist_id: int, cookies: Dict[str, str]) -> Dict[str, Any]:
        """获取歌单详情
        
        Args:
            playlist_id: 歌单ID
            cookies: 用户cookies
            
        Returns:
            歌单详情信息
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            data = {'id': playlist_id}
            headers = {
                'User-Agent': APIConstants.USER_AGENT,
                'Referer': APIConstants.REFERER
            }
            
            response = requests.post(APIConstants.PLAYLIST_DETAIL_API, data=data, 
                                   headers=headers, cookies=cookies, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get('code') != 200:
                raise APIException(f"获取歌单详情失败: {result.get('message', '未知错误')}")
            
            playlist = result.get('playlist', {})
            info = {
                'id': playlist.get('id'),
                'name': playlist.get('name'),
                'coverImgUrl': playlist.get('coverImgUrl'),
                'creator': playlist.get('creator', {}).get('nickname', ''),
                'trackCount': playlist.get('trackCount'),
                'description': playlist.get('description', ''),
                'tracks': []
            }
            
            # 获取所有trackIds并分批获取详细信息
            track_ids = [str(t['id']) for t in playlist.get('trackIds', [])]
            for i in range(0, len(track_ids), 100):
                batch_ids = track_ids[i:i+100]
                song_data = {'c': json.dumps([{'id': int(sid), 'v': 0} for sid in batch_ids])}
                
                song_resp = requests.post(APIConstants.SONG_DETAIL_V3, data=song_data, 
                                        headers=headers, cookies=cookies, timeout=30)
                song_resp.raise_for_status()
                
                song_result = song_resp.json()
                for song in song_result.get('songs', []):
                    info['tracks'].append({
                        'id': song['id'],
                        'name': song['name'],
                        'artists': '/'.join(artist['name'] for artist in song['ar']),
                        'album': song['al']['name'],
                        'picUrl': song['al']['picUrl']
                    })
            
            return info
        except requests.RequestException as e:
            raise APIException(f"获取歌单详情请求失败: {e}")
        except (json.JSONDecodeError, KeyError) as e:
            raise APIException(f"解析歌单详情响应失败: {e}")
    
    def get_album_detail(self, album_id: int, cookies: Dict[str, str]) -> Dict[str, Any]:
        """获取专辑详情
        
        Args:
            album_id: 专辑ID
            cookies: 用户cookies
            
        Returns:
            专辑详情信息
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            url = f'{APIConstants.ALBUM_DETAIL_API}{album_id}'
            headers = {
                'User-Agent': APIConstants.USER_AGENT,
                'Referer': APIConstants.REFERER
            }
            
            response = requests.get(url, headers=headers, cookies=cookies, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get('code') != 200:
                raise APIException(f"获取专辑详情失败: {result.get('message', '未知错误')}")
            
            album = result.get('album', {})
            info = {
                'id': album.get('id'),
                'name': album.get('name'),
                'coverImgUrl': self.get_pic_url(album.get('pic')),
                'artist': album.get('artist', {}).get('name', ''),
                'publishTime': album.get('publishTime'),
                'description': album.get('description', ''),
                'songs': []
            }
            
            for song in result.get('songs', []):
                info['songs'].append({
                    'id': song['id'],
                    'name': song['name'],
                    'artists': '/'.join(artist['name'] for artist in song['ar']),
                    'album': song['al']['name'],
                    'picUrl': self.get_pic_url(song['al'].get('pic'))
                })
            
            return info
        except requests.RequestException as e:
            raise APIException(f"获取专辑详情请求失败: {e}")
        except (json.JSONDecodeError, KeyError) as e:
            raise APIException(f"解析专辑详情响应失败: {e}")
    
    def netease_encrypt_id(self, id_str: str) -> str:
        """网易云加密图片ID算法
        
        Args:
            id_str: 图片ID字符串
            
        Returns:
            加密后的字符串
        """
        import base64
        import hashlib
        
        magic = list('3go8&$8*3*3h0k(2)2')
        song_id = list(id_str)
        
        for i in range(len(song_id)):
            song_id[i] = chr(ord(song_id[i]) ^ ord(magic[i % len(magic)]))
        
        m = ''.join(song_id)
        md5_bytes = hashlib.md5(m.encode('utf-8')).digest()
        result = base64.b64encode(md5_bytes).decode('utf-8')
        result = result.replace('/', '_').replace('+', '-')
        
        return result
    
    def get_pic_url(self, pic_id: Optional[int], size: int = 300) -> str:
        """获取网易云加密歌曲/专辑封面直链
        
        Args:
            pic_id: 封面ID
            size: 图片尺寸
            
        Returns:
            图片URL
        """
        if pic_id is None:
            return ''
        
        enc_id = self.netease_encrypt_id(str(pic_id))
        return f'https://p3.music.126.net/{enc_id}/{pic_id}.jpg?param={size}y{size}'


class QRLoginManager:
    """二维码登录管理器"""
    
    def __init__(self):
        self.http_client = HTTPClient()
        self.crypto_utils = CryptoUtils()
    
    def generate_qr_key(self) -> Optional[str]:
        """生成二维码的key
        
        Returns:
            成功返回unikey，失败返回None
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            config = APIConstants.DEFAULT_CONFIG.copy()
            config["requestId"] = str(randrange(20000000, 30000000))
            
            payload = {
                'type': 1,
                'header': json.dumps(config)
            }
            
            params = self.crypto_utils.encrypt_params(APIConstants.QR_UNIKEY_API, payload)
            response = self.http_client.post_request_full(APIConstants.QR_UNIKEY_API, params, {})
            
            result = json.loads(response.text)
            if result.get('code') == 200:
                return result.get('unikey')
            else:
                raise APIException(f"生成二维码key失败: {result.get('message', '未知错误')}")
        except (json.JSONDecodeError, KeyError) as e:
            raise APIException(f"解析二维码key响应失败: {e}")
    
    def create_qr_login(self) -> Optional[str]:
        """创建登录二维码并在控制台显示
        
        Returns:
            成功返回unikey，失败返回None
        """
        try:
            import qrcode
            
            unikey = self.generate_qr_key()
            if not unikey:
                print("生成二维码key失败")
                return None
            
            # 创建二维码
            qr = qrcode.QRCode()
            qr.add_data(f'https://music.163.com/login?codekey={unikey}')
            qr.make(fit=True)
            
            # 在控制台显示二维码
            qr.print_ascii(tty=True)
            print("\n请使用网易云音乐APP扫描上方二维码登录")
            return unikey
        except ImportError:
            print("请安装qrcode库: pip install qrcode")
            return None
        except Exception as e:
            print(f"创建二维码失败: {e}")
            return None
    
    def check_qr_login(self, unikey: str) -> Tuple[int, Dict[str, str]]:
        """检查二维码登录状态
        
        Args:
            unikey: 二维码key
            
        Returns:
            (登录状态码, cookie字典)
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            config = APIConstants.DEFAULT_CONFIG.copy()
            config["requestId"] = str(randrange(20000000, 30000000))
            
            payload = {
                'key': unikey,
                'type': 1,
                'header': json.dumps(config)
            }
            
            params = self.crypto_utils.encrypt_params(APIConstants.QR_LOGIN_API, payload)
            response = self.http_client.post_request_full(APIConstants.QR_LOGIN_API, params, {})
            
            result = json.loads(response.text)
            cookie_dict = {}
            
            if result.get('code') == 803:
                # 登录成功，提取cookie
                all_cookies = response.headers.get('Set-Cookie', '').split(', ')
                for cookie_str in all_cookies:
                    if 'MUSIC_U=' in cookie_str:
                        cookie_dict['MUSIC_U'] = cookie_str.split('MUSIC_U=')[1].split(';')[0]
            
            return result.get('code', -1), cookie_dict
        except (json.JSONDecodeError, KeyError) as e:
            raise APIException(f"解析登录状态响应失败: {e}")
    
    def qr_login(self) -> Optional[str]:
        """完整的二维码登录流程
        
        Returns:
            成功返回cookie字符串，失败返回None
        """
        try:
            unikey = self.create_qr_login()
            if not unikey:
                return None
            
            while True:
                code, cookies = self.check_qr_login(unikey)
                
                if code == 803:
                    print("\n登录成功！")
                    return f"MUSIC_U={cookies['MUSIC_U']};os=pc;appver=8.9.70;"
                elif code == 801:
                    print("\r等待扫码...", end='')
                elif code == 802:
                    print("\r扫码成功，请在手机上确认登录...", end='')
                else:
                    print(f"\n登录失败，错误码：{code}")
                    return None
                
                time.sleep(2)
        except KeyboardInterrupt:
            print("\n用户取消登录")
            return None
        except Exception as e:
            print(f"\n登录过程中发生错误: {e}")
            return None


# 向后兼容的函数接口
def url_v1(song_id: int, level: str, cookies: Dict[str, str]) -> Dict[str, Any]:
    """获取歌曲URL（向后兼容）"""
    api = NeteaseAPI()
    return api.get_song_url(song_id, level, cookies)


def name_v1(song_id: int) -> Dict[str, Any]:
    """获取歌曲详情（向后兼容）"""
    api = NeteaseAPI()
    return api.get_song_detail(song_id)


def lyric_v1(song_id: int, cookies: Dict[str, str]) -> Dict[str, Any]:
    """获取歌词（向后兼容）"""
    api = NeteaseAPI()
    return api.get_lyric(song_id, cookies)


def search_music(keywords: str, cookies: Dict[str, str], limit: int = 10) -> List[Dict[str, Any]]:
    """搜索音乐（向后兼容）"""
    api = NeteaseAPI()
    return api.search_music(keywords, cookies, limit)


def playlist_detail(playlist_id: int, cookies: Dict[str, str]) -> Dict[str, Any]:
    """获取歌单详情（向后兼容）"""
    api = NeteaseAPI()
    return api.get_playlist_detail(playlist_id, cookies)


def album_detail(album_id: int, cookies: Dict[str, str]) -> Dict[str, Any]:
    """获取专辑详情（向后兼容）"""
    api = NeteaseAPI()
    return api.get_album_detail(album_id, cookies)


def get_pic_url(pic_id: Optional[int], size: int = 300) -> str:
    """获取图片URL（向后兼容）"""
    api = NeteaseAPI()
    return api.get_pic_url(pic_id, size)


# ============ 网易账号能力（依赖 cookie.txt 中的 MUSIC_U 登录态） ============

_ACCOUNT_HEADERS = {
    'User-Agent': APIConstants.USER_AGENT,
    'Referer': APIConstants.REFERER,
}


def _map_web_song(item: Dict[str, Any]) -> Dict[str, Any]:
    """把 web 接口的歌曲对象统一映射为前端列表格式

    兼容两种结构：新版字段 ar/al（歌单详情等），旧版字段 artists/album（每日推荐等）。
    """
    artists = item.get('ar') or item.get('artists') or []
    album = item.get('al') or item.get('album') or {}
    pic = album.get('picUrl') or ''
    if not pic and album.get('pic'):
        pic = get_pic_url(album.get('pic'))
    return {
        'id': item.get('id'),
        'name': item.get('name', ''),
        'artists': '/'.join(a.get('name', '') for a in artists),
        'album': album.get('name', ''),
        'picUrl': pic,
    }


def account_profile(cookies: Dict[str, str]) -> Dict[str, Any]:
    """获取 cookie 对应的网易云账号资料（头像 / 昵称 / userId）

    未登录或 Cookie 失效时返回 {'login': False}。
    """
    response = requests.post(
        APIConstants.ACCOUNT_PROFILE_API,
        headers=_ACCOUNT_HEADERS, cookies=cookies, timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    if result.get('code') != 200:
        raise APIException(f"获取账号资料失败: {result.get('message', '未知错误')}")
    profile = result.get('profile') or {}
    if not profile:
        return {'login': False}
    return {
        'login': True,
        'userId': profile.get('userId'),
        'nickname': profile.get('nickname', ''),
        'avatarUrl': profile.get('avatarUrl', ''),
        'signature': profile.get('signature', ''),
    }


def daily_recommend_songs(cookies: Dict[str, str], limit: int = 30) -> List[Dict[str, Any]]:
    """获取每日推荐歌曲（需要 MUSIC_U 登录态，走 weapi discovery 接口）"""
    payload = {'limit': min(max(int(limit), 1), 100), 'total': True}
    params, enc_sec_key = WeapiCrypto.encrypt(payload)
    response = requests.post(
        APIConstants.DAILY_RECOMMEND_API,
        data={'params': params, 'encSecKey': enc_sec_key},
        headers=_ACCOUNT_HEADERS, cookies=cookies, timeout=30,
    )
    response.raise_for_status()
    if not response.text.strip():
        raise APIException("每日推荐响应为空，请检查 Cookie 是否有效")
    result = response.json()
    code = result.get('code')
    if code == 301:
        raise APIException("每日推荐需要网易云登录 Cookie（MUSIC_U）")
    if code != 200:
        raise APIException(f"获取每日推荐失败: {result.get('message', 'code ' + str(code))}")
    data = result.get('data') or {}
    songs = data.get('dailySongs') or result.get('dailySongs') or []
    return [_map_web_song(s) for s in songs]


def like_list_songs(cookies: Dict[str, str], uid: int, limit: int = 300) -> List[Dict[str, Any]]:
    """获取"我喜欢的音乐"歌曲列表

    likelist 直连接口已下线（实测 404），改为通过用户第一个个人歌单
    （"xx喜欢的音乐"）走歌单详情接口获取曲目。
    """
    response = requests.get(
        APIConstants.USER_PLAYLIST_API,
        params={'uid': uid, 'limit': 1, 'offset': 0},
        headers=_ACCOUNT_HEADERS, cookies=cookies, timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    if result.get('code') != 200:
        raise APIException(f"获取用户歌单失败: {result.get('message', '未知错误')}")
    playlists = result.get('playlist') or []
    if not playlists:
        raise APIException("未找到用户的个人歌单")
    liked_playlist_id = playlists[0].get('id')
    if not liked_playlist_id:
        raise APIException("用户歌单缺少 ID")
    detail = playlist_detail(liked_playlist_id, cookies)
    return detail.get('tracks', [])[:max(min(int(limit), 1000), 1)]


def qr_login() -> Optional[str]:
    """二维码登录（向后兼容）"""
    manager = QRLoginManager()
    return manager.qr_login()


# ============ Cookie 工具 ============

DEFAULT_COOKIE_FILE = "cookie.txt"


def load_cookies(path: str = DEFAULT_COOKIE_FILE) -> Dict[str, str]:
    """从 cookie.txt 直接读取并解析为 dict

    支持标准 ``NMTID=xxx; _ntes_nnid=xxx; ...`` 格式。
    文件不存在或解析失败返回空 dict（不抛异常，调用方决定如何处理）。
    """
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
    except OSError:
        return {}
    return parse_cookie_string(content)


def parse_cookie_string(cookie_string: str) -> Dict[str, str]:
    """把 ``k1=v1; k2=v2`` 格式字符串解析为 dict

    支持 ``;`` 或 ``\\n`` 作为分隔符。
    """
    cookies: Dict[str, str] = {}
    if not cookie_string:
        return cookies
    cookie_string = cookie_string.strip()
    if not cookie_string:
        return cookies
    for sep in (";", "\n"):
        if sep in cookie_string:
            pairs = cookie_string.split(sep)
            break
    else:
        pairs = [cookie_string]
    for pair in pairs:
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            cookies[key] = value
    return cookies


if __name__ == "__main__":
    # 测试代码
    print("网易云音乐API模块")
    print("支持的功能:")
    print("- 歌曲URL获取")
    print("- 歌曲详情获取")
    print("- 歌词获取")
    print("- 音乐搜索")
    print("- 歌单详情")
    print("- 专辑详情")
    print("- 二维码登录")
