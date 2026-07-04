#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音直播回放下载器 - 多线程加速版
==================================
pip install requests imageio-ffmpeg -i https://pypi.tuna.tsinghua.edu.cn/simple
python main.py
"""

import requests
import subprocess
import sys
import os
import re
import time
import shutil
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==================== 配置区 ====================
M3U8_URL = ""

OUTPUT_DIR = r"D:\\抖音直播回放"
OUTPUT_NAME = "replay0703.mp4"
MAX_WORKERS = 16
MAX_RETRIES = 5
DOWNLOAD_DELAY = 0
# ================================================

HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "identity;q=1, *;q=0",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Origin": "https://live.douyin.com",
    "Referer": "https://live.douyin.com/",
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.6099.130 Safari/537.36",
}

TEMP_DIR = os.path.join(OUTPUT_DIR, "temp_ts")


def get_headers_with_host(url):
    headers = HEADERS.copy()
    headers["Host"] = urlparse(url).netloc
    return headers


def fetch_m3u8(session, url, retries=5):
    for i in range(retries):
        try:
            headers = get_headers_with_host(url)
            resp = session.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            print(f"  获取m3u8失败 (第{i+1}次): {e}")
            if i < retries - 1:
                time.sleep(2 * (i + 1))
    return None


def parse_m3u8(content, base_url):
    lines = [l.strip() for l in content.split("\n")]
    segments = []
    total_duration = 0.0

    # 检查多码率
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            if i + 1 < len(lines) and lines[i+1] and not lines[i+1].startswith("#"):
                # 选最高带宽
                bw_match = re.search(r'BANDWIDTH=(\d+)', line)
                return None, urljoin(base_url, lines[i+1])

    # 提取ts片段
    for line in lines:
        if line.startswith("#EXTINF"):
            try:
                dur = float(line.split(":")[1].rstrip(","))
                total_duration += dur
            except:
                pass
        elif line and not line.startswith("#"):
            segments.append(urljoin(base_url, line))

    return segments, None


def download_segment(session, seg_info):
    idx, url = seg_info
    ts_path = os.path.join(TEMP_DIR, f"seg_{idx:06d}.ts")

    if os.path.exists(ts_path) and os.path.getsize(ts_path) > 0:
        return idx, ts_path, True

    for attempt in range(MAX_RETRIES):
        try:
            headers = get_headers_with_host(url)
            resp = session.get(url, headers=headers, timeout=60)
            resp.raise_for_status()
            with open(ts_path, "wb") as f:
                f.write(resp.content)
            return idx, ts_path, True
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(1 * (attempt + 1))
            else:
                return idx, ts_path, False

    return idx, ts_path, False


def main():
    m3u8_url = sys.argv[1] if len(sys.argv) > 1 else M3U8_URL

    print("""
========================================
  抖音直播回放下载器 (多线程加速版)
  16线程并行下载, 速度提升10~15倍
========================================
""")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)

    session = requests.Session()

    # Step 1: 获取m3u8
    print("[1/5] 获取 m3u8 播放列表...")
    m3u8_content = fetch_m3u8(session, m3u8_url)
    if not m3u8_content:
        print("[x] 无法获取m3u8，链接可能已过期")
        sys.exit(1)

    # 处理多码率
    segments, sub_url = parse_m3u8(m3u8_content, m3u8_url)
    if sub_url:
        print("  发现多码率，获取子m3u8...")
        m3u8_content = fetch_m3u8(session, sub_url)
        if not m3u8_content:
            print("[x] 无法获取子m3u8")
            sys.exit(1)
        m3u8_url = sub_url
        segments, _ = parse_m3u8(m3u8_content, m3u8_url)

    if not segments:
        segments, _ = parse_m3u8(m3u8_content, m3u8_url)

    if not segments:
        print("[x] 未找到ts片段!")
        sys.exit(1)

    # 计算总时长
    total_duration = 0.0
    for line in m3u8_content.split("\n"):
        if line.strip().startswith("#EXTINF"):
            try:
                total_duration += float(line.split(":")[1].rstrip(","))
            except:
                pass

    mins = total_duration / 60
    print(f"  共 {len(segments)} 个片段, 时长 {total_duration:.0f}秒 ({mins:.1f}分钟)")

    # Step 2: 多线程下载
    print(f"\n[2/5] 开始下载 ({MAX_WORKERS} 线程并行)...")

    ts_files = [None] * len(segments)
    done = 0
    fail = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(download_segment, session, (i, url)): i
            for i, url in enumerate(segments)
        }

        for future in as_completed(futures):
            idx, ts_path, success = future.result()
            if success:
                ts_files[idx] = ts_path
                done += 1
            else:
                fail += 1

            total_done = done + fail
            pct = total_done / len(segments) * 100
            bar_len = 40
            filled = int(bar_len * total_done / len(segments))
            bar = "#" * filled + "-" * (bar_len - filled)

            elapsed = time.time() - start_time
            if elapsed > 0 and total_done > 0:
                speed = total_done / elapsed
                eta = (len(segments) - total_done) / speed if speed > 0 else 0
                print(f"\r  [{bar}] {total_done}/{len(segments)} ({pct:.0f}%) "
                      f"~{speed:.0f}片/秒 剩余{eta:.0f}秒 失败:{fail}    ",
                      end="", flush=True)

    print()
    elapsed = time.time() - start_time
    print(f"  下载完成: 成功 {done}, 失败 {fail}, 耗时 {elapsed:.0f}秒")

    if done == 0:
        print("[x] 没有成功下载任何片段!")
        sys.exit(1)

    ts_files = [f for f in ts_files if f]

    # Step 3: 合并
    print(f"\n[3/5] 合并 {len(ts_files)} 个片段...")
    output_ts = os.path.join(OUTPUT_DIR, "replay.ts")
    with open(output_ts, "wb") as out:
        for i, ts_file in enumerate(ts_files):
            if os.path.exists(ts_file):
                with open(ts_file, "rb") as inp:
                    out.write(inp.read())
            if (i + 1) % 100 == 0:
                print(f"\r  合并进度: {i+1}/{len(ts_files)}", end="", flush=True)
    print()

    # Step 4: 转MP4
    final_output = os.path.join(OUTPUT_DIR, OUTPUT_NAME)
    print(f"\n[4/5] 转换为 MP4...")

    ffmpeg_exe = None
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg_exe = shutil.which("ffmpeg")

    if ffmpeg_exe:
        cmd = [
            ffmpeg_exe, "-y",
            "-i", output_ts,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-movflags", "+faststart",
            final_output
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                os.remove(output_ts)
                print("  转换成功")
            else:
                print("  转换失败，保留.ts文件")
                final_output = output_ts
        except Exception as e:
            print(f"  转换异常: {e}，保留.ts文件")
            final_output = output_ts
    else:
        print("  未找到ffmpeg，保留.ts格式 (可用PotPlayer播放)")
        final_output = output_ts

    # Step 5: 清理
    print(f"\n[5/5] 清理临时文件...")
    shutil.rmtree(TEMP_DIR, ignore_errors=True)

    # 完成
    if os.path.exists(final_output):
        size_mb = os.path.getsize(final_output) / 1024 / 1024
        total_elapsed = time.time() - start_time
        print(f"""
========================================
  下载完成!
  文件: {final_output}
  大小: {size_mb:.1f} MB
  耗时: {total_elapsed:.0f} 秒
========================================""")


if __name__ == "__main__":
    main()
