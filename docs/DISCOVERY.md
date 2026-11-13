# 环境探测

工作区是 Windows，开始开发时只有原始设计文档。未提供 SSH 或可访问的 Ubuntu 测试环境。开发使用 SQLite 临时数据库、模拟适配器和模拟 tmux/screen 命令响应。

下列生产数据均为 UNKNOWN。部署前请通过只读检查记录实际值。

| 项目 | 建议采集方式 |
| --- | --- |
| Ubuntu、资源与 cgroup | `lsb_release -ds`、`free -m`、`df -h`、`cat /proc/<pid>/cgroup` |
| JVM 用户、启动参数、工作目录、版本 | `ps`、`readlink /proc/<pid>/cwd`、`readlink /proc/<pid>/exe`、脱敏检查启动配置 |
| tmux/screen、会话名、窗口名、socket | 以游戏服务用户运行 `tmux list-sessions`、`tmux list-panes -a` 或 `screen -ls` |
| 游戏端口、RCON 可用性与监听范围 | `ss -ltnp`、脱敏核对 `server.properties` |
| 世界、备份、日志和禁用 Mod 路径 | 只读检查目录、文件权限和备份计划 |
| 面板域名、证书、防火墙与公网入口 | 核对云安全组、Nginx 和本机防火墙 |

采集结果应省略 RCON 密码及其他凭据。
