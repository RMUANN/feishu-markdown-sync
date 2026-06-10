# feishu-markdown-sync

本地 Markdown 文件定时同步到飞书文档的命令行工具。

## 功能

- **增量同步** — 基于字符位置追踪，只同步新增内容
- **全量同步** — `--force-all` 忽略同步状态，重新同步整篇文档
- **自动定时同步** — `auto_sync.py` 每隔 N 小时自动检测并同步
- **安全设计** — 默认 dry-run，confirm 确认，secret 不打印
- **飞书支持** — 普通文档 (docx) 和知识库页面 (wiki)
- **Markdown 解析** — 拆分为 heading / text / bullet blocks 写入
- **状态管理** — `.sync_state.json` 持久化，失败不更新
- **日志系统** — `logs/sync_YYYYMMDD.log` 记录每次同步

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置飞书应用

在 [飞书开放平台](https://open.feishu.cn/) 创建应用，获取 App ID 和 App Secret。

开启权限：
- `docx:document` — 读写文档
- `wiki:wiki:readonly` — 读取知识库（如需同步 wiki 页面）

将应用添加为文档协作者（可编辑权限）。

### 3. 配置环境变量

```bash

编辑 `.env`：

```env
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_DOCUMENT_ID=你的文档ID或wiki token
ENABLE_FEISHU_SYNC=true
```

文档 ID 从飞书 URL 获取：
- 普通文档：`https://xxx.feishu.cn/docx/AbCdEf` → `AbCdEf`
- 知识库页面：`https://xxx.feishu.cn/wiki/AbCdEf` → `AbCdEf`

### 4. 测试连接

```bash
python tools/sync_to_feishu.py --test
```

依次测试 token 获取、文档读取、写入权限。

### 5. 同步

```bash
# 查看将要同步的内容（不写飞书）
python tools/sync_to_feishu.py --dry-run

# 确认后同步
python tools/sync_to_feishu.py --confirm

# 同步整篇文档
python tools/sync_to_feishu.py --force-all --confirm
```

## 自动定时同步

使用内置的 `auto_sync.py` 脚本，每隔指定小时自动检测并同步新增内容。

### 配置

在 `.env` 中设置：

```env
SYNC_INTERVAL_HOURS=2          # 同步间隔（小时），默认 2
SYNC_SOURCE_FILE=research_note.md  # 同步的源文件名，默认 research_note.md
```

### 运行

```bash
# 启动持续运行的自动同步（按 Ctrl+C 停止）
python tools/auto_sync.py

# 只同步一次然后退出
python tools/auto_sync.py --once

# 命令行覆盖间隔为 1 小时
python tools/auto_sync.py --interval 1
```

### 作为后台服务运行

#### Windows（PowerShell 后台）

```powershell
Start-Process -NoNewWindow python "tools/auto_sync.py"
```

#### Linux/macOS（nohup）

```bash
nohup python tools/auto_sync.py &
```

#### Windows 任务计划程序（开机自启）

```powershell
schtasks /create /tn "FeishuAutoSync" /tr "python C:\path\to\tools\auto_sync.py" /sc onlogon
```

## 项目结构

```
work/
├── .env.example              # 飞书配置模板
├── .gitignore
├── README.md
├── requirements.txt
├── research_note.md          # 示例 Markdown 文件
├── tools/
│   ├── __init__.py
│   ├── feishu_client.py      # 飞书 API 客户端
│   ├── sync_to_feishu.py     # 手动同步 CLI 工具
│   └── auto_sync.py          # 自动定时同步脚本
├── logs/                     # 同步日志
└── archive/                  # 归档目录
```

## 同步策略

- 字符位置追踪：`research_note.md` 只追加内容时自动增量同步
- 文件缩短检测：文档被重写时提示使用 `--force-all`
- 空内容检测：没有新增内容时提示并退出

## 安全

- 不打印 `app_secret`
- 默认 dry-run，不写飞书
- 只有 `ENABLE_FEISHU_SYNC=true` 且用户确认时才真正写入
- 同步失败不更新状态文件
- `.env`、`.sync_state.json`、`logs/` 已加入 `.gitignore`

## License

MIT
