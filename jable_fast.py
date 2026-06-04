"""
Jable.TV 高速下載器（32線程並行）
支援排隊模式 — 一次下多部，瀏覽器只開一次
使用 Playwright 提取 m3u8，多線程並發下載 TS 片段，ffmpeg 合成 + 完整性驗證
"""
import subprocess
import re
import os
import sys
import time
import json
import base64
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


def open_browser():
    """開啟持久瀏覽器"""
    print('🟢 啟動瀏覽器...')
    pw('close-all')
    time.sleep(1)
    result = pw('open', '--profile', PROFILE, 'about:blank')
    if result.returncode != 0:
        raise Exception(f'啟動瀏覽器失敗: {result.stderr[:200]}')
    time.sleep(2)
    return True


def close_browser():
    """關閉瀏覽器"""
    print('🔴 關閉瀏覽器...')
    pw('close')


def ensure_browser():
    """檢查瀏覽器是否存活，必要時重新開啟（下載一段時間後瀏覽器可能超時關閉）"""
    check = pw('eval', '1+1', timeout=5)
    if check.returncode != 0:
        print('⚠️  瀏覽器已斷開，重新啟動...')
        open_browser()
        return True
    return False


def extract_m3u8(video_url):
    """在已開啟的瀏覽器中導航到影片頁並提取 m3u8 地址"""
    print('🟢 載入影片頁...')
    result = pw('goto', video_url)
    if result.returncode != 0:
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
        raise Exception('頁面載入超時（Cloudflare 驗證未通過）')

    result = pw('eval',
        'document.documentElement.outerHTML.match(/https?:[^"]+m3u8[^"]*/g)'
    )

    m = re.search(r'"(https?://[^"\s]+\.m3u8)"', result.stdout)
    if not m:
        m = re.search(r"(https?://[^\s\"'<>]+\.m3u8)", result.stdout)
    if not m:
        raise Exception(f'無法提取 m3u8\n輸出: {result.stdout[:300]}')

    return m.group(1)


def get_m3u8_info(video_url):
    """兼容單部下載：開瀏覽器 → 提取 m3u8（由調用方關閉）"""
    open_browser()
    return extract_m3u8(video_url)


def verify_segments(folderPath, expected_count, m3u8_segments):
    """下載後/合成前驗證：數數量、查零字節、算期望時長"""
    mp4_files = [f for f in os.listdir(folderPath) if f.endswith('.mp4') and f != os.path.basename(folderPath) + '.mp4']
    actual = len(mp4_files)

    expected_duration = sum(s.duration for s in m3u8_segments if s.duration)

    issues = []

    if actual != expected_count:
        issues.append(f'片段數量不符: 期望 {expected_count}, 實際 {actual}')
    else:
        print(f'✅ 片段數量: {actual}/{expected_count}')

    zero_bytes = [f for f in mp4_files if os.path.getsize(os.path.join(folderPath, f)) == 0]
    if zero_bytes:
        issues.append(f'零字節片段: {len(zero_bytes)} 個 (應自動重試)')
    else:
        print('✅ 無零字節片段')

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

    filepath = os.path.abspath(filepath)

    size_mb = os.path.getsize(filepath) / 1024 / 1024
    if size_mb < 1:
        print(f'⚠️  檔案過小: {size_mb:.1f} MB')
        return False

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

    print('🔍 驗證下載完整性...')
    seg_ok = verify_segments(folderPath, expected_count, m3u8obj.segments)
    if not seg_ok:
        print('⚠️  片段驗證未通過，仍嘗試合成（可能部分丟失）')

    print('🔗 合成 mp4...')
    mergeMp4(folderPath, tsList)

    print('🎬 ffmpeg 最終處理...')
    ffmpegEncode(folderPath, dirName, 1)

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


def process_single(url, output_base):
    """下載單一影片（瀏覽器已開啟），返回 (番號, True/False, 訊息)"""
    match = re.search(r'/videos/([^/]+)', url)
    if not match:
        return (url, False, '無法解析番號')

    vid = match.group(1)
    output_dir = os.path.join(output_base, vid) if output_base else \
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', vid)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f'{vid}.mp4')

    if os.path.exists(output_path):
        print(f'⚠️ 已存在: {output_path}，刪除重下')
        try:
            os.remove(output_path)
        except PermissionError:
            return (vid, False, '檔案被佔用無法刪除')

    try:
        print(f'\n▶️ [{vid}] 提取 m3u8...')
        # 確保瀏覽器存活（下載過程中可能超時關閉）
        ensure_browser()
        m3u8url = extract_m3u8(url)
        print(f'✅ [{vid}] m3u8 獲取成功')
        download_fast(m3u8url, output_dir, vid)
        return (vid, True, '下載完成')
    except Exception as e:
        print(f'❌ [{vid}] 拋出異常: {e}')
        import traceback
        traceback.print_exc()
        return (vid, False, str(e)[:150])


def _extract_numeric_id(video_url):
    """从视频页面提取数字ID（用于拼封面URL）"""
    pw('goto', video_url)
    for i in range(30):
        time.sleep(1)
        title_r = pw('eval', 'document.title')
        if title_r.returncode != 0:
            continue
        title = title_r.stdout.strip().strip('"')
        if '请稍候' not in title and 'Please' not in title and title:
            break
    else:
        raise Exception(f'⏰ 页面加载超时: {video_url}')
    # 方法1: poster背景图
    r = pw('eval', '(function(){var p=document.querySelector(".plyr__poster");if(p&&p.style.backgroundImage)return p.style.backgroundImage;var v=document.querySelector("[poster]");if(v)return v.getAttribute("poster");return""})()')
    m = re.search(r'/(\d{5,})/preview\.jpg', r.stdout)
    if m:
        return m.group(1)
    # 方法2: HTML源码
    r = pw('eval', 'document.documentElement.outerHTML.match(/contents/videos_screenshots/(\\d{5,})/)?.[1]||""')
    m = re.search(r'"(\d{5,})"', r.stdout)
    if m:
        return m.group(1)
    raise Exception(f'❌ 无法提取数字ID: {video_url}')


def _canvas_extract_cover(output_path):
    """从当前页面用canvas提取封面图片并保存"""
    r = pw('eval', '(function(){var i=document.querySelector("img");if(!i)return"";var c=document.createElement("canvas");c.width=i.naturalWidth;c.height=i.naturalHeight;c.getContext("2d").drawImage(i,0,0);return c.toDataURL("image/jpeg",0.9)})()')
    m = re.search(r'base64,([A-Za-z0-9+/=]+)', r.stdout)
    if not m:
        return False
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(base64.b64decode(m.group(1)))
    return True


def download_covers(video_ids, output_dir=None):
    """批量下载封面 — 并行打开tab + 逐个canvas提取"""
    if not video_ids:
        print('❌ 未指定番号')
        return
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', 'covers')
    # 补全URL
    urls = []
    for vid in video_ids:
        if vid.startswith('http://') or vid.startswith('https://'):
            urls.append(vid)
        else:
            urls.append(f'https://jable.tv/videos/{vid}/')
    print(f'🎴 封面下载: {len(urls)} 部')
    print(f'📁 输出目录: {output_dir}')
    open_browser()
    # 第一步: 提取数字ID（串行）
    ids, vids = [], []
    for i, url in enumerate(urls, 1):
        m = re.search(r'/videos/([^/]+)', url)
        vid = m.group(1) if m else f'video_{i}'
        vids.append(vid)
        print(f'  [{i}/{len(urls)}] 解析 {vid}...', end='', flush=True)
        try:
            num_id = _extract_numeric_id(url)
            ids.append(num_id)
            print(f' ID={num_id} ✅')
        except Exception as e:
            ids.append(None)
            print(f' ❌ {e}')
    # 第二步: 并行打开封面tab
    items = [(i, num_id, vid) for i, (num_id, vid) in enumerate(zip(ids, vids)) if num_id]
    print(f'\n📥 并行加载封面 ({len(items)} 张)...')
    for i, num_id, vid in items:
        pw('tab-new', f'https://assets-cdn.jable.tv/contents/videos_screenshots/59000/{num_id}/preview.jpg')
    time.sleep(3)
    # 第三步: 逐个提取保存
    results = []
    print('\n🎨 提取封面...')
    for idx, (orig_i, num_id, vid) in enumerate(items):
        tab_idx = idx + 1
        pw('tab-select', str(tab_idx))
        time.sleep(0.3)
        fpath = os.path.join(output_dir, f'{vid}.jpg')
        ok = _canvas_extract_cover(fpath)
        if ok:
            size_kb = os.path.getsize(fpath) / 1024
            print(f'  ✅ [{idx+1}/{len(items)}] {vid}.jpg ({size_kb:.0f} KB)')
            results.append((vid, True, fpath))
        else:
            print(f'  ❌ [{idx+1}/{len(items)}] {vid} 提取失败')
            results.append((vid, False, None))
        pw('tab-close', str(tab_idx))
    close_browser()
    # 总结
    print(f'\n{"="*40}')
    print('📊 下载总结')
    print(f'{"="*40}')
    ok_list = [r for r in results if r[1]]
    fail_list = [r for r in results if not r[1]]
    print(f'✅ 成功: {len(ok_list)}')
    for vid, _, path in ok_list:
        print(f'   {vid} → {path}')
    if fail_list:
        print(f'❌ 失败: {len(fail_list)}')
        for vid, _, _ in fail_list:
            print(f'   {vid}')
    return results


def main():
    import argparse

    # cover 子命令
    if len(sys.argv) > 1 and sys.argv[1] == 'cover':
        parser = argparse.ArgumentParser(description='JableTV 封面提取')
        parser.add_argument('ids', nargs='+', help='番号或完整网址（支持多部）')
        parser.add_argument('-o', '--output', default=None, help='封面输出目录（默认: ./output/covers/）')
        args = parser.parse_args(sys.argv[2:])
        download_covers(args.ids, args.output)
        return

    # 原有下载逻辑
    parser = argparse.ArgumentParser(description='JableTV Downloader - 高速並行下載（支援排隊）')
    parser.add_argument('url', nargs='+', help='JableTV 影片網址（可指定多個，自動排隊下載）')
    parser.add_argument('-o', '--output', default=None, help='輸出基礎目錄（預設: ./output/）')
    args = parser.parse_args()

    if not PW_CLI_JS or not os.path.exists(PW_CLI_JS):
        print('❌ 找不到 playwright-cli.js')
        print('   請先安裝: npm install -g @playwright/cli')
        sys.exit(1)

    urls = args.url
    batch_mode = len(urls) > 1
    output_base = args.output if args.output else \
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')

    if batch_mode:
        print(f'🎬 排隊模式: 共 {len(urls)} 部影片')
        for i, u in enumerate(urls, 1):
            vid = re.search(r'/videos/([^/]+)', u)
            v = vid.group(1) if vid else u
            print(f'  [{i}/{len(urls)}] {v}')
    else:
        print(f'🎬 單部下載: {urls[0]}')

    # 啟動瀏覽器（整個批次共用）
    try:
        open_browser()
    except Exception as e:
        print(f'❌ 啟動瀏覽器失敗: {e}')
        sys.exit(1)

    results = []
    try:
        for i, url in enumerate(urls, 1):
            vid_match = re.search(r'/videos/([^/]+)', url)
            label = vid_match.group(1) if vid_match else url

            print(f'\n{"="*50}')
            if batch_mode:
                print(f'[{i}/{len(urls)}] 🎬 {label}')
            else:
                print(f'🎬 {label}')
            print(f'{"="*50}')

            vid, ok, msg = process_single(url, output_base)
            results.append((vid, ok, msg))

    finally:
        close_browser()

    # 總結
    print(f'\n{"="*50}')
    print(f'📊 下載總結')
    print(f'{"="*50}')
    success = [r for r in results if r[1]]
    failed = [r for r in results if not r[1]]
    print(f'✅ 成功: {len(success)}')
    if failed:
        print(f'❌ 失敗: {len(failed)}')
        for vid, _, msg in failed:
            print(f'  ❌ {vid}: {msg}')

    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
