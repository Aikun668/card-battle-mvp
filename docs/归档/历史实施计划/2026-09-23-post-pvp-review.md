# 双人热座提交复核（2026-09-23）

## 范围

对双人热座（[实施计划](../旧模式/本地双人热座实施计划.md)）的全部改动做提交前复核：
`game/battle.py`、`game/public_state.py`、`api_routes.py`、契约与测试更新。

## 复核清单与结论

逐条走边界（AI 触发点、响应收尾、seat 校验、视角隔离、序列化、文案）：

| 检查点 | 结论 |
|---|---|
| 响应挂起条件（`_open_response`）：真人防守挂起、电脑防守当场定夺 | ✅ 正确 |
| **响应收尾（`_finish_response`）：攻击方是真人时 AI 不得接管** | ❌ → **R-01 修复** |
| AI 触发点收敛：`resolve_enemy_turn` 双人下拒绝；`end-turn` 只在"对方是电脑"时跑 | ✅ |
| `seat` 校验：值非法 / AI 座位 → 400；回合归属 → 422 | ✅ |
| `GET ?seat=` 走同一校验 | ✅（补契约断言） |
| 视角隔离：手牌只在 viewer 一侧 | ✅ |
| 序列化：旧存档无 `mode` → pve；双人局存读往返 | ✅ |
| 日志 / 结果文案中性化（无"你 / 电脑"） | ✅（200 局脚本断言） |
| 先手限能、结算规则在双人下同一套 | ✅ |

## R-01：响应收尾的 AI 接管（已修复）

**症状**：双人模式下，玩家2 攻击玩家1 且这次攻击被响应（闪避或放弃）后，
`_finish_response` 按"攻击方是不是 `ENEMY` 座位"决定继续跑电脑行动——
**把玩家2 的回合交给 AI 打完**（AI 会继续出牌并结束回合）。

**根因**：该判断写死于座位枚举，没有经过 `is_human_side()`。
pve 下两者等价，双人下不等价。同族判断在 `_open_response`、`resolve_enemy_turn`、
`end-turn` 路由都用了正确写法，只有这一处漏了。

**修复**：`if attacker is Side.ENEMY:` → `if not self.is_human_side(attacker):`

**为什么初版测试没抓到**：初版 7 项只覆盖"玩家1 攻击玩家2 被响应"（attacker=PLAYER），
没有覆盖反方向。已补两条，且都断言"回合停在 `ENEMY_TURN`、玩家2 能量未被 AI 消耗、
手牌未被动、日志无电脑"——在修复前会红：

- `test_pvp_second_players_attack_keeps_the_turn_with_a_human_after_a_pass`
- `test_pvp_second_players_attack_keeps_the_turn_with_a_human_after_a_dodge`

## 补充断言

- 契约测试并入「`GET ?seat=` 走同一套座位校验」：值非法 / AI 座位 → `400 INVALID_SEAT`。

## 健壮性读数（200 局自动对局）

两个自动玩家（随机合法动作）互打 200 局：

```text
200 局全部正常结束（无死循环、无空状态、日志无"电脑"）
终局分布: {'kill': 159, 'hp': 38, 'shield': 3, 'draw': 0}
平均回合数: 6.4   单局最大步数: 74
```

- 击杀 79.5% / 结算 20.5%：随机玩家不精算防守，比 AI 对局更凶，符合预期；
- 无完全平局（条件苛刻），无异常状态、无卡死。

## 验收

- 全量 **291 passed**（旧 282 全绿 = pve 行为零变化；双人 9 项）；
- 契约文档已同步（双人章节 + 枚举 + 错误码，全部加法）；
- 遗留（记录在案）：战绩记录（SQLite）暂不区分模式；`ai_difficulty` 在双人下无作用但仍返回（契约恒在）。

## 二轮复核（外部清单 F1–F6）

收到一份外部复核清单（6 条），逐条定位源码严格验证——**六条全部属实**，已全部修复：

| # | 问题 | 验证证据 | 修复 |
|---|---|---|---|
| F1 | 契约示例漏 `attacker` | 示例只有 4 键，字段表与 `RESPONSE_KEYS` 都是 5 键 | 示例补 `"attacker": null` |
| F2 | 两份文档的测试数不一致 | 计划文档写 289（R-01 补测前的中间值）、本报告写 291，实际 291 | 计划文档改为 291 并注明演进 |
| F3 | `ENEMY_TURN` 被降级描述，契约测试未锁 pvp 枚举 | 枚举表把 `ENEMY_TURN` 塞进括号；`PHASES` 仅 5 值 | 枚举表改为完整 6 值写法；新增 `PVP_PHASES` 常量与 pvp 状态契约用例（断言创建即返回 `ENEMY_TURN`、视角隔手牌、intent 恒空） |
| F4 | `match_results` 不分模式的后果未记录 | `repository.py` 表无 `mode` 列 | 计划文档风险行补注：统计"某英雄胜率"时会被双人对局污染，将来需要模式维度应加列并回填 |
| F5 | `result.reason` 的 `shield` 分支无契约用例 | `RESULT_REASONS` 含 `shield`、无用例走到 | 结算用例补"血量相同、护盾更厚"分支 |
| F6 | `mode` 在模型层不校验 | `BattleState.create(mode="coop")` 会静默按 pve 跑 | `__init__` 对非法 mode 抛 `ValueError`（合法值仍由 API 层给 `INVALID_MODE`）；`from_dict` 对坏档容错归一（不因一个坏字段整局读不出）；补两条测试 |

**读数**：全量 **293 passed**（修 F3 / F6 各补一条用例）。

## 结论

R-01 修复后，双人热座的 AI 触发点已全部经过 `is_human_side` 判断，不存在
"AI 接管真人回合"的路径；其余复核点无问题。可以提交。
