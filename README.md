# Zepp PC Manager

轻量级 PC 端 Amazfit/Zepp 智能手表管理工具，通过蓝牙 BLE 连接实现手表的桌面端管理。

## 功能

| 功能 | 说明 |
|------|------|
| **设备发现** | 自动扫描附近的 Amazfit 手表 |
| **BLE 连接** | 低功耗蓝牙直连，无需中转 |
| **设备认证** | AES-128 挑战-响应认证（Auth Key 来自 Zepp 云） |
| **电量读取** | 实时电池百分比 |
| **步数同步** | 当前步数 |
| **心率读取** | 手动触发心率测量 |
| **血氧读取** | SpO2 百分比 |
| **查找设备** | 触发手表震动提醒 |
| **同步时间** | 将 PC 时间同步到手表 |
| **DND 设置** | 设置免打扰时段 |
| **目标设置** | 设置步数/卡路里/活动时长目标 |
| **通知推送** | 推送文字通知到手表 |

## 支持的设备

| 系列 | 型号 | 支持状态 |
|------|------|----------|
| T-Rex | T-Rex 2, T-Rex 3, T-Rex 3 Pro, T-Rex Ultra | ✅ |
| GTR/GTS | GTR 3/4, GTS 3/4 (Zepp OS) | ✅ |
| Bip | Bip / Bip S / Bip U | ✅ |

## 环境要求

- Python 3.10+
- 蓝牙适配器（笔记本通常内置）
- **Linux**: 需要 Qt GUI 库（PyQt6 + PyQt6-WebEngine）
- **Windows 64-bit**: 自带 Edge WebView2，无需额外 GUI 依赖

## 快速开始

### 1. 安装依赖

```bash
# 使用 uv 安装（推荐）
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[gui]"
```

Windows 只需：`uv pip install -e "."`（无需 `[gui]`）

### 2. 启动应用

推送 tag 触发 GitHub Actions 自动构建：

```bash
git tag v0.1.0
git push origin v0.1.0
```

构建产物（自动挂载到 Release）：

| 平台 | 产物名 | 说明 |
|------|--------|------|
| Windows | `zepp-pc-v0.1.0-windows-x86_64.exe` | 无控制台窗口 |
| Linux | `zepp-pc-v0.1.0-linux-x86_64` | 需 `libxcb-cursor0` |
| macOS | `zepp-pc-v0.1.0-macos-arm64` | Apple Silicon |

本地开发：
```bash
# 桌面窗口模式
python main.py

# 服务器模式（浏览器访问 http://127.0.0.1:8765/api/）
python -m uvicorn src.server.main:app --host 127.0.0.1 --port 8765
```

### 3. 获取 Auth Key

手表配对前需要从 Zepp 云获取 Auth Key：

```bash
# 安装 huami-token
pip install huami-token

# 运行获取工具
python -m huami_token
```

按提示登录 Zepp 账号，在输出中找到对应设备的 32 位十六进制 auth_key。

## 打包分发

### Linux

```bash
bash build.sh
# 输出: dist/zepp-pc
```

### Windows

双击 `build.bat` 或在命令行运行：
```cmd
build.bat
# 输出: dist\zepp-pc.exe
```

## 项目结构

```
├── main.py                      # 桌面应用入口 (pywebview + FastAPI)
├── pyproject.toml               # uv 项目配置
├── build.spec                   # PyInstaller 打包配置
├── build.sh / build.bat         # 构建脚本
├── .github/workflows/
│   └── build.yml                # GitHub Actions 自动构建 (Win/Linux/macOS)
├── README.md
├── src/
│   ├── ble/
│   │   ├── client.py            # BLE 连接 & 认证 (bleak)
│   │   ├── auth.py              # AES-128 加密
│   │   └── commands.py          # Huami 指令编码/解码
│   ├── server/
│   │   ├── main.py              # FastAPI 服务器
│   │   ├── api/devices.py       # REST API 端点
│   │   └── static/              # 前端页面
│   │       ├── index.html       # UI 页面
│   │       └── js/app.js        # 前端交互逻辑
│   └── models/
│       └── device.py            # 数据模型
└── tests/
    └── test_commands.py         # 单元测试 (16 个)
```

## 开发

```bash
# 安装开发依赖
uv pip install -e ".[dev,gui]"

# 运行测试
pytest -v
```

## 技术栈

- **BLE 通信**: [bleak](https://github.com/hbldh/bleak) — 跨平台 Python BLE 库
- **后端**: FastAPI + uvicorn — 异步 REST API
- **桌面窗口**: [pywebview](https://github.com/r0x0r/pywebview) — 轻量桌面 WebView 框架
- **前端**: 原生 HTML + Tailwind CSS — 无需构建步骤
- **加密**: cryptography — AES-128 认证

## 已知限制

1. **T-Rex 3 协议指令**: 基于 Gadgetbridge 的 Huami 协议实现，但 T-Rex 3 的 BLE 特征值 UUID 需要实际连接后调试验证
2. **Auth Key 获取**: 必须通过 `huami-token` 从 Zepp 云 API 获取，这是协议层面的限制
3. **BT Classic**: T-Rex 3 新固件 (4.5.3.3+) 可能需要经典蓝牙连接，bleak 仅支持 BLE

## License

MIT
