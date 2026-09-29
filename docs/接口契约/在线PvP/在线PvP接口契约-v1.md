# 在线 PvP 接口契约（v1，待实施冻结）

> 状态：**待实施冻结**。本文件在后端和前端开始编写在线 PvP 代码前，作为双方唯一的接口依据。实现完成后，应由 `tests/test_online_contract.py` 将本文件的形状与关键语义锁定。  
> 前置：[产品方向与核心功能](../../产品方案/01-产品方向与核心功能.md)、[在线双人对战架构方案](../../产品方案/02-在线双人对战架构方案.md)、[03-在线 PvP 执行方案 README](../../产品方案/03-在线PvP执行方案/README.md)。  
> 边界：本文只约定新的在线房间 API；现有 [api-contract.md](../本地对局/api-contract.md) 的 `/api/game` 人机与冻结热座语义不在本文修改。

## 1. 契约目标与硬性边界

在线 PvP 的两位玩家在不同浏览器中操作服务端同一份 `BattleState`。`BattleState` 和 `public_battle_state(battle, viewer)` 仍是卡牌规则、行动合法性与手牌隔离的唯一真源。

以下边界不得突破：

- 新接口只位于 `/api/rooms`；不得给旧 `/api/game` 增加 `room_id`、联网身份或房间状态参数。
- 客户端**不得**传 `seat`、`viewer`、玩家 1/2、赢家或任何可决定身份与视角的字段；服务端必须从本浏览器的座位凭证确定身份和 `viewer`。
- 前端只依据服务端返回的 `room`、`battle` 和 `battle.available_actions` 渲染与启用按钮；不得自行结算伤害、能量、回合或响应。
- 所有在线动作均要带 `revision`，服务端必须在同一写事务中比较、执行并递增它。
- 所有房间状态读取及动作响应均为当前请求者视角；任何响应中都不得出现对手手牌、牌库顺序、座位凭证原文或数据库内部 ID。

## 2. 通用传输规则

### 2.1 基础 URL、编码与响应信封

- 所有路径以同源 `https://<host>` 为基准，JSON 请求使用 `Content-Type: application/json; charset=utf-8`。
- 正常响应和业务错误响应均为 JSON；成功、失败和 HTTP 状态码必须同时正确，不以 HTTP 200 承载失败。
- 所有本契约定义的 JSON 响应使用同一信封：

```json
{ "ok": true, "data": {}, "error": null }
```

```json
{
  "ok": false,
  "data": null,
  "error": { "code": "ROOM_NOT_FOUND", "message": "房间不存在或已失效" }
}
```

固定规则：

- `ok` 恒为布尔值；成功时 `true` 且 `error` 恒为 `null`，失败时 `false` 且 `error` 恒为对象。
- `error.code` 是稳定的大写机器码；`error.message` 是可直接显示的中文完整句。
- 成功时 `data` 恒为对象（即使没有额外业务结果）；结构性失败时 `data` 恒为 `null`。
- 仅 `409 STALE_STATE` 与 `422 ACTION_REJECTED` 例外：为了让前端立即复位，`data` 必须携带最新的房间快照，定义见第 4 节。
- 响应必须设置 `Cache-Control: no-store`，避免浏览器、代理或返回缓存保存私有手牌。

### 2.2 座位凭证与 Cookie

创建房间和成功加入房间时，服务端为该浏览器写入座位凭证（或其服务端 Session 映射）。浏览器后续同源请求自动携带该 Cookie；前端 JavaScript 不读取、不拼接、不存储该凭证。

- 凭证 Cookie 必须为 `HttpOnly`、`Secure`、`SameSite=Lax`；生产环境只能经 HTTPS 传输。
- 数据库只能保存凭证摘要，不能保存或响应可直接使用的凭证原文。
- 邀请链接只包含 `room_code`，不包含任何座位凭证。
- 前端同源 `fetch` 使用默认的 `credentials: "same-origin"`；跨域调用不是 v1 支持范围。
- 一个浏览器已持有某房间座位后，不能用该浏览器再加入同一房间的另一座位。

## 3. 稳定枚举与标识符

| 名称 | 固定取值 / 形状 | 说明 |
|---|---|---|
| `room.status` | `WAITING` / `HERO_SELECT` / `PLAYING` / `FINISHED` / `EXPIRED` | 房间流程状态；不是战斗回合。 |
| `battle.phase` | `PLAYER_TURN` / `ENEMY_TURN` / `RESPONSE` / `VICTORY` / `DEFEAT` / `DRAW` | 沿用 `public_battle_state`；双方真人对局中 `ENEMY_TURN` 代表轮到另一座位。 |
| `battle.mode` | 恒为 `pvp` | 在线房间不得返回或接受 `pve`。 |
| `battle.viewer` | `player` / `enemy` | 服务端根据座位写入，客户端只读。 |
| `response.kind` | `attack` / `play` / `null` | 沿用现有公开战斗状态。 |
| `respond.action` | `dodge` / `negate` / `pass` | 仅响应接口请求体使用。 |
| `rematch.status` | `NOT_AVAILABLE` / `WAITING_CONFIRMATION` | `NOT_AVAILABLE` 用于非 `FINISHED`，也用于双方确认后已进入下一轮盲选的快照。 |
| `room_id` | 不透明字符串 | API 资源标识；不等同于数据库自增主键，客户端不得解析。 |
| `room_code` | 随机、不可预测的短字符串 | 邀请/加入使用；不代表座位权限。 |
| `revision` | 非负整数 | 某房间共享状态版本，创建时为 `0`，每次成功改变房间可见状态的写入严格加 `1`。 |

除本文明确允许的可扩展枚举外，v1 实施不得新增、删除或重命名枚举成员。前端遇到未来未知枚举必须使用文本兜底，不得崩溃。

## 4. 统一房间快照

除目录类接口外，所有成功响应的 `data` 都是一个 `RoomSnapshot`。动作成功后返回的是操作完成后的快照；轮询 `GET` 返回当前快照。

```json
{
  "room": {
    "room_id": "r_01J...",
    "room_code": "K7P4WQ",
    "status": "PLAYING",
    "revision": 12,
    "match_number": 1,
    "created_at": "2026-09-28T14:00:00Z",
    "updated_at": "2026-09-28T14:04:12Z",
    "expires_at": "2026-09-28T16:00:00Z",
    "invite_url": "/join?room_code=K7P4WQ"
  },
  "you": {
    "nickname": "小王",
    "hero_key": "warrior",
    "hero_locked": true,
    "rematch_confirmed": false
  },
  "opponent": {
    "nickname": "小李",
    "joined": true,
    "hero_locked": true,
    "rematch_confirmed": false
  },
  "battle": { "phase": "PLAYER_TURN", "...": "见第 5 节" },
  "rematch": { "status": "NOT_AVAILABLE", "requested_by": null }
}
```

### 4.1 `room` 对象

所有字段恒在且不可为 `null`，除非另有版本升级：

| 字段 | 类型 | 规则 |
|---|---|---|
| `room_id` | string | 对当前已授权浏览器稳定；只能用于本契约的路径参数。 |
| `room_code` | string | 供展示、复制和再次分享；不是授权凭证。 |
| `status` | enum | 见第 3 节。 |
| `revision` | integer | 与本快照其他字段完全对应。 |
| `match_number` | integer | 从 `1` 开始；每一局双方确认后进入新盲选时加 `1`。 |
| `created_at` / `updated_at` / `expires_at` | UTC RFC 3339 string | 后端统一生成；前端不得自行延长过期时间。 |
| `invite_url` | string | 同源相对路径，仅承载 `room_code`，恒不含凭证。 |

### 4.2 `you` 和 `opponent` 对象

`you` 恒为对象且字段恒在；`opponent` 在 `WAITING` 时为 `null`，其余状态恒为对象。

| 字段 | 位置 | 类型 | `null` 规则与信息边界 |
|---|---|---|---|
| `nickname` | `you` / `opponent` | string | `you` 恒非空；对手未加入时没有 `opponent` 对象。 |
| `hero_key` | `you` | string / `null` | 未锁定时 `null`，锁定后仅向本人展示自己的选择。 |
| `hero_locked` | `you` / `opponent` | boolean | 对手英雄锁定前只暴露布尔值，绝不通过其他字段泄露英雄。 |
| `joined` | `opponent` | boolean | `opponent` 对象存在时恒为 `true`；保留该字段以减少前端状态分支。 |
| `rematch_confirmed` | `you` / `opponent` | boolean | 仅 `FINISHED` 有业务意义；其他状态恒为 `false`。 |

**盲选泄露禁令：** 当 `room.status` 是 `WAITING` 或 `HERO_SELECT` 时，响应不得在 `battle`、`opponent`、日志、错误消息或任意扩展字段中出现对方 `hero_key`、英雄名、英雄数值、起手牌、先后手或由英雄选择推导的信息。

### 4.3 `battle` 与 `rematch`

- `battle` 在 `WAITING` 与 `HERO_SELECT` 恒为 `null`；在 `PLAYING` 与 `FINISHED` 恒为对象，且精确复用现有 `public_battle_state(battle, viewer)` 的 v1 形状。
- 在线 `battle.mode` 恒为 `pvp`；`battle.viewer` 必须由服务端填入当前请求者的真实视角；前端不得把 `player` 或 `enemy` 假定为“我”。
- `battle.player.hand` 与 `battle.enemy.hand` 中恰有一方存在：哪一方存在由 `battle.viewer` 决定；对手手牌字段必须缺失，不能用空数组代替。
- 在线 `battle.enemy.intent` 恒为 `null`；在线页面不得渲染 AI 意图和难度。
- `battle.result` 在未结束时恒为 `null`，在 `FINISHED` 时恒为对象；其 `winner` 为 `player` / `enemy` / `null`，含义相对于服务端战斗座位，前端须结合 `battle.viewer` 决定“我胜/我负”。
- `rematch` 恒为对象：非 `FINISHED` 时固定为 `{ "status": "NOT_AVAILABLE", "requested_by": null }`；`FINISHED` 时 `requested_by` 为 `"you"`、`"opponent"` 或 `null`。

## 5. 端点契约

除非端点单独说明，错误码与状态码遵守第 6 节；请求体中未定义的字段必须被拒绝为 `400 INVALID_REQUEST`，防止前后端在未审查的字段上悄悄分叉。

### 5.1 `POST /api/rooms`：创建房间

创建者获得玩家座位凭证，并创建一间 `WAITING` 房间。

请求：

```json
{ "nickname": "小王" }
```

| 字段 | 类型 | 规则 |
|---|---|---|
| `nickname` | string | 必填；去除首尾空白后长度 1–12 个 Unicode 字符；不得只含空白。 |

成功：`201 Created`，写入座位凭证 Cookie，返回 `RoomSnapshot`，其中：

- `room.status = "WAITING"`、`room.revision = 0`、`room.match_number = 1`；
- `opponent = null`、`battle = null`；
- `you.hero_key = null`、`you.hero_locked = false`。

失败：`400 INVALID_REQUEST`、`422 INVALID_NICKNAME`。

### 5.2 `POST /api/rooms/join`：加入房间

加入者通过房间码获得另一座位凭证。该端点不接受 `room_id`、座位或邀请码外的身份字段。

请求：

```json
{ "room_code": "K7P4WQ", "nickname": "小李" }
```

| 字段 | 类型 | 规则 |
|---|---|---|
| `room_code` | string | 必填；按服务端规范化后精确匹配。 |
| `nickname` | string | 必填；与创建同规则。 |

成功：`200 OK`，写入加入者座位凭证 Cookie，返回 `RoomSnapshot`，其中：

- `room.status = "HERO_SELECT"`，`revision` 比创建后的版本大 `1`；
- `opponent` 为对象，但双方 `hero_locked = false`，`battle = null`；
- 两侧均不得泄露英雄选择。

失败：`400 INVALID_REQUEST`、`404 ROOM_NOT_FOUND`、`409 ROOM_NOT_JOINABLE`（房间已满、已开局、已结束或已过期）、`409 ALREADY_IN_ROOM`（该浏览器已拥有此房间座位）、`422 INVALID_NICKNAME`。

### 5.3 `GET /api/rooms/{room_id}`：获取当前视角

用于初次恢复页面与轮询；不改变 `revision`。路径的 `room_id` 与当前浏览器凭证必须匹配。

请求体：无。成功：`200 OK`，返回当前 `RoomSnapshot`。

失败：`401 ROOM_AUTH_REQUIRED`（无有效座位凭证）、`403 ROOM_FORBIDDEN`（凭证不属于该 `room_id`）、`404 ROOM_NOT_FOUND`、`410 ROOM_EXPIRED`。访问时若服务端首次判定房间过期，必须先将房间状态原子写为 `EXPIRED` 并递增 `revision`，再返回 `410`；不得把已过期快照当作成功状态继续提供。

### 5.4 `POST /api/rooms/{room_id}/hero`：锁定自己的英雄

仅 `HERO_SELECT` 可调用。双方都成功锁定时，服务端在同一事务中创建 `BattleState`，切换至 `PLAYING`，并返回已公开双方英雄的战斗快照。

请求：

```json
{ "hero_key": "warrior", "revision": 1 }
```

| 字段 | 类型 | 规则 |
|---|---|---|
| `hero_key` | string | 必填，必须是 `/api/heroes` 目录中的有效英雄键。 |
| `revision` | integer | 必填，必须等于当前房间版本。 |

成功：`200 OK`。仅一方锁定时仍为 `HERO_SELECT` 且 `battle = null`；第二方锁定成功时为 `PLAYING` 且 `battle` 为对象。

失败：`400 INVALID_REQUEST`、`401 ROOM_AUTH_REQUIRED`、`403 ROOM_FORBIDDEN`、`404 ROOM_NOT_FOUND`、`409 STALE_STATE`、`409 ROOM_STATE_CONFLICT`、`410 ROOM_EXPIRED`、`422 INVALID_HERO`、`422 HERO_ALREADY_LOCKED`。

### 5.5 `POST /api/rooms/{room_id}/actions/card`：打出手牌

请求：

```json
{ "card_id": "p1-slash-3", "revision": 12 }
```

| 字段 | 类型 | 规则 |
|---|---|---|
| `card_id` | string | 必填；只能引用请求者当前手牌中的实例 ID。 |
| `revision` | integer | 必填，必须等于当前版本。 |

成功：`200 OK`，执行一次合法出牌，保存状态并使 `revision + 1`，返回新快照。

失败：通用房间错误，以及 `409 STALE_STATE`、`409 ROOM_STATE_CONFLICT`、`422 ACTION_REJECTED`。`ACTION_REJECTED` 覆盖“非本人回合、没有该手牌、能量不足、当前响应未完成、对局已结束”等规则拒绝；不得因为前端按钮状态过期而返回 500。

### 5.6 `POST /api/rooms/{room_id}/actions/skill`：使用技能

请求：

```json
{ "revision": 12 }
```

成功与失败语义同 5.5；技能冷却、能量与回合合法性由 `BattleState` 评估，前端不得预先作最终裁决。

### 5.7 `POST /api/rooms/{room_id}/actions/end-turn`：结束自己的回合

请求：

```json
{ "revision": 12 }
```

成功与失败语义同 5.5。在线模式结束回合后不得自动运行 AI；如果规则使对局结算，服务端必须在本次事务中将 `room.status` 写为 `FINISHED`、只保存一次结果并递增 `revision`。

### 5.8 `POST /api/rooms/{room_id}/actions/respond`：处理响应窗口

请求：

```json
{ "action": "dodge", "revision": 13 }
```

| 字段 | 类型 | 规则 |
|---|---|---|
| `action` | string | 必填，仅 `dodge` / `negate` / `pass`。 |
| `revision` | integer | 必填，必须等于当前版本。 |

成功与失败语义同 5.5。只有服务端判定为当前防守/响应方的座位可成功响应；攻击方、旁观浏览器或过期状态只能收到规则拒绝或鉴权错误，绝不能代替对方消耗闪避/反制。

### 5.9 `POST /api/rooms/{room_id}/rematch`：确认再来一局

请求：

```json
{ "revision": 27 }
```

仅 `FINISHED` 可调用，且每个座位每局只可确认一次。

- 第一位确认成功：`200 OK`，状态仍为 `FINISHED`，`rematch.status = "WAITING_CONFIRMATION"`，`rematch.requested_by = "you"` 或对另一位视角的 `"opponent"`。
- 第二位确认成功：`200 OK`，服务端在同一事务中清除上局 `BattleState`、清除双方英雄与确认标记、`match_number + 1`、`room.status = "HERO_SELECT"`、`revision + 1`。返回的新快照中 `battle = null`、双方 `hero_locked = false`、`rematch.status = "NOT_AVAILABLE"`。

失败：通用房间错误，以及 `409 STALE_STATE`、`409 ROOM_STATE_CONFLICT`、`422 REMATCH_ALREADY_CONFIRMED`。

## 6. 错误与并发语义

### 6.1 错误码对照

| HTTP | `error.code` | 含义 | `data` |
|---:|---|---|---|
| 400 | `INVALID_REQUEST` | JSON 不是对象、缺字段、类型错误或包含未知字段。 | `null` |
| 401 | `ROOM_AUTH_REQUIRED` | 当前浏览器没有可用座位凭证。 | `null` |
| 403 | `ROOM_FORBIDDEN` | 凭证存在但不属于所请求房间。 | `null` |
| 404 | `ROOM_NOT_FOUND` | 房间 ID/码不存在。 | `null` |
| 409 | `ALREADY_IN_ROOM` | 浏览器已持有该房间的座位。 | `null` |
| 409 | `ROOM_NOT_JOINABLE` | 房间无法加入。 | `null` |
| 409 | `STALE_STATE` | 请求携带的 `revision` 已过期。 | 最新 `RoomSnapshot` |
| 409 | `ROOM_STATE_CONFLICT` | 当前房间状态不允许该端点，例如在 `PLAYING` 再锁英雄。 | 最新 `RoomSnapshot` |
| 410 | `ROOM_EXPIRED` | 房间已过期，不可恢复。 | `null` |
| 422 | `INVALID_NICKNAME` / `INVALID_HERO` | 业务字段值不合法。 | `null` |
| 422 | `HERO_ALREADY_LOCKED` / `REMATCH_ALREADY_CONFIRMED` | 当前座位在本阶段重复提交不可逆确认。 | 最新 `RoomSnapshot` |
| 422 | `ACTION_REJECTED` | `BattleState` 拒绝动作。 | 最新 `RoomSnapshot` |

`STALE_STATE` 是正常同步分支，不是前端弹错误后继续用旧状态的许可：前端必须无条件用响应内快照替换本地状态，且不得自动重放该动作。

### 6.2 revision 与原子性

1. 前端从任一 `RoomSnapshot.room.revision` 保存当前版本；每次 `POST` 写操作原样带回。
2. 服务端以“房间 ID + 当前 revision”作为比较条件，在一个数据库写事务中完成鉴权、状态检查、`BattleState` 还原、规则执行、房间保存和 revision 递增。
3. 同一个旧 revision 的重复点击、网络重发或两端竞争，最多只能有一个请求成功；其余请求必须得到 `409 STALE_STATE` 和成功操作后的新快照。
4. 规则拒绝不改变战斗状态也不递增 revision；若实现因惰性过期检测改变了房间状态，按过期规则递增。
5. 所有成功改变可见房间状态的操作恰好递增一次 revision；不得一次请求加两次，也不得在成功动作后忘记加。

## 7. 双浏览器标准交互序列

以下序列是契约测试和双端人工联调的最低路径：

```text
浏览器 A                                  浏览器 B
POST /api/rooms
← 201 WAITING, Cookie A, revision 0
分享 invite_url / room_code
                                           POST /api/rooms/join
                                           ← 200 HERO_SELECT, Cookie B, revision 1
GET /api/rooms/{id}
← 200 HERO_SELECT, 对手未锁定
POST /hero {hero_key, revision: 1}
← 200 HERO_SELECT, revision 2             GET /api/rooms/{id}
                                           ← 200 HERO_SELECT, 只知 A 已锁定
                                           POST /hero {hero_key, revision: 2}
                                           ← 200 PLAYING, revision 3, battle.viewer=enemy
GET /api/rooms/{id}
← 200 PLAYING, revision 3, battle.viewer=player
POST /actions/card {card_id, revision: 3}
← 200 (或响应窗口), revision 4
                                           GET /api/rooms/{id}（轮询发现 revision 4）
                                           ← 200 自己视角，按 available_actions 操作
...双方重复读取/动作，直至 FINISHED...
POST /rematch {revision: n}
← 200 FINISHED, WAITING_CONFIRMATION       POST /rematch {revision: n+1}
                                           ← 200 HERO_SELECT, match_number + 1
GET /api/rooms/{id}
← 200 HERO_SELECT，新一局盲选
```

**交叉视角断言：** 同一 `revision` 下，双方 `room`、公开战场、`log` 与 `result` 一致；`battle.viewer`、拥有 `hand` 的那一侧、`available_actions` 与 `response.active` 按请求者不同而不同。任一方不得通过重复 `GET`、修改 query、提交 `seat` 之类无定义字段或读取另一响应获得对手手牌。

## 8. 前端可以依赖的承诺

1. 所有房间页面都以 `RoomSnapshot` 为唯一页面状态；不需要把创建、加入、轮询、动作各自拼成不同数据模型。
2. `room.status` 决定页面阶段，`battle` 的 `null` 规则稳定；前端无需猜测“是否已经开战”。
3. `battle.available_actions` 与 `battle.response` 是按钮可用性和等待提示的唯一依据；`battle.phase` 仅用于文案和战场展示。
4. `revision` 总在快照中；任何 `409 STALE_STATE` 或动作类 `422` 都带可直接替换的最新快照。
5. 对手加入、锁英雄、出牌、响应、结算和再来一局均会反映为 `revision` 变化；等待态可通过 `GET` 轮询检测。
6. 不会返回 AI 意图、AI 难度、对手私有手牌、座位凭证或内部对局 JSON；前端不得依赖这些不存在的数据。
7. 未知的未来枚举值和新增字段必须可降级显示或忽略；不得要求后端为了旧前端删除新增字段。

## 9. 兼容与版本纪律

- `/api/game` 继续由 [api-contract.md](../本地对局/api-contract.md) 管理；其现有 `seat` 只属于冻结热座/旧接口，绝不能复制进在线前端。
- 本文发布后，在线 v1 已有字段不得删除、改名、改类型、改 `null` 语义、改错误码含义或把成功动作变为异步而不升级版本。
- 允许加法：新增响应字段、新增可选端点、或在前端已实现兜底后新增枚举值；新增字段不得泄露私有信息。
- 任何破坏性变更必须新建 `在线PvP接口契约-v2.md`，保留 v1 文档和兼容策略，并同时更新契约测试、后端和前端排期。不得在 v1 文档上静默改写。
- 实施顺序固定为：先为本契约写后端契约测试（含两浏览器 Cookie 隔离、盲选泄露、revision 竞争与错误快照）→ 后端实现通过 → 前端仅按本文件接入 → 双端集成验收。未经契约测试通过，不允许开始正式页面联调。
