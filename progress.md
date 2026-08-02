## 2026-07-03 - Task: 修复顶部服务器信息显示并更新到服务器
### What was done
- 修复了仪表盘顶部服务器信息条的数据映射，让页面直接消费现有 `/api/server` 返回值并显示运行时长、CPU、内存、磁盘和系统信息。
- 在前端补上了“项目内存”汇总，使用 `/api/projects` 的 `memory_bytes` 计算总项目内存，并避免轮询请求互相覆盖显示结果。
- 已将修复后的页面文件同步到服务器 `http://dash.274747.xyz/`，并完成线上接口与页面可视验证。

### Testing
- `python -m pytest test_server.py -v`
- 本地 mock 接口验证：
  - `http://127.0.0.1:19090/api/server`
  - `http://127.0.0.1:19090/api/projects`
  - `npx -y -p playwright node %TEMP%\\vps_dashboard_playwright_check.js`
- 线上验证：
  - `http://dash.274747.xyz/api/server`
  - `http://dash.274747.xyz/api/projects`
  - `npx -y -p playwright node %TEMP%\\vps_dashboard_live_check.js`
- 服务器同步校验：
  - `local_md5=5c8bb42abe6a7a8fa30f48112456673f`
  - `remote_md5=5c8bb42abe6a7a8fa30f48112456673f`

### Notes
- `index.html`：新增顶部服务器信息映射函数与项目内存汇总逻辑，保持现有 ES5 写法和轮询结构。
- `docs/top-server-metrics.md`：记录顶部信息条的数据来源、验证方法和当前实现边界。
- `progress.md`：追加本轮修复、验证和服务器同步记录。
- 回滚方式：在服务器执行 `cp /opt/vps-dashboard/index.html.bak.20260703_095634 /opt/vps-dashboard/index.html` 可回退本轮页面更新；本地回滚点可直接用 `git checkout -- index.html docs/top-server-metrics.md progress.md`。

## 2026-07-03 - Task: 补充更新日志并提交 GitHub
### What was done
- 在 `README.md` 增加本轮上线修复的更新日志，方便直接在 GitHub 首页查看本次变更内容。
- 准备将顶部服务器信息修复相关文件提交到 GitHub，保持本地、服务器和仓库记录一致。

### Testing
- `git diff -- index.html README.md docs/top-server-metrics.md progress.md`
- `python -m pytest test_server.py -v`
- 已复用上一轮线上验证结果：`http://dash.274747.xyz/` 顶部信息条显示正常

### Notes
- `README.md`：新增 2026-07-03 更新日志，概括顶部信息显示修复与线上验证结果。
- `progress.md`：追加本轮“更新日志 + GitHub 提交”记录。
- 回滚方式：本地可执行 `git checkout -- README.md progress.md` 回退本轮日志变更；若已推送，则回滚点以本轮提交 SHA 为准。

## 2026-08-02 - Task: 多服务器模块 + 项目列表更新
### What was done
- 移除 TG FileStreamBot 项目条目。
- 修正过时项目信息：glm2api 域名改为 glm2api.274747.xyz、端口改为 8001；freebuff2api 路径改为 /opt/freebuff2apiNew；Open WebUI 改为实际运行的 Deeix Chat WebUI 容器；DeepSeek Proxy 描述补充 dsapi/ds2pi 子域名。
- 新增多服务器支持：`servers.json` 注册服务器（本机 VPS-1H-2G-4T + 阿里 182.92.127.90），server.py 新增 `/api/servers` 端点（本机本地采集、远程走 paramiko SSH），index.html 新增"服务器"模块卡片（CPU/内存/磁盘进度条/负载/运行时长/在线状态）。
- 服务器已安装 paramiko 5.0.0，vps-dashboard 服务已重启，线上 dash.274747.xyz 已生效。

### Testing
- `/usr/bin/python3` 语法 + JSON 校验通过。
- 本地 9090 冒烟验证 `/api/servers`、`/api/projects` 结构。
- 线上验证 `http://127.0.0.1:9090/api/servers`：两台服务器均 online，阿里（Alibaba Cloud Linux 3, 2核, 内存 46.6%, 磁盘 64%, 运行 60天）数据采集正常。
- 页面 `HTTP 200`，TG 条目已移除，glm2api 新域名已生效。

### Notes
- `servers.json` 含 SSH 凭据，已加入 `.gitignore`（避免误推 GitHub），服务器上权限 600。
- paramiko 通过 `pip3 install --break-system-packages paramiko` 安装（Ubuntu 24.04 externally-managed 环境）。
- 新增服务器只需在 `servers.json` 追加条目（local: false + SSH 凭据）。
