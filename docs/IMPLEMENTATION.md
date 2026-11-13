# MVP 实现与设计差异

| 领域 | 本地 MVP 的决定 |
| --- | --- |
| 控制 | 单 profile、单 Uvicorn worker。同步等待确认，进程内锁与 Linux 文件锁防并发。无持久任务或幂等键，前端禁用重复提交。专用 tmux 会话必须用固定 launcher `exec` 到前台 Java，验证实际监听归属后才报告运行。screen 只读。 |
| 安全 | 按追加任务启用三种角色。HTTPS 用 `__Host-` Cookie，回环 HTTP 开发用独立名称。会话 8 小时空闲、7 天绝对超时，仪表盘后台轮询不延长空闲期。登录限流保存在单进程内，重启后清空。 |
| 日志 | REST 与已验证的 WebSocket 使用有界快照。Vue 采用 5 秒轮询。WebSocket 支持日志推送、Cookie、Origin、单次票据及会话撤销检测。 |
| Mod | 单文件原始 PUT 流替代批量 multipart，限制请求体、文件名和 ZIP 基本结构，按 SHA-256 返回结果。Linux 使用逐级 nofollow、临时文件与原子无覆盖发布。仅进入禁用区。 |
| 前端 | Vue 3 + TypeScript + Vite + Vue Router，轻量 CSS 和 Vue 内存响应式状态。 |
| 范围 | 备份、整合包、RCON、任意控制台命令、Mod 启用、作业持久化、详细玩家与 TPS 指标留待后续阶段。 |

tmux 前台复核与发送固定 `stop` 之间仍存在极短的本机状态变化窗口。专用会话及直接 `exec` 的 launcher 可降低风险。使用长期保留的交互式 shell、共享窗口或任意 pane 的现场配置需要先调整或等待 RCON 接入。配置读取和服务启动不会自动发出游戏控制指令。

Ubuntu 生产环境的 cgroup、tmux/screen、资源和 Nginx 配置需按 [部署说明](DEPLOY.md) 验收。
