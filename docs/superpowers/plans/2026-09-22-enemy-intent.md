# 敌人行动意图预告 Implementation Plan

**Goal:** 在公开状态里给玩家看"电脑下回合打算做什么"（预计重击 10 / 准备防御 / 准备治疗），把玩家的出牌从猜测变成有信息基础的判断。这是路线文档「第四优先：敌人行动意图」的后端部分，前端展示不归本轮。

**Spec:** `docs/队友宏观计划/游戏玩法路线优先级.md` 的「第四优先：敌人行动意图」。

**Architecture:** 改动集中在 `game/ai.py`（新增预估函数）与 `game/public_state.py`（`enemy` 块新增 `intent` 字段）。预估是**纯查询 + 确定性**：不消耗对局 RNG、不修改任何状态，只读取 `AIObservation`（电脑自己的手牌 + 双方公开信息），按"电脑下回合开始时的资源"跑一次该难度的候选排序，取第一名翻译成意图。因为不参与对局，**同一批种子的对局轨迹与读数必须逐字不变**。

**Tech Stack:** Python 3、Flask、pytest。**本轮不碰结算规则、卡牌数值、AI 的选择逻辑、路由形状与前端。**

## Decisions (2026-09-22)

1. **意图 = "电脑下回合的第一个动作"的预估。** 玩家回合期间电脑能量是 0（上回合花光），按当前状态预估只会得到"什么都做不了"，所以预演时把电脑资源按"下回合开始"重置：能量回满 3、技能标记重置、手牌保持当前值。
2. **抽牌不确定性按"计划不是承诺"处理。** 电脑下回合开始会抽 1 张牌，预估时不知道抽到什么，所以按当前手牌算。文档与文案都写明这是"计划"；玩家自己的操作改变局面后，计划也可能变（每次读取都重新预估，同一状态必然给同一结果）。
3. **确定性（硬要求）。** 同一状态必须给出同一意图（刷新不变）：不使用对局 RNG、不使用难度随机抽选，直接取 `rank_enemy_actions(...)[0]`。
   - 后果：简单/中等实际执行时可能不选"最优"（概率抽选），预告与执行存在天然偏差；困难完全一致。这属于"计划 vs 承诺"，接受。
4. **意图形状**（`enemy.intent`，只在该玩家回合有值，其余时刻为 `null`）：

   ```json
   "intent": {
     "kind": "attack",            // attack / defend / heal / equip / pass
     "source": "card",            // card / skill
     "name": "重击",
     "value": 10,                 // attack=含武器加成的伤害 / defend=护盾 / heal=治疗 / equip=加成 / pass=0
     "text": "预计使用【重击】造成 10 点伤害"
   }
   ```

   `pass` 时 `name` 为 `null`、`text` 为 `"预计按兵不动"`（例如手里全是打不出的牌）。
5. **有意保留的信息不对称（记录在案）。** 预告会暴露电脑打算打的那张牌——这是路线文档明确要的体验设计（Slay the Spire 同款），与"人机对等"不冲突：对等管的是"规则/资源/不偷看玩家手牌"，意图是游戏**给玩家的信息优势**；电脑依然读不到玩家手牌。后续任何人不得以"对等"为由删除该功能，也不得把它扩成"展示电脑手牌"。
6. **对局读数必须零变化。** 意图是纯展示：24 组（三档 × 8）以外的验收标准是"2400 局三档读数与上一轮逐字相同"；若不同即为实现 bug（消耗了 RNG 或改了状态），必须修实现而不是改基准。
7. **数值口径**：攻击意图的伤害含武器加成（带着未消耗的长剑时 +2），与真实结算一致；技能按技能类型映射（法师火球术 → attack，战士守护 → defend，游侠连射 → attack）。

## 模拟依据

无需新模拟：本功能不改变任何行为。验收靠"读数逐字不变"（见决策 6）+ 意图与真实首张动作的一致率统计（记录用，不作为通过门槛）：

- 困难难度：预估与执行应为 **100%** 一致（除非抽牌/玩家行为改变局面）；
- 中等：预期 ≥ 85%（0.88 概率选最优）；
- 简单：预期 ≥ 60%（0.60 概率选最优）。

## Global Constraints

- **纯查询**：不修改 `BattleState`、不消耗 `self.rng`、不写日志。
- **确定性**：不用任何随机源；同一状态两次读取必须逐字节相同。
- **不泄露手牌全貌**：`intent` 只描述一个动作，不包含手牌数量、抽牌堆或弃牌堆内容。
- **不改既有字段**：只新增 `enemy.intent`；`player` 侧不加对应字段（玩家不需要"自己下一步"的提示）。
- **难度只影响决策质量**：三档的意图预估共用同一套排序，只按 `difficulty` 取该难度的第一名。
- 前端不参与：本轮不改 `templates/`、`static/`。

## Review Focus

- **确定性**：`estimate_enemy_intent()` 的签名里不出现 `rng`；有一条"同状态两次调用相等"的测试。
- **预演状态**：能量必须重置为 `STARTING_ENERGY`、技能未使用；有一条"电脑当前能量为 0 时意图仍正常"的测试。
- **信息边界**：只改玩家隐藏手牌，意图不变（现有 `test_hard_ai_rank_is_unchanged_when_only_the_hidden_player_hand_changes` 的同款思路）；`AIObservation` 字段集不变。
- **武器加成口径**：与 `_damage_with_weapon` 一致（一回合只加一次，已消耗则回落）。
- **前端契约测试**：`tests/test_frontend_contract.py` 的"enemy 没有 hand"断言必须继续成立。

---

### Task 1: 意图预估（`game/ai.py`）

**Files:**
- Modify: `game/ai.py`
- Test: `tests/test_ai.py`

**Interfaces:**
- 新增 `@dataclass(frozen=True) class EnemyIntent: kind: str; source: str; name: str | None; value: int; text: str`
- 新增 `estimate_enemy_intent(observation: AIObservation, difficulty: AIDifficulty) -> EnemyIntent`
  - 预演：`replace(observation, self_state=replace(self_state, energy=STARTING_ENERGY, skill_used_this_turn=False))`
  - 排序：`rank_enemy_actions(预演, difficulty)`，取 `[0]`
  - 翻译：card → 用卡牌名/数值；skill → 用英雄技能名/数值；pass → 按兵不动
  - 文本用中文模板，与战斗日志风格一致（`预计使用【重击】造成 10 点伤害` / `预计获得 6 点护盾` / `预计恢复 6 点生命值` / `预计装备【长剑】` / `预计按兵不动`）

- [ ] **Step 1: 写失败测试**

```python
def test_intent_predicts_the_first_planned_action():
    battle = make_battle()
    battle.enemy.energy = 0  # 玩家回合：电脑上回合已经把能量花光
    battle.enemy_hand = [{"id": "enemy-heavy", "key": "heavy_strike"}]
    intent = estimate_enemy_intent(battle.enemy_observation(), AIDifficulty.HARD)
    assert (intent.kind, intent.name, intent.value) == ("attack", "重击", 10)
```

再覆盖：能量为 0 也能预估（预演重置到 3）；带未消耗长剑时斩击意图为 8；技能意图映射（法师火球术 → attack 10、战士守护 → defend 8）；全打不出时 `pass`；同状态两次调用相等。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_ai.py -q -k intent`

Expected: 新用例全部失败（函数不存在）。

- [ ] **Step 3: 实现 `EnemyIntent` 与 `estimate_enemy_intent()`**

- [ ] **Step 4: 跑测试**

Run: `pytest tests/test_ai.py -q`

Expected: 全绿。

- [ ] **Step 5: 提交**

```bash
git add game/ai.py tests/test_ai.py
git commit -m "feat: estimate the enemy's next action"
```

### Task 2: 公开状态接入（`game/public_state.py`）

- [ ] **Step 6: 写失败测试（`tests/test_api.py` / `tests/test_ai.py`）**

必须包含：`PLAYER_TURN` 时 `enemy.intent` 存在且形状正确；同一状态两次 `GET /api/game` 的 `enemy.intent` 逐字节相等；终局与 `RESPONSE` 时为 `null`；只改玩家隐藏手牌时意图不变；`enemy` 块里没有 `hand` / `draw_pile`；刷新后意图不丢失。

- [ ] **Step 7: 实现 `public_battle_state()` 的 `enemy.intent`**

`intent` 只在 `battle.phase is BattlePhase.PLAYER_TURN` 且未终局时计算，其余为 `None`。

- [ ] **Step 8: 更新接口契约并跑全量测试**

`docs/api-contract.md` 的公开状态示例加 `intent` 块与字段说明（含"计划不是承诺"的措辞）。

```bash
pytest -q
```

- [ ] **Step 9: 提交**

```bash
git add game/public_state.py tests/ docs/api-contract.md
git commit -m "feat: publish the enemy's next action in the public state"
```

### Task 3: 验收与文档

- [ ] **Step 10: 一致性验收（记录用）**

`%TEMP%\intent_verify.py`：2400 局真实对局，记录"玩家回合开始时显示的意图"与"电脑回合实际第一张动作"的一致率，按难度分档记录，不一致归因（抽牌/玩家行为/难度随机）。

- [ ] **Step 11: 零变化验收（硬标准）**

用 `%TEMP%\combo_verify.py` 复跑三档 2400 局，与 `2026-09-22-damage-combo-planning.md` 的验收记录逐项比较：**必须逐字相同**。

- [ ] **Step 12: 文档同步**

- `README.md`「一句话玩法」或 AI 章节：加"玩家回合能看到电脑下一步计划"；
- `docs/claude-builder/acceptance.md`：新增意图验收项（含"计划不是承诺"、确定性、对局读数不变）；
- `docs/队友宏观计划/游戏玩法路线优先级.md`：把「第四优先」标记为后端完成；
- 本计划"验收记录"补齐。

- [ ] **Step 13: 跑门禁并提交**

```bash
python -X utf8 -m compileall -q app.py api_routes.py demo_routes.py web_support.py game && ruff check . && ruff format --check . && pytest -q
```

---

## 验收记录（Task 1–3）

- 实际改动文件：`game/ai.py`（`EnemyIntent` + `estimate_enemy_intent()` + `_intent_from_candidate()`）、`game/public_state.py`（`enemy.intent`）、`tests/test_ai.py`（8 条）、`tests/test_api.py`（5 条）、`docs/api-contract.md`，以及 README / 验收文档 / 路线文档。
- 实现要点：
  - `estimate_enemy_intent()` 预演"下回合开始"的资源（能量回满 3、技能与装备标记重置），取该难度 `rank_enemy_actions()[0]`，翻译成 `EnemyIntent`；签名里没有 `rng`，纯查询。
  - `public_battle_state()` 只在 `PLAYER_TURN` 计算 `intent`，其余时刻为 `null`；字段始终存在，前端可无条件读。
  - 攻击意图的伤害走 `_damage_with_weapon`，与真实结算一致（带未消耗长剑时 +2）。
  - `pass` 的 `source` 定为 `"none"`（比计划里的示例更准确）：预演会重置技能，`pass` 实际几乎不可达，但翻译口径被测试钉住。
- 门禁：`compileall` 通过、`ruff check .` 通过、`ruff format --check .` 通过、`pytest -q` **238 passed**（本轮前 225，新增 13：`test_ai.py` 8、`test_api.py` 5）。
- **零变化验收（硬标准，通过）**：`%TEMP%\combo_verify.py` 每次迭代增加"读取公开状态"后复跑三档 2400 局，**与上一轮读数逐字相同**——困难 战士 60.1% / 法师 38.4% / 游侠 51.3%、法师 VS 战士 32.3%，中等与简单同样逐字一致，长剑使用量 1250 / 1327 / 938 也完全相同。意图预估确实是零副作用。
- **一致性验收**（`%TEMP%\intent_verify.py`，400 局/格，玩家座位由 AI 驾驶；每格 1000~2800 个可比回合）：

  | 难度 | 战士 | 法师 | 游侠 |
  |---|---|---|---|
  | 困难 | 64.8% | 82.6% | 80.7% |
  | 中等 | 64.4% | 76.2% | 74.6% |
  | 简单 | 58.4% | 56.9% | 57.4% |

- **实施中修正的预期（"模拟依据"一节里"困难应 100% 一致"被实测推翻）**：电脑回合开始固定抽 1 张牌，抽到的牌有相当概率改变它的最优第一步——这是"计划不是承诺"的量化事实。战士偏低（≈65%）是因为它的"技能护盾"经常在计划里排第一、却被抽到的伤害牌取代；简单/中等还叠加难度自身的随机选择。
- 已知特征（记录在案，不是 bug）：
  1. 预告实际约 6~8 成按计划走（困难 65%~83%），偏差主要来自抽牌；
  2. `pass` 意图在预演里几乎不可达（技能每回合重置），翻译口径仍被测试钉住；
  3. 意图会暴露电脑打算打的那张牌——这是设计给玩家的信息优势（决策 5），不得以"对等"为由删除或扩大成"展示手牌"。
- 结束状态：敌人意图预告（后端）落地并通过全量测试、零变化验收与一致性验收；前端展示留给前端同事。

## Completion Criteria

- `enemy.intent` 在玩家回合输出，形状稳定（`kind` / `source` / `name` / `value` / `text`），其余状态为 `null`。
- 同一状态两次读取逐字节相等；不消耗 RNG、不修改任何状态。
- 攻击意图的伤害与真实结算一致（含未消耗的武器加成）。
- 三档难度 2400 局对局读数与上一轮验收记录**逐字不变**。
- 意图与实际首张动作的一致率统计记录在案（困难应 100%）。
- 全量测试、ruff、compileall 全绿；`api-contract.md` 与验收文档同步。
- **本轮不做**：前端展示、意图的历史记录、多回合预测、把意图用于平衡调整。
