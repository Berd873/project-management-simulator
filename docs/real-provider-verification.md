# 真实模型连接验证

配置模型：`qwen3.7-flash`。用户提供的 `/models` 是网页；实际验证的兼容 API base 为 `https://api.v3.cm/v1`。

- 认证模型列表 GET `/v1/models` 返回 200，包含指定模型。
- 真实 Sponsor 调用通过 DecisionEnvelope、Brief 及角色校验。
- 真实审批调用通过 ApprovalDecision 和 target_id/target_version 校验。
- 首次尝试出现 Schema 校验错误，另一次出现 ReadTimeout；改为发送单一完整 JSON Schema，并在本地配置 60 秒超时后，上述两种调用均通过。

本地 `.env` 被 `.gitignore` 排除；不在本文记录凭证。应用入口自动加载项目 `.env`，现有进程环境配置优先。通用超时默认为 30 秒，可通过 `LLM_TIMEOUT_SECONDS` 设置，范围大于 0 且不超过 120 秒；单次响应上限 2048 tokens。

验证范围仅限模型发现、Sponsor 输出和审批输出。尚未证明该服务上六角色完整模拟全部通过，也不保证未来调用的可用性。平台 pytest 仍使用 Mock/HTTP 替身，不依赖此密钥或网络。
