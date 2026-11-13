# Ubuntu 部署

先完成 [环境探测](DISCOVERY.md)，在隔离的测试目录和测试会话验证。以下示例需要替换尖括号占位符。生产尚未部署。

## 1. 安装及数据库

以管理员身份将代码和在本机构建的 `frontend/dist` 发布到 `/opt/mc-panel/current`。代码、虚拟环境和构建产物由 root 管理。服务器运行时只需 Python、Nginx 及所需的多路复用器。

```bash
cd /opt/mc-panel/current/backend
uv sync --locked --no-dev --python /usr/bin/python3
sudo install -d -m 0700 -o <PANEL_USER> -g <PANEL_GROUP> /var/lib/mc-panel
```

在 root 持有的 `/etc/mc-panel/panel.env` 设置以下变量。将文件设为 `0640 root:<PANEL_GROUP>`。先留空 profile 变量可只验收登录和用户管理。

```dotenv
MC_PANEL_ENV=production
MC_PANEL_PUBLIC_ORIGIN=https://<PANEL_DOMAIN>
MC_PANEL_DB_PATH=/var/lib/mc-panel/panel.db
# MC_PANEL_PROFILE_PATH=/etc/mc-panel/profiles/main.toml
MC_PANEL_UPLOAD_LIMIT=33554432
```

以非 root 的面板用户在交互终端运行以下命令。先导入与 systemd 一致的配置。

```bash
cd /opt/mc-panel/current/backend
set -a
. /etc/mc-panel/panel.env
set +a
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli create-admin
```

## 2. systemd

保存为 `/etc/systemd/system/mc-panel.service`，替换用户与组。

```ini
[Unit]
Description=Minecraft Panel API
After=network.target

[Service]
User=<PANEL_USER>
Group=<PANEL_GROUP>
WorkingDirectory=/opt/mc-panel/current/backend
EnvironmentFile=/etc/mc-panel/panel.env
ExecStart=/opt/mc-panel/current/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips=127.0.0.1 --no-access-log --ws-max-size 16384 --ws-max-queue 4
UMask=0077
NoNewPrivileges=true
MemoryAccounting=true
Nice=5
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mc-panel
sudo systemctl status mc-panel
```

## 3. Nginx 和 TLS

先为域名签发证书。把以下片段放在 Nginx 的 `http` 配置范围内。将 MIME 配置保留在 Nginx 主配置中。若改变应用上传上限，调整 `client_max_body_size`。

```nginx
map $http_upgrade $mc_panel_connection {
    default upgrade;
    '' close;
}

server {
    listen 80;
    server_name <PANEL_DOMAIN>;
    return 301 https://<PANEL_DOMAIN>$request_uri;
}

server {
    listen 443 ssl;
    server_name <PANEL_DOMAIN>;
    ssl_certificate <CERT_CHAIN_PATH>;
    ssl_certificate_key <CERT_KEY_PATH>;
    ssl_protocols TLSv1.2 TLSv1.3;
    server_tokens off;
    root /opt/mc-panel/current/frontend/dist;
    access_log off;
    client_max_body_size 8k;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy no-referrer always;
    add_header Content-Security-Policy "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'" always;

    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;

    location / {
        try_files $uri /index.html;
    }
    location ~ /\. {
        return 404;
    }
    location /api/ {
        proxy_read_timeout 280s;
        proxy_pass http://127.0.0.1:8000;
    }
    location ^~ /api/v1/mods/upload/ {
        client_max_body_size 32m;
        proxy_request_buffering off;
        proxy_http_version 1.1;
        proxy_pass http://127.0.0.1:8000;
    }
    location = /healthz {
        proxy_pass http://127.0.0.1:8000;
    }
    location = /ws {
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $mc_panel_connection;
        proxy_read_timeout 75s;
        proxy_pass http://127.0.0.1:8000;
    }
}
```

运行 `sudo nginx -t` 后重载，使用 `curl --fail https://<PANEL_DOMAIN>/healthz` 验收。核对公网安全组、SSH 来源限制、游戏端口与仅回环监听的 API 端口。代理必须覆盖客户端发来的转发头。

## 4. 接入隔离的 tmux/screen 测试会话

1. 用 [profile 样例](profile.example.toml) 填入已经确认的绝对路径、会话、工作目录、启动入口和端口。root 持有 profile 和 launcher，父路径同样不能由面板写入。launcher 使用固定参数并通过 `exec` 交给 Java。
2. tmux 需要 3.2 或更高版本并支持 `-N`。使用面板 cgroup 外现有的、面板用户能访问的明确 socket，保留独立的常驻会话，使游戏会话退出时 tmux server 仍在。被控会话须仅包含一个目标窗口和 pane。不要给 socket 授予宽松权限。 [tmux 手册](https://man7.org/linux/man-pages/man1/tmux.1.html)
3. `allow_tmux_stop` 默认关闭。在专用的单 pane 测试会话验证前台 Java、工作目录、关闭后会话消失和端口释放，再决定是否启用固定 `stop`。screen 只能判断会话有无。RCON 尚未接入。
4. 提前确认 `logs/latest.log` 的读取权限及已存在的 `mods-disabled/` 的写权限。上传会逐级拒绝符号链接并原子发布。禁用目录及其父级需防止非受信任的本地用户移动、替换或挂载。
5. 重启面板并确认只读状态。在测试会话依次验证启动、重复启动拒绝、优雅停止、重启、重启面板时测试 JVM 持续运行、日志刷新、上传拒绝覆盖。测量空闲和并发登录期间内存；先确认 JVM 独立归属，再决定资源上限。

同一 Unix 用户有权访问该用户的 tmux socket 和文件，面板进程被攻破时该权限仍然存在。生产更强的隔离需要独立用户及受限 helper。公网接入前还应安排备份、还原演练及资源实测。升级时先用 SQLite 在线备份功能或停面板后做一致性备份，再迁移；回滚时切回兼容的代码与 DB 快照。不要在 Uvicorn 运行时只复制 WAL 数据库的主文件。
