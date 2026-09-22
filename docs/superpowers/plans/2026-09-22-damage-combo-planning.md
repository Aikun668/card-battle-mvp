# 伤害连招规划 Implementation Plan

**Goal:** 补上电脑 AI 的"伤害连招规划"：在能量允许时，选出本回合能打出最大伤害的动作序列的第一步。只对伤害牌规划，防御与装备保持原评分；按难度分层（简单不规划、中等看一手、困难规划到打光）。

**Spec:** `docs/队友宏观计划/游戏玩法路线优先级.md` 的 P-AI-02 后续；背景见 `docs/队友宏观计划/人机完全对等审计与实施计划.md`。

**Architecture:** 改动集中在 `game/ai.py`。在现有 `score_enemy_action()`（基础分 + 困难一步前瞻）之上叠加一层"伤害连招价值"：对伤害类候选，先把它模拟执行成一份新的 `AIObservation`（纯查询，不动真实对局），再用同一套基础评分递归求"剩余资源能兑现的最优伤害序列总价值"，加到候选分上。防御、装备、pass 的分数一律不变。

**Tech Stack:** Python 3、Flask、pytest。**本轮不碰 `game/battle.py` 的结算规则、`game/catalog.py` 的数值、`game/models.py`、`public_state`、路由与前端。**

## Decisions (2026-09-22)

1. **只对伤害牌做连招规划。** 防御与装备不参与规划、评分不变。理由见"被否掉的方案"：全类型规划会让 AI 用护盾/装备"填满剩余能量"来刷总分，实测把法师 VS 战士从 41% 压到 32%，而连招兑现率并没有更高。
2. **规划只读取 `AIObservation`，纯查询。** 模拟执行不改变真实对局状态；不新增任何隐藏信息通道（玩家手牌、抽牌堆仍然不可见）。
3. **按难度分层**（实验已验证"只前瞻伤害牌"的质量上限）：

   | 难度 | 规划深度 | 行为 |
   |---|---|---|
   | 简单 | 0 | 保持现状：逐张贪心，不会连招 |
   | 中等（默认） | 1 | 看一手：本张 + 剩余资源最优一张 |
   | 困难 | 3 | 规划到打光：本张 + 剩余资源最优序列 |

   简单档的"不会连招"是刻意保留的弱点，同时让三档难度的差异比现在更明显（沿用"难度只改变决策质量、不改数值"的原则）。
4. **规划深度上限 3。** 能量上限 3，最多 3 张 1 费牌；深度 3 已覆盖所有可达序列，不做更深搜索（无 Minimax / MCTS）。
5. **平衡底线与测量条件（本计划一并定下）：**
   - 测量仪 = 本计划落地后的 AI（修好连招的版本），在平衡调整期间不换版本；
   - 口径 = 双方困难 AI 驾驶、先手按种子对半、每组 ≥ 2000 局（±2% 噪声）；
   - 硬标准 = 同英雄镜像 50/50（已达标）；
   - 底线 = **任意对位的劣势方 ≥ 35%**（当前实测 33~34%，只差 1~2 点）；
   - 目标 = 不存在"通吃"英雄（对所有对手都 > 55%）；平衡调整留给下一轮专项任务。

## 模拟依据

两个诊断脚本（2026-09-22 跑，走真正的 `BattleState.create()` 与 `game/ai.py`）：

**一、决策质量**（`%TEMP%\quality_probe.py`，200 个固定手牌场景，法师 AI，统计打出的伤害牌面值与理论最大面值之比）：

| 版本 | 总面伤 | 理论上限 | 兑现率 | 未达上限场景 | 平均动作数 |
|---|---:|---:|---:|---:|---:|
| baseline（逐张贪心） | 2892 | 3150 | 91.8% | 116/200 | 1.31 |
| 全类型前瞻（depth=1） | 2994 | 3150 | 95.0% | 42/200 | 1.93 |
| 全类型前瞻（depth=3） | 2990 | 3150 | 94.9% | 40/200 | 1.96 |
| **只前瞻伤害（depth=1）** | 3138 | 3150 | **99.6%** | 6/200 | 1.93 |
| **只前瞻伤害（depth=3）** | 3150 | 3150 | **100.0%** | 0/200 | 1.96 |

baseline 的典型失误：`[火球, 斩击, 技能可用]` 能量 3，打火球 14 伤收工，而"技能 10 + 斩击 6 = 16 伤"更好；只前瞻伤害的版本 200 个场景全部打出理论上限。

**二、对局读数**（`%TEMP%\combo_experiment.py`，2400 局/组，双方困难 AI，先手对半）：

| 版本 | 战士胜 | 法师胜 | 游侠胜 | 法师 VS 战士 | 战士每局伤害 |
|---|---:|---:|---:|---:|---:|
| baseline | 55.1% | 40.0% | 54.6% | 41.0% | 33.6 |
| 只前瞻伤害（depth=1） | 60.7% | 38.6% | 50.3% | 32.7% | 37.3 |
| 只前瞻伤害（depth=3） | 60.3% | 39.0% | 50.4% | 34.0% | 37.6 |

读数解读（写入验收基线）：修好连招后战士受益最大（每局伤害 +12%），三个对位从 41~43% 移到 33~34%，都逼近"≥ 35%"底线——这是双方 AI 同步升级的真实格局，不是 AI 变差；"法师弱"是牌组/数值层面的独立问题，留给下一轮平衡诊断，本计划不调任何数值。

## 被否掉的方案（量过了，不是拍脑袋）

| 方案 | 读数 | 结论 |
|---|---|---|
| 全类型前瞻（防御/装备也参与规划） | 兑现率只有 95.0%（不如只前瞻伤害的 99.6%）；法师 VS 战士 32.7%；AI 用护盾填满剩余能量刷总分（诊断样例：该打"重击+斩击=16 伤"，选了"斩击+斩击+护盾=12 伤+6 盾"因为总分 24 > 21.5） | **否**：评分里 1 点护盾与 1 点伤害同尺不同价，规划会放大这个缺陷 |
| 三档难度统一做完整规划 | 难度轴会从"三档几乎无差别"继续存在；简单档失去应有的弱点 | **否**：分层设计同时改善难度轴 |
| 只调 `EFFICIENCY_WEIGHT`（提高能量效率权重） | 未实验 | **否**：是调参不是修连招，解决不了"组合价值不在单张分里"的结构问题 |

## Global Constraints

- **不改数值**：`CARDS`、`HEROES`、伤害/护盾/治疗公式、能量与抽牌规则一个数字都不动。
- **不改信息边界**：`AIObservation` 字段集合不变；规划不得读取玩家手牌、抽牌堆或它们的顺序。
- **不改结算**：`game/battle.py` 只在必要时读取（不修改）；规划是"想"，不是"做"——模拟执行绝不能触碰真实 `BattleState`。
- **简单难度逐字不变**：`PLANNING_DEPTH[EASY] = 0` 时，`score_enemy_action` 的结果必须与改动前完全一致。
- **深度 ≤ 3**，不引入 Minimax / MCTS / 多回合搜索。
- **接口与存档不变**：不改 `/api` 形状、不改 `to_dict()` 格式、不碰前端。

## Review Focus

- **状态污染**（本计划最高风险）：`_after_action()` 只能通过 `dataclasses.replace` 构造新观察视图；必须有一个"随机对局跑完，四区守恒与能量非负"的不变量测试兜底。
- **测试漂移**：`tests/test_ai.py` 中钉着具体排序的用例（如"火球排第一"的 `battle_with_three_ranked_choices`）可能因连招加成移动到"技能/斩击优先"。逐条确认是"新行为正确"再改断言，不许批量无脑改。预计漂移集中在：三选一排序、简单难度的分数不变（反向：不应漂移）。
- **简单难度**：`PLANNING_DEPTH.get(EASY, 0) == 0` 的代码路径要有一条测试钉死（分数与 baseline 逐字相同）。
- **递归成本**：困难档每次决策最坏约 6³ 次基础评分；验收记录里记录 2400 局模拟总耗时（基线：baseline 2.7s、depth=1 8.1s、depth=3 9.6s），并确认网页对局无可感知卡顿。
- **LETHAL_BONUS 不重复计分**：击杀奖励只出现在包含击杀的那条路径上；写一条"能击杀时优先完成击杀"的测试。

---

### Task 1: 伤害连招规划核心

**Files:**
- Modify: `game/ai.py`
- Test: `tests/test_ai.py`

**Interfaces:**
- 新增 `PLANNING_DEPTH: dict[AIDifficulty, int] = {EASY: 0, MEDIUM: 1, HARD: 3}`
- 新增 `_after_action(observation: AIObservation, candidate: ActionCandidate) -> AIObservation | None`（纯查询模拟执行；pass 或不可执行返回 None）
- 新增 `_best_damage_sequence(observation: AIObservation, difficulty: AIDifficulty, remaining: int) -> float`（只遍历伤害类候选）
- 修改 `score_enemy_action()`：把现有实现抽成 `_tactical_score()`（基础分 + 困难一步前瞻，逐字保留），`score_enemy_action()` = `_tactical_score()` + 伤害连招价值

- [ ] **Step 1: 写失败测试**

```python
def test_medium_and_hard_plan_the_skill_plus_slash_combo():
    battle = battle_with_enemy_hero("mage")  # 技能 2 费 10 伤可用
    battle.enemy.energy = 3
    battle.enemy_hand = [
        {"id": "fireball", "key": "fireball"},
        {"id": "slash", "key": "slash"},
    ]
    battle.player.hp = 24
    battle.player.shield = 0
    for difficulty in (AIDifficulty.MEDIUM, AIDifficulty.HARD):
        selected = select_enemy_action(
            battle.enemy_observation(), difficulty, random.Random(0)
        )
        # 打火球只有 14 伤；技能 + 斩击能打 16。
        assert selected.card_key in {"slash", None}  # 先打斩击或技能，不先打火球
```

再覆盖：简单难度仍优先火球（逐字保持 baseline 行为）；"能击杀时优先完成击杀"；"防御/装备候选分数与 `_tactical_score` 完全一致"。

- [ ] **Step 2: 实现 `_after_action()`**

卡牌：能量减少、手牌按 id 移除、装备落入对应槽位、斩击消耗武器加成的回合标记；技能：能量减少、技能标记置为已用；pass 与不可执行返回 None。全部用 `dataclasses.replace`。

- [ ] **Step 3: 实现 `_best_damage_sequence()` 并接入 `score_enemy_action()`**

```python
def score_enemy_action(observation, candidate, difficulty):
    score = _tactical_score(observation, candidate, difficulty)
    depth = PLANNING_DEPTH.get(difficulty, 0)
    if depth and _is_damage(observation, candidate):
        after = _after_action(observation, candidate)
        if after is not None:
            score += _best_damage_sequence(after, difficulty, depth)
    return score
```

- [ ] **Step 4: 跑测试**

Run: `pytest tests/test_ai.py -q`

Expected: 新增用例通过；确认没有递归死循环（`_best_damage_sequence` 内部只调 `_tactical_score`，不调 `score_enemy_action`）。

- [ ] **Step 5: 提交**

```bash
git add game/ai.py tests/test_ai.py
git commit -m "feat: plan damage combos in enemy AI"
```

### Task 2: 边界与回归

- [ ] **Step 6: 写边界测试**

必须包含：`_after_action` 不修改传入的观察视图与任何 `BattleState` 字段（快照测试）；隐藏信息不泄漏（只改玩家手牌，规划结果与排序不变）；简单难度分数逐字不变；四区守恒的随机对局上跑 60 局随机动作，每步断言四区守恒与能量非负。

- [ ] **Step 7: 跑全量测试并逐条处理漂移**

Run: `pytest -q`

Expected: 除预期漂移外全绿。逐条检查失败用例：属于"旧行为钉子"的按新行为改断言并在验收记录里列出；属于真 bug 的修实现。

- [ ] **Step 8: 2400 局对局验收并提交**

用 `%TEMP%\combo_experiment.py` 的真实代码版本（不打补丁）复跑，记录三档难度读数与耗时；与本文档"模拟依据"逐项对照。

```bash
git add game/ai.py tests/ README.md docs/
git commit -m "test: verify combo planning on both sides at hard difficulty"
```

### Task 3: 文档与基准

- [ ] **Step 9: 同步文档**

- `README.md`「电脑 AI 与难度」：补充"伤害连招规划"与三档深度；
- `docs/claude-builder/acceptance.md`：新增"中等/困难会打出连招、简单不会"验收项；
- `docs/队友宏观计划/游戏玩法路线优先级.md`：把本任务与"平衡底线（劣势对位 ≥ 35%）""测量条件"记入；
- 本计划"验收记录"补齐。

- [ ] **Step 10: 跑门禁并提交**

```bash
python -X utf8 -m compileall -q app.py api_routes.py demo_routes.py web_support.py game && ruff check . && ruff format --check . && pytest -q
```

---

## 验收记录（Task 1–3）

- 实际改动文件：`game/ai.py`（实现）、`tests/test_ai.py`（新测试 + 漂移修正）、`tests/test_battle.py`（整局不变量），以及三份文档。`game/battle.py`、`game/catalog.py`、`game/models.py`、`public_state`、路由与前端一行未动。
- 实现要点：
  - `PLANNING_DEPTH = {EASY: 0, MEDIUM: 1, HARD: 3}`；原 `score_enemy_action` 抽成 `_tactical_score`（基础分 + 困难一步前瞻，逐字保留），新 `score_enemy_action` = 战术分 + 伤害连招价值。
  - `_after_action()` 用 `dataclasses.replace` 在不可变快照上模拟执行（能量、手牌、装备槽、武器回合标记、技能标记）；`_best_damage_value()` 递归求剩余资源的最优伤害序列，深度上限即 `PLANNING_DEPTH`。
  - **实施中发现的修正（写进决策 1 的落地解释）**：只有伤害牌做前瞻时，"长剑 + 斩击×2"会因为伤害牌的连招分被抬高而不再先穿剑（实测长剑使用量 -41%）。因此 `_plans_sequence()` 把**武器**也纳入规划，但武器的前瞻**只统计它能加成的伤害牌**（`boost_keys=LONGSWORD_BOOST_KEYS`）——否则"长剑配火球"会被误判成值得先穿剑。护盾、治疗、护甲仍然完全不参与规划。
- 门禁：`compileall` 通过、`ruff check .` 通过、`ruff format --check .`（`tests/test_ai.py` 被 `ruff format` 重排过两处换行）通过、`pytest -q` **225 passed**（本轮前 213，新增 12 条：`test_ai.py` 11 条、`test_battle.py` 1 条）。
- **连招兑现（真实代码，不打补丁）**：`%TEMP%\quality_probe.py` 的 baseline 组 200 个固定场景兑现率 **100.0%（0/200 未达上限）**，对照改动前 91.8%（116/200）。平均动作数 1.31 → 1.96。
- **对局验收**（`%TEMP%\combo_verify.py`，真实代码，2400 局/档，双方同难度，先手种子对半）：

  | 难度 | 战士 | 法师 | 游侠 | 法师 VS 战士 | 法师 VS 游侠 | 战士 VS 游侠 | 耗时 |
  |---|---|---|---|---|---|---|---|
  | 困难 | 60.1% | 38.4% | 51.3% | 32.3% | 32.4% | 63.2% | 13.6s |
  | 中等 | 58.4% | 38.4% | 52.8% | 34.2% | 30.6% | 60.3% | 15.2s |
  | 简单 | 58.1% | 39.8% | 51.8% | 35.0% | 33.9% | 60.3% | 8.6s |

  与实验预测（只前瞻伤害 depth=3，法师 VS 战士 34.0%）逐项在 ±2.6 点内，方向一致；镜像仍严格 50%。**长剑使用量 1250 次 > 改动前 922 次**——武器退化修正被对局数据证实。
- 测试漂移逐条处理（共 4 处旧断言 + 1 处实现修正）：
  1. 三选一场景（火球/重击/斩击）——规划后"重击 + 斩击"组合分高于火球，属**新行为正确**：`test_medium_mostly_selects_the_top_action_but_sometimes_the_second`、`_pick_rates`、`test_easy_can_select_a_non_top_action` 改成"最优按评分动态取"，不再硬编码火球为第一。
  2. `test_attack_that_punches_through_shield_beats_a_fully_absorbed_one`——两张牌的连招顺序等价导致平手，属**行为等价**：能量改成 2，恢复"单张决策"的原始语义。
  3. `test_enemy_stops_playing_the_moment_the_player_dies`——6 血时重击与斩击都能击杀，两种顺序总分相同：断言放宽为"击杀成立且只出一张牌"。
  4. `test_a_full_enemy_turn_can_equip_and_then_cash_in_the_bonus`——**判定为新行为退化**，修的是实现而不是测试（见上面"实施中发现的修正"）；测试保持"打穿 12 点护盾"的原场景原样通过。
- 新增测试：`test_ai.py` 11 条（连招开手、整回合 16 伤、简单仍贪心、防御分不受影响、击杀不延迟、排序不污染、`_after_action` 语义 3 条、简单难度的分数等于战术分、连招压过单张）；`test_battle.py` 1 条（AI 规划驱动的整局四区守恒与能量非负，6 局）。
- 已知问题（留给下一轮）：
  1. **平衡底线未达标**：三个对位的劣势方 32.3%~36.8%，低于"≥ 35%"的目标（法师 VS 战士 32.3%、法师 VS 游侠 32.4%）。这是"修好连招后暴露的真实强弱"，按决策 5 留给平衡诊断专项，本计划不调数值。
  2. **难度轴差异仍小**：三档同口径下战士 60.1 / 58.4 / 58.1，分层设计生效但幅度只有 1~2 点。
  3. **平手裁决**：击杀或连招顺序等价时由手牌顺序决定先打哪张（行为等价，记录在案）。
  4. 护盾/治疗/装备的**评分尺度**（削盾 0.4 权重、装备静态定价）仍未重审——它是"全类型前瞻会被刷分"与"武器时机"两个现象的根因，留给后续专项。
- 结束状态：伤害连招规划落地并通过全量测试、真实代码质量诊断与三档对局验收。

## Completion Criteria

- 质量诊断：只前瞻伤害的版本在 200 个固定场景兑现率 ≥ 99.6%（对照 baseline 91.8%）。
- 中等/困难在"火球 + 斩击 + 技能"类场景打出 16 伤序列，不再"有火球就打火球"。
- 简单难度评分与行为逐字保持 baseline，不享受规划。
- 规划是纯查询：随机对局不变量测试、装备/防御评分不变、信息边界不泄漏。
- 全量测试、ruff、compileall 全绿；2400 局对局读数与本文档"模拟依据"一致；耗时记录在案。
- **本轮不做**：平衡数值调整（法师/游侠/战士强弱留待下一轮专项诊断，底线 35%、测量条件已在本计划定下）、护盾/治疗评分尺度的重审、行动意图、新卡牌。
