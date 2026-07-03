# 顶部服务器信息条说明

## 数据来源

- `CPU`：使用 `/api/server` 的 `cpu_cores` 与 `load_1m` 组合显示
- `总内存`：使用 `/api/server.ram_total_human`
- `已用内存`：使用 `/api/server.ram_used_human` 与 `ram_percent`
- `项目内存`：汇总 `/api/projects[*].memory_bytes` 后在前端格式化显示
- `磁盘`：使用 `/api/server.disk_used_human`、`disk_total_human` 与 `disk_percent`
- `系统`：使用 `/api/server.kernel`
- 顶部摘要运行时长：使用 `/api/server.uptime_human`

## 验证要点

1. 先检查 `http://dash.274747.xyz/api/server`
2. 再检查 `http://dash.274747.xyz/api/projects`
3. 最后直接打开 `http://dash.274747.xyz/`，确认顶部信息条各卡片都有值

## 当前实现边界

- 只修正顶部服务器信息条的数据映射和项目内存汇总
- 不改动项目卡片布局
- 不改动后端接口契约
