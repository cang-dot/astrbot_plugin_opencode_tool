# astrbot_plugin_opencode_tool

AstrBot LLM Tool 插件，让 Agent 能够主动调用 OpenCode 执行开发任务。

## 功能

- Agent 可在对话中自动调用 `opencode_execute` 工具
- 支持读写文件、代码重构、生成单元测试、分析代码结构等任务
- 自动启动 OpenCode 服务器，无需手动管理
- **实时事件流**：通过 SSE 监听 OpenCode 事件，实时推送给用户
- **消息聚合**：累积 3 条消息发送一次，超过 5 分钟未满也发送
- **权限交互**：OpenCode 需要写文件等操作时，用户可实时允许/拒绝
- **支持 Plan/Build 模式切换**：先分析制定计划，确认后再执行
- **支持 dry_run 预览模式**：AI 可先展示执行计划，用户确认后再执行

## 工作原理

```
用户发送任务 → AstrBot Agent 调用 opencode_execute 工具
    → 插件启动 opencode serve 后台服务
    → 通过 HTTP API 发送任务
    → SSE 实时监听事件流
    → 消息聚合后推送给用户
    → 权限请求实时交互
```

## 前置要求

1. **Node.js** 和 **npm** 已安装
2. **OpenCode CLI** 已安装：
   ```bash
   npm install -g opencode-ai
   ```
3. **OpenCode 认证** 已配置：
   ```bash
   opencode auth login
   ```

## 安装

### 方式一：复制到 AstrBot 插件目录

```bash
# 复制插件到 AstrBot
cp -r astrbot_plugin_opencode_tool C:\Users\Administrator\mybot\data\plugins\
```

### 方式二：通过 AstrBot WebUI

1. 打开 AstrBot WebUI
2. 进入插件管理
3. 上传插件文件夹

## 使用方法

安装插件后，在 AstrBot 对话中直接说：

- "帮我读取 src/main.py 文件"
- "重构 user_auth 模块"
- "为 utils.py 生成单元测试"
- "分析项目的代码结构"

### Plan/Build 模式工作流

Agent 会先用 Plan 模式分析任务，制定计划后再用 Build 模式执行：

```
用户: 帮我重构 user_auth 模块
Agent: [调用 opencode_execute mode="plan"]
       → OpenCode 分析代码，制定重构计划
Agent: 计划如下：1. 分析 auth.py... 2. 修改 routes.py... 确认执行吗？
用户: 确认执行
Agent: [调用 opencode_execute mode="build"]
       → OpenCode 实际执行重构
       → 实时推送: 🔧 调用工具: bash ls src/
       → 实时推送: 📄 文件updated: src/auth.py
       → 实时推送: ✅ 工具结果: write 文件已写入
Agent: 重构完成！
```

### 权限交互

当 OpenCode 需要写文件等敏感操作时，会请求用户授权：

```
OpenCode: 🔐 OpenCode 需要授权
          工具: write
          操作: Write to file src/main.py
          文件: src/main.py
          
          回复「允许 a1b2c3d4」或「拒绝 a1b2c3d4」
用户: 允许 a1b2c3d4
OpenCode: [继续执行写入操作]
```

### 模式说明

| 模式 | 说明 | 是否修改文件 |
|------|------|-------------|
| `plan` | 分析任务，制定执行计划 | ❌ 不修改 |
| `build` | 实际执行任务，修改代码 | ✅ 会修改 |

## 配置

在 AstrBot WebUI 的插件管理中可以配置以下选项：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `server_port` | OpenCode 服务器端口 | 14096 |
| `model` | OpenCode 使用的模型 | opencode/deepseek-v4-flash-free |
| `timeout` | 任务超时时间（秒） | 300 |
| `batch_size` | 消息聚合条数 | 3 |
| `batch_timeout` | 消息聚合超时（秒） | 300 |

## 技术细节

| 项目 | 说明 |
|------|------|
| 插件名称 | astrbot_plugin_opencode_tool |
| 工具名称 | opencode_execute |
| 版本 | 2.0.0 |
| 通信方式 | HTTP API + SSE 实时事件流 |
| 消息推送 | 聚合后通过 context.send_message 推送 |
| 权限交互 | permission_request 事件 + 用户回复 |

## 文件结构

```
astrbot_plugin_opencode_tool/
├── __init__.py          # 插件入口
├── main.py              # 主逻辑（SSE + 消息聚合 + 权限交互）
├── _conf_schema.json    # 插件配置 Schema
├── metadata.yaml        # 插件元数据
├── requirements.txt     # 依赖（aiohttp）
└── logo.png             # 插件 Logo
```

## 故障排查

### 问题：未找到 OpenCode CLI

确保已安装：
```bash
npm install -g opencode-ai
```

### 问题：需要认证

运行：
```bash
opencode auth login
```

### 问题：服务器启动失败

检查端口是否被占用：
```bash
netstat -ano | findstr 14096
```

### 问题：SSE 连接断开

插件会自动重连。如果持续断开，检查 OpenCode 服务器状态。

## 许可证

MIT
