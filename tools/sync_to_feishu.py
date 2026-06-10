#!/usr/bin/env python3
"""
本地研究文档定时同步到飞书文档

用法：
    python tools/sync_to_feishu.py --dry-run      # 默认，只显示将要同步的内容
    python tools/sync_to_feishu.py --confirm       # 显示内容，询问确认后同步
    python tools/sync_to_feishu.py --force-all     # 忽略同步状态，同步整篇文档
    python tools/sync_to_feishu.py --force-all --confirm  # 同上，但需确认

安全约束：
- 默认 dry-run
- 只有 ENABLE_FEISHU_SYNC=true 且用户确认时才真正写飞书
- 同步失败不更新 .sync_state.json
- 不打印 secret
"""

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# 项目根目录：tools/ 的上级目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_NOTE = PROJECT_ROOT / "research_note.md"
SYNC_STATE_FILE = PROJECT_ROOT / ".sync_state.json"
LOG_DIR = PROJECT_ROOT / "logs"
ENV_FILE = PROJECT_ROOT / ".env"


def setup_logging() -> logging.Logger:
    """配置日志，同时输出到文件和终端"""
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"sync_{datetime.now().strftime('%Y%m%d')}.log"

    logger = logging.getLogger("sync")
    logger.setLevel(logging.DEBUG)

    # 清除已有 handler，避免重复输出
    logger.handlers.clear()

    # 文件 handler — 详细日志
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)

    # 终端 handler — 只显示 INFO 及以上
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ch)

    return logger


def load_dotenv() -> None:
    """手动加载 .env 文件到环境变量（不依赖 python-dotenv 的 CLI）"""
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
            # 不覆盖已存在的环境变量
            if key not in os.environ:
                os.environ[key] = value


def sha256_of(text: str) -> str:
    """计算文本的 SHA-256"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_sync_state() -> dict:
    """读取同步状态文件"""
    if not SYNC_STATE_FILE.exists():
        return {
            "file": "research_note.md",
            "last_synced_char": 0,
            "last_synced_at": None,
            "last_checksum": None,
        }
    with open(SYNC_STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_sync_state(state: dict) -> None:
    """写入同步状态文件"""
    with open(SYNC_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_new_content(full_text: str, last_synced_char: int) -> str:
    """根据字符位置提取新增内容"""
    if last_synced_char == 0:
        return full_text
    if last_synced_char > len(full_text):
        return ""
    return full_text[last_synced_char:]


def main():
    parser = argparse.ArgumentParser(
        description="本地研究文档同步到飞书文档",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python tools/sync_to_feishu.py --test              # 测试飞书连接（token/读/写）
  python tools/sync_to_feishu.py --dry-run           # 查看将要同步的内容
  python tools/sync_to_feishu.py --confirm           # 确认后同步新增内容
  python tools/sync_to_feishu.py --force-all         # 同步整篇文档（dry-run）
  python tools/sync_to_feishu.py --force-all --confirm  # 确认后同步整篇文档
        """,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="只显示将要同步的内容，不写飞书，不更新状态（默认行为）",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="显示新增内容后询问确认，输入 yes 才真正同步",
    )
    parser.add_argument(
        "--force-all",
        action="store_true",
        default=False,
        help="忽略同步状态，重新同步整篇文档",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        default=False,
        help="测试飞书连接：获取 token → 读取文档 → 尝试写入",
    )

    args = parser.parse_args()
    logger = setup_logging()

    # ------------------------------------------------------------------
    # --test 模式：测试飞书连接
    # ------------------------------------------------------------------
    if args.test:
        load_dotenv()
        logger = setup_logging()
        logger.info("=" * 50)
        logger.info("飞书连接测试")
        logger.info("=" * 50)

        sys.path.insert(0, str(PROJECT_ROOT / "tools"))
        from feishu_client import FeishuClient

        client = FeishuClient()

        # Step 1: 获取 token
        logger.info("\n[1/3] 获取 tenant_access_token ...")
        try:
            client.get_tenant_access_token()
            logger.info("✅ token 获取成功")
        except Exception as e:
            logger.error(f"❌ token 获取失败: {e}")
            sys.exit(1)

        # Step 2: 读取文档 blocks
        logger.info("\n[2/3] 读取文档 blocks ...")
        try:
            root_id = client.get_root_block_id()
            logger.info(f"✅ 读取成功，root block id: {root_id}")
        except Exception as e:
            logger.error(f"❌ 读取失败: {e}")
            sys.exit(1)

        # Step 3: 尝试写入
        logger.info("\n[3/3] 尝试写入测试内容 ...")
        try:
            test_text = f"[连接测试] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            client.config.enabled = True  # 临时启用写入
            result = client.append_text_block(test_text, parent_block_id=root_id)
            logger.info(f"✅ 写入成功！")
            logger.info(f"   测试内容: {test_text}")
        except Exception as e:
            logger.error(f"❌ 写入失败: {e}")
            logger.error("   请检查应用是否已添加为文档协作者（可编辑权限）")
            sys.exit(1)

        logger.info("\n" + "=" * 50)
        logger.info("✅ 所有测试通过！可以正常使用同步功能。")
        sys.exit(0)

    # 如果没有指定 --confirm，等同于 --dry-run
    if not args.confirm:
        args.dry_run = True

    logger.info("=" * 50)
    logger.info(f"同步开始: {datetime.now().isoformat()}")
    logger.info(f"模式: {'dry-run' if args.dry_run else 'confirm'}")
    if args.force_all:
        logger.info("选项: --force-all（忽略同步状态，同步整篇文档）")

    # ------------------------------------------------------------------
    # 1. 加载环境变量
    # ------------------------------------------------------------------
    load_dotenv()

    # ------------------------------------------------------------------
    # 2. 读取 research_note.md
    # ------------------------------------------------------------------
    if not RESEARCH_NOTE.exists():
        logger.error(f"文件不存在: {RESEARCH_NOTE}")
        sys.exit(1)

    with open(RESEARCH_NOTE, "r", encoding="utf-8") as f:
        full_text = f.read()

    logger.info(f"读取文件: {RESEARCH_NOTE}")
    logger.info(f"文件总长度: {len(full_text)} 字符")

    # ------------------------------------------------------------------
    # 3. 读取同步状态
    # ------------------------------------------------------------------
    state = load_sync_state()
    last_synced_char = state.get("last_synced_char", 0)

    # ------------------------------------------------------------------
    # 4. 确定要同步的内容
    # ------------------------------------------------------------------
    if args.force_all:
        # --force-all: 同步整篇文档
        new_content = full_text
        logger.info("force-all 模式: 同步整篇文档")
    else:
        # 增量同步: 检查文件长度
        if len(full_text) < last_synced_char:
            logger.warning(
                f"文件长度 ({len(full_text)}) 小于上次同步位置 ({last_synced_char})，"
                "文档可能被重写。"
            )
            logger.warning("请使用 --force-all 重新同步整篇文档。")
            sys.exit(1)

        new_content = get_new_content(full_text, last_synced_char)

    # ------------------------------------------------------------------
    # 5. 检查是否有新增内容
    # ------------------------------------------------------------------
    new_content_stripped = new_content.strip()
    if not new_content_stripped:
        logger.info("✅ 没有新增内容需要同步。")
        sys.exit(0)

    logger.info(f"新增内容长度: {len(new_content)} 字符")
    logger.info("")
    logger.info("─" * 40)
    logger.info("将要同步的内容:")
    logger.info("─" * 40)
    # 显示内容，截断过长的部分
    preview_limit = 2000
    if len(new_content) > preview_limit:
        logger.info(new_content[:preview_limit])
        logger.info(f"\n... [截断，共 {len(new_content)} 字符]")
    else:
        logger.info(new_content)
    logger.info("─" * 40)
    logger.info("")

    # ------------------------------------------------------------------
    # 6. dry-run 模式: 到此为止
    # ------------------------------------------------------------------
    if args.dry_run:
        logger.info("🔍 dry-run 模式，未写入飞书。")
        logger.info("如需真正同步，请添加 --confirm 参数。")
        sys.exit(0)

    # ------------------------------------------------------------------
    # 7. confirm 模式: 询问用户
    # ------------------------------------------------------------------
    try:
        answer = input("Sync to Feishu? type yes to continue: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        logger.info("\n❌ 用户取消。")
        sys.exit(0)

    if answer != "yes":
        logger.info("❌ 用户取消同步。")
        sys.exit(0)

    # ------------------------------------------------------------------
    # 8. 检查飞书配置
    # ------------------------------------------------------------------
    enabled = os.getenv("ENABLE_FEISHU_SYNC", "false").lower() == "true"
    if not enabled:
        logger.warning(
            "ENABLE_FEISHU_SYNC=false，同步未启用。\n"
            "如需真正写入飞书，请在 .env 中设置 ENABLE_FEISHU_SYNC=true"
        )
        sys.exit(1)

    # ------------------------------------------------------------------
    # 9. 调用飞书 API 同步
    # ------------------------------------------------------------------
    try:
        # 延迟导入，避免未安装 requests 时报错
        sys.path.insert(0, str(PROJECT_ROOT / "tools"))
        from feishu_client import FeishuClient, FeishuConfig

        client = FeishuClient()
        logger.info("正在获取飞书 tenant_access_token ...")
        client.get_tenant_access_token()
        logger.info("✅ token 获取成功")

        logger.info("正在写入飞书文档 ...")
        # 优先用 Markdown 拆分写入
        client.append_markdown_blocks(new_content)
        logger.info("✅ 飞书文档写入成功")

    except Exception as e:
        logger.error(f"❌ 飞书同步失败: {e}")
        logger.error("同步状态未更新。")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 10. 同步成功，更新状态
    # ------------------------------------------------------------------
    now_iso = datetime.now().isoformat()
    new_state = {
        "file": "research_note.md",
        "last_synced_char": len(full_text),
        "last_synced_at": now_iso,
        "last_checksum": sha256_of(full_text),
    }
    save_sync_state(new_state)
    logger.info(f"✅ 同步状态已更新: last_synced_char={len(full_text)}")
    logger.info(f"同步完成: {now_iso}")


if __name__ == "__main__":
    main()
