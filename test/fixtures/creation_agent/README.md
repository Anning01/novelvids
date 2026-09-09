# 创作助手固定验收集

`cases.json` 固定 30 个案例，10 个图片修改、10 个分镜修改、10 个范围/跨章案例，每个案例重复 3 次，共 90 个实例。连续对话案例包含多个步骤，90 个实例不代表只有 90 次模型请求。冻结内容的 SHA-256 随每次结果保存，修改案例后不能把不同版本混在一次对比里。

## 合成起始状态

每个实例独立创建三章、每章四个 Scene；A–D 属于第一章，E–H 属于第二章，I–L 属于第三章。四个共享资产是林岚、周鸣、站台、值班室，另有仅第三章适用的林岚雨衣形态。Scene 总时长均为 6 秒，已有声音轨道、素材绑定和元数据。部分案例明确从空 Prompt、历史纯文本或手工文本与旧结构不一致的状态开始。

实例内部使用真实会话、AiTask 执行器、两类工具、约束存储及账单记录。新会话步骤仍在同一合成项目内；下一个实例从全新起始状态开始。测试数据库由现有 pytest 隔离夹具管理，不连接真实业务数据库，不生成图片/视频。

## 检查与报告边界

- 自动检查实际业务快照、目标范围、不变字段、内部编号、当前定义、来源范围和改动记录。没有保存的可执行请求计为未完成，不能用成功文案替代。
- 自动记录所有调用、用量、缓存 token、重试信息、首协议事件、首文字/工具事件、完成时间及按核实配置计算的费用。没有用量时费用为未知。
- `quality_review` 初始全部留空。评审者核对请求和实际最终 Prompt，填写 `reviewer`、`reason`、`intent_fulfilled` 及 `intent/continuity/independent_use` 三项 1–5 分。生成模型不能给自己的结果充当独立评审。
- 汇总保留失败与重复尝试，不覆盖旧结果，不挑最好一次。可执行请求单独计算至少 95% 的已评审成功率；歧义/越权案例不混入该分母。三维均分至少 4，任何维度有 1 分不能通过。
- 工具展示的当前 Prompt/定义是证据之一；最终供应商出站请求还要按照主验收矩阵 P10 检查。此评测不替代界面、权限、迁移或视觉成片验收。

## 真实调用前提与费用上限

用户已批准本线程真实验收总预算最多人民币 10 元。必须先核对实际提供服务的一方及其定价；不根据模型名字套用另一平台的价格。测试读取 `test/.test.env`，其次读取进程环境或已加载的根 `.env`：

- `CREATION_AGENT_BASE_URL`、`CREATION_AGENT_API_KEY`、`CREATION_AGENT_MODEL`：连接参数。密钥不进入结果文件。
- `CREATION_AGENT_INPUT_PRICE_CNY_PER_1M`、`CREATION_AGENT_OUTPUT_PRICE_CNY_PER_1M`：经核实的人民币每百万 token 单价。
- `CREATION_AGENT_CACHE_INPUT_PRICE_CNY_PER_1M`：供应商明确报告缓存命中 token 且提供独立价格时填写；预留仍按全部输入的普通价格计算，结算才使用缓存价。
- `CREATION_AGENT_PRICE_SOURCE`：核价来源，不能填一个未经核实的数字。

这是本地评测配置，不替代产品后台配置。代理充值倍率、额外收费或不同的推理 token 计价必须先核实适用性；未经核实不发调用。

每次请求先按序列化输入字节、协议余量和明确输出上限做保守费用预留。估算并非供应商强制消费额度，若服务商支持账户/密钥消费上限，应同时使用其额度控制。请求失败、中断、缺用量或超出预估时保留费用记录并阻止后续请求，先对账；不假定失败免费。原有真实冒烟测试共用同一累计账本。

累计账本与结果位于 仓库已忽略的 `logs/creation-agent-evaluation/`，分别为 `spend.jsonl` 和 `results.jsonl`。文件跨 pytest 运行保留，不能为了继续验收删除或另建账本；进程中断留下的预留必须与供应商账单核对。测试输出包含实例与证据路径。账本不随临时测试目录清理；如工作区被清理，须先恢复既有支出记录，不能重置本线程已消费费用。

## 执行

先运行离线评测工具回归：

```bash
AUTH_ENABLED=false uv run pytest test/test_services/test_creation_agent_evaluation.py test/test_services/test_creation_agent_evaluation_budget.py -o addopts='' -q
```

核实配置、单价和累计已花费用后，执行固定集。不要并行真实实例；工具预算按同一账本串行预留。先遇到硬错误即停止排查，修复后的全部尝试仍保留，未完成 90 个实例时保持未完成。

```bash
AUTH_ENABLED=false uv run pytest test/test_services/test_creation_agent_real_evaluation.py -m real_llm -o addopts='' -q --maxfail=1
```

将实际 `results.jsonl` 路径传入汇总器；它同时读取旁边的累计 `spend.jsonl`：

```bash
uv run python -m test.creation_agent_evaluation_report logs/creation-agent-evaluation/results.jsonl
```

2026-09-05 已完成 `contract-fixed-v5` 的完整 90 实例和 123 步独立评审。结果通过既定门槛：可执行请求成功率 96.08%，意图/连续性/独立可用性均分分别为 4.84/4.86/4.82；固定集报告费用 1.133990 元。后续 `post-quality-fixes-v6` / `v6b` 定向验证评测暴露的问题。所有原始结果、失败和累计费用均追加保留；累计账本 7.176794 元，其中 0.609467 元按用户授权的完整预留保守计入，不冒充供应商确认实扣。`expected_version` 由服务端上下文快照维护，模型工具协议不接收或信任并发版本。独立评审通过证据哈希合并，重复尝试、重复评审或证据哈希不匹配都会拒绝。
