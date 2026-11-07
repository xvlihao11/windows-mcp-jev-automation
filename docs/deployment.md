# 部署与操作说明

本说明对应 2026-11-08 公开源码导出，先读 README 中的当前限制。不要把仓库上传理解为已在另一台电脑部署成功。

## 依赖与目录

- Windows x64，Python 3.12（含 Tkinter）、Node.js，已安装并登录的钉钉，桌面已解锁。
- 自行从 sbroenne/mcp-windows 官方来源取得并核对兼容的 `wincli.exe`。本地历史实测使用 v1.3.28、提交 `655b9fc92d03ad52a270067c6844ea1231c90559` 的同源构建；本仓库不提供二进制。
- 将二进制放入 `asphalt-daily/wincli-trial/bin/wincli.exe`。
- 自己的智能体个人日报 SQLite 数据库及原 `markdown.js`。渲染器必须提供 `mdToHtml`、`stripMarkdown`；仓库复用该渲染器，不重新设计排版。
- 有效的 TypeSafe API 凭据。导出代码沿用历史实测的官方 URL 和 `jev-1.13.0`；新环境需自行核对服务支持情况。

Python 执行部分使用标准库；实际桌面执行不在 CI 中运行。

## 数据对接

在启动监听的同一进程环境设置：

```powershell
$env:DAILY_AGENT_DB = 'C:/your-agent/data/app.db'
$env:DAILY_RENDERER_PATH = 'C:/your-agent/web/js/markdown.js'
$env:DAILY_WORKFLOW_ROOT = (Get-Location).Path
```

默认数据库路径为当前用户目录下的 `asphalt-agent/data/app.db`；默认渲染器相对数据库的 `web/js/markdown.js`。路径只从配置指向本机已有文件。

监听使用只读数据库连接，监控 `daily` 表：`id,date,author,category,narrative,polished,blocks,updated_at`。常规来源为个人日报；`category` 精确为“周报”时走周报分支，其他非空分类为日报。空分类停止。`date` 须为当天 `YYYY-MM-DD`，上游应仅在审核完成后把可发送版本写到此库。此监听不监听另一个聊天窗口的消息。

保留的通用快照函数还支持 `library` 表，但本工作流 `live_watch.py` 明确关闭该来源，不监控知识库文件上传。

## 配置与首次基线

1. 将 `asphalt-daily/execution-mode.example.json` 复制为同目录的 `execution-mode.json`。示例默认暂停，启用日期故意设在未来，避免误发。
2. 设置实际已安装的 `dingtalk_executable`。Node 不在 PATH 时创建本机 `runtime-paths.json`，内容为 `{"node_executable":"C:/path/to/node.exe"}`。
3. 在 `asphalt-daily` 目录建立当前记录基线：

```powershell
python -c "from agent_watch import scan,DEFAULT_DB,DEFAULT_STATE; print(scan(DEFAULT_DB,DEFAULT_STATE,include_library=False)['status'])"
```

首次结果应为 `BASELINED`，已有记录不会当成新上传。后续不要删除状态文件来实现重试；版本、粘贴、保存及授权记录共同保护重复动作。

4. 在同目录用隐藏输入保存自己的 API 凭据：

```powershell
python -c "import getpass; from jev_secret import save_key; save_key(getpass.getpass('TypeSafe API key: '))"
```

密钥由当前 Windows 用户的 DPAPI 加密保存在仓库根 `.local-secrets/typesafe.dpapi`，此目录被忽略。不要上传加密文件；换用户或换电脑应重新配置。

5. 初次试跑将配置设为 `mode: "test"`、`actual_send: false`、`stop_before_save: true`，并将 `enabled_at` 改成启用时带时区的实际 ISO 时间。试跑只验证时间，不保存。测试模式也只应上传当天已审核报告。
6. 测试合格且明确允许正式保存后，设置 `mode: "daily"`、`actual_send: true`、`stop_before_save: false`、`save_policy: "daily_once"`，更新 `enabled_at`，保持 `schedule_time: "23:30"`。模式组合不完整时停止。

## 启动及生命周期

手动在仓库根启动：

```powershell
python asphalt-daily/live_watch.py
```

绑定智能体：将 `agent_monitor_bridge.py` 接入智能体服务可导入的位置，在服务启动时及请求入口调用 `ensure_started()`。服务进程应继承上述路径环境变量。桥接器使用该服务的 Python 解释器，通过 `--parent-pid` 启动隐藏监听，父进程退出后监听结束。仓库不自动修改其他项目的 `server.py`；接入后验证服务和监听进程的父子关系。

本地轮询约每两秒查看数据库文件签名，写入稳定后才扫描。模型不参与等待；发现可执行新版本才调用 Jev。单实例锁防止同目录多监听重复启动。

`execution-mode.json` 和 `report-day-selection.json` 的变化也会触发待处理事件重检，不需要为恢复开关重新上传日报。

## 模板、排程和结果

- 普通日期自动日报；指定周报日通过同日 `report-day-selection.json` 选择。旧日期的周报选择不影响新一天日报。同日明确不授权则停止。
- 源代码已实现模板分支和周报双栏目，但正式周报路由仍保留阻断，见 `jev_dispatch.route_for`。不要仅改为日报分类绕过该限制。
- 成功依据是钉钉出现“将于 YYYY-MM-DD 23:30 发布”。这表示原生定时保存成功，不表示实际已投递。
- 接收对象和群设置沿用钉钉当前状态，不自动检查或改动。
- `live-watch-status.json` 查看监听状态；`live-runs/<版本摘要>/execution-receipt.json` 查看本次结果。执行时显示桌面进度条，结束后发送一次结果通知。
- 相同事件跳过，同一天同类型已有排程跳过。`UNKNOWN` 或已经派发保存但未读到回执时，不自动重试、不删除授权记录。
- 23:30 已过即停止，不改成立即发或次日。API 503 仅对纯判断请求最多重试一次，不重放桌面输入。

暂停：将配置 `mode` 设为 `paused`，保留检测但不再启动发送。完全禁用启动可在 `asphalt-daily` 创建 `AUTOMATION_DISABLED` 标记；当前执行每次调用工具前也会核对。状态仍须检查，不能把标记创建当成已经撤销派发的动作。

## 模拟验证

在仓库根执行以下两组测试；测试使用模拟桌面和临时数据，不连接 Jev、不发钉钉日志：

```powershell
python -m unittest discover -s asphalt-daily -p 'test_*.py'
python -m unittest discover -s asphalt-daily/wincli-trial -p 'test_*.py'
```

覆盖日期路由、版本去重、同日保存保护、结果不明不重试、剪贴板准备、一次粘贴、时间读回、窗口发现、周报滚动及结果通知。实际钉钉版本兼容性仍需在自己的电脑用不保存模式验证。

## 发布范围

公开代码由明确文件清单导出，修改仅限机器路径、历史事件回退和独立实验入口；具体记录在 `source-manifest.json`。不包含上游智能体完整应用、业务报告、数据库、联系人、密钥、屏幕截图、原始运行日志或第三方二进制。
