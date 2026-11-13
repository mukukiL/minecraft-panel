# API

开发模式可通过 `/docs` 查看 OpenAPI。API 前缀为 `/api/v1`。错误响应为 `application/problem+json`，包含 `code` 和 `request_id`。所有认证 API 响应禁用缓存。

| 方法与路径 | 权限 | 请求与结果 |
| --- | --- | --- |
| GET `/healthz`（无前缀） | 公共 | `{"ok":true}` |
| POST `/auth/login` | 匹配 Origin | JSON `username,password`。设置会话 Cookie，返回用户、CSRF 令牌、绝对过期时间 |
| GET `/auth/me` | 登录 | 当前用户、权限、CSRF 令牌和绝对过期时间 |
| POST `/auth/logout` | 登录 | 撤销当前会话，204 |
| POST `/auth/password` | 登录 | JSON `current_password,new_password`，204 后重新登录 |
| GET `/users?after=0` | admin | 分页 `items,next_cursor` |
| POST `/users` | admin | JSON `username,password,role`，201 |
| PATCH `/users/{id}` | admin | JSON `enabled` 和/或 `role`。角色或启用状态变更会撤销该用户所有会话 |
| POST `/users/{id}/password` | admin | JSON `password`。重置并撤销该用户所有会话，204 |
| GET `/server/status` | 登录 | 状态、适配器、可用控制项、上传能力 |
| POST `/server/start` | operator / admin | 空请求体或空 JSON |
| POST `/server/stop` | operator / admin | JSON `{"confirm":"STOP"}` |
| POST `/server/restart` | operator / admin | JSON `{"confirm":"RESTART"}` |
| GET `/console/logs?limit=100` | 登录 | 最近日志，最多 200 行 |
| PUT `/mods/upload/{filename}` | operator / admin | 单个原始 JAR 字节流，`Content-Type: application/java-archive`，201 |
| POST `/auth/ws-ticket` | 登录 | 30 秒单次票据 |
| WS `/ws`（无前缀） | 登录、匹配 Origin、单次票据 | 首帧 `{"type":"auth","ticket":"..."}`。认证后返回 `ready` 及日志快照。 |

登录后所有状态变更接口需发送正确的 `Origin` 和 `X-CSRF-Token`。浏览器自动设置 Origin 和 Cookie。重放或跨会话使用 WS ticket 会失败。WS 仅用于读取日志。

控制接口同步等待状态确认，锁忙返回 409。启动或停止超时后，先检查状态及日志，再决定是否手动处理。当前实现不持久化控制任务或幂等键，客户端不应自动重试。

上传拒绝重名并返回 SHA-256，真实 profile 下仅写 `mods-disabled`。模拟模式验证字节流并返回 `location=simulated`。ZIP 容器检查只验证基本结构，上传成功不代表代码可信或与 Fabric 兼容。
