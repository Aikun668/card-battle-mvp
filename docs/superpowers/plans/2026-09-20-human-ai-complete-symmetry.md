# 人机完全对等 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让人类玩家与电脑在同一局中拥有相同的英雄池、牌库、起手、先后手机会、能量、护盾、普通牌、英雄技能、结束行动、响应权和信息边界；AI 只负责选择电脑合法动作。

**Architecture:** 把当前“玩家状态 + 特例电脑状态”收敛为两个 `ParticipantState`，每个参与者独立拥有英雄、战斗体、手牌区、抽牌区、弃牌区和技能次数。`BattleState` 仍是唯一规则所有者；`game/ai.py` 只接收电脑私有信息和双方公开信息构成的观察视图，返回候选动作而不直接结算。

**Tech Stack:** Python 3、Flask、pytest、原生 HTML/CSS/JavaScript、SQLite 会话持久化。

**Spec:** `docs/队友宏观计划/人机完全对等审计与实施计划.md`

## Decisions (2026-09-20)

实施前确认的九条决策，覆盖计划中留白或存在冲突的地方：

1. **session 只写新结构。** `to_dict()` 只输出 `participants` 结构，不再双写旧的扁平键；`from_dict()` 同时兼容新旧 payload（缺 `participants` 时按 Task 1 Step 5 迁移）。同一提交里把 `tests/test_acceptance_scenarios.py` 等直接读旧键的断言全部迁走，避免两套键长期漂移。
2. **回合数按第一个行动方计。** 本局第一个行动方每次开始自己的新行动回合时 `round_number + 1`，因此无论谁先手，10 回合上限都保证双方各行动 10 次。
3. **电脑先手在 `create()` 内同步跑完。** `BattleState.create()` 返回时只会是玩家回合或终局，`POST /api/game` 不需要新增轮询或"推进电脑"端点；创建路由统一改用 `persist_battle()`，将来出现"创建即终局"时结果仍然入表。（当前首回合电脑最多 18 点伤害 < 法师 24 点生命，不会触发，但接口按此约定实现。）
4. **`pass` 允许策略性使用，但不许随机空过。** `score_pass()` 必须有真实依据（手上有闪避且保留 1 点能量更有价值等），只有它排到第一时才空过；简单难度不做策略性空过，困难同样按评分决定。`pass` 始终是候选，但**不进入简单/中等的随机抽取池**——随机池只用来表达"选得差"，不能表达"整回合不做任何事"。
5. **电脑英雄纯随机。** 允许与玩家同英雄，不根据玩家英雄反选；页面必须展示电脑英雄。验收改为记录"三档难度 × 三种电脑英雄"的胜率与平衡探针结果，不要求各组合胜率一致。
6. **闪避响应复用现有难度配置。** 电脑的闪避 / 放弃走同一套候选评分与 `DIFFICULTY_SELECTION`，不新增闪避专用阈值表。
7. **困难模式接受信息边界带来的降级。** 一步前瞻改为只用公开牌表、公开弃牌、玩家公开能量和英雄技能做最坏情况估算；难度因此下降是预期结果，不给困难额外补偿。
8. **本轮只做规则对等，不加护盾上限。** 删除电脑护盾清零后双方护盾都跨回合持久化，"拖平"风险记为已知平衡问题；Task 2 完成后立即跑平衡探针，再单独决定是否做护盾上限或衰减。
9. **每个 Task 边界都要验收，不能堆到最后。** 每个 Task 结束运行：本任务测试、全量 `pytest`、对应的 API/HTTP 流程、前端契约或页面冒烟检查，并附一轮平衡探针。Task 6 的 Files 清单补上 `tests/test_frontend_contract.py`。

## Global Constraints

- 双方使用同一英雄池、同一 13 张固定牌库、相同手牌上限、相同能量、相同技能费用、相同技能次数与相同护盾持续规则。
- 电脑英雄独立随机选择，允许同英雄，不根据玩家英雄反选；首个行动方也独立随机决定。
- 双方攻击均可触发一次闪避响应；玩家由 UI 选择，电脑由 AI 选择。
- AI 不得读取玩家私有手牌或抽牌堆顺序；困难模式的一步前瞻只能基于公开信息。
- 简单、中等、困难不改动生命、伤害、能量、抽牌、牌库和行动权限；只改变 AI 的候选排序与选择质量。
- `pass` 是双方真实合法动作，电脑不能因为评分实现被强制把所有正收益牌打完。
- 浏览器不能接收电脑手牌或电脑抽牌堆；双方英雄、生命、护盾、能量、技能状态和公开日志必须可见。
- 保留 Flask 路由和 `/api` JSON 约定的职责边界；前端不计算战斗伤害、抽牌、响应或 AI 决策。
- 不加入装备、多人、花色、判定、反击链、Minimax、MCTS 或新卡牌。

## Review Focus

- 旧 session 缺少敌方英雄和参与者分区时，读取后必须能安全迁移或返回明确的新局提示，不能 500。
- 电脑先手时，创建对局后必须正确进入电脑行动、完成行动并把状态保存；不能假设每局都从玩家回合开始。
- 电脑用闪避抵消玩家攻击时，只能使用其上一回合保留的能量，不能在响应前免费刷新到 3。
- 困难 AI 在测试中被给予一张玩家私有火球时，评分结果不得随该私有手牌变化；只可依据公开信息判断危险。
- 双方任意一个英雄技能造成终局、抽牌或响应后，不能再继续执行同一行动链中的后续卡牌。

---

### Task 1: 建立通用参与者状态与英雄选择

**Files:**
- Modify: `game/models.py`
- Modify: `game/battle.py`
- Modify: `game/session_state.py`
- Test: `tests/test_battle.py`
- Test: `tests/test_session_state.py`

**Interfaces:**
- Consumes: `HEROES`、`Combatant`、现有 session `battle` payload。
- Produces: `Side` 枚举、`ParticipantState`、`BattleState.participant(side)`、`BattleState.enemy_hero` 与可向后兼容的 `to_dict()` / `from_dict()`。

- [ ] **Step 1: 写双方英雄与旧 session 迁移失败测试**

```python
def test_new_battle_assigns_two_heroes_from_the_same_roster():
    battle = BattleState.create("mage", random.Random(7), starting_side=Side.PLAYER)
    assert battle.participant(Side.PLAYER).hero.key == "mage"
    assert battle.participant(Side.ENEMY).hero.key in HEROES
    assert battle.participant(Side.ENEMY).combatant.max_hp == HEROES[
        battle.enemy_hero.key
    ].max_hp


def test_old_session_payload_migrates_with_a_valid_enemy_hero():
    payload = BattleState.create("warrior", random.Random(7)).to_dict()
    payload.pop("participants", None)
    payload.pop("enemy_hero", None)
    restored = BattleState.from_dict(payload)
    assert restored.enemy_hero.key in HEROES
```

- [ ] **Step 2: 运行测试，确认当前状态只有玩家英雄和固定 28 生命电脑**

Run: `pytest tests/test_battle.py tests/test_session_state.py -q`

Expected: 新增测试因 `Side`、`ParticipantState` 或 `enemy_hero` 不存在而失败。

- [ ] **Step 3: 在模型中定义双方参与者**

```python
class Side(str, Enum):
    PLAYER = "player"
    ENEMY = "enemy"


@dataclass
class ParticipantState:
    hero: HeroDefinition
    combatant: Combatant
    hand: list[dict]
    draw_pile: list[str]
    discard_pile: list[str]
    skill_used_this_turn: bool = False
```

`BattleState` 持有两个 `ParticipantState`，并提供 `participant(side)` 和 `opponent_of(side)`。在过渡期保留只读 `player`、`enemy`、`hero` 属性，映射到对应参与者，避免一次性破坏路由和旧测试。

- [ ] **Step 4: 独立随机电脑英雄，不做反选**

`create()` 使用同一个会话 RNG 从 `HEROES` 中选择电脑英雄；允许与玩家同英雄。选择函数只接收 RNG 和英雄目录，不接收玩家英雄 key，确保电脑不会根据玩家选择进行隐藏克制。

```python
def choose_enemy_hero(rng: random.Random) -> HeroDefinition:
    return rng.choice(list(HEROES.values()))
```

- [ ] **Step 5: 为旧 session 提供兼容读取**

旧 payload 缺少 `participants` 时，根据旧的 `hero`、`player`、`enemy`、`hand` 和三套牌区构建双方参与者；敌方英雄使用固定且可复现的默认英雄 `warrior`，并把旧电脑的 `max_hp` 规范为战士的生命上限、把当前生命夹在 `0..32` 范围内。这样旧存档从下一次保存开始就进入新规则，不会留下“战士英雄却只有 28 点最大生命”的半迁移状态。新对局必须使用随机选择，不能沿用该默认值。

- [ ] **Step 6: 运行状态与会话测试**

Run: `pytest tests/test_battle.py tests/test_session_state.py -q`

Expected: 新局存在两个英雄；旧 session 可读取；新 payload 往返不丢失双方英雄和技能状态。

- [ ] **Step 7: 提交参与者模型改动**

```bash
git add game/models.py game/battle.py game/session_state.py tests/test_battle.py tests/test_session_state.py
git commit -m "refactor: model both combatants as equal participants"
```

### Task 2: 统一牌库、先手、回合资源和护盾生命周期

**Files:**
- Modify: `game/battle.py`
- Modify: `game/catalog.py`
- Test: `tests/test_battle.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: Task 1 的 `Side` 和 `ParticipantState`。
- Produces: `draw_cards_for(side, count)`、`start_turn(side, *, initial=False)`、`advance_turn()` 和可测试的 `starting_side` 创建参数。

- [ ] **Step 1: 写双方相同牌库、随机先手与护盾持久测试**

```python
def test_both_sides_receive_the_same_fixed_deck_composition():
    battle = BattleState.create("warrior", random.Random(7), starting_side=Side.PLAYER)
    assert sorted(battle.participant(Side.PLAYER).draw_pile +
                  [card["key"] for card in battle.participant(Side.PLAYER).hand]) == sorted(FIXED_DECK_KEYS)
    assert sorted(battle.participant(Side.ENEMY).draw_pile +
                  [card["key"] for card in battle.participant(Side.ENEMY).hand]) == sorted(FIXED_DECK_KEYS)


def test_enemy_shield_persists_until_player_damage_consumes_it():
    battle = BattleState.create("warrior", random.Random(7), starting_side=Side.PLAYER)
    battle.enemy.shield = 6
    battle.end_player_turn()
    battle.resolve_enemy_turn()
    assert battle.enemy.shield == 6
```

另写测试覆盖：显式 `starting_side=Side.ENEMY` 时电脑先行动；未传时由 RNG 决定；任一方自己的第二回合才抽 1 张并恢复 3 点能量。

- [ ] **Step 2: 运行测试，确认电脑牌库缺闪避且其护盾会被单独清零**

Run: `pytest tests/test_battle.py tests/test_catalog.py -q`

Expected: 牌库相同与护盾持久测试失败。

- [ ] **Step 3: 删除电脑专属牌库与资源特例**

删除 `ENEMY_DECK_KEYS` 和所有按“电脑 / 玩家”复制的抽牌代码，双方各用 `list(FIXED_DECK_KEYS)` 洗牌。删除 `resolve_enemy_turn()` 中的 `self.enemy.shield = 0`。用一个参与方参数化的抽牌函数统一手牌上限、弃牌回洗和日志。

- [ ] **Step 4: 实现通用回合推进与公平先手**

`start_turn(side, initial=False)` 在非初始回合抽 1 张、恢复该方能量为 3、重置该方技能次数；`advance_turn()` 切换到对手。`BattleState.create()` 接受只供测试使用的 `starting_side: Side | None`；传 `None` 时由 RNG 均匀选择。

- [ ] **Step 5: 运行资源与回合测试**

Run: `pytest tests/test_battle.py tests/test_catalog.py -q`

Expected: 双方牌库均含 13 张和 1 张闪避；护盾只受伤害影响；两种先手均可完成第一轮。

- [ ] **Step 6: 提交资源规则改动**

```bash
git add game/battle.py game/catalog.py tests/test_battle.py tests/test_catalog.py
git commit -m "feat: unify player and enemy resource rules"
```

### Task 3: 将卡牌、技能与结束行动改成双方共享的合法动作

**Files:**
- Modify: `game/battle.py`
- Modify: `game/ai.py`
- Test: `tests/test_battle.py`
- Test: `tests/test_ai.py`

**Interfaces:**
- Consumes: Task 1 的参与者状态和 Task 2 的通用回合函数。
- Produces: `play_card_for(side, card_id)`、`use_skill_for(side)`、`end_turn_for(side)`、包含 `card` / `skill` / `pass` 的 `ActionCandidate`。

- [ ] **Step 1: 写电脑技能与真实结束行动失败测试**

```python
def test_enemy_can_use_the_same_hero_skill_once_per_own_turn():
    battle = BattleState.create("mage", random.Random(7), starting_side=Side.ENEMY)
    battle.enemy_hand = []
    battle.resolve_enemy_turn()
    assert battle.player.hp == battle.player.max_hp - battle.enemy_hero.skill_value
    assert battle.participant(Side.ENEMY).skill_used_this_turn is True
    assert battle.enemy.energy == 1


def test_pass_remains_a_selectable_enemy_candidate_when_a_card_is_playable():
    battle = BattleState.create("warrior", random.Random(7), starting_side=Side.ENEMY)
    battle.enemy_hand = [{"id": "slash", "key": "slash"}]
    assert any(action.kind == "pass" for action in get_available_enemy_actions(battle))
```

再覆盖战士护盾技能、游侠伤害加抽牌技能、电脑技能和普通卡共用 3 点能量、技能一回合不能重复使用。

- [ ] **Step 2: 运行测试，确认当前 AI 候选只有 `card` 和 `pass` 且电脑没有技能状态**

Run: `pytest tests/test_ai.py tests/test_battle.py -q`

Expected: 电脑技能测试失败，候选类型缺少 `skill`。

- [ ] **Step 3: 实现参数化卡牌与技能结算**

```python
def play_card_for(self, side: Side, card_id: str) -> ActionResult: ...
def use_skill_for(self, side: Side) -> ActionResult: ...
```

两个函数必须从 `participant(side)` 取手牌、能量、英雄和弃牌区，从 `opponent_of(side)` 取攻击目标。游侠抽牌使用 `draw_cards_for(side, 1)`。现有 `play_card()` 和 `use_skill()` 只作为玩家 API 兼容包装器调用对应通用函数。

- [ ] **Step 4: 扩展 AI 候选与评分**

`get_available_enemy_actions()` 枚举电脑费用足够的普通牌、未使用且费用足够的英雄技能、以及始终可选的 `pass`。为技能增加与对应卡牌效果一致的评分入口；`pass` 不得在简单/中等模式被预先过滤，而应通过“保留能量用于闪避、当前无有效收益”等评分参与排序。

- [ ] **Step 5: 运行双方动作测试**

Run: `pytest tests/test_ai.py tests/test_battle.py -q`

Expected: 双方均可在自己的回合使用普通牌、一次技能和结束行动；电脑候选不再缺技能或被强制出所有牌。

- [ ] **Step 6: 提交共享动作改动**

```bash
git add game/ai.py game/battle.py tests/test_ai.py tests/test_battle.py
git commit -m "feat: give both sides equal cards skills and pass actions"
```

### Task 4: 通用化攻击响应，并让 AI 拥有闪避选择

**Files:**
- Modify: `game/models.py`
- Modify: `game/battle.py`
- Modify: `game/ai.py`
- Test: `tests/test_battle.py`
- Test: `tests/test_ai.py`

**Interfaces:**
- Consumes: Task 3 的 `play_card_for()` 和 AI 候选模型。
- Produces: `PendingAttack(attacker: Side, defender: Side, card_key: str, card_name: str, damage: int)`、`respond_for(side, action)`、`choose_enemy_response(observation, rng)`。

- [ ] **Step 1: 写双方均可闪避的失败测试**

```python
def test_enemy_can_dodge_a_player_attack_with_retained_energy():
    battle = BattleState.create("warrior", random.Random(7), starting_side=Side.PLAYER)
    battle.enemy.energy = 1
    battle.enemy_hand = [{"id": "enemy-dodge", "key": "dodge"}]
    battle.hand = [{"id": "player-heavy", "key": "heavy_strike"}]
    before = battle.enemy.hp
    battle.play_card("player-heavy")
    assert battle.enemy.hp == before
    assert battle.enemy.energy == 0
    assert "dodge" in battle.enemy_discard_pile
```

再覆盖：玩家闪避电脑攻击、任意一击只响应一次、无能量时不能闪避、放弃后护盾优先吸收伤害、电脑闪避后玩家仍可继续自己的行动回合。

- [ ] **Step 2: 运行响应测试，确认当前只会为玩家创建 `RESPONSE`**

Run: `pytest tests/test_battle.py tests/test_ai.py -q`

Expected: 电脑闪避测试失败，玩家攻击立即结算。

- [ ] **Step 3: 以攻击方 / 防御方建立待响应事件**

攻击牌从攻击方手牌移到弃牌区、扣除能量后，创建 `PendingAttack`。若防御方有闪避和足够能量：防御方为玩家时进入现有 UI 等待；防御方为电脑时调用 AI 响应选择。若没有可用闪避，立即按护盾优先规则结算。

- [ ] **Step 4: 让 AI 对“闪避 / 放弃”评分**

电脑响应候选只包含 `dodge` 和 `pass`。闪避分数基于本次可抵消的实际生命伤害与剩余能量价值；简单难度允许偶尔放弃，中等/困难在高实际伤害时优先闪避。不得为电脑自动免费闪避。

- [ ] **Step 5: 运行响应回归测试**

Run: `pytest tests/test_ai.py tests/test_battle.py -q`

Expected: 两边拥有相同的闪避资格、费用和弃牌去向；没有嵌套响应或重复扣费。

- [ ] **Step 6: 提交通用响应改动**

```bash
git add game/models.py game/battle.py game/ai.py tests/test_ai.py tests/test_battle.py
git commit -m "feat: make dodge responses symmetric"
```

### Task 5: 建立 AI 信息边界，移除对玩家私有手牌的读取

**Files:**
- Modify: `game/ai.py`
- Modify: `game/battle.py`
- Test: `tests/test_ai.py`
- Test: `tests/test_battle.py`

**Interfaces:**
- Consumes: 双方参与者状态和公开行动日志。
- Produces: `AIObservation`、`BattleState.enemy_observation()` 和只接受 `AIObservation` 的 `rank_enemy_actions()` / `select_enemy_action()`。

- [ ] **Step 1: 写 AI 不读取玩家私有手牌的失败测试**

```python
def test_hard_ai_rank_is_unchanged_when_only_hidden_player_hand_changes():
    battle = public_state_with_dangerous_enemy()
    first = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.HARD)
    battle.hand = [{"id": "hidden-fireball", "key": "fireball"}]
    second = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.HARD)
    assert [(item.kind, item.card_key) for item in first] == [
        (item.kind, item.card_key) for item in second
    ]
```

同时测试 AI 能读取自己的手牌、双方公开生命/护盾/能量/英雄、固定牌表与公开弃牌记录。

- [ ] **Step 2: 运行测试，确认当前困难模式遍历 `state.hand`**

Run: `pytest tests/test_ai.py -q`

Expected: 隐藏手牌改变时，当前 `estimate_player_threat()` 的排序发生变化。

- [ ] **Step 3: 定义受限观察视图**

```python
@dataclass(frozen=True)
class AIObservation:
    self_state: PublicParticipantState
    opponent_state: PublicParticipantState
    own_hand: tuple[dict, ...]
    public_discard_keys: tuple[str, ...]
    catalog_keys: tuple[str, ...]
```

`PublicParticipantState` 只包含英雄 key、生命、护盾、能量、技能是否已使用；绝不能包含对方手牌、对方抽牌堆或其顺序。

- [ ] **Step 4: 用公开威胁估计替代窥视手牌**

困难模式的一步前瞻只根据公开英雄技能、玩家当前公开能量、固定牌表和公开弃牌记录估算“潜在最大威胁”；不能读取玩家当前拥有哪一张。所有 AI 评分与选择函数改为只接收 `AIObservation`。

- [ ] **Step 5: 运行信息边界测试**

Run: `pytest tests/test_ai.py tests/test_battle.py -q`

Expected: 私有玩家手牌变化不影响 AI 排名；公开生命、能量或已打出牌变化会影响 AI 排名。

- [ ] **Step 6: 提交信息边界改动**

```bash
git add game/ai.py game/battle.py tests/test_ai.py tests/test_battle.py
git commit -m "fix: prevent AI from reading hidden player cards"
```

### Task 6: 公开双方状态、适配路由与完成验收

**Files:**
- Modify: `game/public_state.py`
- Modify: `api_routes.py`
- Modify: `demo_routes.py`
- Modify: `templates/game.html`
- Modify: `static/game.js`
- Modify: `docs/interaction-design.md`
- Modify: `docs/api-contract.md`
- Modify: `docs/claude-builder/acceptance.md`
- Modify: `README.md`
- Test: `tests/test_api.py`
- Test: `tests/test_app.py`
- Test: `tests/test_acceptance_scenarios.py`
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Consumes: Tasks 1–5 的双参与者状态、通用响应和 `AIObservation`。
- Produces: 不泄露电脑手牌的公开 API；页面上双方对称的英雄/资源/技能信息；唯一的对等规则文档。

- [ ] **Step 1: 写公开状态与隐私边界测试**

```python
def test_public_state_shows_both_public_resources_but_not_enemy_hand(client):
    state = create_battle_and_get_state(client, hero="mage")
    assert state["player"]["energy"] == 3
    assert state["enemy"]["energy"] == 3
    assert state["enemy"]["hero"]["key"] in {"warrior", "mage", "ranger"}
    assert "enemy_hand" not in state
    assert "enemy_draw_pile" not in state
```

再覆盖：电脑先手时 `POST /api/game` 返回可保存状态；刷新后双方英雄、能量、技能次数和 pending response 不丢失；旧 session 不返回 500。

- [ ] **Step 2: 运行接口与页面测试，确认当前不公开电脑英雄、能量和技能状态**

Run: `pytest tests/test_api.py tests/test_app.py tests/test_acceptance_scenarios.py -q`

Expected: 新增断言失败。

- [ ] **Step 3: 增量扩展公开 API 与页面**

`public_battle_state()` 为双方各输出 `hero`、`combatant` 与 `skill` 的公开字段；只为玩家输出完整 `hand`。战斗页在电脑区域增加英雄名、能量和技能本回合状态，复用现有视觉语言，不修改 1920×1080 舞台或卡牌素材。

- [ ] **Step 4: 适配创建和演示路由**

API 和 demo 创建对局均调用新的 `BattleState.create()`；当电脑先手时，创建流程必须完成其自动行动或返回明确进行中的电脑回合状态。所有玩家动作端点继续只允许玩家一侧调用，电脑动作只能由服务端 AI 驱动。

- [ ] **Step 5: 更新文档与验收清单**

删除“电脑固定 28 生命”“电脑不能主动打出闪避”“电脑无英雄技能”“电脑护盾回合开始清零”“玩家固定先手”等旧规则。新增双方英雄、随机先手、共享牌库、双向响应、私有信息边界和难度不作弊的验收项。

- [ ] **Step 6: 完成自动化、真实 HTTP 与人工验收**

Run: `pytest -q`

Expected: 全部通过。

真实 HTTP 至少验证：玩家先手一局、电脑先手一局、电脑使用英雄技能、玩家闪避、电脑闪避、双方护盾持续、难度切换后资源不变。人工分别游玩三局，检查双方公开资源都能看见、电脑手牌从不泄露、对局胜负不依赖隐藏作弊信息。

- [ ] **Step 7: 提交公开状态与验收改动**

```bash
git add game/public_state.py api_routes.py demo_routes.py templates/game.html static/game.js README.md docs/interaction-design.md docs/api-contract.md docs/claude-builder/acceptance.md tests/test_api.py tests/test_app.py tests/test_acceptance_scenarios.py
git commit -m "feat: expose and verify symmetric human AI rules"
```

## Completion Criteria

- 电脑与玩家都从同一英雄池获得英雄，并使用同一牌库、起手、手牌上限、能量、抽牌、弃牌和护盾规则。
- 每局首个行动方由 RNG 公平决定，测试可稳定指定先手。
- 双方均可使用普通牌、一次英雄技能、结束回合和闪避响应；电脑通过 AI 选择，玩家通过 UI 选择。
- AI 绝不读取玩家私有手牌或抽牌堆；困难模式只基于公开信息做一步前瞻。
- 双方的英雄、生命、护盾、能量和技能状态在 UI/API 中对称公开，双方手牌保持私有。
- 三档难度只影响决策质量，不影响任何比赛数值或权限。
- 自动化测试、真实 HTTP 流程和人工对局分别验证双方先手、双方英雄技能、双方闪避、状态持久化与隐私边界。
