"""用户账号与收藏服务模块

基于 SQLite 的轻量账号体系，包含：
- 用户注册 / 登录验证（werkzeug pbkdf2 密码哈希）
- 登录失败阶梯封禁：连续失败达阈值后按历史封禁次数逐级加倍封禁
- 歌曲收藏的增 / 删 / 查
"""

import os
import re
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = os.path.join("data", "users.db")

# 登录失败次数达到该值即触发封禁
BAN_THRESHOLD = 5
# 阶梯封禁时长（秒）：第1次5分钟，之后 15分钟 / 30分钟 / 1小时 / 6小时 / 24小时（封顶）
BAN_STEPS = [300, 900, 1800, 3600, 21600, 86400]

USERNAME_RE = re.compile(r"^[\w\u4e00-\u9fa5]{2,20}$")
TEXT_LIMIT = 200


class AuthService:
    """账号与收藏的存储与校验逻辑"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._lock = threading.Lock()
        # 单一持久连接，所有访问经线程锁串行化
        self._db = sqlite3.connect(self.db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    username      TEXT    NOT NULL UNIQUE,
                    password_hash TEXT    NOT NULL,
                    failed_count  INTEGER NOT NULL DEFAULT 0,
                    ban_count     INTEGER NOT NULL DEFAULT 0,
                    banned_until  REAL    NOT NULL DEFAULT 0,
                    created_at    REAL    NOT NULL
                );
                CREATE TABLE IF NOT EXISTS favorites (
                    user_id   INTEGER NOT NULL,
                    song_id   TEXT    NOT NULL,
                    name      TEXT    NOT NULL DEFAULT '',
                    artist    TEXT    NOT NULL DEFAULT '',
                    album     TEXT    NOT NULL DEFAULT '',
                    pic       TEXT    NOT NULL DEFAULT '',
                    added_at  REAL    NOT NULL,
                    PRIMARY KEY (user_id, song_id)
                );
                """
            )
            self._db.commit()

    # ---------- 用户 ----------

    def create_user(self, username: str, password: str) -> Tuple[bool, str]:
        """注册新用户，返回 (是否成功, 提示信息)"""
        username = (username or "").strip()
        password = password or ""
        if not USERNAME_RE.match(username):
            return False, "用户名需为 2-20 位字母/数字/下划线/中文"
        if not (6 <= len(password) <= 64):
            return False, "密码长度需为 6-64 位"
        with self._lock:
            exists = self._db.execute(
                "SELECT 1 FROM users WHERE username = ?", (username,)
            ).fetchone()
            if exists:
                return False, "用户名已被注册"
            self._db.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, generate_password_hash(password), time.time()),
            )
            self._db.commit()
        return True, "注册成功"

    def verify_user(self, username: str, password: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """登录验证（含阶梯封禁判定），返回 (是否成功, 提示信息, 用户信息)"""
        username = (username or "").strip()
        now = time.time()
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
            # 统一错误文案，避免枚举用户名
            if row is None:
                return False, "用户名或密码错误", None

            if row["banned_until"] > now:
                remain = int(row["banned_until"] - now)
                return False, f"账号已封禁，请 {self._fmt_duration(remain)} 后重试", None

            if check_password_hash(row["password_hash"], password or ""):
                self._db.execute(
                    "UPDATE users SET failed_count = 0 WHERE id = ?", (row["id"],)
                )
                self._db.commit()
                return True, "登录成功", {"id": row["id"], "username": row["username"]}

            # 密码错误：累计失败次数，达到阈值触发阶梯封禁
            failed = row["failed_count"] + 1
            if failed >= BAN_THRESHOLD:
                step = BAN_STEPS[min(row["ban_count"], len(BAN_STEPS) - 1)]
                until = now + step
                self._db.execute(
                    "UPDATE users SET failed_count = 0, ban_count = ban_count + 1,"
                    " banned_until = ? WHERE id = ?",
                    (until, row["id"]),
                )
                self._db.commit()
                return False, f"失败次数过多，账号封禁 {self._fmt_duration(step)}", None
            self._db.execute(
                "UPDATE users SET failed_count = ? WHERE id = ?", (failed, row["id"])
            )
            self._db.commit()
            left = BAN_THRESHOLD - failed
            return False, f"用户名或密码错误，再错 {left} 次将触发封禁", None

    @staticmethod
    def _fmt_duration(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds} 秒"
        if seconds < 3600:
            return f"{seconds // 60} 分钟"
        if seconds < 86400:
            return f"{seconds // 3600} 小时"
        return f"{seconds // 86400} 天"

    # ---------- 收藏 ----------

    def add_favorite(self, user_id: int, song: Dict[str, Any]) -> Tuple[bool, str]:
        song_id = str(song.get("song_id", "")).strip()
        if not re.fullmatch(r"\d{1,20}", song_id):
            return False, "无效的歌曲 ID"
        fields = {}
        for key in ("name", "artist", "album", "pic"):
            value = str(song.get(key, "") or "").strip()
            fields[key] = value[:TEXT_LIMIT]
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO favorites"
                " (user_id, song_id, name, artist, album, pic, added_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, song_id, fields["name"], fields["artist"],
                 fields["album"], fields["pic"], time.time()),
            )
            self._db.commit()
        return True, "已收藏"

    def remove_favorite(self, user_id: int, song_id: str) -> Tuple[bool, str]:
        song_id = str(song_id).strip()
        if not re.fullmatch(r"\d{1,20}", song_id):
            return False, "无效的歌曲 ID"
        with self._lock:
            cur = self._db.execute(
                "DELETE FROM favorites WHERE user_id = ? AND song_id = ?",
                (user_id, song_id),
            )
            self._db.commit()
            if cur.rowcount == 0:
                return False, "该歌曲不在收藏中"
        return True, "已取消收藏"

    def list_favorites(self, user_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT song_id, name, artist, album, pic, added_at"
                " FROM favorites WHERE user_id = ? ORDER BY added_at DESC",
                (user_id,),
            ).fetchall()
        return [
            {
                "id": r["song_id"],
                "name": r["name"],
                "artists": r["artist"],
                "album": r["album"],
                "picUrl": r["pic"],
            }
            for r in rows
        ]

    def has_favorite(self, user_id: int, song_id: str) -> bool:
        song_id = str(song_id).strip()
        if not re.fullmatch(r"\d{1,20}", song_id):
            return False
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM favorites WHERE user_id = ? AND song_id = ?",
                (user_id, song_id),
            ).fetchone()
        return row is not None


if __name__ == "__main__":
    # 简单自检
    svc = AuthService(":memory:")
    print(svc.create_user("tester", "abc12345"))
    print(svc.verify_user("tester", "wrong"))
    print(svc.verify_user("tester", "abc12345"))
    print(svc.add_favorite(1, {"song_id": "123", "name": "测试"}))
    print(svc.list_favorites(1))
