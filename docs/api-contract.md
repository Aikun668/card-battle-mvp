# 卡牌对战后端 API 约定

## 边界

`game/` 负责角色、卡牌、回合、AI 和胜负规则。`/api` 只返回 JSON，供后续前端插件调用。

现有 HTML 页面已经从正式入口隔离到 `/demo`，只用于本地联调和人工验收，不作为后续页面设计的基础实现。

## 服务信息

`GET /`

返回服务元信息：

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
| `GET` | `/api/heroes` | 获取角色列表和技能数据 |
| `GET` | `/api/cards` | 获取卡牌定义（`effect_type` 为 `"damage"` / `"shield"` / `"heal"` / `"dodge"` / `"equip"` / `"charge"` 六类，含两张装备牌与三张条件牌） |

目录接口统一返回：

```json
{
  "ok": true,
  "data": [],
  "error": null
}
```

## 对局接口

| 方法 | 路径 | 作用 |
|---|---|---|
| `POST` | `/api/game` | 使用 `hero_key` 创建新对局，可选 `ai_difficulty` |
| `GET` | `/api/game` | 获取当前对局的公开状态 |
| `POST` | `/api/game/actions/card` | 使用 `card_id` 出牌，攻击牌、防御牌和装备牌都走这一条 |
| `POST` | `/api/game/actions/skill` | 使用角色技能 |
| `POST` | `/api/game/actions/end-turn` | 结束玩家回合，电脑按能量连续行动后进入下一回合 |
| `POST` | `/api/game/actions/respond` | 对挂起的攻击响应 `dodge` 或 `pass` |
| `POST` | `/api/game/restart` | 清除当前对局 |

创建对局：

```json
POST /api/game
{
  "hero_key": "warrior",
  "ai_difficulty": "medium"
}
```

`ai_difficulty` 可选值为 `easy`、`medium`、`hard`，省略时为 `medium`。它只改变电脑的决策质量与随机性，不改变卡牌数值、生命值、能量或抽牌规则。非法取值返回 `INVALID_DIFFICULTY`。

创建对局时先手由服务端 RNG 随机决定。电脑先手时，它开局的整个回合已经在创建流程里跑完，所以 `POST /api/game` 只会返回 `PLAYER_TURN` 或终局，永远不会返回 `ENEMY_TURN` 或 `RESPONSE`。

成功的对局接口返回：

```json
{
  "ok": true,
  "data": {
    "phase": "PLAYER_TURN",
    "round_number": 1,
    "starting_side": "player",
    "ai_difficulty": "medium",
    "player": {
      "name": "战士",
      "max_hp": 32,
      "hp": 32,
      "shield": 0,
      "energy": 3,
      "hero": {},
      "skill": {
        "name": "守护",
        "type": "shield",
        "value": 8,
        "cost": 2,
        "used_this_turn": false
      },
      "equipment": {
        "weapon": {
          "key": "longsword",
          "name": "长剑",
          "cost": 1,
          "effect_type": "equip",
          "value": 2,
          "exhaust": false
        },
        "armor": null
      },
      "bonus_energy_next_turn": 0,
      "exhaust_pile": [],
      "hand": []
    },
    "enemy": {
      "name": "电脑",
      "max_hp": 24,
      "hp": 24,
      "shield": 0,
      "energy": 3,
      "hero": {},
      "skill": {
        "name": "火球术",
        "type": "damage",
        "value": 10,
        "cost": 2,
        "used_this_turn": false
      },
      "equipment": {
        "weapon": null,
        "armor": null
      },
      "bonus_energy_next_turn": 0,
      "exhaust_pile": [],
      "intent": {
        "kind": "attack",
        "source": "card",
        "name": "重击",
        "value": 10,
        "text": "预计使用【重击】造成 10 点伤害"
      }
    },
    "response": {
      "active": false,
      "card_name": null,
      "damage": 0,
      "dodge_cost": 1
    },
    "available_actions": {
      "play_card": true,
      "use_skill": true,
      "end_turn": true,
      "respond": {"dodge": false, "pass": false}
    },
    "log": []
  },
  "error": null
}
```

双方的血量、护盾、能量、蓄力结余、英雄、技能状态和装备两边对称，`starting_side` 说明本局谁先手。`player` 额外带 `hand`（玩家自己的手牌），`enemy` 额外带 `intent`（它的下回合计划，见下节）；电脑的手牌与抽牌堆不进入 API 响应，也没有 `enemy_hand`、`enemy_draw_pile` 这类键，没有前端可以绕过这一点。前端只根据 `available_actions` 和当前状态决定按钮展示与禁用；最终合法性仍由后端判断。

### 蓄力字段

`bonus_energy_next_turn` 是双方都有的公开字段：打出【蓄力】后累加（1 费换下回合 +2 能量），在持有者自己的回合开始时并入能量（`能量 = 3 + 结余`）并清零。双方都能看到对面攒了多少，前端可以据此提示"对方下回合能量更多"；`enemy.intent` 的预演也已包含它。

### 敌人意图字段

`enemy.intent` 是玩家回合里电脑"下回合第一个动作"的预估，让玩家的出牌从猜测变成有信息基础的判断：

- **只在玩家回合有值**，响应窗口、终局等其余时刻一律为 `null`（字段始终存在，前端可无条件读）；
- **确定性**：同一局面读取多次结果相同，刷新不会变；不消耗对局随机数、不改变任何状态；
- **它是"计划"不是"承诺"**：电脑下回合抽到的牌未知，所以按它当前手牌预估；玩家改变局面后，计划也会随之改变；
- `kind` 取值 `attack` / `defend` / `heal` / `equip` / `pass`；`source` 说明动作来自手牌（`card`）还是英雄技能（`skill`），`pass` 时为 `none`；`text` 是可直接展示的中文描述；
- 攻击的 `value` 含武器加成，与真实结算一致（带着未消耗的长剑时 +2）；
- 意图会暴露电脑打算打的那张牌——这是刻意给玩家的信息优势（单机游戏的设计选择）；它不包含电脑手牌的数量、抽牌堆或弃牌堆内容，电脑依然读不到玩家的手牌。

### 装备字段

`equipment` 是双方都有的公开字段（决策 10），形状与 `hero`、`skill` 一致：

- `weapon` 和 `armor` 两个键**任何时刻都存在**，没装备时是 `null`，前端可以无条件读，不用先判断键在不在；
- 装上装备后，对应槽位是那张装备牌的完整定义：`key`、`name`、`cost`、`effect_type`（`"equip"`）、`value`；
- 装备是挂在角色身上、对面也看得见的信息，所以两边对称输出；手牌仍然只有玩家自己有。

装备不需要任何新路由：`POST /api/game/actions/card` 照常接受装备牌的 `card_id`，成功后就地更新 `equipment`，同一次响应里就能看到槽位变化。装备牌不进入弃牌堆，所以它不会出现在任何取牌区的接口数据里。

### 消耗与移除区

- 卡牌定义（`/api/cards` 与公开状态里的卡牌）带 `exhaust` 布尔：`true` 表示打出后从本局移除（不进弃牌堆、洗牌也回不来）；
- 双方参与者带 `exhaust_pile`：已移除的牌（公开信息——打出去就没了的东西，对面也算得清）；
- 装备槽里的卡牌定义同样带 `exhaust`（当前装备牌都是 `false`）。

## 错误格式

错误也返回统一 JSON：

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "ACTION_REJECTED",
    "message": "能量不足，还差 2 点"
  }
}
```

当前主要错误码：

- `INVALID_HERO`：角色不存在；
- `INVALID_DIFFICULTY`：电脑难度不是 `easy`、`medium`、`hard`；
- `INVALID_REQUEST`：请求字段缺失或格式错误；
- `NO_ACTIVE_GAME`：当前没有进行中的对局；
- `ACTION_REJECTED`：战斗规则拒绝了本次操作。

## 当前阶段不做

- 不把模板页面继续扩展成正式前端；
- 不让前端自行计算伤害、能量、AI 或胜负；
- 不把电脑隐藏信息放进 API 响应；
- 不增加多人、登录、抽卡或外部 AI 服务。
