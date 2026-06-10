#!/usr/bin/env python3
"""
自动定时同步脚本

每隔指定小时数自动将本地 Markdown 文件同步到飞书文档。
配置项从 .env 读取：
  - SYNC_INTERVAL_HOURS: 同步间隔（小时），默认 2
  - SYNC_SOURCE_FILE:    同步的源文件名，默认 research_note.md

用法：
    python tools/auto_sync.py              # 启动定时同步
    python tools/auto_sync.py --once       # 只同步一次然后退出
    python tools/auto_sync.py --interval 1 # 覆盖间隔为 1 小时

按 Ctrl+C 停止。
"""

import argparse
import hashlib
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
LOG_DIR = PROJECT_ROOT / "logs"
SYNC_STATE_FILE = PROJECT_ROOT / ".sync_state.json"

# 优雅退出标志
_running = True


def _handle_signal(signum, frame):
    global _running
    _running = False
    print("\n收到停止信号，等待当前同步完成后退出...")


def load_dotenv() -> None:
    if not ENV_FILE.exists():
        return
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key not in os.environ:
                os.environ[key] = value


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"auto_sync_{datetime.now().strftime('%Y%m%d')}.log"

    logger = logging.getLogger("auto_sync")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ch)

    return logger


def load_sync_state() -> dict:
    if not SYNC_STATE_FILE.exists():
        return {"last_synced_char": 0, "last_synced_at": None}
    with open(SYNC_STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_sync_state(state: dict) -> None:
    with open(SYNC_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def do_sync(logger: logging.Logger) -> bool:
    """执行一次同步，返回是否成功"""
    source_file = os.getenv("SYNC_SOURCE_FILE", "research_note.md")
    source_path = PROJECT_ROOT / source_file

    if not source_path.exists():
        logger.error(f"源文件不存在: {source_path}")
        return False

    with open(source_path, "r", encoding="utf-8") as f:
        full_text = f.read()

    state = load_sync_state()
    last_synced_char = state.get("last_synced_char", 0)

    # 检测文件是否被重写
    if len(full_text) < last_synced_char:
        logger.warning(
            f"文件长度 ({len(full_text)}) < 上次同步位置 ({last_synced_char})，"
            "文件可能被重写，跳过本次同步。请手动执行 --force-all --confirm。"
        )
        return False

    new_content = full_text[last_synced_char:].strip()
    if not new_content:
        logger.info("没有新增内容，跳过。")
        return True

    logger.info(f"检测到新增内容: {len(new_content)} 字符，开始同步...")

    try:
        sys.path.insert(0, str(PROJECT_ROOT / "tools"))
        from feishu_client import FeishuClient

        client = FeishuClient()
        client.get_tenant_access_token()
        client.append_markdown_blocks(new_content)
        logger.info("飞书文档写入成功")

        now_iso = datetime.now().isoformat()
        new_state = {
            "file": source_file,
            "last_synced_char": len(full_text),
            "last_synced_at": now_iso,
            "last_checksum": sha256_of(full_text),
        }
        save_sync_state(new_state)
        logger.info(f"同步状态已更新: last_synced_char={len(full_text)}")
        return True

    except Exception as e:
        logger.error(f"同步失败: {e}")
        return False


def main():
    global _running

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    parser = argparse.ArgumentParser(description="自动定时同步到飞书")
    parser.add_argument("--once", action="store_true", help="只同步一次然后退出")
    parser.add_argument("--interval", type=float, help="覆盖同步间隔（小时）")
    args = parser.parse_args()

    load_dotenv()
    logger = setup_logging()

    interval_hours = args.interval or float(os.getenv("SYNC_INTERVAL_HOURS", "2"))
    interval_seconds = interval_hours * 3600

    logger.info("=" * 50)
    logger.info("自动同步已启动")
    logger.info(f"同步间隔: {interval_hours} 小时")
    logger.info(f"源文件: {os.getenv('SYNC_SOURCE_FILE', 'research_note.md')}")
    logger.info("按 Ctrl+C 停止")
    logger.info("=" * 50)

    if args.once:
        success = do_sync(logger)
        sys.exit(0 if success else 1)

    while _running:
        do_sync(logger)

        if not _running:
            break

        logger.info(f"下次同步: {interval_hours} 小时后")
        # 分段 sleep，以便及时响应退出信号
        slept = 0
        while _running and slept < interval_seconds:
            time.sleep(min(5, interval_seconds - slept))
            slept += 5

    logger.info("自动同步已停止。")


if __name__ == "__main__":
    main()
