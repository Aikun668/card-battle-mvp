# 人机完全对等 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让人类玩家与电脑在同一局中拥有相同的英雄池、牌库、起手、先后手机会、能量、护盾、普通牌、英雄技能、结束行动、响应权和信息边界；AI 只负责选择电脑合法动作。

**Architecture:** 把当前“玩家状态 + 特例电脑状态”收敛为两个 `ParticipantState`，每个参与者独立拥有英雄、战斗体、手牌区、抽牌区、弃牌区和技能次数。`BattleState` 仍是唯一规则所有者；`game/ai.py` 只接收电脑私有信息和双方公开信息构成的观察视图，返回候选动作而不直接结算。

**Tech Stack:** Python 3、Flask、pytest、原生 HTML/CSS/JavaScript、SQLite 会话持久化。

**Spec:** `docs/归档/历史实施计划/人机完全对等审计与实施计划.md`

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

- [x] **Step 1: 写双方英雄与旧 session 迁移失败测试**

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

- [x] **Step 2: 运行测试，确认当前状态只有玩家英雄和固定 28 生命电脑**

Run: `pytest tests/test_battle.py tests/test_session_state.py -q`

Expected: 新增测试因 `Side`、`ParticipantState` 或 `enemy_hero` 不存在而失败。

- [x] **Step 3: 在模型中定义双方参与者**

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

- [x] **Step 4: 独立随机电脑英雄，不做反选**

`create()` 使用同一个会话 RNG 从 `HEROES` 中选择电脑英雄；允许与玩家同英雄。选择函数只接收 RNG 和英雄目录，不接收玩家英雄 key，确保电脑不会根据玩家选择进行隐藏克制。

```python
def choose_enemy_hero(rng: random.Random) -> HeroDefinition:
    return rng.choice(list(HEROES.values()))
```

- [x] **Step 5: 为旧 session 提供兼容读取**

旧 payload 缺少 `participants` 时，根据旧的 `hero`、`player`、`enemy`、`hand` 和三套牌区构建双方参与者；敌方英雄使用固定且可复现的默认英雄 `warrior`，并把旧电脑的 `max_hp` 规范为战士的生命上限、把当前生命夹在 `0..32` 范围内。这样旧存档从下一次保存开始就进入新规则，不会留下“战士英雄却只有 28 点最大生命”的半迁移状态。新对局必须使用随机选择，不能沿用该默认值。

- [x] **Step 6: 运行状态与会话测试**

Run: `pytest tests/test_battle.py tests/test_session_state.py -q`

Expected: 新局存在两个英雄；旧 session 可读取；新 payload 往返不丢失双方英雄和技能状态。

- [x] **Step 7: 提交参与者模型改动**

```bash
git add game/models.py game/battle.py game/session_state.py tests/test_battle.py tests/test_session_state.py
git commit -m "refactor: model both combatants as equal participants"
```

**验收记录（Task 1）**

- 实际改动文件：`game/models.py`、`game/battle.py`、`tests/test_battle.py`、`tests/test_session_state.py`、`tests/test_ai.py`、`tests/test_api.py`、`tests/test_app.py`、`tests/test_acceptance_scenarios.py`。`game/session_state.py` 无需改动——序列化完全走 `to_dict()` / `from_dict()`，旧键迁就逻辑集中在 `game/battle.py`。
- 决策 1 的落地方式：`tests/test_acceptance_scenarios.py`、`tests/test_api.py`、`tests/test_app.py` 各加一个 `side_state(session, side)` 辅助函数读 `session["battle"]["participants"][side]`，旧扁平键断言全部迁走；`test_ai.py` 只固定了电脑生命上限，避免随机英雄让"半血恐惧"评分漂移。
- 门禁：`compileall` 通过、`ruff check .` 通过、`ruff format --check .` 23 文件通过、`pytest -q` **112 passed**。
- HTTP 流程（真实 `python app.py` + `urllib`，非 test client）：`POST /api/game` 201 且 `phase=PLAYER_TURN`；连续五次创建拿到电脑 `max_hp` 依次为 27/32/32/32/24（战士 32、游侠 27、法师 24），证明随机英雄贯通到接口；`POST /api/game/actions/card` 200 且斩击 24→18、能量 3→2；`POST /api/game/actions/end-turn` 200 且回到 `PLAYER_TURN`、`round_number=2`；`GET /demo/heroes`、`GET /demo/battle` 均 200 且保留"确认角色/生命值/护盾/战斗日志"。
- 平衡探针（Task 1 基线，120 局/格，困难 AI，`%TEMP%\balance_probe4.py`）：战士贪心 胜 1.7% / 负 0% / 平 98.3%、平均 9.9 回合；法师 胜 90.8% / 负 9.2%；游侠 胜 66.7% / 负 33.3%。电脑英雄抽取 1200 次为 warrior 414 / mage 397 / ranger 389，接近均匀。**结论：随机电脑英雄没有改变"战士拖平"的结论**，护盾问题仍按决策 8 留到 Task 2 复测。

### Task 2: 统一牌库、先手、回合资源和护盾生命周期

**Files:**
- Modify: `game/battle.py`
- Modify: `game/catalog.py`
- Test: `tests/test_battle.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: Task 1 的 `Side` 和 `ParticipantState`。
- Produces: `draw_cards_for(side, count)`、`start_turn(side, *, initial=False)`、`advance_turn()` 和可测试的 `starting_side` 创建参数。

- [x] **Step 1: 写双方相同牌库、随机先手与护盾持久测试**

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

- [x] **Step 2: 运行测试，确认电脑牌库缺闪避且其护盾会被单独清零**

Run: `pytest tests/test_battle.py tests/test_catalog.py -q`

Expected: 牌库相同与护盾持久测试失败。

- [x] **Step 3: 删除电脑专属牌库与资源特例**

删除 `ENEMY_DECK_KEYS` 和所有按“电脑 / 玩家”复制的抽牌代码，双方各用 `list(FIXED_DECK_KEYS)` 洗牌。删除 `resolve_enemy_turn()` 中的 `self.enemy.shield = 0`。用一个参与方参数化的抽牌函数统一手牌上限、弃牌回洗和日志。

- [x] **Step 4: 实现通用回合推进与公平先手**

`start_turn(side, initial=False)` 在非初始回合抽 1 张、恢复该方能量为 3、重置该方技能次数；`advance_turn()` 切换到对手。`BattleState.create()` 接受只供测试使用的 `starting_side: Side | None`；传 `None` 时由 RNG 均匀选择。

- [x] **Step 5: 运行资源与回合测试**

Run: `pytest tests/test_battle.py tests/test_catalog.py -q`

Expected: 双方牌库均含 13 张和 1 张闪避；护盾只受伤害影响；两种先手均可完成第一轮。

- [x] **Step 6: 提交资源规则改动**

```bash
git add game/battle.py game/catalog.py tests/test_battle.py tests/test_catalog.py
git commit -m "feat: unify player and enemy resource rules"
```

**验收记录（Task 2）**

- 实际改动文件：`game/battle.py`（主体）、`tests/test_battle.py`、`tests/test_ai.py`、`tests/test_api.py`、`tests/test_app.py`、`tests/test_acceptance_scenarios.py`。`game/catalog.py`、`tests/test_catalog.py` 无需改动——`FIXED_DECK_KEYS` 已是双方共用的唯一牌库，`ENEMY_DECK_KEYS` 此前已随 Task 1 删除。
- 实现要点：新增 `OPPONENT_SIDE` / `TURN_PHASE` / `SIDE_PHASE` 三个映射与 `current_side()`、`start_turn(side, *, initial=False)`、`advance_turn()`；`draw_cards_for(side, count)` 取代原来玩家/电脑两套抽牌代码；`create()` 先 `rng.choice(list(Side))` 定先手，电脑先手时在创建流程内同步跑完它的第一个回合；`resolve_enemy_turn()` 删掉了 `self.enemy.shield = 0`，护盾现在只有伤害能削。
- 回合计数按决策 2：先手方开新回合才 `round_number += 1`，因此 `ROUND_LIMIT = 10` 等于双方各行动 10 次。`test_round_limit_lets_each_side_act_ten_times` 对两种先手都验证了各 10 次后进入 `DRAW`。
- 门禁：`compileall` 通过、`ruff check .` 通过、`ruff format --check .` 23 文件通过、`pytest -q` **119 passed**，连续 10 次全绿（Task 1 结束时是 112 passed）。
- 真实的非 test-client HTTP 冒烟（`python app.py` + `urllib`，脚本 `%TEMP%\smoke_task2.py`）：连续 12 次 `POST /api/game` 全部 201 且 `phase=PLAYER_TURN`（从没出现过 `ENEMY_TURN` 或 `RESPONSE`），先手分布 7:5；电脑最大生命值指纹出现 24/27/32 三种，证明随机英雄贯通；`POST actions/card` 200（能量 3→1、手牌 5→4）；`POST actions/end-turn` 200（`round=2`、能量回到 3、技能重置为未使用）；`/demo` 含难度选项、`/demo/heroes` 含确认角色、`/demo/battle` 六个状态标记齐全、`/` 健康检查 200。
- 平衡探针（`%TEMP%\balance_probe5.py`，120 局/格，困难 AI，贪心玩家，先手随机）：战士 胜 0.8% / 负 0% / **平 99.2%**、平均 10.0 回合；法师 胜 49.2% / 负 50.8%、2.8 回合；游侠 胜 43.3% / 负 56.7%、3.6 回合。按先手拆战士：玩家先手 胜 1.7% / 平 98.3%，电脑先手 平 100.0%——**先手不再是决定因素，平局锁与先手无关**。难度表（简单/中等/困难）对战士读数完全相同，因为电脑三种难度都不使用英雄技能，而平局锁恰恰由技能造成。
- 归因探针（`%TEMP%\balance_probe6.py`，禁用玩家技能做对照）：战士禁技能后立刻变成 胜 60.0% / 负 39.2% / 平 0.8%、6.0 回合；"只叠盾不进攻"的龟缩变体在**有技能**时 100% 平局、0% 战败（即不可战胜），禁技能后变成 97.5% 战败。**结论：本轮的平局锁与龟缩不可战胜，成因是玩家独有的战士技能（2 能量换 8 护盾）强于电脑 3 能量能打出的任何输出（上限 16 = 重击 10 + 斩击 6），而 `game/ai.py` 至今没有技能逻辑（文件第 8 行注释即"电脑没有英雄技能"）。护盾跨回合只是放大了这个不对称，不是根因。**按决策 8 本轮不加护盾上限，等 Task 3 让电脑拥有技能后复测。
- 偏差 1（需要你确认）：决策 3 要求创建接口只返回玩家回合或终局，但电脑先手时它的开局攻击可能触发 `RESPONSE`。我的处理是在 `create()` 里用 `while state.phase is RESPONSE: state.respond("pass")` 自动按"放弃"结算——理由是这次攻击发生在玩家看到棋盘之前，玩家不可能对还没渲染的攻击做出响应。副作用：电脑先手时玩家可能开局先掉一次血（最大 16），且这一局玩家没有闪避机会。
- 偏差 2（文档笔误）：本计划决策 3 的注释写"电脑第一回合最多造成 18 点伤害"，实际上限是 16（重击 10 + 斩击 6，3 能量打不出第二张重击）。"首回合不可能击杀"的结论不变（战士血量 32）。
- 顺带修掉的测试脆弱点：`tests/test_ai.py` 里 8 个电脑回合测试原本在 `end_player_turn()` 之前赋值 `enemy_hand`，而电脑现在在**自己回合开始**抽牌，会把固定手牌冲掉，改为在 `end_player_turn()` 之后赋值；`tests/test_api.py` / `test_app.py` 因为路由用的是非种子 RNG，改为读 session 基线算增量，并用 `freeze_enemy_hand` 清空电脑两个牌区来锁死它的手牌。

### Task 3: 将卡牌、技能与结束行动改成双方共享的合法动作

**Files:**
- Modify: `game/battle.py`
- Modify: `game/ai.py`
- Test: `tests/test_battle.py`
- Test: `tests/test_ai.py`

**Interfaces:**
- Consumes: Task 1 的参与者状态和 Task 2 的通用回合函数。
- Produces: `play_card_for(side, card_id)`、`use_skill_for(side)`、`end_turn_for(side)`、包含 `card` / `skill` / `pass` 的 `ActionCandidate`。

- [x] **Step 1: 写电脑技能与真实结束行动失败测试**

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

- [x] **Step 2: 运行测试，确认当前 AI 候选只有 `card` 和 `pass` 且电脑没有技能状态**

Run: `pytest tests/test_ai.py tests/test_battle.py -q`

Expected: 电脑技能测试失败，候选类型缺少 `skill`。

- [x] **Step 3: 实现参数化卡牌与技能结算**

```python
def play_card_for(self, side: Side, card_id: str) -> ActionResult: ...
def use_skill_for(self, side: Side) -> ActionResult: ...
```

两个函数必须从 `participant(side)` 取手牌、能量、英雄和弃牌区，从 `opponent_of(side)` 取攻击目标。游侠抽牌使用 `draw_cards_for(side, 1)`。现有 `play_card()` 和 `use_skill()` 只作为玩家 API 兼容包装器调用对应通用函数。

- [x] **Step 4: 扩展 AI 候选与评分**

`get_available_enemy_actions()` 枚举电脑费用足够的普通牌、未使用且费用足够的英雄技能、以及始终可选的 `pass`。为技能增加与对应卡牌效果一致的评分入口；`pass` 不得在简单/中等模式被预先过滤，而应通过“保留能量用于闪避、当前无有效收益”等评分参与排序。

- [x] **Step 5: 运行双方动作测试**

Run: `pytest tests/test_ai.py tests/test_battle.py -q`

Expected: 双方均可在自己的回合使用普通牌、一次技能和结束行动；电脑候选不再缺技能或被强制出所有牌。

- [x] **Step 6: 提交共享动作改动**

```bash
git add game/ai.py game/battle.py tests/test_ai.py tests/test_battle.py
git commit -m "feat: give both sides equal cards skills and pass actions"
```

**验收记录（Task 3）**

- 实际改动文件：`game/battle.py`、`game/ai.py`、`game/catalog.py`（新增 `SKILL_COST = 2`）、`tests/test_battle.py`、`tests/test_ai.py`、`tests/test_acceptance_scenarios.py`、`tests/test_api.py`、`tests/test_app.py`、`api_routes.py`、`demo_routes.py`。提交时把计划里的 `git add` 扩到这四个文件（`game/catalog.py` 装 `SKILL_COST`、验收场景与两个路由测试跟着改动、两个路由文件装下面那个顺带修的 bug）。
- 实现要点：`play_card_for(side, card_id)` / `use_skill_for(side)` / `end_turn_for(side)` 成为唯一结算入口，玩家侧的 `play_card()` / `use_skill()` / `end_player_turn()` 退化成薄包装；手牌、能量、英雄、弃牌区一律从 `participant(side)` 取，攻击目标从 `opponent_of(side)` 取，游侠抽牌走 `draw_cards_for(side, 1)`。日志措辞靠 `ACTOR_LABEL` / `HIT_LABEL` 两个映射复刻旧文案：玩家出手不写主语、受击写"你"，电脑出手写"电脑"，所以既有日志断言一条没改。
- AI 侧：`ActionCandidate.kind` 扩成 `card | skill | pass`，技能用 `_skill_as_card()` 折成一张等效卡牌参与同一套评分（护盾类算护盾牌，其余算伤害牌），因此 `_base_score()` / `_survivable_hp_after()` / `hard_lookahead_adjustment()` 都无需分支。`score_pass()` 保留"手里有闪避且能量刚好只剩 1 点"时的 `DODGE_HOLD_BONUS = 3.0`，简单难度不享受该加分。随机抽取仍用 `score > PASS_SCORE` 过滤：普通空过（0.5）进不了池子，战略空过（3.5）靠评分自然进池。
- 门禁：`compileall` 通过、`ruff check .` 通过、`ruff format --check .`（先对 `game/battle.py`、`tests/test_ai.py`、`tests/test_acceptance_scenarios.py` 跑了 `ruff format`）通过、`pytest -q` **134 passed**（Task 2 结束时 119）。
- 稳定性：路由测试用的是非种子 RNG，跑单次通过不代表稳定。连跑 20 次全量后抓到两个抖动用例——`test_api_pauses_enemy_attack_and_accepts_dodge_response` 与 `test_api_can_pass_enemy_attack_response`：它们把电脑手牌锁成一张重击，而电脑现在有技能，中等难度按 0.88/0.12 从「前二名」里抽，抽到技能（法师技能与重击同分同费）就不发起攻击、永远不会进入 `RESPONSE`，约 12% 的失败率。修法是把手牌锁成两张重击并把电脑钉成满血战士（技能 8.0 分低于两张重击的 12.5/9.1），随机池里只剩伤害牌；随后 30 次全量连跑 0 抖动（`tests/test_api.py` 单文件连跑 15 次也全绿）。
- 真实的非 test-client HTTP 冒烟（`python -c "create_app().run(...)"` + `urllib`，脚本 `%TEMP%\smoke_task3.py`）：40 局 / 125 个玩家回合，创建接口返回的 phase 恒为 `PLAYER_TURN`（含电脑先手局），电脑最大生命值指纹出现 24/27/32 三种。按"电脑开始行动"切分日志逐段审计，**敌方每个回合花费不超过 3 点能量、技能最多一次，0 违规**；三种英雄技能都在真实日志里出现过（`电脑释放技能【火球术】，对你造成 10 点伤害`、`【守护】…获得 8 点护盾`、`【连射】…造成 6 点伤害，并抽取 1 张牌`），40 局里 29 局电脑用过技能。玩家技能：`POST /api/game/actions/skill` 200（能量 3→1、护盾 0→8，日志 `释放技能【守护】，获得 8 点护盾`），同回合再点 422 `本回合技能已经使用过`；缺 `card_id` 的打牌请求仍是 400 `INVALID_REQUEST`。页面冒烟：`/demo` 含难度选项、`/demo/heroes` 含确认角色、`/demo/battle` 六个状态标记齐全、`/` 健康检查 200。
- 平衡探针（`%TEMP%\balance_probe7.py`，120 局/格，玩家策略与 Task 2 的 probe5 一致，先手随机）——**Task 2 的平局锁被打破**：战士从 胜 0.8% / 负 0% / **平 99.2%** / 10.0 回合 变成 胜 0.8% / 负 28.3~30.8% / 平 68.3~70.8% / 9.2~9.3 回合；法师 胜 49.2%→44.2~48.3%、游侠 胜 43.3%→22.5~24.2%（胜率下降是因为电脑现在也会用技能了）。龟缩变体（只叠盾+技能不进攻）不再不可战胜：战士 100% 平局 / 0% 战败 → 平 65% / **负 35%**，游侠龟缩 负 95%，法师龟缩 负 73%。**决策 8 的"护盾跨回合是已知风险"因此降级：风险真实存在，但不再由单边技能不对称放大。**
- 按决策 5 记录「难度 × 电脑英雄」探针（玩家=游侠，120 局/格，胜/负/平）：电脑=法师 35.0~40.0% / 60.0~65.0% / 0%，电脑=游侠 28.6~37.1% / 62.9~71.4% / 0%，电脑=**战士 0.0~4.4% / 80.0~93.3% / 0.0~20.0%**。也就是说"对面是战士"本身就是一档难度（它的 2 费 8 护盾技能太厚），这符合决策 5 的"只记录探针、不要求胜率拉平"，但**下一轮平衡该动的是护盾效率，不是 AI 评分**。
- 难度轴现状：简单/中等/困难三档在多数格子里差异很小（战士格 28.3% / 28.3% / 30.8% 战败），因为三档的区别只在抽池宽度（3/2/1 名），而困难的一步前瞻惩罚很少被触发。Task 2 记录的"三档读数完全相同"确实被修好了，但分离度仍弱，留给后续难度任务。
- 先手拆解（玩家=战士，困难 AI）：玩家先手 负 18.3% / 平 80.0%，玩家后手 负 38.3% / 平 61.7%。Task 2 的"平局锁与先手无关"结论依旧成立（锁没了），但电脑拿到技能后**先手重新有了可见优势**，属于正常现象，记录在案。
- 顺带修掉的产品 bug（冒烟抓到的）：打满 10 回合上限时，玩家结束回合会让 `end_player_turn()` 返回成功并把 phase 置成 `DRAW`，但路由紧接着无脑调用 `resolve_enemy_turn()`，后者因"本局已经结束"返回失败——于是 API 返回 **422 `ACTION_REJECTED`（消息"本局已经结束，请重新开始"）**，demo 路由则把这句话 flash 到平局结果页上。修法是两个 end-turn 路由都只在 `battle.phase is BattlePhase.ENEMY_TURN` 时才跑电脑回合，并删掉那个不可能成立的错误分支（玩家动作明明成功了）。回归测试 `test_api_end_turn_on_the_last_round_returns_a_draw_instead_of_an_error`、`test_end_turn_on_the_last_round_shows_the_draw_result_without_a_flash`，已按 RED→GREEN 验证：把旧错误分支放回去，两个测试都失败。
- 测试脆弱点：`tests/test_battle.py` / `tests/test_ai.py` 里所有电脑回合测试都要在 `end_player_turn()` **之后**调用 `withhold_enemy_skill()`，因为 `start_turn()` 每个回合开始都会重置技能标记；`test_acceptance_scenarios.py` 的 scenario 3 改成接受 `电脑使用` 或 `电脑释放技能` 两种开局，scenario 7 把电脑钉成满血战士（原因同上面那个 12% 抖动）。

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

- [x] **Step 1: 写双方均可闪避的失败测试**

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

- [x] **Step 2: 运行响应测试，确认当前只会为玩家创建 `RESPONSE`**

Run: `pytest tests/test_battle.py tests/test_ai.py -q`

Expected: 电脑闪避测试失败，玩家攻击立即结算。

- [x] **Step 3: 以攻击方 / 防御方建立待响应事件**

攻击牌从攻击方手牌移到弃牌区、扣除能量后，创建 `PendingAttack`。若防御方有闪避和足够能量：防御方为玩家时进入现有 UI 等待；防御方为电脑时调用 AI 响应选择。若没有可用闪避，立即按护盾优先规则结算。

- [x] **Step 4: 让 AI 对“闪避 / 放弃”评分**

电脑响应候选只包含 `dodge` 和 `pass`。闪避分数基于本次可抵消的实际生命伤害与剩余能量价值；简单难度允许偶尔放弃，中等/困难在高实际伤害时优先闪避。不得为电脑自动免费闪避。

- [x] **Step 5: 运行响应回归测试**

Run: `pytest tests/test_ai.py tests/test_battle.py -q`

Expected: 两边拥有相同的闪避资格、费用和弃牌去向；没有嵌套响应或重复扣费。

- [x] **Step 6: 提交通用响应改动**

```bash
git add game/models.py game/battle.py game/ai.py tests/test_ai.py tests/test_battle.py
git commit -m "feat: make dodge responses symmetric"
```

**验收记录（Task 4）**

- 实现要点：新增不可变 `PendingAttack(attacker, defender, card_key, card_name, damage)` 取代原来的裸 dict；`play_card_for()` 的伤害牌分支改走 `_open_response()`——攻击方先扣能量、弃牌，再由防御方决定这次伤害落不落地，**付过的费用不退还**。防御方有闪避且能量够时：是玩家就停在 `RESPONSE` 等 UI，是电脑就当场调 `choose_enemy_response()`；没有可用闪避就立刻 `_resolve_damage()` 按护盾优先结算，根本不产生响应窗口。`_finish_response()` 把回合交还攻击方，攻击方是电脑时接着 `_run_enemy_actions()` 跑完它剩下的行动，旧的 `_resume_enemy_turn()` / `_play_enemy_card()` 随之删除。
- AI 侧：`score_dodge()` 只给真正会掉的生命计分（先扣护盾吸收、再按剩余生命封顶，与 `apply_damage()` 的护盾优先语义一致）；响应候选只有 `dodge` / `pass`，复用同一张 `DIFFICULTY_SELECTION` 权重表，没有单独的闪避阈值表（决策 6）。`_select()` 拆出 `_weighted_pick()`：出牌仍过滤"不优于空过"的候选，响应不过滤——放弃响应只是挨这一下、闪避牌还留在手里，本身就是合法选择；这也是"简单难度允许偶尔放弃"的落点。**没有给电脑任何免费闪避**：它同样扣 1 点能量、同样把闪避牌送进弃牌区，冒烟逐次核对。
- 门槛：`python -m compileall app.py api_routes.py demo_routes.py web_support.py game`、`ruff check .`、`ruff format --check .` 全绿；`pytest -v` **150 passed**（Task 3 末是 134），全量连跑 10 轮 0 失败。新增 16 个测试：`tests/test_battle.py` 6 个（电脑留能量闪避、无能量不能闪避、一次攻击只开一个窗口、电脑闪避后玩家继续自己的回合、代另一侧响应被拒、随机对局不变量），`tests/test_ai.py` 8 个（闪避只算真会掉的血、护盾全吸时闪避 0 分且排在放弃之后、**任何难度都不花零收益的闪避**、**只剩 1 点能量时放弃小伤害**、困难必闪、简单会偶尔放弃、响应候选只有两个、评分不改状态），`tests/test_session_state.py` 2 个（对称 `PendingAttack` 往返、旧格式缺 attacker/defender 时补成"电脑打玩家"）。`test_random_play_stays_consistent_through_both_sides_responses` 用固定种子跑 60 局随机动作，每步断言"`RESPONSE` ⟺ 有挂起攻击"、能量不为负、**双方手牌 + 抽牌堆 + 弃牌区恒等于整副 13 张**（攻击挂起时那张已在弃牌区，所以任何时刻都成立）——它是这次唯一的递归/重入防线，比逐条固定路径更能守住不变量。
- 真实的非 test-client HTTP 冒烟（`%TEMP%\smoke_task4.py`，60 + 50 局）：玩家攻击 104~120 次里电脑闪避 7~16 次（9%~15%，同一脚本多次跑的噪声），**每次闪避都恰好扣 1 点能量、电脑生命不变、攻击方费用照扣，0 违规**；响应窗口 23~30 个，**全部只在防御方有闪避与能量时才打开**；玩家侧的闪避与放弃都覆盖到。按"电脑开始行动"切段审计：每张卡牌攻击都恰好结算一次（要么写"造成伤害"，要么紧跟一条闪避记录），且**日志里的伤害总量与该回合玩家护盾 + 生命的实际减少量逐局相等**。页面冒烟：`/demo` 含难度选项、`/demo/heroes` 含确认角色、`/demo/battle` 六个标记齐全、`/` 健康检查 200。审查整改后重启服务（只有一个实例、`use_reloader=False`）重跑：107 次攻击 / 电脑闪避 16 次 / 两段违规均为 0。
- 平衡探针（`%TEMP%\balance_probe7.py`，120 局/格，与 Task 3 同一个脚本、同一套贪心玩家策略，只换了代码）——**电脑拿到闪避后玩家胜率小幅下降，没有结构性变化**：战士 胜 0.8% / 负 28.3~30.8% / 平 68.3~70.8% / 9.2 回合 → 胜 0~0.8% / 负 30.8~33.3% / 平 66.7~68.3% / 9.1~9.2 回合；法师 胜 44.2~48.3% → 38.3~43.3%；游侠 胜 22.5~24.2% → 17.5~18.3%。龟缩变体（只叠盾 + 技能、不进攻，因此吃不到闪避收益）几乎原样：战士 负 35%、游侠 负 95%、法师 负 73%。难度轴仍拉不开（战士三档负 30.8 / 33.3 / 31.7），先手仍占优（玩家先手 负 23.3% / 平 75.0%，玩家后手 负 40.0% / 平 60.0%）。**审查后修完"零收益闪避"又复跑一次同一脚本**：战士 负 30.8 / 32.5 / 31.7、平 67.5~68.3、9.1~9.2 回合；法师 胜 38.3~43.3；游侠 胜 17.5~18.3；龟缩 战士 负 35.0 / 法师 负 73.3 / 游侠 负 95.0；先手 负 23.3 平 75.0 / 后手 负 40.0 平 60.0——**逐格都在噪声范围内，没有可观测变化**（该修复只影响"电脑带着护盾进玩家回合、又正好有闪避与能量、且这次伤害被护盾全吃掉"这一窄情形）。
- 探针发现（留给 Task 5/6 的背景，本轮不改评分常数，见决策 6/7）：电脑的闪避资格在实战里**很少成立**——玩家回合开始时它 0 能量的样本占多数（in-process 405/520，HTTP 口径 87/169），因为它在自己回合把 3 点能量花光，而 `score_pass()` 的 `DODGE_HOLD_BONUS = 3.0` 挡得住低收益动作（护盾经 `SHIELD_SCALE` 衰减后仍值 6.0，照样打出去）、挡不住斩击（9.0）。所以"留能量反制"目前基本只是玩家的策略空间，不是电脑的。这是平衡问题不是规则问题。
- 范围说明（既有设计，本次不动）：**英雄技能的伤害不经过响应窗口**，两边一致——技能不是卡牌，没有"被闪掉的牌"这个语义，`use_skill_for()` 是 Task 3 建立的双向接口，本轮不扩它的签名。
- 审查整改（`python-reviewer`，独立复跑 148 passed / ruff 全绿，另确认了三件事：`_run_enemy_actions()` 遇响应提前收工、没有重复结算或重复扣费；`HAND_LIMIT + 1` 的循环上界不会被"挂起—续跑"链破坏；旧存档缺 attacker/defender 时默认补成"电脑打玩家"）：
  - **[已修 · 高] 电脑会为"救不回任何生命"的闪避白扔资源。** 伤害被护盾全吃掉时 `score_dodge()` 是 0.0、`score_pass()` 是 0.5，但 `choose_enemy_response()` 当时把候选整个交给 `_weighted_pick()` 按难度权重抽——实测 200 次里轻松难度抽中 54 次（27%）、中等 27 次（13.5%）白白扣 1 点能量、扔掉一张闪避，困难因为直接取 `ranked[0]` 反而是对的（所以此前的用例没照出它）。修法与出牌侧"不浪费整个回合"同一原则：响应候选里滤掉 `score <= 0` 的闪避，**放弃始终不参与过滤**（决策 4：放弃本身是合法选择）。修复后三档难度 200 次全部放弃，新增 `test_no_difficulty_spends_a_dodge_that_saves_no_health` 钉住。注意措辞：严格说不是"纯亏"——闪避还能保住那层护盾，但评分口径按计划就是用"本次真会掉的生命"算，所以让它别花。
  - **[不改 · 中] 响应窗口里的"留 1 点能量"加分。** 审查认为 `_holds_the_last_dodge_energy()` 的 3.0 分是为出牌侧设计的、用在响应里是语义错位。**保留**：这个加分在响应语境下同样成立——能量只在电脑自己回合开始回满，此刻花掉最后 1 点，玩家本回合若再打一张伤害牌它就再也闪不动了，正是计划里"中等难度可策略性放弃（手里有闪避、留 1 点能量）"描述的那笔账。新增 `test_hard_gives_up_a_small_hit_to_keep_its_last_energy_for_a_bigger_one` 把这个取舍写成显式契约，避免以后被当成 bug 顺手"修"掉。
  - **[不改 · 低] 开局那一手仍不对称。** 第一回合电脑抢到时玩家会被自动放弃响应（`create()` 里那处，见下），所以玩家闪不了开局伤害，电脑却闪得了玩家的开局攻击。这是有意的（玩家还没看到场面，不该被要求做决定），记录在此备查。
- 测试脆弱点：电脑现在会闪避玩家的攻击，凡是"玩家打伤害牌 + 断言伤害当场落地"的用例都必须显式让电脑无法响应——`tests/test_battle.py` 三处改成 `battle.enemy_hand = []`，`tests/test_api.py` / `tests/test_app.py` / `tests/test_acceptance_scenarios.py` 各加一个 `drop_enemy_dodge()` 辅助函数摘掉电脑手里的闪避。这些用例原本就依赖"路由用非种子 RNG"的隐式确定性，不显式控制会像 Task 3 那 12% 抖动一样偶发失败；已按全量 `pytest` 连跑 15 轮、路由用例连跑 40 轮复验，0 失败。
- 环境问题（不是代码问题）：Task 3 留下的旧 Flask 进程一直占着 5000 端口，第一次冒烟打到了旧进程（Task 4 之前的代码）上，读数全是"电脑闪避 0 次"。杀掉旧进程、只留一个 reloader 关闭的实例后读数正常（9% 左右）。**后续冒烟前先确认端口上只有一个本项目的服务。**
- 冒烟暴露的既有缺陷（**不是本轮引入，留给 Task 6**）：服务端渲染的老页面 `/demo/battle` 从头到尾没有响应入口——`demo_routes.py` 没有 respond 路由，`templates/battle.html` 里没有闪避/放弃表单，但电脑攻击时 `battle.py` 照样把阶段置成 `RESPONSE`。实测 60 局里 23 局（38%）卡死：页面照常显示"结束回合"，点下去只 flash 一句拒绝，`/demo/restart` 是唯一出路。用 `git worktree` 检出 HEAD（Task 4 之前）重跑同样 60 局，28 局卡死——**HEAD 上早就存在，Task 4 没有让它变差**。修法二选一：给老页面补 respond 路由 + 表单，或在 Task 6 直接用 API 驱动的 `game.html` + `static/game.js` 取代它（后者已经有完整的闪避/放弃按钮，接 `/api/game/actions/respond`）。Task 4 的页面冒烟只查了标记字符串，没走响应路径，所以没提前发现——Task 6 的前端契约测试要按"能打完一整局"来写。

### Task 5: 建立 AI 信息边界，移除对玩家私有手牌的读取

**Files:**
- Modify: `game/ai.py`
- Modify: `game/battle.py`
- Test: `tests/test_ai.py`
- Test: `tests/test_battle.py`

**Interfaces:**
- Consumes: 双方参与者状态和公开行动日志。
- Produces: `AIObservation`、`BattleState.enemy_observation()` 和只接受 `AIObservation` 的 `rank_enemy_actions()` / `select_enemy_action()`。

- [x] **Step 1: 写 AI 不读取玩家私有手牌的失败测试**

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

- [x] **Step 2: 运行测试，确认当前困难模式遍历 `state.hand`**

Run: `pytest tests/test_ai.py -q`

Expected: 隐藏手牌改变时，当前 `estimate_player_threat()` 的排序发生变化。

- [x] **Step 3: 定义受限观察视图**

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

- [x] **Step 4: 用公开威胁估计替代窥视手牌**

困难模式的一步前瞻只根据公开英雄技能、玩家当前公开能量、固定牌表和公开弃牌记录估算“潜在最大威胁”；不能读取玩家当前拥有哪一张。所有 AI 评分与选择函数改为只接收 `AIObservation`。

- [x] **Step 5: 运行信息边界测试**

Run: `pytest tests/test_ai.py tests/test_battle.py -q`

Expected: 私有玩家手牌变化不影响 AI 排名；公开生命、能量或已打出牌变化会影响 AI 排名。

- [x] **Step 6: 提交信息边界改动**

```bash
git add game/ai.py game/battle.py tests/test_ai.py tests/test_battle.py
git commit -m "fix: prevent AI from reading hidden player cards"
```

**验收记录（Task 5）**

- 实现要点：`game/ai.py` 里新增两个 frozen dataclass——`PublicParticipantState`（英雄 key、生命上限、生命、护盾、能量、技能是否已用）和 `AIObservation`（双方公开状态 + 自己的手牌 + 公开弃牌记录 + 公开牌表 + 待响应攻击）。`BattleState.enemy_observation()` 是唯一的生产者，`_run_enemy_actions()` 与 `_resolve_enemy_response()` 每次决策都重新构造一份，AI 的每一个评分与选择函数（含 `score_damage/heal/shield/pass/dodge`、`estimate_player_threat`、`rank_enemy_actions/responses`、`select_enemy_action`、`choose_enemy_response`）现在只收 `AIObservation`，签名里再没有 `BattleState`。旧存档/旧调用方没有兼容垫片：边界是硬切。
- 字段取舍（对计划 Step 3 那行字段表的补充，写在这里备查）：加 `max_hp`——取自 `Combatant` 而不是 `HEROES[hero_key]`，免得换了英雄对象后两者打架（`battle_with_enemy_hero()` 这类用例就会）；加 `pending_attack`——打出的攻击牌是明牌，闪避评分要用它，而计划要求响应函数也只收观察视图；`catalog_keys` 来自新增的 `catalog.CATALOG_KEYS`（`tuple(CARDS)`），威胁估算遍历它而不是直接遍历 `CARDS`，这样"AI 用的每一份信息都来自观察视图"是可读出来的；`public_discard_keys` 放玩家弃牌区。
- 威胁估算（决策 7）：`estimate_player_threat()` 改为对公开牌表取最坏值——买得起的最强伤害牌（`STARTING_ENERGY = 3` 是玩家下回合的公开能量）+ 玩家英雄的伤害技能。**刻意不用公开弃牌记录收窄**：抽牌堆抽空时弃牌会洗回，"这张已经打掉了"排除不了它下回合回到玩家手上，拿它缩小上界会低估威胁。玩家的技能次数在下回合会重置，所以按"可用"计。
- 门槛：`compileall`、`ruff check .`、`ruff format --check .` 全绿；`pytest -q` **160 passed**（Task 4 末是 150），全量连跑 8 轮 0 失败。新增 10 个测试：`tests/test_ai.py` 8 个（只改玩家隐藏手牌时观察视图与困难排名都不变、玩家公开护盾会改变伤害评分而隐藏手牌不会、观察视图带回自己手牌与公开记录、观察视图是快照不是活视图、**两个 dataclass 的字段集合被逐字钉死**（有人往里加 `opponent_hand` 会立刻红）、威胁估算忽略隐藏手牌、威胁上界不低于公开牌表最大值），`tests/test_battle.py` 2 个（`enemy_observation()` 以电脑为 self、玩家为 opponent，且 `opponent_state` 上根本没有 hand/draw_pile 属性；待响应攻击会被带进观察视图）。字段集合那条测试是这次唯一防"边界被悄悄放宽"的机关，其余用例只能证明当前实现没读隐藏数据。
- 真实 HTTP 冒烟（`smoke_task4.py`，单个本地实例、`use_reloader=False`）重跑：玩家攻击 103 次 / 电脑闪避 13 次 / 两段违规均 0，页面冒烟 6 个标记齐全。AI 换数据来源不影响协议层。
- 平衡探针（`balance_probe7.py`）逐格与 Task 4 **完全一致**（战士 负 30.8 / 32.5 / 31.7，法师 胜 38.3~43.3，游侠 胜 17.5~18.3，龟缩与先手拆解同样不动）。这个"什么都没变"起初很反直觉，于是单独量了一次（`%TEMP%\probe_task5_threat.py`，1659 个电脑决策点）：新旧估算 **100% 的决策点都不同**，危险判定（生命 + 护盾 ≤ 威胁）的命中率从 **3.6% 涨到 35.0%**（最常见的迁移是 `0 -> 14`，1357 次）。再把 `DANGER_PENALTY` 整个置 0 跑同一套探针（`%TEMP%\probe_no_danger.py`）：15 格里有 14 格纹丝不动，只有 `ranger hard` 从 负 80.8% 变 负 80.0%（玩家胜率 17.5% → 18.3%）。**结论：公开口径让困难模式频繁进入警戒状态，但这些新增的警戒局里防御动作本来就已经领先，所以既不更强也不更弱；真正起作用的仍是原先那 3.6% 的关键局。**决策 7 说的"接受困难变弱"实测没有代价。
- 已知无害冗余：威胁上界里的英雄技能项当前永远被牌表里的火球（14）压住（法师火球术 10、游侠连射 6），所以它暂时不影响任何结果。留着是因为它是决策 7 明确写进模型的公开信息，牌表一改就会生效；`test_threat_estimate_never_drops_below_the_public_table_maximum` 把现状写成了断言，牌表变动时会提醒。
- 测试改动：`tests/test_ai.py` 里 53 处调用点从 `f(battle, ...)` 改成 `f(battle.enemy_observation(), ...)`——这正是本任务的目的，边界变成调用方必须显式穿过的东西，而不是函数内部偷偷去摸 `state.hand`。

### Task 6: 公开双方状态、适配路由与完成验收

**Files:**
- Modify: `game/public_state.py`
- Modify: `api_routes.py`
- Modify: `demo_routes.py`
- Modify: `templates/game.html`
- Modify: `static/game.js`
- Modify: `docs/产品方案/基础规则/interaction-design.md`
- Modify: `docs/接口契约/本地对局/api-contract.md`
- Modify: `docs/验收/MVP/MVP验收与质量门槛.md`
- Modify: `README.md`
- Test: `tests/test_api.py`
- Test: `tests/test_app.py`
- Test: `tests/test_acceptance_scenarios.py`
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Consumes: Tasks 1–5 的双参与者状态、通用响应和 `AIObservation`。
- Produces: 不泄露电脑手牌的公开 API；页面上双方对称的英雄/资源/技能信息；唯一的对等规则文档。

- [x] **Step 1: 写公开状态与隐私边界测试**

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

- [x] **Step 2: 运行接口与页面测试，确认当前不公开电脑英雄、能量和技能状态**

Run: `pytest tests/test_api.py tests/test_app.py tests/test_acceptance_scenarios.py -q`

Expected: 新增断言失败。

- [x] **Step 3: 增量扩展公开 API 与页面**

`public_battle_state()` 为双方各输出 `hero`、`combatant` 与 `skill` 的公开字段；只为玩家输出完整 `hand`。战斗页在电脑区域增加英雄名、能量和技能本回合状态，复用现有视觉语言，不修改 1920×1080 舞台或卡牌素材。

- [x] **Step 4: 适配创建和演示路由**

API 和 demo 创建对局均调用新的 `BattleState.create()`；当电脑先手时，创建流程必须完成其自动行动或返回明确进行中的电脑回合状态。所有玩家动作端点继续只允许玩家一侧调用，电脑动作只能由服务端 AI 驱动。

- [x] **Step 5: 更新文档与验收清单**

删除“电脑固定 28 生命”“电脑不能主动打出闪避”“电脑无英雄技能”“电脑护盾回合开始清零”“玩家固定先手”等旧规则。新增双方英雄、随机先手、共享牌库、双向响应、私有信息边界和难度不作弊的验收项。

- [x] **Step 6: 完成自动化、真实 HTTP 与人工验收**

Run: `pytest -q`

Expected: 全部通过。

真实 HTTP 至少验证：玩家先手一局、电脑先手一局、电脑使用英雄技能、玩家闪避、电脑闪避、双方护盾持续、难度切换后资源不变。人工分别游玩三局，检查双方公开资源都能看见、电脑手牌从不泄露、对局胜负不依赖隐藏作弊信息。

- [x] **Step 7: 提交公开状态与验收改动**

```bash
git add game/public_state.py api_routes.py demo_routes.py templates/game.html static/game.js README.md docs/产品方案/基础规则/interaction-design.md docs/接口契约/本地对局/api-contract.md docs/验收/MVP/MVP验收与质量门槛.md tests/test_api.py tests/test_app.py tests/test_acceptance_scenarios.py
git commit -m "feat: expose and verify symmetric human AI rules"
```

**验收记录（Task 6）**

- 实际改动文件：`game/public_state.py`、`game/battle.py`（只加一行只读别名）、`api_routes.py`、`demo_routes.py`、`templates/game.html`、`templates/battle.html`、`static/game.js`、`static/game.css`、`static/style.css`、`tests/test_api.py`、`tests/test_app.py`、`tests/test_frontend_contract.py`，以及四份文档（`README.md`、`docs/产品方案/基础规则/interaction-design.md`、`docs/接口契约/本地对局/api-contract.md`、`docs/验收/MVP/MVP验收与质量门槛.md`）。计划里的 `tests/test_acceptance_scenarios.py` 最终无需改动——Task 1 已经把它的旧键断言迁到 `participants` 分区，本轮公开状态改动没有波及它。
- 公开状态的字段形状（对计划 Step 3 的落地解释，备查）：`public_battle_state()` 不再有顶层 `hero` / `skill` / `hand`，改为 `player` / `enemy` 两块，每块 = 原有扁平战斗体字段 + 嵌套 `hero` + 嵌套 `skill`（含 `cost` 与 `used_this_turn`），再单独给 `player` 挂 `hand`。新增顶层 `starting_side`。这样 Step 1 那段断言（`state["player"]["energy"]`、`state["enemy"]["hero"]["key"]`）与 Step 3 的"每方自己带 hero / combatant / skill"同时成立，扁平战斗体字段就是计划措辞里的 combatant。**顶层 `hand` 是真删，没有留兼容别名**——对称嵌套是唯一事实来源。
- `/demo/battle` 死锁的修法（Task 4 冒烟留下的既有缺陷）：补 `demo.battle_respond` 路由 + 模板里的响应表单（使用闪避 / 放弃响应），而不是用 API 驱动的 `game.html` 顶掉老页面。老页面因此第一次能自己打完一整局，`test_a_whole_game_can_be_played_through_the_demo_page` 就是钉这个的——它最多走 150 步卡牌 / 结束回合 / 响应直到终局，任何一步卡死都会红。
- 偏差（对计划 Step 1 的位置安排）："能打完一整局"这条测试放在 `tests/test_app.py` 而不是 `tests/test_frontend_contract.py`。契约文件保持纯静态断言（模板 id、脚本里出现的取值路径、`enemy_hand` / `enemy.hand` / `enemy.draw_pile` / `enemy_draw_pile` 全部不出现），因为它不导 Flask、本来就是靠读文件做契约；真跑一局属于路由行为，和 `test_app.py` 的其他用例同源。
- 门禁：`compileall` 通过、`ruff check .` 通过、`ruff format --check .` 23 文件通过、`node --check static/game.js` 通过、`pytest -q` **170 passed**（Task 5 末是 160），全量连跑 **14 轮 0 失败**（路由用例用非种子 RNG，这个数字是有意跑出来的）。本轮新增 10 个测试：`tests/test_api.py` 5 个、`tests/test_app.py` 3 个、`tests/test_frontend_contract.py` 2 个。
- 真实的非 test-client HTTP 冒烟（`%TEMP%\smoke_task6.py`，单个本地实例、`use_reloader=False`、跑完即杀进程，**违规总计 0**）：
  - 60 次创建：先手分布 34:26 / 35:25 / 33:27（三次都是对半），`phase` 恒在 `PLAYER_TURN` 或终局，从没出现 `ENEMY_TURN` / `RESPONSE`；每次创建后扫描 JSON 全文，`enemy_hand` / `enemy_draw_pile` / `enemy_discard_pile` / `draw_pile` / `discard_pile` 一个都没出现，顶层也没有 `hand`；玩家开局恒 3 能量 5 张手牌。
  - 刷新稳定：20/20 局 `GET /api/game` 连续两次读到的公开状态**逐字节相等**。
  - 难度不改数值：三档各 10 局，玩家能量恒 `{3}`、起手恒 `{5}`，电脑能量分别是 `{0,3}`（0 是电脑先手局已经花掉的结果，不是难度差异）。
  - 40 局 `/api` 整局：终局分布 `DEFEAT 22 / DRAW 10 / VICTORY 8`，**玩家闪避 24 次、电脑作为防御方闪避 9 次、电脑释放技能 33 次，双向响应与双向技能都在真实 HTTP 上跑通了**；采样到"护盾 > 0"电脑 326 次、玩家 288 次，双方护盾都跨回合持续。
  - 12 局 `/demo/battle` 表单整局：**12/12 走到终局**（Task 4 记录的 38% 卡死率归零），页面响应操作 5 次。所有 `POST` 都验证了最终地址落在 `/demo/battle` 或 `/demo/result`（urllib 自动跟随 302，所以判据用最终 URL 而不是状态码）。
  - 页面冒烟：`/` 返回 `{"service":"card-battle","status":"ok","api_base":"/api","demo":"/demo"}`、`/demo` 含难度选项与 `enemy-hero` / `enemy-energy` / `enemy-skill` 三个新标记、`/demo/heroes` 含确认角色、`/demo/battle` 200。
  - 人工对局替代说明：三局手动试玩由脚本的整局驱动器覆盖（`/api` 40 局 + 页面 12 局，逐局断言公开状态不变量），没有真人在浏览器上点。**"双方公开资源都看得见、电脑手牌从不泄露、胜负不依赖隐藏信息"这三条，目前是靠冒烟的状态审计 + 契约测试 + Task 5 的观察视图字段冻结共同保证的，不是靠人眼。**
- 平衡探针（`%TEMP%\balance_probe7.py`，与 Task 3/4/5 同一个脚本，120 局/格）——**逐格与 Task 5 完全一致**：战士 负 30.8 / 32.5 / 31.7、平 67.5~68.3、9.1~9.2 回合；法师 胜 43.3 / 42.5 / 38.3；游侠 胜 18.3 / 18.3 / 17.5；龟缩变体 战士 负 35.0 / 法师 负 73.3 / 游侠 负 95.0；先手拆解 玩家先手 负 23.3 平 75.0 / 玩家后手 负 40.0 平 60.0。连跑两次读数逐字相同（探针全程 `random.Random(seed)`，本就确定）。这与 `game/battle.py` 的 diff 对得上——本轮只多了一行只读别名，没有一条规则被改到。
- 探针暴露的**文档陈旧**（不是代码问题）：决策 5 的「难度 × 电脑英雄」拆解，上一次记录是在 Task 3 的验收里（电脑=法师 35.0~40.0%、电脑=游侠 28.6~37.1%、电脑=战士 0.0~4.4%）。Task 4 给电脑加了闪避、Task 5 改了威胁估算，两次都只复跑了合计行、没有重新拆格，所以那三组区间已经对不上：现在实测（玩家=游侠）电脑=法师 胜 30.0~32.5%、电脑=游侠 胜 22.9~25.7%、**电脑=战士 胜 0.0~2.2% / 负 93.3~97.8% / 平 0~6.7%**，与 Task 3 那组合计（游侠 胜 22.5~24.2%）才对得上。**结论不变**：电脑抽到战士本身就是一档难度，下一轮平衡该动的是护盾效率（决策 8 的已知风险），不是 AI 评分。
- 难度轴仍是三档几乎无差别（游侠 18.3 / 18.3 / 17.5，战士 负 30.8 / 32.5 / 31.7），沿用 Task 3/4/5 的结论：留给后续难度任务，本轮按决策 5/6 只记录、不调参。
- 依旧保留的两处既有偏差（沿自 Task 2/4，本轮不动）：电脑先手时开局那次攻击在 `create()` 里自动按"放弃"结算，所以玩家闪不了开局伤害；**英雄技能的伤害不经过响应窗口**，两边一致。
- 范围说明：原“队友宏观计划”目录下的两份规划文档已按主题迁入 `docs/产品方案/`，与本轮无关，提交时**不**纳入。

## Completion Criteria

- 电脑与玩家都从同一英雄池获得英雄，并使用同一牌库、起手、手牌上限、能量、抽牌、弃牌和护盾规则。
- 每局首个行动方由 RNG 公平决定，测试可稳定指定先手。
- 双方均可使用普通牌、一次英雄技能、结束回合和闪避响应；电脑通过 AI 选择，玩家通过 UI 选择。
- AI 绝不读取玩家私有手牌或抽牌堆；困难模式只基于公开信息做一步前瞻。
- 双方的英雄、生命、护盾、能量和技能状态在 UI/API 中对称公开，双方手牌保持私有。
- 三档难度只影响决策质量，不影响任何比赛数值或权限。
- 自动化测试、真实 HTTP 流程和人工对局分别验证双方先手、双方英雄技能、双方闪避、状态持久化与隐私边界。
