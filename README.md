# 网易云音乐无损解析

<div align="center">

![GitHub stars](https://img.shields.io/github/stars/Vevolat/Music_url?style=flat-square)
![GitHub forks](https://img.shields.io/github/forks/Vevolat/Music_url?style=flat-square)
![GitHub issues](https://img.shields.io/github/issues/Vevolat/Music_url?style=flat-square)
![GitHub license](https://img.shields.io/github/license/Vevolat/Music_url?style=flat-square)

**功能强大的网易云音乐解析工具**

支持歌曲搜索 | 单曲解析 | 歌单解析 | 专辑解析 | 音乐下载

[在线体验](https://wyapi.toubiec.cn) • [使用文档](./使用文档.md) • [问题反馈](https://github.com/Vevolat/Music_url/issues)

</div>

---

> **⚠️ 重要声明**  
> 本项目采用 MIT 许可证开源。根据 MIT 许可证的条款，任何个人或组织均可自由使用、修改和分发本项目的源代码，包括用于商业项目。

> **🔧 二次开发说明**  
> 本项目由 [Vevolat](https://github.com/Vevolat) 基于 [Suxiaoqinx/Netease_url](https://github.com/Suxiaoqinx/Netease_url)（原项目开发者）二次开发而来，在原项目基础上新增了下载文件元数据（歌词/封面/歌手/专辑）写入、歌名自动清洗、缓存自动清理等功能。原项目版权归原作者所有，感谢原作者的贡献。

**注意**：本项目旨在为开源社区做贡献，我们鼓励用户：
- 在遵守开源精神的前提下使用和分享代码
- 如有改进，欢迎贡献回本项目
- 在商业使用中，请考虑对开源项目的支持和回馈

虽然 MIT 许可证允许商业使用，但我们希望用户能尊重开源精神，合理使用本项目。

## ✨ 功能特性

### 🎵 核心功能
- **🔍 歌曲搜索**：支持关键词搜索网易云音乐库中的歌曲
- **🎧 单曲解析**：解析单首歌曲的详细信息和下载链接
- **📋 歌单解析**：批量解析歌单中的所有歌曲信息
- **💿 专辑解析**：批量解析专辑中的所有歌曲信息
- **⬇️ 音乐下载**：支持多种音质的音乐文件下载

### 📝 下载文件元数据（自动写入）
下载的音乐文件会自动写入完整元数据（无需手动操作）：
- **标题**：歌曲名称
- **歌手**：艺术家
- **专辑**：所属专辑
- **歌词**：原文 + 翻译歌词（按时间戳逐行合并，LRC 格式）
- **封面**：专辑封面图

> 依赖 [mutagen](https://pypi.org/project/mutagen/)（纯 Python，自动安装）；若系统装有 ffmpeg 则优先使用 ffmpeg 写入，否则自动回退 mutagen，无需额外配置。

### 🧹 歌名自动清洗
网易云部分歌曲名自带多余修饰，下载时会自动移除：
- `(有字幕)` / `（有字幕）` / `[有字幕]` 等修饰后缀
- `#` 与 `＃` 符号（歌名、歌手、专辑中的均会移除）

### 🎼 音质支持
- `standard`：标准音质 (128kbps)
- `exhigh`：极高音质 (320kbps)
- `lossless`：无损音质 (FLAC)
- `hires`：Hi-Res音质 (24bit/96kHz)
- `jyeffect`：高清环绕声
- `sky`：沉浸环绕声
- `jymaster`：超清母带

### 🌐 使用方式
- **Web界面**：直观友好的网页操作界面
- **RESTful API**：完整的API接口支持
- **批量处理**：支持歌单和专辑的批量解析
- **多格式支持**：支持ID和链接多种输入格式

### 📁 项目结构

```
Music_url/
├── main.py              # Flask 服务主入口（API 路由、配置）
├── music_api.py         # 网易云 API 核心模块（加密、请求、Cookie 工具）
├── music_downloader.py  # 音乐下载模块（下载、元数据写入、缓存清理）
├── qr_login.py          # 二维码登录工具
├── cookie.py            # Cookie 提取/格式化工具
├── templates/
│   └── index.html       # Web 页面（纯结构）
├── static/
│   ├── css/style.css    # 页面样式
│   └── js/app.js        # 页面脚本
├── downloads/           # 下载文件缓存目录（自动清理）
├── requirements.txt     # Python 依赖
├── Dockerfile           # Docker 构建文件
├── docker-compose.yml   # Docker Compose 配置
└── README.md            # 项目说明
```

---

## 🚀 快速开始

### 环境要求
- Python 3.7+
- 网易云音乐黑胶会员账号
- mutagen（`pip install -r requirements.txt` 自动安装）
- ffmpeg（可选，安装后优先用于元数据写入，不装则自动使用 mutagen）

### 安装步骤

#### 1. 克隆项目
```bash
git clone https://github.com/Vevolat/Music_url.git
cd Music_url
```

#### 2. 安装依赖
```bash
pip install -r requirements.txt
```

#### 3. 配置Cookie
在 `cookie.txt` 文件中填入黑胶会员账号的Cookie：

> 💡 **获取Cookie方法**：登录网易云音乐网页版 → F12开发者工具 → Network标签页 → 复制任意请求的Cookie值

#### 4. 启动服务
```bash
python main.py
```

#### 5. 访问界面
打开浏览器访问：`http://localhost:5000`

### 🐳 Docker部署

```bash
# 使用Docker Compose
docker-compose up -d

# 或使用Docker
docker build -t netease-music-api .
docker run -d -p 5000:5000 netease-music-api
```

---

## 📖 使用指南

### Web界面使用

> 💡 顶部导航 Tab 用于切换功能（歌曲搜索 / 单曲解析 / 歌单解析 / 专辑解析 / 音乐下载），输入框支持按回车快速提交。

#### 🔍 歌曲搜索
1. 点击顶部 **歌曲搜索** Tab
2. 输入关键词（歌曲名、歌手名等）
3. 点击**搜索**按钮（或按回车）
4. 在搜索结果中点击**解析**或**下载**按钮

#### 🎧 单曲解析
1. 点击顶部 **单曲解析** Tab
2. 输入歌曲ID或网易云音乐链接
   - 支持格式：`1234567890` 或 `https://music.163.com/song?id=1234567890`
3. 点击**解析**按钮查看歌曲信息

#### 📋 歌单解析
1. 点击顶部 **歌单解析** Tab
2. 输入歌单ID或网易云音乐歌单链接
   - 支持格式：`1234567890` 或 `https://music.163.com/playlist?id=1234567890`
3. 点击**解析**按钮查看歌单中所有歌曲
4. 点击单首歌曲的**解析**或**下载**按钮

#### 💿 专辑解析
1. 点击顶部 **专辑解析** Tab
2. 输入专辑ID或网易云音乐专辑链接
   - 支持格式：`1234567890` 或 `https://music.163.com/album?id=1234567890`
3. 点击**解析**按钮查看专辑中所有歌曲
4. 点击单首歌曲的**解析**或**下载**按钮

#### ⬇️ 音乐下载
1. 点击顶部 **音乐下载** Tab
2. 输入歌曲ID或链接
3. 选择音质（标准/极高/无损/Hi-Res等）
4. 点击**下载**按钮

> **下载文件说明**：
> - 文件名格式：`歌曲名.扩展名`（如 `稻香.flac`），自动移除 `(有字幕)`、`#` 等多余内容
> - 文件自动写入完整元数据：标题、歌手、专辑、歌词（含翻译）、封面
> - 如需在文件名中标识音质（如 `稻香 [lossless].flac`），可将 `main.py` 中 `APIConfig.filename_include_quality` 改为 `True`
> - **缓存自动清理**：`downloads` 目录总大小超过 200MB 时，自动按修改时间从旧到新删除文件（正在下载的文件会跳过，不会被误删）。可通过 `main.py` 中 `APIConfig.cache_max_size` 调整上限

### 支持的链接格式

```
# 歌曲链接
https://music.163.com/song?id=1234567890
https://music.163.com/#/song?id=1234567890

# 歌单链接
https://music.163.com/playlist?id=1234567890
https://music.163.com/#/playlist?id=1234567890

# 专辑链接
https://music.163.com/album?id=1234567890
https://music.163.com/#/album?id=1234567890

# 直接使用ID
1234567890
```

## 🔌 API接口文档

### 基础信息
- **Base URL**: `http://localhost:5000`
- **请求方式**: GET / POST
- **响应格式**: JSON

### 接口列表

#### 1. 健康检查
```http
GET /health
```
**响应示例**:
```json
{
  "status": "ok",
  "message": "Service is running"
}
```

#### 2. 歌曲搜索
```http
POST /search
Content-Type: application/json

{
  "keywords": "周杰伦 稻香",
  "limit": 10
}
```
**响应示例**:
```json
{
  "code": 200,
  "result": {
    "songs": [
      {
        "id": 185668,
        "name": "稻香",
        "artists": ["周杰伦"],
        "album": "魔杰座",
        "duration": 223000
      }
    ]
  }
}
```

#### 3. 单曲解析
```http
POST /song
Content-Type: application/json

{
  "id": "185668"
}
```

#### 4. 歌单解析
```http
POST /playlist
Content-Type: application/json

{
  "id": "123456789"
}
```

#### 5. 专辑解析
```http
POST /album
Content-Type: application/json

{
  "id": "123456789"
}
```

#### 6. 音乐下载
```http
POST /download
Content-Type: application/json

{
  "id": "185668",
  "quality": "lossless"
}
```
**响应**: 直接返回音频文件流

---

## 音质参数说明（仅限单曲解析）

- `standard`：标准音质
- `exhigh`：极高音质
- `lossless`：无损音质
- `hires`：Hi-Res音质
- `jyeffect`：高清环绕声
- `sky`：沉浸环绕声
- `jymaster`：超清母带

> 黑胶VIP音质：standard, exhigh, lossless, hires, jyeffect  
> 黑胶SVIP音质：sky, jymaster

---

## Docker 一键部署

1. **修改参数**

   - 如需修改端口，请编辑 `.env` 或 `docker-compose.yml` 文件中的 `ports` 配置，例如：

     ```yaml
     ports:
       - "8080:5000"
     ```

2. **启动服务**

   ```bash
   docker-compose up -d
   ```

---

## 在线演示

[在线解析](https://wyapi.toubiec.cn/)

---

## 注意事项

- 必须使用黑胶会员账号的 Cookie 才能解析高音质资源。
- Cookie 格式请严格按照 `cookie.txt` 示例填写。
- 下载文件自动写入元数据依赖 `mutagen` 库（已加入 `requirements.txt`），请确保安装。
- 若下载日志提示"元数据写入失败"，通常是因为 mutagen 未安装或文件格式异常；安装 ffmpeg 可提供更健壮的封面嵌入（尤其杜比全景声 MP4）。

---

## 致谢

- [Ravizhan](https://github.com/ravizhan)

---

## 反馈与交流

- 在 Github [Issues](https://github.com/Vevolat/Music_url/issues) 提交反馈
- 或访问 [我的博客](https://www.toubiec.cn)

---

欢迎 Star、Fork 和 PR！



