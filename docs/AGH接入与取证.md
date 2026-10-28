# AGH 接入与取证

接入位置是你已运行的 Agnes Harness。不要再安装另一套 AGH，也不要把模型密钥写进项目代码。

## 最终入口

在固定工程位置双击 02_接入AGH.bat。脚本实际调用官方 CLI 的 mcp list/get，再按是否存在最终服务执行 add 或 update；更新携带最新 revision，白名单列出八个工具。

stdio 命令使用运行脚本的真实 Python 可执行文件，参数逐项为：`-u`、`-X`、`utf8`、本工程 `mcp_server.py` 完整路径、`--database` 与本工程 SQLite 路径、`--evidence-dir` 与本工程 `evidence/agh/tasks` 路径。所有参数用 argv 传递，路径含空格或中文也不需手动拼接命令。

在 AGH 设置 → MCP 查找 yaohang-guard-final，审核登记内容并启用。登记或更新后以当前 revision 的信任状态为准。结束当前轮或新开会话，再运行 03_检查AGH连接.bat，读取实际 get/status/tools。工具列表完整仅证明当前能发现工具，还需要模型真正调用。

测试时停用旧的 yaohang 入口，任务 ID 只使用最终入口真实返回的值。同一个任务被多个工具调用时由 SQLite 保存当前位置和资源；MCP 进程重启也不重新创建该任务。

## 模型与执行

在 AGH 选择你实际可用的 Agnes 模型，例如已经配置的 Agnes 模型；完整版本以实际会话导出的 request/sent 等记录为准。API key 在 AGH 自身的配置中使用，项目不直接向模型端点发送请求。

用 04 打开的指令执行四个核心用例。遇到 AGH 原生审批时，按已授权的本地仿真范围核对并处理；审批拒绝、工具未启用、模型无额度或网络错误都要保留真实失败反馈。可按 prompts/01–04 分开完成，每个测试独立 create_task。

任务完成后工具 export_evidence 生成 `evidence/agh/tasks/mcp_<task_id>.json`。不要编辑这个文件；若需更改测试条件，创建新任务重新执行。任务 JSON 不含模型身份认证，因此还需要 AGH 原始记录。

## 官方会话导出

双击 05_导出AGH会话.bat，脚本先列出当前 profile 中的会话。填写执行测试的 AGH 会话 ID，不是 12 位项目 task_id。官方命令为：

```text
node <agnes.mjs> sessions --json
node <agnes.mjs> export <AGH会话ID> --format agnes -o <session.jsonl>
node <agnes.mjs> export <AGH会话ID> --html -o <session.html>
```

脚本保留官方默认脱敏，不使用 --raw。多个会话分别导出；与 Web 使用同一 profile／AGH_HOME。默认 profile 未配置时不强行指定名称。

导出的 JSONL 是完整原生 EventEnvelope 行，至少有 session/start、模型请求、模型发起的 tool/call 和对应 tool/result。整理器匹配实际参数、工具结果和 export_evidence 的 SHA256。HTML 便于评审查看，不用纯文本“成功”描述替代实际痕迹。

## 证据范围

任务 SHA256 检查内容是否变化，代码摘要检查使用版本，原生事件匹配帮助定位调用链。它们不提供数字签名或身份认证。赛事页面说明运行材料留存不等于自动认定真实性；参赛团队和评审仍需核对原始来源、实际模型参与、视频和材料。

参考官方文档：
- https://github.com/AgnesAI-Labs/agnes-harness/blob/main/docs/guide/mcp.zh-CN.md
- https://github.com/AgnesAI-Labs/agnes-harness/blob/main/docs/guide/sessions.zh-CN.md

## 修订版检查

连接检查要求状态 ready、服务 revision 与工具目录 catalog revision 均为当前值。模型检查覆盖导出会话中所有已观察到的模型记录；出现其他模型或无法识别的模型请求时保持待核查。仅名字匹配不能认证模型提供商。导出的会话 ID 必须与请求一致；HTML 文件不存在时明确报告失败。
