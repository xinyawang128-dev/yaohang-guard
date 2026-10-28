# 药航守护 AGH 最终工程包 v2.0.1

一句话：让 Agnes 在 AGH 中调用冷链与航程计算工具，为药品配送选择包装和航线，遇到途中异常后根据实际仿真反馈重新规划或停止仿真任务并转人工处理。

先解压，进入 `yaohang_guard_agh_final`，按下表操作。保留原来已能启动的 AGH；这个文件夹是配送工具工程。

| 顺序 | 双击的文件 | 完成标志 |
|---|---|---|
| 1 | `01_本机检查.bat` | MCP、接入／证据、独立手算和 HTTP 检查全部 PASS |
| 2 | `02_接入AGH.bat` | 登记 `yaohang-guard-final`；在 AGH 设置 → MCP 审核、启用 |
| 3 | `03_检查AGH连接.bat` | 当前 revision 连接 ready，发现 8/8 工具 |
| 4 | `04_打开测试指令.bat` | 复制全部文字到 AGH 新会话，以实际 Agnes 模型完成四个用例 |
| 5 | `05_导出AGH会话.bat` | 使用实际 **AGH 会话 ID** 导出 JSONL、HTML；多个会话重复导出 |
| 6 | `07_填写提交信息.bat` | 填队伍信息、实际模型、视频、公开链接及每位成员声明 |
| 7 | `06_整理比赛数据.bat` | 在 `submission` 中生成 CSV、报告、缺项检查和提交 ZIP |

在本项目测试期间，停用 `yaohang-guard`、`yaohang-guard-full`、`yaohang-task-tools`、`yaohang-inject-event` 等旧入口。最终入口只有一个，包含全部八个工具。`inject_event.py` 仍单独存放，供查看事件注入实现；AGH 运行入口统一为 `mcp_server.py`。

## 要提交的代码在哪里

整个 `yaohang_guard_agh_final` 就是可运行作品。`mcp_server.py` 是直接接入 AGH 的代码；`engine.py` 是仿真计算；`inject_event.py` 是异常注入；`task_store.py` 用 SQLite 保留同一任务；`collect_results.py` 汇总数据。

八个工具是 `create_task`、`plan_candidates`、`simulate_plan`、`execute_step`、`inject_event`、`abort_task`、`verify_delivery`、`export_evidence`。closure、wind、sensor_failure 是注入工具的事件类型。

不需要 `pip install`，工具只用 Python 标准库。要求 Python 3.10+；接入需 Node.js 和你已安装、能够打开的官方 AGH。模型调用由 AGH 执行，工具代码不保存或要求输入 API 密钥。

## 数据保存与提交检查

| 位置 | 内容 |
|---|---|
| `evidence/local_tests` | 本机 stdio 和程序检查；未调用 Agnes，不能作为模型证据 |
| `evidence/offline` | `python cli.py --all` 的离线仿真结果 |
| `evidence/agh/tasks` | MCP 实际调用 `export_evidence` 后的任务数据、成功 RPC 参数／结果、代码摘要 |
| `evidence/agh/sessions` | 官方 AGH CLI 导出的原生会话 JSONL 和展示用 HTML |
| `evidence/agh/setup` | 实际登记和连接检查记录；这些记录也不能代替模型执行 |
| `submission` | 比赛数据 CSV、报告、缺项列表、整理 ZIP |

CSV 包含航线、包装、时间、能耗、剩余电量、温度、故障次数、规划调用次数、初始方案角点与 Monte Carlo 指标、任务和会话 ID。温度和能耗都是合成仿真值；传感器故障后的温度不代表实际观测。

四个核心用例覆盖正常配送、封路重规划、时间边界及传感器失败。**ABORTED 可以是正确的安全处理，并不意味着边界／故障测试失败。** 可继续执行 `prompts/AGH附加测试指令.txt` 完成逆风、低电量、高温三项。

汇总脚本核对证据 SHA256、代码版本和固定用例参数，并尝试把每个任务的参数与结果和原生 AGH 事件配对。缺少实际会话时保留“待提供”，不会把本机记录当成 AGH 模型证据。旧 AGH 事件格式、脱敏变化或命名不同可能使自动匹配失败；保留原生 JSONL 和 HTML，按痕迹人工核查。自动匹配与 SHA256 都不能认证真实性，最终由赛事审核。

未补齐时生成 `药航守护_提交草稿.zip`。自动预检查通过后使用 `组别-参赛编号-队伍名称-队长姓名.zip`。仍须检查视频和公开链接能访问、声明属实、模型版本与原始记录一致；程序不能替成员签名或发布公开内容。

## 查看与录屏

双击 `00_打开演示和结果页面.bat` 打开 `http://127.0.0.1:8765`。AGH 测试导出后，刷新“已保存的 MCP 结果”，选择任务查看轨迹和温度曲线。配合 AGH 原始痕迹录制 3–5 分钟视频。页面的“运行离线演示”用于理解模型，会明确标记为离线。

## 如果卡住

- 双击脚本后窗口会停留。复制完整错误文字便于排查。不要直接双击 `mcp_server.py`；stdio 服务没有网页，需要 AGH 发请求。
- 未找到 Python：重新打开终端；默认优先使用 `%LocalAppData%\Programs\Python\Python314\python.exe`，也支持 Python 3.13、PATH 中的 python 或 py。
- AGH 路径默认是 `桌面/agnes-harness-main/packages/cli/dist/local/agnes.mjs`。找不到时，02 会要求粘贴实际路径；它会保存到本机 `agh_connection.json`。
- 若 AGH Web 使用非默认 profile／AGH_HOME，在终端用下方命令指定相同配置。设置或修改服务后，结束当前轮或新建会话再检查；“已启用”不等于当前连接已就绪。
- 提示 unknown task_id：从最终服务重新 `create_task`，用它真实返回的 ID。旧服务任务或 AGH 会话 ID 不能直接作为项目任务 ID。
- 只有 7 个工具：确认运行的是最终服务，重新登记并审核当前 revision，然后运行 03。最终版的 `value` 使用 `anyOf`，避免 AGH 严格 Schema 校验拒绝 `inject_event`。
- 移动工程文件夹后：重新运行 02；新建任务并重新导出测试，勿混用旧路径。
- 8765 端口占用：`python -X utf8 server.py --port 8766 --open`。

```bat
python -X utf8 register_agh.py --agh-cli "C:\实际位置\agnes.mjs" --profile "实际profile"
python -X utf8 check_agh.py --profile "实际profile"
python -X utf8 export_agh_session.py "实际AGH会话ID" --profile "实际profile"
```

需要自定义 AGH_HOME 时，在运行这些脚本前设置实际使用的目录；不要创建另一个空目录来替代已有配置。

## 项目与赛事材料

项目说明：`docs/项目说明.md`。AGH 接入与取证：`docs/AGH接入与取证.md`。视频脚本：`docs/演示视频脚本.md`。分工与披露模板：`docs/成员分工与使用披露模板.md`。填写说明：`docs/提交信息填写说明.md`。

赛事列出的主题为参考方向，不是独立赛道；本项目建议按实际学历选本科生组／硕博组，参考方向为 Agent/Harness 工程，结合数字孪生、生命健康和航空航天应用。

依据官方公开规则整理：AGH 完整能力调用闭环、正常／边界／失败测试、可复现作品、3–5 分钟视频、运行证据、成员声明及公开作品内容。官方页面和通知均要求所有模型调用仅限 Agnes。本工程的模型请求由 AGH 执行，须核对整个实际会话均使用 Agnes 并记录完整版本。ChatGPT/Codex 参与开发辅助已如实披露，允许范围及学生独立完成要求需由团队向主办方确认。规则如更新，以提交页面为准。

- 赛事页面：https://agnes-ai.cn/hackathon
- 大学官方通知：https://www.czu.cn/_t454/2026/1007/c6a177943/pagem.htm
- AGH MCP 文档：https://github.com/AgnesAI-Labs/agnes-harness/blob/main/docs/guide/mcp.zh-CN.md
- AGH 会话导出：https://github.com/AgnesAI-Labs/agnes-harness/blob/main/docs/guide/sessions.zh-CN.md

本机参考数值见 `evidence/local_tests/本机仿真参考数据.csv`，交付验证见 `本机验证说明.txt`。

开发环境已验证本机代码与 Schema；尚未访问你的 Windows、实际 AGH 配置或模型会话。因此请按上面的实际测试步骤产生自己的记录，不能把开发环境检查当成比赛已完成。

## v2.0.1 工程修订

修复保存的 MCP 结果页面；增加封路显示、传感器失效提示、下载和错误恢复。极端逆风返回不可行方案，不再中断规划；已交付任务不能被中止调用覆盖。证据检查核对整个会话模型记录、当前工具目录 revision、材料类型和公开内容平台。

新入口支持 Windows、macOS 和 Linux：

```text
python run.py check
python run.py serve --open
python run.py register --agh-cli /实际路径/agnes.mjs
python run.py check-agh
python run.py export-session 实际AGH会话ID
python run.py collect
```

macOS/Linux 可使用 python3；Windows 继续使用原 BAT。Python 工具保持仅依赖标准库。可选浏览器回归需要开发环境已有 Playwright 与 Chrome，不影响日常运行。

`docs/项目说明.pdf` 可用于上传。`docs/工程验证报告.pdf` 及 `evidence/local_tests` 是本机工程验证，不能代替参赛队伍的真实 AGH 会话。已生成基线对照 CSV；其参数均为合成示例。旧版 AGH 任务不能混入新版证据，请用修订包重新测试。
