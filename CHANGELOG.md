# Changelog

All notable changes to this fork are documented here.

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
