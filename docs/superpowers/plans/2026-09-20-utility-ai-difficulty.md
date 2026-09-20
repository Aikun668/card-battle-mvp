# 效用评分 AI 与可调难度 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将电脑从固定 `if / elif` 规则树升级为“候选行动 + 效用评分 + 难度选择”AI，让简单、中等、困难共享同一套战斗数值与动作权限，只表现为不同的决策质量。

**Architecture:** `game/ai.py` 只负责枚举候选、评估候选和按难度选择候选，绝不直接修改生命、能量、手牌或日志；这些结算仍由 `BattleState` 统一执行。电脑回合每完成一个动作就重新生成候选并评分，因此既能支持连续行动，也能让以后新增的装备、条件牌和响应牌以独立评分函数接入。

**Tech Stack:** Python 3、Flask、pytest、原生 HTML/CSS/JavaScript、SQLite 会话持久化。

**Spec:** `docs/队友宏观计划/游戏玩法路线优先级.md`

## Decisions (2026-09-20)

实施前确认的六项决策，覆盖原计划中未明确或存在冲突的地方：

1. **电脑保持连续行动。** 玩家每回合有 3 点能量、可连出多张牌，电脑同样如此。这是刻意的平衡改动，不是纯重构；`test_end_turn_runs_one_enemy_action_then_returns_to_player` 必须改名为多动作语义并重写断言。
2. **旧的阈值测试重写。** `tests/test_ai.py` 中编码 if/elif 行为的测试不再有效。保留意图仍成立的三项（低血治疗、玩家低血时击杀、低血无治疗时转防御），删除"默认打最高面板伤害"（能量效率计入评分后该前提不成立），其余由新评分测试替代。
3. **难度存进 `BattleState`。** 新增 `ai_difficulty` 字段并随 `to_dict()` / `from_dict()` 序列化进 session，否则刷新即丢失。Task 5 的 Files 清单因此包含 `game/battle.py`、`game/session_state.py` 和 `tests/test_session_state.py`。
4. **简单难度只改变选择随机性，三档共用同一套评分函数。** 路线图表格中"击杀/能量效率/伤害溢出 = 弱化"的写法不再采用：维护两套评分会产生双倍代码路径和 bug 面，而"从高分候选中选得差"已经足以制造难度差异。路线图表格以本节为准。
5. **电脑闪避不在本轮实现。** 电脑响应玩家攻击需要全新的反向响应流程（玩家出牌 → 电脑响应窗口），原计划仅在 Task 4 Step 4 用一句话带过且没有任何测试。本轮只把 `select_enemy_action()` 写成可直接复用的纯函数，为将来接入留好入口，不实现反向响应。
6. **基线提交。** 闪避响应机制、JSON API 与 JS 前端此前均未提交。实施本计划前先以 `13f075b` 提交这批工作作为安全基线。
7. **电脑技能候选本轮不实现。** 电脑是通用 `Combatant`（名为"电脑"），没有 `HeroDefinition`，也没有任何技能结算路径。Task 1 示例测试中"候选必须包含 skill"一项无法在不凭空发明敌方技能（并牵动平衡）的前提下满足，因此本轮候选只有 `card` 与 `pass`；`ActionCandidate.kind` 保留 `"skill"` 取值，等电脑拥有英雄后再接入。同理，电脑手牌中的闪避牌不会成为候选（`ENEMY_UNUSABLE_EFFECTS`）。

## Global Constraints

- 不再用“生命值低于固定阈值就必定治疗/护盾”的 `if / elif` 决策树作为 AI 主流程。
- 所有电脑合法动作先生成候选，再评分，再选择；候选至少包含手牌、英雄技能和结束行动，响应时包含可用响应牌。
- 攻击评分必须考虑实际可造成伤害、击杀价值、伤害溢出、目标护盾和能量效率。
- 治疗评分必须只按实际可恢复生命计值，并考虑濒死风险与治疗溢出。
- 护盾评分必须考虑当前护盾、当前生命风险和可预估的近期威胁，不能无条件叠盾。
- 简单、中等、困难共用卡牌数据、英雄数据、生命值、能量、抽牌和费用规则；不得靠数值作弊调难度。
- 默认难度为中等；随机选择必须使用可注入的 `random.Random`，便于测试复现。
- 简单模式从高分候选中更常选择非最优项；中等大多选择最优项；困难选择最优项并额外做一步风险修正。
- 困难模式只做一步前瞻，不引入 Minimax、MCTS、深层博弈树或多回合搜索。
- AI 性格不是本轮功能；后续只能通过额外权重配置叠加，不能复制一套新的决策主流程。
- 不修改 Flask 路由职责、API 基础结构、固定 1920×1080 舞台、背景、人物区和卡牌素材。

## Review Focus

- 玩家剩余 8 点生命时，重击可以击杀而火球伤害溢出，电脑应优先重击而非只按面板伤害选火球。
- 电脑接近满血时，治疗的实际恢复很低，不能因为手里有治疗就取得高分。
- 电脑已有大量护盾时，继续使用护盾的评分应明显低于具有实际收益的行动。
- 相同种子和相同状态下，简单/中等难度的随机选择必须稳定可复现；困难模式必须稳定选择评分最高的行动。
- 任何行动造成终局后，电脑回合必须停止重新评分和继续出牌。

---

### Task 1: 建立统一候选行动与难度配置

**Files:**
- Modify: `game/ai.py`
- Modify: `game/models.py`
- Test: `tests/test_ai.py`

**Interfaces:**
- Consumes: `BattleState` 的电脑手牌、能量、英雄技能状态与战斗双方状态。
- Produces: `AIDifficulty` 枚举、不可变 `ActionCandidate` 数据结构、`get_available_enemy_actions(state) -> list[ActionCandidate]`。

- [ ] **Step 1: 写候选行动与难度配置失败测试**

```python
def test_available_enemy_actions_include_cards_skill_and_pass():
    battle = BattleState.create("mage", random.Random(7))
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]
    actions = get_available_enemy_actions(battle)
    assert {action.kind for action in actions} == {"card", "skill", "pass"}
    assert any(action.card_id == "enemy-slash" for action in actions)


def test_unaffordable_cards_are_not_candidates():
    battle = BattleState.create("mage", random.Random(7))
    battle.enemy.energy = 1
    battle.enemy_hand = [{"id": "enemy-fireball", "key": "fireball"}]
    assert all(action.kind != "card" for action in get_available_enemy_actions(battle))
```

- [ ] **Step 2: 运行测试，确认当前 AI 只能返回一张卡牌 ID**

Run: `pytest tests/test_ai.py -q`

Expected: 新增测试因 `ActionCandidate`、`AIDifficulty` 和候选生成函数不存在而失败。

- [ ] **Step 3: 定义最小 AI 数据结构**

在 `game/models.py` 定义 `AIDifficulty` 为 `EASY`、`MEDIUM`、`HARD`；在 `game/ai.py` 定义只描述、不结算的候选结构。

```python
@dataclass(frozen=True)
class ActionCandidate:
    kind: Literal["card", "skill", "pass", "response"]
    card_id: str | None = None
    card_key: str | None = None
    score: float = 0.0
```

候选生成只能根据费用、阶段、手牌和技能次数过滤合法动作；`pass` 始终存在。

- [ ] **Step 4: 运行候选生成测试**

Run: `pytest tests/test_ai.py -q`

Expected: 可支付手牌、可用技能和结束行动均出现；不可支付牌不出现。

- [ ] **Step 5: 提交候选模型改动**

```bash
git add game/ai.py game/models.py tests/test_ai.py
git commit -m "feat: add AI action candidates and difficulty config"
```

### Task 2: 用评分函数替代硬编码规则树

**Files:**
- Modify: `game/ai.py`
- Test: `tests/test_ai.py`

**Interfaces:**
- Consumes: `ActionCandidate`、`CARDS`、英雄技能定义、当前生命/护盾/能量。
- Produces: `score_enemy_action(state, candidate, difficulty) -> float` 与 `rank_enemy_actions(state, difficulty) -> list[ActionCandidate]`。

- [ ] **Step 1: 写关键评分排序测试**

```python
def test_lethal_heavy_strike_outranks_overkill_fireball():
    battle = BattleState.create("warrior", random.Random(7))
    battle.player.hp = 8
    battle.enemy.energy = 3
    battle.enemy_hand = [
        {"id": "heavy", "key": "heavy_strike"},
        {"id": "fireball", "key": "fireball"},
    ]
    ranked = rank_enemy_actions(battle, AIDifficulty.HARD)
    assert ranked[0].card_id == "heavy"


def test_heal_near_max_health_scores_below_damage():
    battle = BattleState.create("warrior", random.Random(7))
    battle.enemy.hp = battle.enemy.max_hp - 1
    battle.enemy_hand = [
        {"id": "heal", "key": "heal"},
        {"id": "slash", "key": "slash"},
    ]
    ranked = rank_enemy_actions(battle, AIDifficulty.MEDIUM)
    assert ranked[0].card_id == "slash"
```

再写“已有 12 点护盾时护盾低于攻击”“低血且没有致命攻击时实际治疗高于普通攻击”的测试。

- [ ] **Step 2: 运行评分测试，确认现有选择仍由 `if / elif` 主导**

Run: `pytest tests/test_ai.py -q`

Expected: 评分排序函数不存在，或旧逻辑错误地优先面板最高伤害。

- [ ] **Step 3: 实现可组合的基础评分函数**

不要在一个超长函数中重建规则树，拆成按动作类型计算的纯函数：

```python
def score_damage(state, definition) -> float: ...
def score_heal(state, definition) -> float: ...
def score_shield(state, definition) -> float: ...
def score_skill(state, hero) -> float: ...
def score_pass(state) -> float: ...
```

攻击得分必须基于 `max(0, damage - player.shield)`；可击杀时加入高额击杀奖励；多余伤害按比例扣分；低费用且不浪费能量的行动可获得效率加分。治疗只使用 `min(heal_value, max_hp - hp)`；护盾收益随现有护盾升高而递减。

- [ ] **Step 4: 在统一入口返回带分数的候选列表**

```python
def rank_enemy_actions(state, difficulty):
    scored = [replace(action, score=score_enemy_action(state, action, difficulty))
              for action in get_available_enemy_actions(state)]
    return sorted(scored, key=lambda action: action.score, reverse=True)
```

`pass` 必须低于可带来正向收益的合法行动，但在没有正向行动时可以排名第一。

- [ ] **Step 5: 运行评分测试**

Run: `pytest tests/test_ai.py -q`

Expected: 击杀成本、治疗溢出和护盾递减测试全部通过。

- [ ] **Step 6: 提交评分改动**

```bash
git add game/ai.py tests/test_ai.py
git commit -m "feat: score enemy actions by utility"
```

### Task 3: 根据难度选择评分候选，并只给困难模式一步前瞻

**Files:**
- Modify: `game/ai.py`
- Test: `tests/test_ai.py`

**Interfaces:**
- Consumes: `rank_enemy_actions(state, difficulty)` 和注入的 `random.Random`。
- Produces: `select_enemy_action(state, difficulty, rng) -> ActionCandidate`。

- [ ] **Step 1: 写可复现的难度选择测试**

```python
def test_hard_always_selects_top_scored_action():
    battle = battle_with_ranked_choices()
    selected = select_enemy_action(battle, AIDifficulty.HARD, random.Random(3))
    assert selected.card_id == rank_enemy_actions(battle, AIDifficulty.HARD)[0].card_id


def test_easy_can_select_non_top_action_with_fixed_seed():
    battle = battle_with_ranked_choices()
    selected = select_enemy_action(battle, AIDifficulty.EASY, random.Random(1))
    assert selected.card_id == "second-best-card"
```

再覆盖中等模式在固定种子下主要选择第一名、偶尔第二名；候选只有一项时三种难度都选择它。

- [ ] **Step 2: 运行难度测试，确认选择策略尚不存在**

Run: `pytest tests/test_ai.py -q`

Expected: `select_enemy_action` 不存在而失败。

- [ ] **Step 3: 实现三档选择策略**

简单模式只从前 3 个正分候选中按固定权重抽取；中等模式在前 2 个正分候选中高概率选择第一名；困难模式直接选择第一名。权重必须写成集中配置，不散落在各评分函数中。

按 Decisions 第 4 条，难度只体现在选择概率与困难模式的一步前瞻上；三档使用完全相同的评分函数，不实现"弱化版评分"。

```python
DIFFICULTY_SELECTION = {
    AIDifficulty.EASY: (0.60, 0.25, 0.15),
    AIDifficulty.MEDIUM: (0.88, 0.12),
}
```

- [ ] **Step 4: 实现困难模式的一步风险修正**

对每个困难候选构造轻量预测值：动作后自己的有效生命（生命 + 护盾）与玩家下一回合当前可见攻击牌的最高可支付伤害比较。危险越高，非防御行动的分数修正越低。该函数只能读取状态并计算估算，不执行真实动作或递归模拟回合。

```python
def hard_lookahead_adjustment(state, candidate) -> float:
    return 0.0
```

- [ ] **Step 5: 运行难度测试**

Run: `pytest tests/test_ai.py -q`

Expected: 同一种子结果稳定；困难优先高分且能在明显危险局面提高防御/治疗候选。

- [ ] **Step 6: 提交难度选择改动**

```bash
git add game/ai.py tests/test_ai.py
git commit -m "feat: add configurable utility AI difficulty"
```

### Task 4: 将评分 AI 接入电脑回合与响应时机

**Files:**
- Modify: `game/battle.py`
- Modify: `game/ai.py`
- Test: `tests/test_battle.py`
- Test: `tests/test_ai.py`

**Interfaces:**
- Consumes: `select_enemy_action()`、现有电脑出牌与响应结算入口。
- Produces: 电脑每次行动后重新选择的回合循环；响应阶段可使用同一评分/难度选择入口。

- [ ] **Step 1: 写重新评分而非预写连招的失败测试**

```python
def test_enemy_re_ranks_actions_after_each_play():
    battle = battle_with_heal_and_two_attacks()
    battle.end_player_turn()
    battle.resolve_enemy_turn()
    assert battle.log_contains_in_order("电脑使用【重击】", "电脑使用【斩击】")
```

测试必须通过改变第一张牌后的生命、能量或护盾来验证第二次选择重新读取新状态，而不是断言一份预生成动作列表。

同时处理旧测试（见 Decisions 第 1、2 条）：`test_end_turn_runs_one_enemy_action_then_returns_to_player` 改名为 `test_end_turn_runs_enemy_actions_until_pass` 并重写为多动作语义；`tests/test_ai.py` 中被删除的 `choose_enemy_card` 相关断言一并迁移到新入口。

- [ ] **Step 2: 运行回合测试，确认当前只选择一次牌**

Run: `pytest tests/test_ai.py tests/test_battle.py -q`

Expected: 电脑当前回合只执行一次动作，重新评分测试失败。

- [ ] **Step 3: 用评分候选驱动行动循环**

`resolve_enemy_turn()` 不再调用旧 `choose_enemy_card()`。每轮循环调用 `select_enemy_action()`，由 `BattleState` 执行所选动作，再检查终局、响应状态与能量。仅保留 `HAND_LIMIT + 1` 的内部防死循环上限；它不是游戏行动限制。

- [ ] **Step 4: 保持响应可复用（本轮不实现电脑闪避）**

见 Decisions 第 5 条：电脑响应玩家攻击需要全新的反向响应流程，本轮不实现。此处只要求 `select_enemy_action()` 保持为"只读状态、返回候选"的纯函数，不使用 `self` 之外的隐式状态、不直接结算，以便将来接入电脑响应时无须改动评分与选择逻辑。验证方式：确认 `select_enemy_action()` 不修改传入的 `state`（比较调用前后的 `to_dict()`）。

- [ ] **Step 5: 运行 AI 与战斗回归**

Run: `pytest tests/test_ai.py tests/test_battle.py -q`

Expected: 电脑可连续行动；每次动作后重新评估；响应、终局和能量扣减不重复结算。

- [ ] **Step 6: 提交战斗接入改动**

```bash
git add game/ai.py game/battle.py tests/test_ai.py tests/test_battle.py
git commit -m "refactor: drive enemy turns with utility AI"
```

### Task 5: 暴露难度选择、更新文档并验收

**Files:**
- Modify: `game/battle.py`（新增 `ai_difficulty` 字段与序列化，见 Decisions 第 3 条）
- Modify: `game/session_state.py`
- Modify: `game/public_state.py`
- Modify: `api_routes.py`
- Modify: `static/game.js`
- Modify: `templates/game.html`
- Modify: `docs/interaction-design.md`
- Modify: `docs/api-contract.md`
- Modify: `docs/claude-builder/acceptance.md`
- Modify: `README.md`
- Test: `tests/test_api.py`
- Test: `tests/test_acceptance_scenarios.py`
- Test: `tests/test_session_state.py`

**Interfaces:**
- Consumes: `AIDifficulty` 和 `BattleState` 的已选难度。
- Produces: 新对局可选择或默认使用 `medium`，公开状态包含 `ai_difficulty`，API 和页面显示同一难度值。

- [ ] **Step 1: 写创建对局与公开状态测试**

```python
def test_create_battle_defaults_to_medium_ai_difficulty(client):
    response = client.post("/api/game", json={"hero_key": "mage"})
    assert response.get_json()["data"]["ai_difficulty"] == "medium"


def test_create_battle_accepts_hard_ai_difficulty(client):
    response = client.post("/api/game", json={"hero_key": "mage", "ai_difficulty": "hard"})
    assert response.status_code == 201
    assert response.get_json()["data"]["ai_difficulty"] == "hard"
```

- [ ] **Step 2: 运行接口测试，确认难度字段尚未存在**

Run: `pytest tests/test_api.py -q`

Expected: 新增断言失败。

- [ ] **Step 3: 增量接入难度字段**

创建对局时未传难度则使用 `medium`；仅接受 `easy`、`medium`、`hard`，其他值返回现有风格的 422 错误。前端仅负责提交/显示难度，不计算评分或决定 AI 行动。

- [ ] **Step 4: 更新规则与验收文档**

删除电脑固定 `if / elif` 优先级和“最高伤害优先”的旧描述，替换为候选、评分、选择、难度和一步前瞻说明。明确三档难度绝不改变卡牌数值、生命值、能量或抽牌数。

- [ ] **Step 5: 执行自动化、真实 HTTP 与人工难度验收**

Run: `pytest -q`

Expected: 全部通过。

真实 HTTP 分别创建简单、中等、困难对局，确认：难度字段持久化；简单在固定种子可出现非最优选择；困难在可击杀时不浪费高费伤害；页面日志和后端状态一致。随后每档难度完整游玩至少一局，记录“决策是否自然、难度是否仅来自选择质量、是否出现不可解释的作弊数值”。

- [ ] **Step 6: 提交难度公开与验收改动**

```bash
git add game/public_state.py api_routes.py static/game.js templates/game.html README.md docs/interaction-design.md docs/api-contract.md docs/claude-builder/acceptance.md tests/test_api.py tests/test_acceptance_scenarios.py
git commit -m "feat: expose utility AI difficulty settings"
```

## Completion Criteria

- `game/ai.py` 主流程不再依赖固定 `if / elif` 行为树，而是候选生成、评分、排序、选择。
- 攻击会处理击杀、护盾、伤害溢出和能量效率；治疗与护盾只按实际收益评分。
- 简单、中等、困难使用同一规则和数值，只由选择质量、评分能力与一步前瞻区分。
- 难度选择可通过 API 和页面创建、持久化、读取；默认中等。
- 电脑连续行动或响应时，每次都从最新状态重新生成候选。
- 所有 AI 随机行为可用固定种子测试复现，终局后不会继续行动。
