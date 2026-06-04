"""JableTV 封面下载器 — 独立 CLI，支持批量并发提取封面

用法:
  python cover.py https://jable.tv/videos/jur-704/
  python cover.py https://jable.tv/videos/jur-704/ https://jable.tv/videos/jur-753/ https://jable.tv/videos/ntrh-020/
  python cover.py -o D:/my_covers https://jable.tv/videos/jur-704/
"""

import os
import sys
import time
import re
import base64
import argparse
from jable_fast import pw, open_browser, close_browser, ensure_browser

DEFAULT_OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', 'covers')


def extract_numeric_id(video_url):
    """从视频页面提取数字ID（用于拼封面 URL）"""
    pw('goto', video_url)

    # 等 Cloudflare 验证通过
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

    # 方法1: 从 poster 背景图 URL 提取
    r = pw('eval', '(function(){var p=document.querySelector(".plyr__poster");if(p&&p.style.backgroundImage)return p.style.backgroundImage;var v=document.querySelector("[poster]");if(v)return v.getAttribute("poster");return""})()')
    m = re.search(r'/(\d{5,})/preview\.jpg', r.stdout)
    if m:
        return m.group(1)

    # 方法2: 从页面 HTML 源码搜
    r = pw('eval', 'document.documentElement.outerHTML.match(/contents/videos_screenshots/(\\d{5,})/)?.[1]||""')
    m = re.search(r'"(\d{5,})"', r.stdout)
    if m:
        return m.group(1)

    raise Exception(f'❌ 无法提取数字ID: {video_url}')


def download_one_cover(num_id, vid, output_dir):
    """导航到封面URL，用canvas提取并保存"""
    url = f'https://assets-cdn.jable.tv/contents/videos_screenshots/59000/{num_id}/preview.jpg'

    r_goto = pw('goto', url)
    if r_goto.returncode != 0:
        return None

    time.sleep(1.5)  # 等图片渲染

    r = pw('eval', '(function(){var i=document.querySelector("img");if(!i)return"";var c=document.createElement("canvas");c.width=i.naturalWidth;c.height=i.naturalHeight;c.getContext("2d").drawImage(i,0,0);return c.toDataURL("image/jpeg",0.9)})()')

    m = re.search(r'base64,([A-Za-z0-9+/=]+)', r.stdout)
    if not m:
        return None

    os.makedirs(output_dir, exist_ok=True)
    fpath = os.path.join(output_dir, f'{vid}.jpg')
    with open(fpath, 'wb') as f:
        f.write(base64.b64decode(m.group(1)))
    return fpath


def download_covers_concurrent(video_urls, output_dir):
    """批量并发下载封面：
    1. 串行提取每个视频的数字ID
    2. tab-new 并行打开所有封面URL
    3. 逐个 tab-select + canvas 提取保存
    """
    if not video_urls:
        print('❌ 未指定影片 URL')
        return

    print(f'🎴 封面下载: {len(video_urls)} 部')
    print(f'📁 输出目录: {output_dir}')

    open_browser()

    # 第一步: 提取所有数字ID（串行）
    ids = []
    vids = []
    for i, url in enumerate(video_urls, 1):
        m = re.search(r'/videos/([^/]+)', url)
        vid = m.group(1) if m else f'video_{i}'
        vids.append(vid)

        print(f'  [{i}/{len(video_urls)}] 解析 {vid}...', end='', flush=True)
        try:
            num_id = extract_numeric_id(url)
            ids.append(num_id)
            print(f' ID={num_id} ✅')
        except Exception as e:
            ids.append(None)
            print(f' ❌ {e}')

    # 第二步: 并行打开所有封面（tab-new 同时加载）
    print(f'\n📥 并行加载封面 ({len(ids)} 张)...')
    success_ids = [(i, num_id, vid) for i, (num_id, vid) in enumerate(zip(ids, vids)) if num_id]
    
    for i, num_id, vid in success_ids:
        cover_url = f'https://assets-cdn.jable.tv/contents/videos_screenshots/59000/{num_id}/preview.jpg'
        pw('tab-new', cover_url)
    
    # 等所有封面加载
    time.sleep(3)

    # 第三步: 逐个提取保存
    results = []
    print(f'\n🎨 提取封面...')
    for idx, (i, num_id, vid) in enumerate(success_ids):
        tab_idx = idx + 1  # tab0 是首页
        pw('tab-select', str(tab_idx))
        time.sleep(0.3)

        r = pw('eval', '(function(){var i=document.querySelector("img");if(!i)return"";var c=document.createElement("canvas");c.width=i.naturalWidth;c.height=i.naturalHeight;c.getContext("2d").drawImage(i,0,0);return c.toDataURL("image/jpeg",0.9)})()')

        m = re.search(r'base64,([A-Za-z0-9+/=]+)', r.stdout)
        if m:
            os.makedirs(output_dir, exist_ok=True)
            fpath = os.path.join(output_dir, f'{vid}.jpg')
            with open(fpath, 'wb') as f:
                f.write(base64.b64decode(m.group(1)))
            size_kb = os.path.getsize(fpath) / 1024
            print(f'  ✅ [{idx+1}/{len(success_ids)}] {vid}.jpg ({size_kb:.0f} KB)')
            results.append((vid, True, fpath))
        else:
            print(f'  ❌ [{idx+1}/{len(success_ids)}] {vid} 提取失败')
            results.append((vid, False, None))

        pw('tab-close', str(tab_idx))

    close_browser()

    # 总结
    print(f'\n{"="*40}')
    print(f'📊 下载总结')
    print(f'{"="*40}')
    ok = [r for r in results if r[1]]
    fail = [r for r in results if not r[1]]
    print(f'✅ 成功: {len(ok)}')
    for vid, _, path in ok:
        print(f'   {vid} → {path}')
    if fail:
        print(f'❌ 失败: {len(fail)}')
        for vid, _, _ in fail:
            print(f'   {vid}')
    return results


def main():
    parser = argparse.ArgumentParser(
        description='JableTV 封面下载器 — 支持批量并发',
        epilog='示例:\n'
               '  python cover.py https://jable.tv/videos/jur-704/\n'
               '  python cover.py jur-704 jur-753 ntrh-020\n'
               '  python cover.py -o D:/covers jur-704'
    )
    parser.add_argument('url', nargs='+', help='JableTV 影片网址或番号（支持多部）')
    parser.add_argument('-o', '--output', default=DEFAULT_OUTPUT,
                        help=f'封面输出目录 (默认: {DEFAULT_OUTPUT})')
    args = parser.parse_args()

    # 处理输入：如果是番号（无 https://），补全 URL
    urls = []
    for u in args.url:
        if u.startswith('http://') or u.startswith('https://'):
            urls.append(u)
        else:
            urls.append(f'https://jable.tv/videos/{u}/')

    download_covers_concurrent(urls, args.output)


if __name__ == '__main__':
    main()
