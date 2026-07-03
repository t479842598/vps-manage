# VPS 项目仪表盘 (vps-dashboard)

VPS 上所有项目的运行状态仪表盘，深色科技风 Web 界面。

## 更新日志

### 2026-07-03

- 修复顶部服务器信息条显示，补齐 `CPU`、`总内存`、`已用内存`、`项目内存`、`磁盘`、`系统` 和顶部运行时长的数据映射
- 前端新增项目内存汇总展示，基于 `/api/projects[*].memory_bytes` 计算总项目内存
- 已同步更新到线上 `http://dash.274747.xyz/`，并完成接口与页面可视验证
- 补充 `docs/top-server-metrics.md`，记录顶部信息条的数据来源和验证方法

## 功能

- 📊 展示 VPS 上所有项目的运行状态
- 📍 显示项目地址:端口（可点击跳转）
- 🔗 GitHub 仓库链接（如项目关联了 GitHub）
- 💾 实时内存占用（通过 systemctl MemoryCurrent）
- ⏱️ 运行时长（人性化显示：X天 X小时）
- 📅 项目创建时间
- 🔄 每 30 秒自动刷新

## 技术栈

- **后端**: Python 3.12+ 标准库 (http.server)
- **前端**: 单文件 HTML + Vue 3 + Naive UI
- **设计**: 深色科技风，cyan/emerald 霓虹配色，毛玻璃卡片

## 项目结构

```
vps-dashboard/
├── server.py              # HTTP 服务，监听 127.0.0.1:9090
├── index.html             # 仪表盘前端
├── projects.json          # 项目注册表（手动编辑）
├── nginx-vps-dashboard.conf  # Nginx 反代配置模板
├── vps-dashboard.service     # systemd 服务文件
├── start.sh               # 启动脚本
├── test_server.py         # 单元测试
└── .lrnev/                # 治理记录
```

## 快速开始

### 本地开发

```bash
# 安装依赖（零外部依赖，仅 Python 3.12+）
python server.py           # 启动在 127.0.0.1:9090

# 运行测试
python -m pytest test_server.py -v
```

### VPS 部署

```bash
# 1. 克隆项目
cd /opt && git clone https://github.com/t479842598/vps-manage.git vps-dashboard

# 2. 编辑项目注册表
vim /opt/vps-dashboard/projects.json

# 3. 启动服务
cp /opt/vps-dashboard/vps-dashboard.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now vps-dashboard

# 4. 配置 Nginx 反代（可选，推荐通过子域名访问）
cp /opt/vps-dashboard/nginx-vps-dashboard.conf /etc/nginx/sites-available/vps-dashboard
# 编辑 server_name 为你的域名
ln -s /etc/nginx/sites-available/vps-dashboard /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

## 项目注册表 (projects.json)

```json
{
  "projects": [
    {
      "name": "项目名称",
      "path": "/opt/项目路径",
      "port": 8000,
      "description": "项目简介",
      "github_url": "https://github.com/user/repo",
      "service_name": "systemd服务名"
    }
  ]
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| name | ✅ | 项目名称 |
| path | ✅ | VPS 上的项目路径 |
| port | ✅ | 服务端口 |
| description | ✅ | 项目简介 |
| github_url | ❌ | GitHub 仓库地址（有则显示链接） |
| service_name | ❌ | systemd 服务名（用于采集实时数据） |

## API

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 返回仪表盘 HTML |
| `/api/projects` | GET | 返回项目数据 JSON（含实时指标） |
| `/health` | GET | 健康检查 |

## 安全

- server.py 仅监听 `127.0.0.1:9090`，不直接暴露到公网
- 通过 Nginx 反代对外提供服务（可加 SSL）
- 不影响 VPS 上其他服务
