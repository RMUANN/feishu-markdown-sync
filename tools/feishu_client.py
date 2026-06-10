"""
飞书文档 API 客户端

提供 tenant_access_token 获取、文档 root block 查询、Markdown 内容追加写入等功能。
使用 requests 库，不依赖飞书官方 SDK。

安全约束：
- 不打印 app_secret
- 请求失败显示状态码和错误信息
- 配置缺失时友好提示
- 失败时不伪装成功
"""

import os
import requests
from typing import Optional


class FeishuConfig:
    """飞书配置，从环境变量读取"""

    def __init__(self):
        self.app_id = os.getenv("FEISHU_APP_ID", "")
        self.app_secret = os.getenv("FEISHU_APP_SECRET", "")
        self.document_id = os.getenv("FEISHU_DOCUMENT_ID", "")
        self.parent_block_id = os.getenv("FEISHU_PARENT_BLOCK_ID", "")
        self.enabled = os.getenv("ENABLE_FEISHU_SYNC", "false").lower() == "true"

    def validate(self) -> list[str]:
        """校验配置完整性，返回缺失项列表"""
        missing = []
        if not self.app_id:
            missing.append("FEISHU_APP_ID")
        if not self.app_secret:
            missing.append("FEISHU_APP_SECRET")
        if not self.document_id:
            missing.append("FEISHU_DOCUMENT_ID")
        return missing

    def is_ready(self) -> bool:
        """配置是否完整可用"""
        return len(self.validate()) == 0


class FeishuClient:
    """飞书文档 API 客户端

    支持两种文档类型：
    - 普通文档 (docx): document_id 直接使用
    - 知识库页面 (wiki): 需先通过 wiki API 解析为实际 document_id
    """

    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(self, config: Optional[FeishuConfig] = None):
        self.config = config or FeishuConfig()
        self._token: Optional[str] = None
        self._resolved_doc_id: Optional[str] = None  # wiki 解析后的实际文档 ID

    # ------------------------------------------------------------------
    # 配置校验
    # ------------------------------------------------------------------

    def check_config(self) -> None:
        """校验配置，缺失时抛出 ValueError"""
        missing = self.config.validate()
        if missing:
            raise ValueError(
                f"飞书配置缺失，请在 .env 中设置: {', '.join(missing)}"
            )

    def check_enabled(self) -> None:
        """检查同步是否启用"""
        if not self.config.enabled:
            raise RuntimeError(
                "ENABLE_FEISHU_SYNC=false，同步未启用。"
                "如需真正同步，请在 .env 中设置 ENABLE_FEISHU_SYNC=true"
            )

    # ------------------------------------------------------------------
    # Token
    # ------------------------------------------------------------------

    def get_tenant_access_token(self) -> str:
        """获取 tenant_access_token"""
        if self._token:
            return self._token

        self.check_config()
        url = f"{self.BASE_URL}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.config.app_id,
            "app_secret": self.config.app_secret,
        }
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(
                f"获取 tenant_access_token 失败: "
                f"code={data.get('code')}, msg={data.get('msg')}"
            )

        self._token = data["tenant_access_token"]
        return self._token

    def _headers(self) -> dict:
        """构造请求头"""
        token = self.get_tenant_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    # ------------------------------------------------------------------
    # 文档操作
    # ------------------------------------------------------------------

    def resolve_document_id(self) -> str:
        """解析 document_id，如果是 wiki token 则获取实际的文档 ID

        飞书知识库 (wiki) 页面的 token 不能直接用于 docx API，
        需要先调用 wiki API 获取 obj_token（即实际的 document_id）。

        Returns:
            可直接用于 docx API 的 document_id
        """
        if self._resolved_doc_id:
            return self._resolved_doc_id

        raw_id = self.config.document_id
        url = f"{self.BASE_URL}/wiki/v2/spaces/get_node"
        resp = requests.get(
            url,
            headers=self._headers(),
            params={"token": raw_id},
            timeout=10,
        )
        data = resp.json()

        if data.get("code") != 0:
            # 可能不是 wiki token，尝试直接作为 docx document_id 使用
            # 这种情况会在后续 get_root_block_id 时暴露真正的错误
            self._resolved_doc_id = raw_id
            return self._resolved_doc_id

        node = data.get("data", {}).get("node", {})
        obj_token = node.get("obj_token", "")
        obj_type = node.get("obj_type", "")

        if obj_type == "docx" and obj_token:
            self._resolved_doc_id = obj_token
            return self._resolved_doc_id

        # 非 docx 类型（如 sheet、bitable 等），不支持
        raise RuntimeError(
            f"Wiki 节点类型为 '{obj_type}'，当前仅支持 docx 类型。"
            f"obj_token={obj_token}"
        )

    def get_root_block_id(self) -> str:
        """获取文档的 root block id"""
        self.check_config()
        doc_id = self.resolve_document_id()
        url = f"{self.BASE_URL}/docx/v1/documents/{doc_id}/blocks"

        resp = requests.get(
            url,
            headers=self._headers(),
            params={"page_size": 1},
            timeout=10,
        )
        data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(
                f"获取文档 blocks 失败: code={data.get('code')}, msg={data.get('msg')}"
            )

        items = data.get("data", {}).get("items", [])
        if not items:
            raise RuntimeError("文档为空，无法获取 root block id")

        # root block 的 parent_id 为空或不存在
        for item in items:
            if not item.get("parent_id"):
                return item["block_id"]

        # fallback: 第一个 block
        return items[0]["block_id"]

    def get_parent_block_id(self) -> str:
        """获取目标父 block id（配置优先，否则自动获取 root）"""
        if self.config.parent_block_id:
            return self.config.parent_block_id
        return self.get_root_block_id()

    def append_text_block(self, text: str, parent_block_id: Optional[str] = None) -> dict:
        """
        将文本作为 text block 追加到文档

        TODO: 后续版本拆分 Markdown 为 heading / paragraph / bullet list blocks

        Args:
            text: 要追加的文本内容
            parent_block_id: 父 block id，为空时自动获取 root block

        Returns:
            飞书 API 响应数据
        """
        self.check_config()
        self.check_enabled()

        if parent_block_id is None:
            parent_block_id = self.get_parent_block_id()

        doc_id = self.resolve_document_id()
        url = (
            f"{self.BASE_URL}/docx/v1/documents/{doc_id}"
            f"/blocks/{parent_block_id}/children"
        )

        # 构造 text block
        # 飞书文档 API 的 text block 结构
        block = {
            "block_type": 2,  # 2 = text
            "text": {
                "elements": [
                    {
                        "text_run": {
                            "content": text,
                        }
                    }
                ],
                "style": {},
            },
        }

        payload = {
            "children": [block],
            "index": -1,  # 追加到末尾
        }

        resp = requests.post(
            url,
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(
                f"写入飞书文档失败: code={data.get('code')}, msg={data.get('msg')}"
            )

        return data

    def append_markdown_blocks(self, markdown_text: str, parent_block_id: Optional[str] = None) -> dict:
        """
        将 Markdown 文本拆分为多个 block 写入飞书文档

        解析规则：
        - # heading -> heading block (type 3-8)
        - - item -> bullet block (type 12)
        - 其他 -> text block (type 2)

        Args:
            markdown_text: Markdown 格式文本
            parent_block_id: 父 block id

        Returns:
            最后一次 API 调用的响应数据
        """
        self.check_config()
        self.check_enabled()

        if parent_block_id is None:
            parent_block_id = self.get_parent_block_id()

        doc_id = self.resolve_document_id()
        url = (
            f"{self.BASE_URL}/docx/v1/documents/{doc_id}"
            f"/blocks/{parent_block_id}/children"
        )

        blocks = []
        for line in markdown_text.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue

            # 标题: # heading, ## heading, ...
            if stripped.startswith("# "):
                level = len(stripped) - len(stripped.lstrip("#"))
                content = stripped.lstrip("# ").strip()
                # 飞书 heading block_type: 3=h1, 4=h2, ..., 8=h6
                # key 名为 heading1, heading2, ..., heading6
                block_type = min(2 + level, 8)
                heading_key = f"heading{block_type - 2}"
                blocks.append({
                    "block_type": block_type,
                    heading_key: {
                        "elements": [{"text_run": {"content": content}}],
                        "style": {},
                    },
                })
            # 无序列表: - item
            elif stripped.startswith("- "):
                content = stripped[2:].strip()
                blocks.append({
                    "block_type": 12,  # 12 = bullet
                    "bullet": {
                        "elements": [{"text_run": {"content": content}}],
                        "style": {},
                    },
                })
            # 普通段落
            else:
                blocks.append({
                    "block_type": 2,  # 2 = text
                    "text": {
                        "elements": [{"text_run": {"content": stripped}}],
                        "style": {},
                    },
                })

        if not blocks:
            raise ValueError("Markdown 内容为空，无 block 可写入")

        # 分批写入（飞书 API 单次最多 50 个 children）
        batch_size = 50
        last_data = None
        for i in range(0, len(blocks), batch_size):
            batch = blocks[i : i + batch_size]
            payload = {
                "children": batch,
                "index": -1,
            }
            resp = requests.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            last_data = resp.json()

            if last_data.get("code") != 0:
                raise RuntimeError(
                    f"写入飞书文档失败 (batch {i // batch_size + 1}): "
                    f"code={last_data.get('code')}, msg={last_data.get('msg')}"
                )

        return last_data
