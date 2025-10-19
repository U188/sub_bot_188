# Telegram 代理管理/同步/扫描/AI 对话 Bot

一个基于 Python 的 Telegram 机器人，使用 python-telegram-bot 框架，集成了以下能力：

- 节点管理：支持通过链接或 YAML 批量添加、查看、搜索、导出、删除节点
- 代理同步：从多个订阅源抓取并解析节点，按 server:port 去重，支持手动同步与自动定时同步
- 扫描工具：
  - XUI 面板扫描（尝试默认口令登录，自动抓取节点配置）
  - Ollama API 扫描（探测可用的 /v1/models 接口）
- AI 对话：内置多模型聊天（Gemini/GPT），支持角色预设与自定义 Prompt
- 管理员后台：用户权限管理、使用统计、系统参数设置

本项目采用文件存储，所有节点、配置均保存在本地文件中，部署简单，开箱即用。


## 目录结构

```
.
├─ main.py                 # 应用入口，注册所有指令/回调并调度各模块
├─ config.py               # 全局配置与枚举（从环境变量读取 BOT_TOKEN）
├─ data_manager.py         # 统一的数据读写（YAML 节点、JSON 配置）
├─ handlers/               # 业务模块（命令/回调处理器）
│  ├─ common.py            # 通用指令（/start 等）、权限/限流/主菜单
│  ├─ node_management.py   # 节点管理（添加/查看/搜索/导出/批量操作）
│  ├─ scanner.py           # XUI 与 Ollama 扫描（完全异步、进度与结果文件）
│  ├─ proxy_sync.py        # 代理源同步（多源、去重、定时、统计、可视化菜单）
│  ├─ admin.py             # 管理员面板（权限/统计/参数设置/进入同步面板）
│  └─ ai_chat.py           # AI 对话（多模型、角色预设、自定义 Prompt）
├─ services/
│  └─ scanner_service.py   # 扫描服务（可复用的异步扫描实现）
├─ utils/
│  ├─ proxy_parser.py      # 统一代理解析器（链接/YAML，多协议）
│  └─ ui_helpers.py        # 内联键盘与显示文案辅助
└─ README.md               # 本文件
```

运行时会生成/使用的文件（默认路径可在 config.py 中查看/调整）：

- all_proxies.txt：保存所有节点（YAML 格式）
- bot_config.json：保存用户权限与管理员列表
- data/proxy_sources.json：保存代理订阅源配置（名称、URL、同步间隔等）
- uploads/：临时存放上传的扫描列表文件
- 其他运行期文件：ollama_apis.txt、scan_nodes_*.txt、scan_logins_*.txt 等


## 快速开始

1) 安装 Python 依赖

- Python 版本建议 3.10+（开发调试使用了 Python 3.12）
- 推荐在虚拟环境中安装依赖

```
# 任选其一：
python -m venv .venv && source .venv/bin/activate
# or
python3 -m venv .venv && source .venv/bin/activate

pip install -r requirements.txt
```

如未使用 requirements.txt，可手动安装核心依赖：

```
pip install python-telegram-bot aiohttp requests pyyaml
```

2) 配置环境变量（Telegram 机器人 Token）

```
export TELEGRAM_BOT_TOKEN=你的机器人Token
```

3) 启动机器人

```
python main.py
```

首次启动将在当前目录下自动创建必要的数据文件夹/文件（如 uploads/、data/）。


## 基本用法

- 发送 /start 获取主菜单，根据按钮进入不同模块
- 支持以下快捷命令：
  - /start：显示主菜单
  - /cancel、/c、/stop：取消当前操作或停止扫描

主要能力说明：

- 节点管理
  - 添加节点：支持以下格式（每行一个，批量添加）：
    - 协议链接：ss://、vmess://、vless://、trojan://、hysteria://、hy2:// 等
    - YAML：单个节点或 proxies 列表
  - 查看/搜索：分页展示节点，支持关键词搜索（名称/服务器/协议）
  - 多选管理：批量删除、导出所选节点
  - 下载文件：导出全部节点 YAML 文件

- 代理同步（管理员）
  - 源管理：添加/删除/启用/禁用订阅源，设置每个源的同步间隔
  - 手动同步：立即抓取所有启用源，按 server:port 去重并合并
  - 自动同步：开启后台调度器，按各源独立间隔自动同步并推送报告
  - 解析特性：支持链接、YAML、Base64 包装，自动解析协议（SS/SSR/VMess/Trojan/Hy2 等）

- 扫描工具（管理员）
  - XUI 面板扫描：
    - 输入一批 URL（每行一个，支持 http/https，默认端口 54321）
    - 尝试使用 admin/123456 登录
    - 登录成功后自动抓取面板中的节点
    - 扫描异步并发，带进度提示，可随时取消
  - Ollama API 扫描：
    - 探测 /v1/models 是否可用
    - 可选把可用端点追加到 ollama_apis.txt

- AI 对话
  - 内置两类模型：Gemini 与 GPT（通过 ChatPub API）
  - 角色预设：默认助手、编程专家、耐心老师、创意写手、翻译专家
  - 支持自定义 Prompt 与会话重置

- 管理员面板
  - 查看/设置用户权限（user/guest/banned）
  - 查看统计（节点总数、用户数、协议分布等）
  - 设置扫描数量限制
  - 进入代理同步面板


## 代理配置格式示例

- VLESS 链接示例：

```
vless://uuid@server:port/?type=tcp&security=reality&pbk=key&sid=id#MyNode
```

- YAML 单条节点示例：

```yaml
- name: My-SS-Node
  type: ss
  server: 1.2.3.4
  port: 8388
  cipher: aes-256-gcm
  password: yourpassword
```

- YAML proxies 列表示例：

```yaml
proxies:
  - name: My-Vmess
    type: vmess
    server: 2.2.2.2
    port: 443
    uuid: 00000000-0000-0000-0000-000000000000
    network: ws
    tls: true
    ws-opts:
      path: /ws
      headers:
        Host: example.com
```

提示：name 字段需唯一，重复名称将更新原有节点；也支持按 server:port 去重（在扫描/订阅同步时）。


## 配置与持久化

- Telegram 机器人 Token：从环境变量 TELEGRAM_BOT_TOKEN 读取
- 管理员 ID：默认写在 config.py 的 Config.ADMIN_IDS 中；运行时也会在 bot_config.json 中持久化
- 运行期文件路径：在 config.py 中集中配置（PROXIES_FILE、CONFIG_FILE、UPLOAD_DIR、SOURCE_CONFIG_FILE 等）
- 订阅源配置：写入 data/proxy_sources.json，自动保存/加载

如需自定义 AI API（模型名、API Key、API URL），可修改 handlers/ai_chat.py 中的 AIConfig。


## 开发说明

- 框架：python-telegram-bot（v20+ API）
- 并发：aiohttp + asyncio（扫描/抓取）
- 解析：utils/proxy_parser.py 统一处理链接/YAML，支持多协议与 Reality、WS、gRPC 等参数
- 存储：YAML/JSON 文件，便于直接查看/备份

建议使用 logging 与断点调试定位问题；代码已尽量遵循 SRP/DRY/OCP 等设计原则，方便扩展维护。


## 注意与声明

- 本项目仅供学习与研究，请勿用于任何违反当地法律法规或服务条款的用途
- XUI 扫描功能会尝试弱口令登录，仅应在授权环境中进行安全测试
- 使用本项目造成的一切后果由使用者自负


## 许可

未显式提供许可证文件，默认保留所有权利。如需以特定协议开源/商用，请自行添加 LICENSE 并在 PR 中说明。
