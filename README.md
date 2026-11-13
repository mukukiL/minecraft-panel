# Minecraft Panel

基于 FastAPI、Vue 3 和 SQLite 的 Minecraft Fabric 服务器管理面板。支持管理员初始化、登录与退出、密码修改、角色管理、服务器状态、启停重启、日志与 Mod 上传。开发模式默认使用进程内模拟服务。

## 本地启动

安装 Python 3.11 或更高版本、uv 和 Node.js 22.12+ 或 24+。从项目根目录执行。仅需自定义配置时，才需要复制 `.env.example` 为 `.env`。

后端终端

```powershell
cd backend
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked python -m app.cli create-admin
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers --no-access-log --ws-max-size 16384 --ws-max-queue 4
```

管理员命令仅接受交互式输入，密码需要输入两次。数据库初始化时没有预设账号。密码需 12–128 个字符。

前端另开终端

```powershell
cd frontend
npm ci
npm run dev
```

浏览器打开 [http://localhost:5173](http://localhost:5173)。后端健康检查位于 [http://127.0.0.1:8000/healthz](http://127.0.0.1:8000/healthz)。

## 检查

```powershell
cd backend
uv run --locked pytest -q
uv run --locked ruff check
uv run --locked mypy --platform linux app
```

```powershell
cd frontend
npm ci
npm run build
```

Windows 会跳过依赖 Linux `dir_fd` 的文件系统测试。服务器控制的单元测试用模拟命令响应。请在隔离的 Ubuntu 环境验证真实适配器和文件落盘。

## 使用范围

- viewer 查看状态和日志，operator 另有控制和上传权限，admin 另有用户管理权限。
- 生产需 HTTPS，使用 Secure、HttpOnly、SameSite=Strict 会话 Cookie。开发 HTTP 仅允许回环 Origin，前端不持久化凭据或令牌。
- 开发服务器启停、重启和上传默认只做模拟。真实 tmux 需配置现有 socket、独立 cgroup 和固定 launcher。screen 仅提供会话探测，日志与上传由文件层提供。
- 当前采用有界日志快照、同步控制和单文件上传。RCON、备份、整合包、Mod 启用和持久控制任务属于后续范围。

## Ubuntu 部署概要

1. 在本地执行 `npm ci` 和 `npm run build`，将 `frontend/dist` 交给 Nginx 托管。
2. 参考 [环境变量样例](.env.example)，设置 `MC_PANEL_ENV=production`、实际的 HTTPS Origin 及面板用户专用的数据库路径。以非 root 面板用户运行数据库迁移并初始化管理员。
3. 使用 systemd 启动单 worker Uvicorn，监听 `127.0.0.1:8000`。由 Nginx 终止 TLS，将 `/api/`、`/healthz` 和 `/ws` 反代给 Uvicorn。Nginx 应覆盖转发头，Uvicorn 仅信任本机代理。
4. 参考 [服务器配置样例](docs/profile.example.toml)，先在隔离的 Ubuntu 测试会话验证启停、日志与上传。确认 tmux 位于面板服务的 cgroup 外，且固定启动脚本由 root 管理，再接入现有服务器。

开发模式可访问后端的 `/docs` 查看 API。

## 开源许可证

本项目采用 [MIT 许可证](LICENSE)。
