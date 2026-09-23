# 卡牌对战后端 API 契约（v1，已冻结）

> **冻结日期：2026-09-23。** 本文档是前端对接的唯一依据，替代此前的《卡牌对战后端 API 约定》。
>
> **冻结纪律**：
>
> 1. 已定字段**不删、不改形状、不改语义**；
> 2. 允许的改动只有**加法**——新增键、新增可选请求参数、枚举新成员；
> 3. 前端遇到不认识的枚举值时应**降级展示**（用文本兜底），不得崩溃；
> 4. 形状由 `tests/test_api_contract.py` 锁定：想改契约，先改测试并评审，否则测试红。
> 5. 破坏性需求（删改已有字段）必须升级为"契约 v2"并同步前端排期，不在 v1 上原地改。

## 边界

`game/` 负责角色、卡牌、回合、AI 和胜负规则。`/api` 只返回 JSON，供前端插件调用。

现有 HTML 页面已经从正式入口隔离到 `/demo`，只用于本地联调和人工验收，不作为后续页面设计的基础实现。

两条前端纪律：

- 前端**不计算规则**：伤害、能量、护甲减免、胜负判定全部由后端给出，前端只展示；
- 前端**只看 `available_actions` 与状态**决定按钮可用性，最终合法性仍由后端判断。

## 通用响应信封

所有 `/api` 响应（不论成败）都是同一形状：

```json
{ "ok": true, "data": {}, "error": null }
```

```json
{ "ok": false, "data": null, "error": { "code": "NO_ACTIVE_GAME", "message": "当前没有进行中的对局" } }
```

- `ok`：布尔，`error is null` 时为 `true`；
- `data`：成功时的载荷；失败时通常为 `null`——**唯一例外**是动作类接口被规则拒绝（`ACTION_REJECTED`）时会捎带最新公开状态，见下文；
- `error`：失败时为 `{ "code", "message" }`；`message` 是可直接展示的中文。

## 枚举总表（一次看全）

| 枚举 | 取值 | 出现位置 |
|---|---|---|
| `phase` | `PLAYER_TURN` / `RESPONSE` / `VICTORY` / `DEFEAT` / `DRAW` | 公开状态顶层 |
| `starting_side` | `player` / `enemy` | 公开状态顶层 |
| `ai_difficulty` | `easy` / `medium` / `hard` | 公开状态顶层、创建请求 |
| `winner` | `player` / `enemy` / `null` | `result` |
| `result.reason` | `kill` / `hp` / `shield` / `draw` | `result` |
| `effect_type` | `damage` / `shield` / `heal` / `dodge` / `equip` / `charge` | 卡牌定义 |
| `skill_type` | `shield` / `damage` / `damage_draw` | 英雄与技能 |
| `intent.kind` | `attack` / `defend` / `heal` / `equip` / `charge` / `pass` | `enemy.intent` |
| `intent.source` | `card` / `skill` / `none` | `enemy.intent` |

`phase` 的说明：内部枚举里还有 `START`、`HERO_SELECTION`、`ENEMY_TURN`，但它们**不会出现在任何 API 响应里**——电脑回合永远在服务端跑完（中途最多停在 `RESPONSE` 等玩家决定）才返回。

## 服务信息

`GET /`

```json
{
  "service": "card-battle",
  "status": "ok",
  "api_base": "/api",
  "demo": "/demo"
}
```

## 目录接口

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/api/heroes` | 角色列表：数值、技能、打法描述与卡组汇总 |
| `GET` | `/api/cards` | 全部 11 种卡牌的定义，含效果文案 |

### GET /api/heroes

```json
{
  "ok": true,
  "data": [
    {
      "key": "warrior",
      "name": "战士",
      "max_hp": 32,
      "skill_name": "守护",
      "skill_type": "shield",
      "skill_value": 7,
      "description": "牌多血厚，靠护盾和治疗把对局拖长",
      "deck": [
        { "key": "slash", "name": "斩击", "count": 6 },
        { "key": "heavy_strike", "name": "重击", "count": 3 },
        { "key": "shield", "name": "护盾", "count": 2 },
        { "key": "heal", "name": "治疗", "count": 1 },
        { "key": "dodge", "name": "闪避", "count": 1 },
        { "key": "longsword", "name": "长剑", "count": 1 },
        { "key": "iron_armor", "name": "铁甲", "count": 1 },
        { "key": "armor_break", "name": "破甲", "count": 1 }
      ]
    }
  ],
  "error": null
}
```

- `description`：选人页展示的一句话打法；文案来源在后端，前端直接显示；
- `deck`：卡组汇总，按牌组里的首次出现顺序排列，每个英雄的 `count` 总和恒为 16。前端**不要**自己按名字统计。

### GET /api/cards

每张牌是同一个"卡牌定义"形状——它与公开状态里手牌、装备槽里的卡牌完全一致：

```json
{
  "ok": true,
  "data": [
    { "key": "slash", "name": "斩击", "cost": 1, "effect_type": "damage", "value": 6, "exhaust": false, "text": "造成 6 点伤害" },
    { "key": "armor_break", "name": "破甲", "cost": 1, "effect_type": "damage", "value": 4, "exhaust": false, "text": "造成 4 点伤害；目标有护盾时改为 8 点" },
    { "key": "execute", "name": "处决", "cost": 2, "effect_type": "damage", "value": 8, "exhaust": true, "text": "造成 8 点伤害；目标生命低于其最大生命的 30% 时改为 16 点；使用后从本局移除" },
    { "key": "dodge", "name": "闪避", "cost": 1, "effect_type": "dodge", "value": 0, "exhaust": false, "text": "只能用于响应：抵消一次伤害" },
    { "key": "longsword", "name": "长剑", "cost": 1, "effect_type": "equip", "value": 2, "exhaust": false, "text": "装备到武器槽：每回合第一次使用斩击时额外造成 2 点伤害" },
    { "key": "charge", "name": "蓄力", "cost": 1, "effect_type": "charge", "value": 2, "exhaust": false, "text": "本回合不造成伤害：下回合额外获得 2 点能量" }
  ],
  "error": null
}
```

卡牌定义七字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `key` | string | 稳定标识；前端做图标、样式映射用它 |
| `name` | string | 中文名 |
| `cost` | int | 能量消耗 |
| `effect_type` | string | 见枚举总表；`dodge` 不能主动打出 |
| `value` | int | 基础数值（伤害/护盾/治疗/加成）；`dodge` 为 0 |
| `exhaust` | bool | `true` 表示打出后从本局移除 |
| `text` | string | **可直接展示的效果文案**，含条件规则；前端不要自己拼数字 |

## 对局接口

| 方法 | 路径 | 作用 | 成功状态码 |
|---|---|---|---|
| `POST` | `/api/game` | 创建新对局（`hero_key` 必填，`ai_difficulty` 可选，默认 `medium`） | `201` |
| `GET` | `/api/game` | 获取当前对局的公开状态 | `200` |
| `POST` | `/api/game/actions/card` | 使用 `card_id` 出牌（攻击/防御/装备都走这里） | `200` |
| `POST` | `/api/game/actions/skill` | 使用角色技能 | `200` |
| `POST` | `/api/game/actions/end-turn` | 结束玩家回合；电脑连续行动后回到玩家回合 | `200` |
| `POST` | `/api/game/actions/respond` | 对挂起的攻击响应 `dodge` 或 `pass` | `200` |
| `POST` | `/api/game/restart` | 清除当前对局 | `200` |

除 `POST /api/game` 的成功码是 `201` 外，其余成功一律 `200`。

### POST /api/game

```json
{ "hero_key": "warrior", "ai_difficulty": "medium" }
```

- `hero_key`：必须是 `/api/heroes` 里的 key，否则 `422 INVALID_HERO`；
- `ai_difficulty`：`easy` / `medium` / `hard`，省略为 `medium`，非法值 `422 INVALID_DIFFICULTY`；
- 重复调用会**以新对局覆盖当前对局**（旧对局不保留）；
- 先手由服务端 RNG 决定。电脑先手时，它的开局回合在创建流程里跑到"需要玩家决定的点"为止：返回 `PLAYER_TURN`（回合已跑完）、`RESPONSE`（有攻击等玩家响应，`response.active` 为 `true`）或终局——**永远不会返回 `ENEMY_TURN`**；
- 玩家在 `RESPONSE` 下用 `POST /api/game/actions/respond` 响应（`dodge` 或 `pass`）；响应后电脑继续把回合跑完，最终回到 `PLAYER_TURN`。

### 动作接口的请求体

| 接口 | 请求体 | 备注 |
|---|---|---|
| `actions/card` | `{ "card_id": "card-xxxxxxxx" }` | `card_id` 是手牌元素里的 `id`（不是 `key`），缺字段 `400 INVALID_REQUEST` |
| `actions/skill` | 无（空 body 即可） | |
| `actions/end-turn` | 无（空 body 即可） | |
| `actions/respond` | `{ "action": "dodge" }` 或 `{ "action": "pass" }` | 其它值 `400 INVALID_REQUEST` |

## 公开状态 schema

`GET /api/game`、创建对局、以及所有动作接口成功时返回的 `data` 都是这一份公开状态：

```json
{
  "phase": "PLAYER_TURN",
  "round_number": 1,
  "starting_side": "player",
  "ai_difficulty": "medium",
  "player": {
    "name": "战士",
    "max_hp": 32,
    "hp": 32,
    "shield": 0,
    "energy": 2,
    "hero": {
      "key": "warrior",
      "name": "战士",
      "max_hp": 32,
      "skill_name": "守护",
      "skill_type": "shield",
      "skill_value": 7
    },
    "skill": { "name": "守护", "type": "shield", "value": 7, "cost": 2, "used_this_turn": false },
    "equipment": { "weapon": null, "armor": null },
    "bonus_energy_next_turn": 0,
    "exhaust_pile": [],
    "hand": [
      { "id": "card-7284c016", "key": "slash", "name": "斩击", "cost": 1, "effect_type": "damage", "value": 6, "exhaust": false, "text": "造成 6 点伤害" }
    ]
  },
  "enemy": {
    "name": "电脑",
    "max_hp": 28,
    "hp": 28,
    "shield": 0,
    "energy": 3,
    "hero": { "key": "mage", "name": "法师", "max_hp": 28, "skill_name": "火球术", "skill_type": "damage", "skill_value": 10 },
    "skill": { "name": "火球术", "type": "damage", "value": 10, "cost": 2, "used_this_turn": false },
    "equipment": { "weapon": null, "armor": null },
    "bonus_energy_next_turn": 0,
    "exhaust_pile": [],
    "intent": { "kind": "attack", "source": "card", "name": "重击", "value": 10, "text": "预计使用【重击】造成 10 点伤害" }
  },
  "response": { "active": false, "card_name": null, "damage": 0, "dodge_cost": 1 },
  "available_actions": {
    "play_card": true,
    "use_skill": false,
    "end_turn": true,
    "respond": { "dodge": false, "pass": false }
  },
  "result": null,
  "log": ["战斗开始，玩家选择角色：战士"]
}
```

### 顶层字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `phase` | string | 见枚举总表；`RESPONSE` 表示有攻击挂起等玩家响应 |
| `round_number` | int | 当前回合数，1 起 |
| `starting_side` | string | 本局先手方；先手方第 1 个回合只有 2 点能量 |
| `ai_difficulty` | string | 本局难度 |
| `player` / `enemy` | object | 双方公开块，见下 |
| `response` | object | 响应窗口信息，见下 |
| `available_actions` | object | 按钮可用性，见下 |
| `result` | object \| null | 终局结果，非终局恒为 `null`，见下 |
| `log` | string[] | 战斗日志（中文整句，前端直接逐行显示，不要解析） |

### 双方公开块（对称）

`player` 与 `enemy` 的公开字段**完全对称**，只有各自主有的一个键不同：

| 字段 | 说明 |
|---|---|
| `name` / `max_hp` / `hp` / `shield` / `energy` | 血条与资源；`shield` 跨回合累计 |
| `hero` | 精简英雄信息：`key` / `name` / `max_hp` / `skill_name` / `skill_type` / `skill_value`（**精简版**；完整目录见 `/api/heroes`） |
| `skill` | `name` / `type` / `value` / `cost` / `used_this_turn` |
| `equipment` | `{ "weapon": 卡牌定义 \| null, "armor": 卡牌定义 \| null }`，两个键恒在 |
| `bonus_energy_next_turn` | 蓄力结余，双方都看得见的明牌 |
| `exhaust_pile` | 已移除的牌，**元素是 card key 字符串**（如 `["execute"]`）；显示中文名用 `/api/cards` 映射 |

各自私有键：

| 键 | 出现位置 | 说明 |
|---|---|---|
| `hand` | 仅 `player` | 手牌，每项是 `id` + 卡牌定义（八字段） |
| `intent` | 仅 `enemy` | 电脑下回合计划，见下节 |

**电脑的手牌与抽牌堆不进入任何响应**——没有 `enemy.hand`、没有 `enemy_hand`、没有 `draw_pile` 这类键，前端也没有绕过途径。

### response（响应窗口）

| 字段 | 说明 |
|---|---|
| `active` | `true` 表示正等玩家对一次攻击做响应 |
| `card_name` | 挂起攻击的牌名（如 `"重击"`）；无响应时为 `null` |
| `damage` | 挂起攻击的伤害值；无响应时为 `0` |
| `dodge_cost` | 闪避的能量费用（恒为 1） |

### available_actions

| 字段 | 说明 |
|---|---|
| `play_card` | 玩家回合且未终局时可出牌 |
| `use_skill` | 技能未用、能量足够且未终局 |
| `end_turn` | 玩家回合且未终局 |
| `respond.dodge` | 响应窗口里手里有闪避且能量够 |
| `respond.pass` | 响应窗口里可以放弃响应 |

### result（终局结果）

| 字段 | 类型 | 说明 |
|---|---|---|
| `winner` | `"player"` \| `"enemy"` \| `null` | `null` 仅出现在平局 |
| `reason` | string | `kill`（击倒）/ `hp`（10 回合结算血多）/ `shield`（血量相同、护盾更厚）/ `draw`（完全平局） |
| `text` | string | 可直接展示的中文结果说明 |

示例：

```json
{ "winner": "player", "reason": "kill", "text": "你击败了对手，本局获胜" }
{ "winner": "enemy", "reason": "hp", "text": "达到 10 回合上限，电脑生命值更高，本局失败" }
{ "winner": null, "reason": "draw", "text": "达到 10 回合上限，双方生命值与护盾相同，本局平局" }
```

### 恒在字段与 null 规则

前端可以无条件读以下键（任何 phase 下都存在）：

| 键 | 何时为 `null` / 空 |
|---|---|
| `player.hand` | 手牌为空时是 `[]` |
| `enemy.intent` | 只在玩家回合有值；响应窗口、终局等其余时刻恒为 `null` |
| `enemy.equipment.weapon` / `.armor` | 没装备时 `null` |
| `response.card_name` | 无响应时 `null` |
| `result` | 非终局时 `null` |
| `exhaust_pile` | 无牌移除时 `[]` |

### 敌人意图

`enemy.intent` 是玩家回合里电脑"下回合第一个动作"的预估，让玩家的出牌从猜测变成有信息基础的判断：

- **确定性**：同一局面读取多次结果相同，刷新不会变；不消耗对局随机数、不改变任何状态；
- **它是"计划"不是"承诺"**：电脑下回合抽到的牌未知，所以按它当前手牌预估；玩家改变局面后，计划也会随之改变；
- 攻击的 `value` 含武器加成，与真实结算一致（带着未消耗的长剑时 +2）；
- 意图会暴露电脑打算打的那张牌——这是刻意给玩家的信息优势（单机游戏的设计选择）；它不包含电脑手牌的数量、抽牌堆或弃牌堆内容。

### 蓄力字段

`bonus_energy_next_turn` 是双方都有的公开字段：打出【蓄力】后累加（1 费换下回合 +2 能量），在持有者自己的回合开始时并入能量（`能量 = 3 + 结余`）并清零。双方都能看到对面攒了多少，前端可以据此提示"对方下回合能量更多"；`enemy.intent` 的预演也已包含它。

### 消耗与移除区

- 卡牌定义的 `exhaust` 为 `true` 表示打出后从本局移除（不进弃牌堆、洗牌也回不来）；
- `exhaust_pile` 的元素是 **card key 字符串**，不是卡牌定义对象；要显示中文名/图标时用 `/api/cards` 建立映射；
- 装备牌不进弃牌堆，也不会出现在移除区。

## 错误格式与状态码

| `error.code` | HTTP | 场景 |
|---|---|---|
| `NO_ACTIVE_GAME` | `404` | 当前没有进行中的对局（含 `GET /api/game`） |
| `INVALID_HERO` | `422` | `hero_key` 不存在 |
| `INVALID_DIFFICULTY` | `422` | 难度不是 `easy` / `medium` / `hard` |
| `INVALID_REQUEST` | `400` | 请求字段缺失或格式错误（含非法的 respond action） |
| `ACTION_REJECTED` | `422` | 战斗规则拒绝本次操作（能量不足、不在手中、回合不对等） |

`ACTION_REJECTED` 是唯一"失败但带状态"的情况：`data` 里带最新公开状态（形状同"公开状态 schema"），前端可以借此同步状态而不是再发一次 `GET`。

```json
{
  "ok": false,
  "data": { "phase": "PLAYER_TURN", "round_number": 1, "...": "..." },
  "error": { "code": "ACTION_REJECTED", "message": "能量不足，还差 2 点" }
}
```

## 前端可以依赖的承诺

1. **形状稳定**：本文档描述的所有键、类型、枚举由契约测试锁定；此后只有加法；
2. **未知枚举降级**：未来新增 `effect_type` / `intent.kind` 等枚举成员时，前端用 `text` 兜底展示，不允许崩溃；
3. **隐私边界**：`enemy` 永远不含手牌/抽牌堆/弃牌堆内容；
4. **错误可展示**：`error.message` 是中文整句，可直接 toast；
5. **状态可同步**：任何动作失败（`ACTION_REJECTED`）都能从 `data` 里拿到最新状态。

## 当前阶段不做

- 不把模板页面继续扩展成正式前端；
- 不让前端自行计算伤害、能量、AI 或胜负；
- 不把电脑隐藏信息放进 API 响应；
- 不增加多人、登录、抽卡或外部 AI 服务。
