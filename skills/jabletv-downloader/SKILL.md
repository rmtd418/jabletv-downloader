---
name: jabletv-downloader
description: "Download JableTV videos and extract covers using the jabletv-downloader tool — parallel m3u8 downloader, batch queue mode, and integrated cover subcommand (jable_fast.py cover)"
version: 2.4.0
author: rmtd418
license: Apache 2.0
platforms: [windows]
metadata:
  hermes:
    tags: [jabletv, downloader, m3u8, cover-extraction, playwright]
---

# JableTV Downloader

Download JableTV videos and extract covers using the [jabletv-downloader](https://github.com/rmtd418/jabletv-downloader) tool — Python-based parallel m3u8 downloader, 32-thread TS segment download, AES-128 decryption, ffmpeg lossless concat, and full integrity verification.

Repository: `https://github.com/rmtd418/jabletv-downloader`
Local clone: `D:\project\jabletv-downloader\`（**严禁**放其他项目目录下）

---

## 项目结构 | Project Structure

```
D:\project\jabletv-downloader\
├── jable_fast.py       # 主入口 — 下载 + cover 子命令
├── crawler.py          # 多线程下载引擎 + 自动重试 + 零字节检测
├── merge.py            # ffmpeg concat 清单生成
├── encode.py           # ffmpeg 封装 + tqdm 进度
├── delete.py           # 安全清理（保留最终文件）
├── config.py           # HTTP 请求头
├── requirements.txt    # Python 依赖
├── README.md           # 文档
├── CHANGELOG.md        # 更新日志
├── skills/             # 项目 SKILL.md（本文件）
│   └── jabletv-downloader/
│       └── SKILL.md
└── output/             # 下载输出
    ├── covers/         # ← 封面（cover 子命令）
    └── <番号>/         # ← 视频（下载命令）
```

---

## ⚠️ 铁律

### 必须先问才能下载

1. 用户说"下 XXX" → 先确认"要下这部吗？" → 等用户回复
2. 用户说"下" → 启动 background 下载
3. 绝不能在用户没明确同意的情况下擅自启动

### 下载必须用 background

| 模式 | 说明 |
|:-----|:------|
| ✅ `terminal(background=true, notify_on_complete=true)` | 无超时限制，跑完自动通知 |
| ❌ `terminal(timeout=600)` | 600s 超时截断，文件只合半残 |

### 所有功能必须集成进 jable_fast.py

❌ 禁止新建独立脚本（`xxx.py`）  
✅ 新功能必须作为 `jable_fast.py` 的子命令（subcommand）

### 改代码必须同步更新文档

`git add -A` 把 README.md + CHANGELOG.md 和代码一起提交。漏了会被骂。

---

## Workflow: 视频下载

```bash
# 单部
python jable_fast.py https://jable.tv/videos/<番号>/
# → output/<番号>/<番号>.mp4

# 批量排队（浏览器只开一次，一部接一部）
python jable_fast.py https://jable.tv/videos/xxx/ https://jable.tv/videos/yyy/ https://jable.tv/videos/zzz/

# 自定义输出路径
python jable_fast.py https://jable.tv/videos/xxx/ -o D:/downloads
```

### 技术流程

```
Playwright 打开页面 → 提取 m3u8 → 解析播放列表 → 32 线程下载 TS
→ 零字节检测 → 片段数量校验 → ffmpeg 合成 → ffprobe 验证 → 输出 MP4
```

1. Playwright 打开视频页，提取 m3u8 地址（Cloudflare 轮询等待，最长 30s）
2. m3u8 解析获取全部 TS 片段地址和加密密钥
3. 32 线程并行下载所有片段，失败自动重试
4. 零字节检测 + 片段数量校验
5. ffmpeg concat demuxer 无损合成
6. ffprobe 检查视频流、音频流、时长偏差 < 60s
7. 自动清理临时文件，保留最终 mp4

### 完整性验证

```bash
# 检查退出码（0=成功）
echo $?

# 检查文件
ls -lh output/<番号>/<番号>.mp4

# 检查时长
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 output/<番号>/<番号>.mp4
```

预期: ~2h35m（完整 JAV）。~67min 说明被截断。

---

## Workflow: 封面提取

封面功能**集成在 `jable_fast.py`** 中，无需下载完整视频即可提取 800×538 高清封面。

```bash
# 单部封面
python jable_fast.py cover jur-704

# 批量并发（tab-new 并行加载封面图片）
python jable_fast.py cover jur-704 jur-753 ntrh-020

# 自定义输出目录
python jable_fast.py cover -o D:/my_covers jur-704

# 支持完整网址
python jable_fast.py cover https://jable.tv/videos/jur-704/
```

**输出路径：** `output/covers/<番号>.jpg`（默认）

| 格式 | 分辨率 | 大小 |
|:-----|:-------|:-----|
| preview.jpg | **800×538** ✅ | ~140KB |
| 320x180/1.jpg | ❌ 320×180 | 模糊 ~25KB |

### 技术原理

CDN (`assets-cdn.jable.tv`) 走 Cloudflare，curl/requests 全部超时。只能用 Playwright 浏览器直连：

1. **提取数字 ID** — 浏览器导航到视频页，从 poster 背景图 URL 或 HTML 源码提取数字 ID（JUR-704 → 59444）
2. **导航到封面 URL** — `playwright-cli goto` 直接打开 CDN 封面 URL（同源 → canvas 不报 Tainted）
3. **Canvas 提取** — `canvas.toDataURL('image/jpeg', 0.9)` 获取 base64 → 解码存为 `.jpg`

**批量并发原理：**
- 串行提取每个视频的数字 ID
- `tab-new` 并行打开所有封面 URL（浏览器同时加载）
- 等待加载完成 → `tab-select` 逐个 canvas 提取保存 → `tab-close`
- 比串行 `goto` 快数倍

### 不要用的方法

| 方法 | 结果 |
|:-----|:------|
| curl/requests/Node.js https | CDN 直接 timeout，Cloudflare 拦截 |
| playwright screenshot | PNG 带黑色页面背景 |
| 320x180/1.jpg 缩略图 | 太模糊 |
| canvas 从视频页提取 | 跨域 CORS — Tainted canvases 错误 |
| fetch 从浏览器上下文 | CDN 无 Access-Control-Allow-Origin 头 |

---

## Pitfalls

| Pitfall | 说明 |
|:--------|:------|
| ❌ `cover.py` 独立脚本 | 封面功能已在 `jable_fast.py` 中作为 `cover` 子命令，**不要创建独立脚本** |
| 🕒 浏览器超时 | Playwright daemon 120s 不活动自动关，`ensure_browser()` 自动重连 |
| 🔥 下载超时被截 | Foreground 600s 超时 → 67min 半残文件。**必须用 background** |
| 🔄 浏览器断线 | 长时间下载后浏览器可能关闭，v2.3.0+ `ensure_browser()` 自动检测重连 |
| 💥 浏览器冲突 | "Browser is already in use" → `taskkill -f -im chrome.exe` + `playwright-cli close-all` |
| 🗑️ 半残文件 | 中断后必须删掉不完整 .mp4 再重跑，否则脚本以为已存在跳过 |
| 🔒 Windows 文件锁 | ffprobe/Explorer/杀软可能锁住 .mp4，`deleteMp4` 有 `PermissionError` 保护 |
| 📎 路径过长 | 多章下载注意 Windows MAX_PATH（260字符），可用 `subst` 映射短路径 |

### 浏览器超时封面提取

封面提取也有超时问题。如果在 `tab-new` 后间隔太久才 `tab-select`，浏览器可能已经关掉。尽量连续操作，不要中间做其他事。

---

## 已实现的功能

### 封面提取子命令（v2.4.0 ✅）
- 集成在 `jable_fast.py` 中，非独立脚本
- 番号简写支持：`jur-704` 自动补全 URL
- 批量并发：`tab-new` 并行加载 + canvas 提取
- 封面输出到 `output/covers/<番号>.jpg`，与视频下载分离
- 800×538 高清，canvas 同源绕过 CORS + Cloudflare

### 排队批量下载（v2.3.0 ✅）
- `nargs='+'` 多 URL 自动排队
- 浏览器只开一次，多部共用
- 单部失败不影响队列继续
- 结束输出总结：成功/失败统计

### 完整性验证管道（v2.2.0 ✅）
- `verify_segments()` — 零字节检测 + 片段数核对 + 期望时长
- `verify_mp4()` — ffprobe 检查视频/音频/时长偏差
- `deleteMp4(folderPath, keep_file=...)` 安全清理

---

## 重新克隆后需修改

| 修改项 | 路径 |
|:-------|:------|
| Playwright-CLI.js | 硬编码 `D:\DevEnv\Tools\npm-global\node_modules\@playwright\cli\playwright-cli.js` |
| Profile 路径 | `C:\Users\rmtd\playwright-profile` |

详见 `references/patching-guide.md`。
