"""
Jable.TV 高速下載器（32線程並行）
使用 Playwright 提取 m3u8，多線程並發下載 TS 片段，ffmpeg 合成
"""
import subprocess
import re
import os
import sys
import time
import json
import requests
import m3u8 as m3u8lib
from crawler import prepareCrawl
from merge import mergeMp4
from encode import ffmpegEncode
from delete import deleteM3u8, deleteMp4
from config import headers

NODE = 'node'
PW_TIMEOUT = 120


def _find_playwright_cli():
    import shutil
    pw = shutil.which('playwright-cli')
    if pw:
        return pw
    for prefix in [
        os.path.expanduser('~/.npm-global'),
        os.path.expanduser('~/AppData/Roaming/npm'),
        r'C:\Program Files\nodejs',
    ]:
        candidate = os.path.join(prefix, 'node_modules', '@playwright', 'cli', 'playwright-cli.js')
        if os.path.exists(candidate):
            return candidate
    try:
        result = subprocess.run(
            ['node', '-e', 'console.log(require.resolve("@playwright/cli/playwright-cli.js"))'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            path = result.stdout.strip()
            if os.path.exists(path):
                return path
    except Exception:
        pass
    return None


PW_CLI_JS = r'D:\DevEnv\Tools\npm-global\node_modules\@playwright\cli\playwright-cli.js'
if not os.path.exists(PW_CLI_JS):
    PW_CLI_JS = _find_playwright_cli()
PROFILE = os.path.join(os.path.expanduser('~'), 'playwright-profile')


def pw(*args, timeout=PW_TIMEOUT):
    return subprocess.run(
        [NODE, PW_CLI_JS] + list(args),
        capture_output=True, text=True, timeout=timeout
    )


def get_m3u8_info(video_url):
    """用 Playwright 提取 m3u8 地址"""
    print('🟢 啟動瀏覽器...')
    pw('close-all')
    time.sleep(1)
    result = pw('open', '--profile', PROFILE, 'about:blank')
    if result.returncode != 0:
        raise Exception(f'啟動瀏覽器失敗: {result.stderr[:200]}')
    time.sleep(2)

    print('🟢 載入影片頁...')
    result = pw('goto', video_url)
    if result.returncode != 0:
        pw('close')
        raise Exception(f'導航失敗: {result.stderr[:200]}')

    for i in range(30):
        time.sleep(1)
        title_result = pw('eval', 'document.title')
        if title_result.returncode != 0:
            continue
        title = title_result.stdout.strip().strip('"')
        if '请稍候' not in title and 'Please' not in title and title:
            print(f'✅ 頁面載入完成: {title[:60]}')
            break
    else:
        pw('close')
        raise Exception('頁面載入超時（Cloudflare 驗證未通過）')

    result = pw('eval',
        'document.documentElement.outerHTML.match(/https?:[^"]+m3u8[^"]*/g)'
    )

    m = re.search(r'"(https?://[^"\s]+\.m3u8)"', result.stdout)
    if not m:
        m = re.search(r'(https?://[^\s"\'<>]+\.m3u8)', result.stdout)
    if not m:
        pw('close')
        raise Exception(f'無法提取 m3u8\n輸出: {result.stdout[:300]}')

    return m.group(1)


def verify_segments(folderPath, expected_count, m3u8_segments):
    """下載後/合成前驗證：數數量、查零字節、算期望時長"""
    mp4_files = [f for f in os.listdir(folderPath) if f.endswith('.mp4') and f != os.path.basename(folderPath) + '.mp4']
    actual = len(mp4_files)

    expected_duration = sum(s.duration for s in m3u8_segments if s.duration)

    issues = []

    # 1. 檢查數量
    if actual != expected_count:
        issues.append(f'片段數量不符: 期望 {expected_count}, 實際 {actual}')
    else:
        print(f'✅ 片段數量: {actual}/{expected_count}')

    # 2. 檢查零字節
    zero_bytes = [f for f in mp4_files if os.path.getsize(os.path.join(folderPath, f)) == 0]
    if zero_bytes:
        issues.append(f'零字節片段: {len(zero_bytes)} 個 (應自動重試)')
    else:
        print('✅ 無零字節片段')

    # 3. 輸出期望時長
    if expected_duration:
        exp_m, exp_s = divmod(int(expected_duration), 60)
        exp_h, exp_m = divmod(exp_m, 60)
        dur_str = f'{exp_h}h{exp_m:02d}m{exp_s:02d}s' if exp_h else f'{exp_m}m{exp_s:02d}s'
        print(f'📐 期望時長: {dur_str} ({expected_count} 片段 × ~{m3u8_segments[0].duration:.2f}s)')

    if issues:
        for issue in issues:
            print(f'⚠️  {issue}')
        return False
    return True


def verify_mp4(filepath, expected_duration=None):
    """合成後用 ffprobe 驗證 MP4 完整性"""
    if not os.path.exists(filepath):
        print(f'❌ 檔案不存在: {filepath}')
        return False

    # 轉為 Windows 絕對路徑（ffprobe 需要）
    filepath = os.path.abspath(filepath)

    # 檢查檔案大小
    size_mb = os.path.getsize(filepath) / 1024 / 1024
    if size_mb < 1:
        print(f'⚠️  檔案過小: {size_mb:.1f} MB')
        return False

    # ffprobe 檢查
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_entries', 'format=duration,size',
             '-show_entries', 'stream=codec_type,codec_name',
             filepath],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            print(f'❌ ffprobe 失敗')
            return False

        info = json.loads(result.stdout)
        fmt = info.get('format', {})
        streams = info.get('streams', [])

        actual_duration = float(fmt.get('duration', 0))
        has_video = any(s.get('codec_type') == 'video' for s in streams)
        has_audio = any(s.get('codec_type') == 'audio' for s in streams)

        dur_m, dur_s = divmod(int(actual_duration), 60)
        dur_h, dur_m = divmod(dur_m, 60)
        dur_str = f'{dur_h}h{dur_m:02d}m{dur_s:02d}s' if dur_h else f'{dur_m}m{dur_s:02d}s'

        print(f'✅ 影片大小: {size_mb:.0f} MB')
        print(f'✅ 影片時長: {dur_str}')
        print(f'✅ 視頻流: {"有" if has_video else "無"}')
        print(f'✅ 音頻流: {"有" if has_audio else "無"}')

        if not has_video:
            print('❌ 缺少視頻流')
            return False

        # 對比期望時長（允許 60s 誤差，HLS 片段時長波動正常）
        if expected_duration and abs(actual_duration - expected_duration) > 60:
            print(f'⚠️  時長偏差較大: 期望 {expected_duration:.0f}s, 實際 {actual_duration:.0f}s')

        return True

    except subprocess.TimeoutExpired:
        print('❌ ffprobe 超時')
        return False
    except Exception as e:
        print(f'❌ ffprobe 異常: {e}')
        return False


def download_fast(m3u8url, folderPath, dirName):
    """32線程並行下載 TS 片段 + 合成 + 驗證"""
    m3u8urlList = m3u8url.split('/')
    m3u8urlList.pop(-1)
    downloadurl = '/'.join(m3u8urlList)

    m3u8file = os.path.join(folderPath, dirName + '.m3u8')
    resp = requests.get(m3u8url, headers=headers, timeout=15)
    resp.raise_for_status()
    with open(m3u8file, 'wb') as f:
        f.write(resp.content)

    m3u8obj = m3u8lib.load(m3u8file)
    m3u8uri = ''
    m3u8iv = ''
    for key in m3u8obj.keys:
        if key:
            m3u8uri = key.uri
            m3u8iv = key.iv

    tsList = []
    for seg in m3u8obj.segments:
        tsUrl = downloadurl + '/' + seg.uri
        tsList.append(tsUrl)
    expected_count = len(tsList)
    print(f'📋 共 {expected_count} 個 TS 片段')

    if m3u8uri:
        m3u8keyurl = downloadurl + '/' + m3u8uri
        response = requests.get(m3u8keyurl, headers=headers, timeout=10)
        contentKey = response.content
        vt = bytes.fromhex(m3u8iv.replace("0x", ""))
        ci_params = {'key': contentKey, 'iv': vt}
    else:
        ci_params = None

    deleteM3u8(folderPath)

    print('🚀 32線程並行下載中...')
    prepareCrawl(ci_params, folderPath, tsList)

    # === 驗證 1: 下載後檢查 ===
    print('🔍 驗證下載完整性...')
    seg_ok = verify_segments(folderPath, expected_count, m3u8obj.segments)
    if not seg_ok:
        print('⚠️  片段驗證未通過，仍嘗試合成（可能部分丟失）')

    # 合成 mp4
    print('🔗 合成 mp4...')
    mergeMp4(folderPath, tsList)

    print('🎬 ffmpeg 最終處理...')
    ffmpegEncode(folderPath, dirName, 1)

    # === 驗證 2: 合成後檢查 ===
    output_path = os.path.join(folderPath, f'{dirName}.mp4')
    print('🔍 驗證最終 MP4...')
    expected_dur = sum(s.duration for s in m3u8obj.segments if s.duration)
    mp4_ok = verify_mp4(output_path, expected_duration=expected_dur)

    if not mp4_ok:
        print('⚠️  MP4 驗證未通過，檔案可能不完整')
    else:
        print('✅ 完整性驗證全部通過')

    try:
        deleteMp4(folderPath, keep_file=f'{dirName}.mp4')
    except Exception:
        pass
    print(f'✅ 完成: {output_path}')


def main():
    import argparse
    parser = argparse.ArgumentParser(description='JableTV Downloader - 高速並行下載')
    parser.add_argument('url', help='JableTV 影片網址 (https://jable.tv/videos/xxx/)')
    parser.add_argument('-o', '--output', default=None, help='輸出目錄 (預設: ./output/番號/)')
    args = parser.parse_args()

    if not PW_CLI_JS or not os.path.exists(PW_CLI_JS):
        print('❌ 找不到 playwright-cli.js')
        print('   請先安裝: npm install -g @playwright/cli')
        sys.exit(1)

    url = args.url
    print(f'🎬 開始: {url}')

    match = re.search(r'/videos/([^/]+)', url)
    if not match:
        print('❌ 無法解析番號')
        sys.exit(1)
    vid = match.group(1)

    output_dir = args.output if args.output else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', vid)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f'{vid}.mp4')

    if os.path.exists(output_path):
        print(f'⚠️ 已存在: {output_path}，刪除重下')
        try:
            os.remove(output_path)
        except PermissionError:
            print(f'⚠️ 無法刪除舊檔案（可能被佔用），跳過')

    browser_opened = False
    try:
        print('🔍 提取 m3u8...')
        m3u8url = get_m3u8_info(url)
        browser_opened = True
        print(f'✅ m3u8: {m3u8url}')

        download_fast(m3u8url, output_dir, vid)

    except Exception as e:
        print(f'❌: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if browser_opened:
            print('🔴 關閉瀏覽器...')
            pw('close')
        else:
            pw('close-all')


if __name__ == '__main__':
    main()
