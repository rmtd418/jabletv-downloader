# Changelog

All notable changes to this fork are documented here.

## v2.4.0 — 2026-06-04

### ✨ Features

- **🎴 封面下载器 / Cover downloader**: New standalone CLI tool `cover.py` for batch extracting JableTV video covers (800×538 HD). Supports concurrent parallel loading via `tab-new`, significantly faster than sequential extraction. Usage: `python cover.py jur-704 jur-753 ntrh-020`
- **📁 独立封面输出目录 / Dedicated cover output folder**: Covers are stored in `output/covers/<番号>.jpg`, separate from video downloads.
- **🔢 番号简写支持 / Shorthand ID support**: `cover.py` accepts both full URLs and bare番号 (e.g., `jur-704` → auto-completes to `https://jable.tv/videos/jur-704/`)

## v2.3.0 — 2026-06-02

### ✨ Features

- **排隊批量下載 / Batch queue mode**: Support multiple URLs as positional arguments. Opens browser once and processes downloads sequentially, reusing the same Playwright session. Usage: `python jable_fast.py URL1 URL2 URL3`
- **瀏覽器斷線自動重連 / Browser auto-reconnect**: Added `ensure_browser()` — checks if the Playwright browser is still alive before each video in the queue. If the browser timed out during a long download (e.g., >2 min), it automatically reopens it instead of crashing.
- **架構重構 / Code refactor**: Split browser lifecycle management into `open_browser()`, `close_browser()`, `extract_m3u8()`, and `ensure_browser()` for clean reuse between single and batch modes.

### 🐛 Bug fixes

- **ffmpegEncode NoneType crash**: `get_segment_count()` could return `None` when `concat_list.txt` was missing. Added `if total_segments is None: total_segments = 0` guard to prevent `TypeError: '<' not supported between instances of 'int' and 'NoneType'`.

## v2.2.0 — 2026-06-02

### 🐛 Bug fixes

- **Browser process leak**: Added `browser_opened` flag with precise `finally` block to close only the browser we opened. Previously, every download spawned a new Chrome process that was never cleaned up, accumulating dozens of zombie processes over multiple runs.
- **`pw()` internal timeout**: Raised the default Playwright timeout from 30s to 120s. The old 30s limit would trigger `TimeoutError` on slow networks or under Cloudflare anti-bot challenge.
- **Cloudflare hard wait → polling loop**: Replaced `time.sleep(8)` with a 30-second polling loop that checks `document.title` every second. The fixed 8s delay was either too short (under load) or wasted time (when fast), while polling adapts dynamically.
- **`urlretrieve` no timeout → `requests.get(timeout=15)`**: Changed `urllib.request.urlretrieve()` to `requests.get(timeout=15)` for m3u8 file downloads. `urlretrieve` has no timeout parameter and could hang indefinitely on stalled connections.
- **Proper browser cleanup on exit**: Restored `pw('close')` in `finally` block with accurate tracking. The previous removal of `pw('close')` caused every download session to leave a lingering Chrome process.
- **`deleteMp4()` PermissionError handling**: Wrapped file deletion in `try/except PermissionError` to handle Windows file locks (e.g., ffprobe, Explorer, antivirus holding the file). The final `.mp4` output is never deleted; only temporary segment files are cleaned.

### ✨ Enhancements

- **Browser lifecycle management**: The script now properly tracks whether it opened the browser itself vs. using an existing session, ensuring clean teardown in all code paths.

### 🔧 Maintenance

- Updated `delete.py` with safer cleanup logic that skips files still in use instead of crashing.
