# 云音盒子（Music_url）

基于 Flask 的网易云音乐工具，提供两种使用模式：**音乐播放器**（在线听歌）与**音乐下载器**（解析下载）。支持搜索、单曲/歌单/专辑解析、多音质下载（自动写入歌词与封面元数据）、全屏播放界面、网易云 Cookie 登录与账号收藏。

> 由 [Vevolat](https://github.com/Vevolat) 基于 [Suxiaoqinx/Netease_url](https://github.com/Suxiaoqinx/Netease_url) 二次开发，新增元数据写入、歌名清洗、缓存清理、播放器与账号体系。MIT 许可证。

## 功能

- **双模式**：顶栏一键切换"听音乐 / 下音乐"，页签与操作按钮按模式自动显隐，选择持久保存
- **解析与下载**：歌曲/歌单/专辑解析，支持 ID、链接与 163cn.tv 短链；下载自动写入标题、歌手、专辑、歌词（含翻译）、封面
- **音质**：standard / exhigh / lossless / hires / jyeffect / sky / jymaster / dolby（高音质需黑胶 Cookie）
- **播放器**：底部常驻播放条（含实时歌词行，点封面进全屏）、全屏播放界面双视图（中央封面控制 <-> 右下角「歌词」按钮平滑切换至左控制右沉浸歌词，歌词自动滚动、点击跳播、手动滚动暂停跟随）、播放器页（大封面 / 收藏红心 / 大字平滑歌词 + 队列）、列表循环 / 单曲循环 / 随机播放、键盘快捷键（空格 / 方向键 / L / Esc）
- **网易云 Cookie 绑定**：先登录站点账号，再网页粘贴 Cookie（完整串或仅 MUSIC_U 值）绑定到当前账号，按账号隔离存储（刷新/重启不丢失，互不可见），支持退出；绑定后展示头像昵称、每日推荐、我喜欢的音乐（小卡片，点击即播）
- **站点账号**：注册 / 登录 / 歌曲收藏；登录失败连续 5 次触发阶梯封禁（5 分钟起步，逐次加倍，上限 24 小时）
- **界面**：iOS 液态玻璃（Liquid Glass）风格——高透玻璃卡片、背景折射模糊、顶缘高光描边、胶囊控件、悬浮玻璃坞站播放条、页签滑动玻璃指示器、漂浮彩色光斑；响应式适配移动端，封面占位兜底（无封面/加载失败不显示破图），无第三方 CDN 依赖，离线可用
- **加载体验**：全站按钮 loading 态防重复提交、解析等待动画、列表骨架屏

## 快速开始

```bash
git clone https://github.com/Vevolat/Music_url.git
cd Music_url
pip install -r requirements.txt
python main.py
# 访问 http://localhost:5000，点击右上角"网易云登录"粘贴 Cookie（可选，用于高音质与每日推荐）
```

Docker：

```bash
docker-compose up -d
```

## API

统一响应：`{"status": 200, "success": true, "message": "...", "data": {...}}`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查与 Cookie 状态 |
| GET/POST | `/song` | 歌曲信息（参数 `id`/`url`、`level`、`type`=url/name/lyric/json） |
| GET/POST | `/search` | 搜索（`keyword`、`limit`） |
| GET/POST | `/playlist` | 歌单详情 |
| GET/POST | `/album` | 专辑详情 |
| GET/POST | `/download` | 下载（`id`、`quality`、`format`=file/json） |
| POST | `/auth/register` | 注册（`username`、`password`） |
| POST | `/auth/login` | 登录，失败阶梯封禁 |
| POST | `/auth/logout` | 退出登录 |
| GET | `/auth/me` | 登录状态 |
| GET/POST | `/favorites` | 收藏列表 / 添加收藏（需登录） |
| DELETE | `/favorites/<song_id>` | 移除收藏 |
| POST | `/netease/login` | 网易云 Cookie 登录（`cookie`：完整串或 MUSIC_U 值） |
| POST | `/netease/logout` | 退出网易云登录 |
| GET | `/netease/profile` | 网易云账号资料（头像/昵称，需 MUSIC_U） |
| GET | `/netease/daily` | 每日推荐歌曲（需 MUSIC_U） |
| GET | `/netease/likes` | 我喜欢的音乐（需 MUSIC_U） |
| GET | `/api/info` | API 信息 |

## 安全机制

- 强制安全响应头：CSP、X-Frame-Options、nosniff、Referrer-Policy
- 所有 ID 参数仅接受纯数字，关键词限长，请求体上限 64KB
- 接口限流：搜索 30/分、解析 60/分、下载 10/分、登录 10/5分钟、注册 5/小时（按 IP）
- 密码 pbkdf2 哈希存储，Session Cookie HttpOnly + SameSite
- 登录失败阶梯封禁：5 次 / 15 分钟 / 30 分钟 / 1 小时 / 6 小时 / 24 小时

## 项目结构

```
Music_url/
├── main.py              # Flask 入口（路由、限流、安全头、账号接口）
├── auth_service.py      # 账号与收藏（SQLite，封禁阶梯）
├── music_api.py         # 网易云 API（加密、请求、Cookie）
├── music_downloader.py  # 下载与元数据写入、缓存清理
├── templates/index.html # 页面结构
├── static/              # 样式 / 脚本 / 图标
├── tools/gen_favicon.py # 图标生成脚本
├── data/                # 运行时数据（用户库、网易云 Cookie、密钥）
```

## 注意事项

- 网易云 Cookie 按站点账号隔离存储于 `data/cookie.json`（`{uid: cookie}` 结构），游客与其他账号无法使用你的登录态；旧版全局 `cookie.txt` / flat 格式 `cookie.json` 启动时自动迁移绑定至最早注册的站点账号；未登录站点账号时仅开放部分接口能力
- `downloads` 缓存超过 200MB 自动按时间从旧到新清理，上限可通过 `APIConfig.cache_max_size` 调整
- ffmpeg 可选，存在时优先用于元数据写入
- 仅供学习研究，请勿用于商业用途

## 反馈

[Issues](https://github.com/Vevolat/Music_url/issues) · [使用文档](./使用文档.md)
