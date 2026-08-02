# VPS 项目仪表盘 (vps-dashboard)

> 一个轻量、美观、零依赖的 VPS 运维仪表盘：集中展示服务器上所有服务的运行状态，并支持多服务器资源监控。

深色科技风 Web 界面，实时展示项目状态、内存占用、运行时长，以及每台服务器的 CPU / 内存 / 磁盘 / 负载。

在线地址：[https://dash.274747.xyz](https://dash.274747.xyz)（HTTP 自动跳转 HTTPS）

---

## ✨ 功能特性

### 🖥️ 多服务器监控
- 集中监控多台服务器，每台独立卡片展示：**CPU 核数/负载、内存、磁盘（带使用率进度条）、运行时长、在线状态**
- 本机直接采集，远程服务器通过 SSH（paramiko）采集，60 秒缓存避免频繁连接
- 新增服务器只需在 `servers.json` 追加一条配置即可

### 📦 项目状态面板
- 展示服务器上所有服务的运行状态：**运行中 / 已停止 / 异常**
- 实时内存占用（基于 systemd `MemoryCurrent`）、运行时长、项目创建时间
- 项目域名可点击直达，GitHub 仓库快捷入口

### 🎨 其他
- 每 30 秒自动刷新，实时数据
- 深色霓虹风格（cyan/emerald），响应式布局
- 纯 Python 标准库后端 + 原生 HTML/JS 前端，无框架依赖（Vue 3 CDN）

---

## 🏗️ 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12+ 标准库 (`http.server`)，paramiko（远程 SSH 采集） |
| 前端 | 单文件 HTML + Vue 3（CDN），ES5 兼容写法 |
| 部署 | systemd 服务 + Nginx 反向代理（HTTPS, Let's Encrypt） |

## 📁 项目结构

```
vps-dashboard/
├── server.py              # HTTP 服务，监听 127.0.0.1:9090
├── index.html             # 仪表盘前端（单文件）
├── projects.json          # 项目注册表（手动编辑）
├── servers.json           # 服务器注册表（含 SSH 凭据，已 gitignore，勿提交）
├── nginx-vps-dashboard.conf  # Nginx 反代配置模板
├── vps-dashboard.service     # systemd 服务文件
├── start.sh               # 启动脚本
├── test_server.py         # 单元测试
└── docs/                  # 设计文档
```

## 🔧 配置指南

### 添加/移除项目（`projects.json`）
每个项目条目：
```json
{
  "name": "项目名称",
  "path": "/opt/项目路径",
  "port": 3002,
  "domain": "xxx.274747.xyz",
  "description": "项目描述",
  "github_url": "https://github.com/xxx/yyy",
  "service_name": "systemd 服务名"
}
```
> `service_name` 填 systemd 服务名即可自动获取状态/内存/运行时长；Docker 容器项目可留 `null`（仅显示端口活跃状态）。

### 添加服务器（`servers.json`）
```json
{
  "name": "服务器名称",
  "host": "1.2.3.4",
  "port": 22,
  "user": "root",
  "password": "密码",
  "local": false,
  "plan": "1核 / 2G / 40G",
  "note": "备注"
}
```
> `local: true` 表示本机（直接采集）；`local: false` 走 SSH 远程采集。
> ⚠️ 该文件含明文密码，已在 `.gitignore` 排除，服务器上权限建议 `chmod 600`。

## 🚀 部署

```bash
# 1. 安装依赖（Ubuntu 24.04）
pip3 install --break-system-packages paramiko

# 2. 安装服务
cp vps-dashboard.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now vps-dashboard

# 3. Nginx 反代（模板见 nginx-vps-dashboard.conf）
# 4. HTTPS（Let's Encrypt）
certbot --nginx -d dash.274747.xyz --redirect
```

## 🔄 更新日志

### 2026-08-02 — 多服务器监控 + HTTPS
- 🆕 **多服务器模块**：新增 `servers.json` 注册表与 `/api/servers` 接口，支持 SSH 远程采集（paramiko，60s 缓存）
- 🆕 **前端「服务器」区**：每台服务器独立卡片，内存/磁盘进度条（>70% 黄、>85% 红）、负载、运行时长、在线状态
- 🗑️ 移除 TG FileStreamBot 项目；修正 glm2api 域名/端口、freebuff2api 路径等过时信息
- 🔒 dash.274747.xyz 启用 **HTTPS**（Let's Encrypt，自动续期，HTTP 301 跳转）

### 2026-07-03 — 顶部服务器信息修复
- 修复顶部服务器信息条（CPU/内存/磁盘/系统/运行时长）数据映射
- 前端新增项目内存汇总，基于 `/api/projects[*].memory_bytes` 计算

### v0.1.0 — 初始版本
- VPS 项目仪表盘初始版本：项目状态、内存、运行时长、创建时间展示

---

## 📜 License

MIT
