# Changelog

All notable changes to this fork are documented here.

## v2.1.0 — 2026-06-02

Forked from [hcjohn463/JableTVDownload](https://github.com/hcjohn463/JableTVDownload) v2.0 with the following changes:

### 🐛 Bug fixes

- **File write mode**: Changed `open()` from `ab` (append) to `wb` (overwrite). Previously, partial or corrupted segment files from interrupted runs would be appended to instead of replaced, causing corrupted output.
- **AES IV decoding**: Fixed IV hex parsing from `m3u8iv.replace("0x", "")[:16].encode()` to `bytes.fromhex(...)`. The old code produced 8 ASCII bytes instead of 16 decoded hex bytes, which would decrypt encrypted streams with the wrong IV.
- **Stale segment handling**: Removed the "skip existing files" optimization in `_run_crawl()`. Old segment files left behind by a killed process were treated as valid and skipped during re-download, leading to corrupted merges. Now cleans all stale `.mp4` segments before starting fresh.
- **Output file collision**: Changed early `return` when output `.mp4` exists to `os.remove()` + proceed, so a corrupted or partial output file doesn't block re-download.

### ✨ Enhancements

- **Auto-detect playwright-cli**: No more hardcoded paths. Searches `PATH`, common npm global locations, and `require.resolve()` automatically.
- **`--output` / `-o` flag**: Custom output directory via CLI argument instead of always using CWD.
- **Argument parser**: Replaced bare `sys.argv` with proper `argparse` for better UX and `--help` support.
- **Cleaner dependencies**: Removed unused packages (beautifulsoup4, selenium, soupsieve, etc.). Down to 4 runtime deps.
- **Updated `.gitignore`**: Removed chromedriver references, added `concat_list.txt` and `.playwright-cli/`.

### 🔧 Maintenance

- Stripped deprecated Docker, Kubernetes, ChromeDriver, and Selenium code.
- Removed unused modules: `main.py`, `args.py`, `download.py`, `jable_dl.py`, `cover.py`, `movies.py`, `getchromedriver.py`.
- Rewrote README with English docs, comparison table, and flow diagram.
