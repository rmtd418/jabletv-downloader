"""
Jable.TV 高速下載器（32線程並行）
使用 Playwright 提取 m3u8，多線程並發下載 TS 片段，ffmpeg 合成
"""
import subprocess
import re
import os
import sys
import time
import urllib.request
import m3u8 as m3u8lib
import requests
from crawler import prepareCrawl
from merge import mergeMp4
from encode import ffmpegEncode
from delete import deleteM3u8, deleteMp4
from config import headers

NODE = 'node'


def _find_playwright_cli():
    """Auto-detect playwright-cli.js path"""
    import shutil
    # Try PATH first
    pw = shutil.which('playwright-cli')
    if pw:
        return pw
    # Try common npm global locations
    for prefix in [
        os.path.expanduser('~/.npm-global'),
        os.path.expanduser('~/AppData/Roaming/npm'),
        r'C:\Program Files\nodejs',
    ]:
        candidate = os.path.join(prefix, 'node_modules', '@playwright', 'cli', 'playwright-cli.js')
        if os.path.exists(candidate):
            return candidate
    # Try locating via npm root -g
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


PW_CLI_JS = _find_playwright_cli()
PROFILE = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'PlaywrightCliProfile')


def pw(*args):
    """執行 playwright-cli 命令（繞過 .cmd，避免 ^ 被 cmd.exe 吃掉）"""
    return subprocess.run(
        [NODE, PW_CLI_JS] + list(args),
        capture_output=True, text=True, timeout=30
    )


def get_m3u8_info(video_url):
    """用 Playwright 提取 m3u8 地址和頁面原始碼"""
    # 打開瀏覽器
    pw('open', '--profile', PROFILE, 'about:blank')
    time.sleep(2)
    
    # 導航到視頻頁
    pw('goto', video_url)
    time.sleep(2)

    # 提取 m3u8 URL
    result = pw('eval',
        'document.documentElement.outerHTML.match(/https?:[^"]+m3u8[^"]*/g)'
    )

    m = re.search(r'"(https?://[^"\s]+\.m3u8)"', result.stdout)
    if not m:
        m = re.search(r'(https?://[^\s"\'<>]+\.m3u8)', result.stdout)
    if not m:
        raise Exception(f'無法提取 m3u8\n輸出: {result.stdout[:300]}')

    return m.group(1)


def download_fast(m3u8url, folderPath, dirName):
    """32線程並行下載 TS 片段 + 合成"""
    # 提取 m3u8 目錄
    m3u8urlList = m3u8url.split('/')
    m3u8urlList.pop(-1)
    downloadurl = '/'.join(m3u8urlList)

    # 下載 m3u8 文件
    m3u8file = os.path.join(folderPath, dirName + '.m3u8')
    urllib.request.urlretrieve(m3u8url, m3u8file)

    # 解析 m3u8
    m3u8obj = m3u8lib.load(m3u8file)
    m3u8uri = ''
    m3u8iv = ''
    for key in m3u8obj.keys:
        if key:
            m3u8uri = key.uri
            m3u8iv = key.iv

    # TS 片段列表
    tsList = []
    for seg in m3u8obj.segments:
        tsUrl = downloadurl + '/' + seg.uri
        tsList.append(tsUrl)
    print(f'📋 共 {len(tsList)} 個 TS 片段')

    # 加密處理
    if m3u8uri:
        m3u8keyurl = downloadurl + '/' + m3u8uri
        response = requests.get(m3u8keyurl, headers=headers, timeout=10)
        contentKey = response.content
        vt = bytes.fromhex(m3u8iv.replace("0x", ""))
        ci_params = {'key': contentKey, 'iv': vt}
    else:
        ci_params = None

    # 刪除 m3u8
    deleteM3u8(folderPath)

    # 32線程並行下載
    print('🚀 32線程並行下載中...')
    prepareCrawl(ci_params, folderPath, tsList)

    # 合成 mp4
    print('🔗 合成 mp4...')
    mergeMp4(folderPath, tsList)

    # ffmpeg 轉檔（-c copy，很快）
    print('🎬 ffmpeg 最終處理...')
    ffmpegEncode(folderPath, dirName, 1)

    # 清理
    deleteMp4(folderPath)
    print(f'✅ 完成: {folderPath}/{dirName}.mp4')


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
        os.remove(output_path)

    try:
        # 獲取 m3u8
        print('🔍 提取 m3u8...')
        m3u8url = get_m3u8_info(url)
        print(f'✅ m3u8: {m3u8url}')

        # 高速下載
        download_fast(m3u8url, output_dir, vid)

    except Exception as e:
        print(f'❌: {e}')
        import traceback
        traceback.print_exc()
    finally:
        pw('close')


if __name__ == '__main__':
    main()
