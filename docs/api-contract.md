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
| `GET` | `/api/cards` | 获取卡牌定义 |

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
| `POST` | `/api/game/actions/card` | 使用 `card_id` 出牌 |
| `POST` | `/api/game/actions/skill` | 使用角色技能 |
| `POST` | `/api/game/actions/end-turn` | 结束玩家回合，电脑按能量连续行动后进入下一回合 |
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

成功的对局接口返回：

```json
{
  "ok": true,
  "data": {
    "phase": "PLAYER_TURN",
    "round_number": 1,
    "ai_difficulty": "medium",
    "hero": {},
    "player": {},
    "enemy": {},
    "hand": [],
    "skill": {},
    "available_actions": {
      "play_card": true,
      "use_skill": true,
      "end_turn": true
    },
    "log": []
  },
  "error": null
}
```

公开状态不会包含电脑手牌、抽牌堆或弃牌堆。前端只根据 `available_actions` 和当前状态决定按钮展示与禁用；最终合法性仍由后端判断。

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
