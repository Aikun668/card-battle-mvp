# 装备牌后端 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在规则内核里加入「武器槽 + 护甲槽」装备机制，双方对等可用、装备跨回合持续生效、AI 能自主决策装备，并通过 JSON 公开状态暴露给后续前端。

**Architecture:** 装备是牌库里的普通卡牌，打出后不进入弃牌堆，而是留在 `ParticipantState` 的 `weapon` / `armor` 槽位里持续生效。它引入「第四牌区」，因此现有的三区守恒不变量要扩成四区。伤害结算新增一个统一漏斗 `_deal_damage()`，让铁甲减伤同时覆盖卡牌伤害和英雄技能伤害。

**Tech Stack:** Python 3、Flask、pytest。**本轮不碰 `templates/` 和 `static/`**——前端展示、卡牌素材和视觉后面单独做。

**Spec:** `docs/产品方案/玩法路线/游戏玩法路线优先级.md` 的「第二优先：装备牌」

## Decisions (2026-09-20)

用户确认的十条，本轮按此执行：

1. 长剑、铁甲进入普通牌库。
2. 装备牌可以被玩家和电脑正常抽到。
3. 打出装备消耗 1 点能量。
4. 装备后进入角色旁边的武器/护甲槽。
5. 装备不进入弃牌堆。
6. 每种装备暂时只有 1 张，不做替换。
7. 长剑只强化斩击。
8. 铁甲同时影响普通攻击和英雄技能。
9. 先实现对等规则，再通过 120 局测试观察是否拖平或失衡。
10. 前端暂时不改，但后端状态中必须保留 `weapon` 和 `armor` 两个公开字段。

由上述十条推导出的落地口径：

- 牌库从 13 张变 **15 张**（斩击 4 / 重击 2 / 护盾 3 / 治疗 2 / 火球 1 / 闪避 1 / 长剑 1 / 铁甲 1），双方各持一套。
- 装备是**第四牌区**：手牌 + 抽牌堆 + 弃牌堆 + 装备槽恒等于整副 15 张，随机对局守恒不变量要按这个语义扩展。
- 决策 6 的必然结果：**不做替换逻辑、不做同名拒绝**。每种装备只有 1 张，装上后那张牌就在槽里，不可能再抽到第二张同名——那两条是永远跑不到的死代码。将来某种装备加到 2 张时再连替换规则一起做。

两条用户未特别指定、计划内按推荐执行的细节（实施中若发现问题再单独提出）：

- **"每回合第一次"的消耗语义**：打出即消耗，不管这次攻击有没有真的掉血。长剑加成被闪避抵消时照样消耗，铁甲把伤害减到 0 时照样消耗。理由是这两个标记与 `skill_used_this_turn` 共用生命周期（都在持有者自己的 `start_turn()` 里重置），语义统一；否则要额外区分"真的受伤"和"挨了一次攻击"。
- **铁甲减伤在护盾之前结算**：顺序为 长剑加成 → 闪避判定 → 铁甲减伤 → 护盾吸收 → 扣血。这样铁甲对高护盾角色仍然有用，也和主流卡牌游戏的伤害修正顺序一致。

决策 9 的已知风险来自 `docs/归档/历史实施计划/2026-09-20-human-ai-complete-symmetry.md` 决策 8：护盾跨回合持久化已经让战士容易拖平，铁甲每回合白吃 2 点伤害会进一步加剧。本轮**不预先加护盾上限或装备数量限制**，按上面数值实现后跑 120 局/格的探针，用数据决定要不要调。

## Global Constraints

- **人机完全对等**：装备是双方共用的牌库卡牌，电脑通过同一个 `play_card_for(side, ...)` 通路装备，不新增任何特例；`ENEMY_UNUSABLE_EFFECTS` 仍然只含 `dodge`。
- **AI 信息边界**：装备挂在身上是公开信息，可以进 `AIObservation`；玩家手牌与抽牌堆仍然不许进。
- **前端不参与**：本轮不改 `templates/`、`static/`，也不改 `/api` 的路由形状——装备就是打牌，沿用 `POST /api/game/actions/card`。
- **序列化约定**：`to_dict()` 只写新结构（四个装备字段必写），`from_dict()` 用 `.get()` 容缺，旧存档读出来装备为空、标记为 `False`，不返回 500。
- 不改动任何现有卡牌、英雄或能量的既有数值。

## Review Focus

- `_take_pending_attack()` 当前传的是 `CARDS[pending.card_key]` 而不是 `pending.damage`，长剑加成会在这里被丢掉——必须一起修。
- 英雄技能的两处伤害（`use_skill_for()` 里 `damage` 与 `damage_draw` 分支）直接调 `apply_damage()`，绕过了 `_resolve_damage()`。铁甲要覆盖它们，必须走统一漏斗。
- 三区守恒不变量（`tests/test_battle.py`）要扩成四区：装备槽也是牌的去处。
- `tests/test_ai.py` 的字段集合钉死测试必须同步更新字段清单——它钉的是"没有隐藏手牌位"，不是"永不加字段"。
- 牌库 +2 张会改变洗牌结果，任何依赖固定种子的整局断言都可能漂移，必须逐个重跑校准而不是改断言数字了事。

---

### Task 1: 装备的数据模型、牌库与存档

**Files:**
- Modify: `game/catalog.py`
- Modify: `game/models.py`
- Modify: `game/battle.py`
- Test: `tests/test_catalog.py`
- Test: `tests/test_session_state.py`

**Interfaces:**
- Consumes: 现有的 `CARDS`、`FIXED_DECK_KEYS`、`ParticipantState`、`to_dict()` / `from_dict()`。
- Produces: `longsword`（长剑）、`iron_armor`（铁甲）两张 `effect_type="equip"` 的卡牌；15 张的 `FIXED_DECK_KEYS`；`ParticipantState.weapon` / `.armor` / `.weapon_used_this_turn` / `.armor_used_this_turn`。

- [x] **Step 1: 写牌库构成与存档往返的失败测试**

```python
def test_fixed_deck_carries_one_weapon_and_one_armor():
    assert len(FIXED_DECK_KEYS) == 15
    assert FIXED_DECK_KEYS.count("longsword") == 1
    assert FIXED_DECK_KEYS.count("iron_armor") == 1
    assert CARDS["longsword"].effect_type == "equip"
    assert CARDS["iron_armor"].effect_type == "equip"
    assert CARDS["longsword"].cost == 1 and CARDS["longsword"].value == 2
    assert CARDS["iron_armor"].cost == 1 and CARDS["iron_armor"].value == 2


def test_battle_payload_round_trips_equipped_gear():
    battle = BattleState.create("warrior", random.Random(7), starting_side=Side.PLAYER)
    battle.hand = [{"id": "gear-1", "key": "longsword"}]
    battle.play_card("gear-1")
    restored = BattleState.from_dict(battle.to_dict())
    assert restored.participant(Side.PLAYER).weapon.key == "longsword"


def test_old_payload_without_gear_keys_reads_back_empty():
    payload = BattleState.create("warrior", random.Random(7)).to_dict()
    payload["participants"][Side.PLAYER.value].pop("weapon", None)
    payload["participants"][Side.PLAYER.value].pop("armor", None)
    restored = BattleState.from_dict(payload)
    assert restored.participant(Side.PLAYER).weapon is None
```

- [x] **Step 2: 运行测试，确认牌库仍是 13 张且没有装备字段**

Run: `pytest tests/test_catalog.py tests/test_session_state.py -q`

Expected: 新增断言因牌库只有 13 张、`ParticipantState` 没有 `weapon` 而失败。

- [x] **Step 3: 在目录里加入两张装备牌**

`CARDS` 新增两条：`longsword`（长剑，`cost=1`、`effect_type="equip"`、`value=2`）和 `iron_armor`（铁甲，同样 1 费、`value=2`）。`FIXED_DECK_KEYS` 各追加 1 张，总数变 15。`CATALOG_KEYS` 是 `tuple(CARDS)`，自动跟随。

- [x] **Step 4: 给参与者加上装备槽**

`ParticipantState` 新增四个字段：`weapon`、`armor`（都是 `CardDefinition | None`，默认 `None`）和两个本回合标记（`bool`，默认 `False`）。放在 `ParticipantState` 而不是 `Combatant`，因为 `Combatant` 只管血量、护盾和能量，装备是牌的去处，和手牌、抽牌堆、弃牌堆同类。

- [x] **Step 5: 存档读写装备**

`_participant_to_payload()` 写出 `weapon` / `armor` 的 key（没有就写 `None`）和两个标记；`_participant_from_payload()` 用 `payload.get("weapon")` 之类容缺，读到的 key 经 `CARDS` 还原成对象，未知 key 一律当 `None`（不能让一个坏存档炸掉整局）。

- [x] **Step 6: 运行测试**

Run: `pytest tests/test_catalog.py tests/test_session_state.py tests/test_battle.py -q`

Expected: 牌库 15 张、存档往返保留装备、旧 payload 读出空装备。

- [x] **Step 7: 提交装备数据模型**

```bash
git add game/catalog.py game/models.py game/battle.py tests/test_catalog.py tests/test_session_state.py
git commit -m "feat: add equipment cards and gear slots to the participant model"
```

**验收记录（Task 1）**

- 实际改动文件：`game/catalog.py`、`game/models.py`、`game/battle.py`、`tests/test_catalog.py`、`tests/test_session_state.py`。计划里列的五个文件全部用上，没有额外扩散。
- 实现要点：`CARDS` 增 `longsword`（长剑）/ `iron_armor`（铁甲），都是 1 费 `effect_type="equip"`、`value=2`；`FIXED_DECK_KEYS` 各追加 1 张，**13 → 15 张**。`ParticipantState` 加 `weapon` / `armor`（`CardDefinition | None`）与 `weapon_used_this_turn` / `armor_used_this_turn`——放在参与者而不是 `Combatant` 上，因为装备是牌的第四个去处，和手牌区、抽牌堆、弃牌堆同类。序列化侧新增 `_equipped_card_from_payload()`：槽里**只认装备牌**，未知 key（`excalibur`）、普通牌（`slash`）、非字符串一律还原成空槽，坏存档不会炸掉整局。旧扁平存档走 `_migrate_legacy_participants()`，不传装备字段即默认空槽，无需改动。
- 门禁：`compileall` 通过、`ruff check .` 通过、`ruff format --check .` 23 文件通过、`pytest -q` **174 passed**（Task 6 结束时是 170）。新增 6 个测试：`tests/test_catalog.py` 3 个（牌库 15 张且两种装备各 1 张、装备牌的文案与数值、`len(CARDS) == 8`），`tests/test_session_state.py` 3 个（装备存档往返、旧 payload 缺装备字段读出空槽、槽里塞进非装备 key 读出空槽）。RED→GREEN 走完：实现前 6 个新测试全红，实现后全绿。
- **证伪了一个预设风险**：计划里写"牌库 +2 张会改变所有固定种子对局的洗牌轨迹，依赖整局轨迹的用例可能漂移，要逐个重新校准"。实测**没有任何一个测试因扩容而失败**——现有用例断言的都是不变量和相对性质（能量增减、牌区守恒），没有一条钉死具体牌序。这条风险从"需要逐个校准"降级为"不需要处理"。
- **本任务结束时的中间状态（Task 2 才修）**：装备牌现在可以被双方抽到、也可以被打出去，但 `play_card_for()` 还没有装备分支——它会走通用路径**进入弃牌堆**，而 `_apply_card_effect()` 对 `equip` 类型不做任何事。也就是说此刻打出一张装备牌 = 花 1 点能量、牌进弃牌堆、什么都不发生。**这是 TDD 分步的正常中间态，不是可交付状态**；Task 2 补齐结算、Task 3 才让 AI 学会正确估值。
- **订正（Task 2 实施时实测）**：上面写"AI 会把装备牌当普通候选打掉"是**错的**。装备确实是候选（`ENEMY_UNUSABLE_EFFECTS` 只排除闪避），但 `_base_score()` 对 `effect_type == "equip"` 没有分支、返回 `0.0`，输给 `score_pass()` 的 `0.5`；`_select()` 的 `usable` 池又是"分数严格高于空过"，装备永远进不去。实测 12 个种子、电脑手上只有一长一甲时：12/12 都是空过，装备原封不动留在手里、能量也没花。真正的问题是**装备变成电脑手里永远打不出去的死牌**，会一直占着手牌位（上限 6）直到 Task 3 给它定价。
- 结构说明：`EQUIP_SLOTS`（装备 key → 槽位名的映射）曾在实现中加进 `catalog.py`，但它到 Task 2 才有第一个人使用，属于死代码，已删除；Task 2 实现装备分支时再加。

### Task 2: 装备结算规则、长剑加成与铁甲减伤

**Files:**
- Modify: `game/battle.py`
- Test: `tests/test_battle.py`

**Interfaces:**
- Consumes: Task 1 的装备字段与两张装备牌。
- Produces: 装备结算分支、统一的伤害漏斗 `_deal_damage(attacker, defender, damage)`、带加成的 `PendingAttack.damage`。**不新增门面函数**——装备就是打牌，走现有的 `play_card_for()`。

- [x] **Step 1: 写装备流程与两个装备效果的失败测试**

```python
def test_equipping_moves_the_card_into_the_slot_without_discarding_it():
    battle = BattleState.create("warrior", random.Random(7), starting_side=Side.PLAYER)
    battle.hand = [{"id": "gear-1", "key": "longsword"}]
    assert battle.play_card("gear-1").ok
    participant = battle.participant(Side.PLAYER)
    assert participant.weapon.key == "longsword"
    assert "longsword" not in participant.discard_pile
    assert participant.combatant.energy == 2


def test_weapon_boosts_only_the_first_slash_of_its_owners_turn():
    # 第一次斩击 6+2=8，第二次回到 6；下个自己回合重新加成。
    ...


def test_armor_soaks_the_first_damage_of_each_owner_turn():
    # 首次受伤 -2，同回合第二次不减；减到 0 仍然算消耗；被闪避则不消耗。
    ...


def test_armor_reduces_hero_skill_damage_too():
    # 法师技能 10 点打在装着铁甲、护盾为 0 的一方身上，只掉 8 点。
    ...
```

还要覆盖：装备不合法时的拒绝（能量不足、不是自己的回合）、装备牌不进入响应窗口、长剑加成出现在 `PendingAttack.damage` 里、铁甲在护盾之前结算（护盾 + 铁甲同时存在时的分配）。

- [x] **Step 2: 运行测试，确认装备现在还只能当普通牌打掉**

Run: `pytest tests/test_battle.py -q`

Expected: 新增断言失败，装备牌现在会走通用路径进弃牌堆。

- [x] **Step 3: 实现装备分支**

`play_card_for()` 在扣完能量、把手牌 pop 出来之后、进弃牌堆之前加一个 `effect_type == "equip"` 分支：按 `definition.key` 决定进 `weapon` 还是 `armor` 槽，**不进弃牌堆**，写入日志，早期返回。弃牌那一行（现在对所有牌无条件执行，`game/battle.py:245`）要挪到分支之后。**不新增门面函数**：装备就是打牌，测试也用 `play_card()`。

- [x] **Step 4: 让长剑加成进入挂起的伤害**

`_open_response()` 增加一个 `damage` 参数（默认取 `definition.value`）。`play_card_for()` 的伤害分支在调用它之前算出加成：如果攻击方装了长剑、本回合还没用过、且打的是 `slash`，就 `damage += weapon.value` 并把 `weapon_used_this_turn` 置 `True`。加成后的数值同时用于 `PendingAttack.damage`、日志文案和伤害结算——**响应窗口显示的数字必须是玩家真正要挨的数字**。

顺带修掉 `_take_pending_attack()`：它现在传的是 `CARDS[pending.card_key]`，会把加成丢掉，要改成用 `pending.damage`。

- [x] **Step 5: 建立统一的伤害漏斗与铁甲减伤**

把 `_resolve_damage()` 改造成 `_deal_damage(attacker, defender, damage)`：先看防御方有没有铁甲且本回合没用过，有就 `damage = max(0, damage - armor.value)` 并置标记，然后调 `apply_damage()`。`_take_pending_attack()`、`_open_response()` 的无法响应分支、以及 `use_skill_for()` 的两处技能伤害全部改走这个漏斗——这是铁甲能覆盖技能伤害的唯一办法。

`start_turn()` 里连同技能标记一起重置该方的 `weapon_used_this_turn` 和 `armor_used_this_turn`。

- [x] **Step 6: 把三区守恒不变量扩成四区**

`tests/test_battle.py` 的随机对局不变量现在断言「手牌 + 抽牌堆 + 弃牌堆 == 整副牌库」。装备槽是第四个去处，要把双方 `weapon` / `armor` 的 key 一起加进 `Counter`，语义变成「手牌 + 抽牌堆 + 弃牌堆 + 装备槽 == 整副牌库」。

- [x] **Step 7: 运行测试并重新校准被洗牌轨迹影响的用例**

Run: `pytest -q`

Expected: 全部通过。**牌库从 13 张变 15 张会改变所有固定种子对局的发牌结果**，`tests/test_acceptance_scenarios.py` 等依赖整局轨迹的用例可能漂移；要逐个确认漂移原因确实是发牌变了，而不是规则写错了，然后重新校准断言。

- [x] **Step 8: 提交装备结算规则**

```bash
git add game/battle.py tests/test_battle.py tests/test_acceptance_scenarios.py
git commit -m "feat: settle equipment effects for both sides"
```

**验收记录（Task 2）**

- 实际改动文件：`game/battle.py`、`game/catalog.py`、`tests/test_battle.py`、`tests/test_catalog.py`。比计划多两个：`catalog.py` 里加回 `EQUIP_SLOTS`（Task 1 记过"Task 2 再加"）和新增 `LONGSWORD_BOOST_KEYS = frozenset({"slash"})`——决策 7 的"只强化斩击"是一条规则，放在牌表旁边比写死在 `battle.py` 的条件里更容易被下一次改数值时看见；`tests/test_catalog.py` 加一条 `EQUIP_SLOTS` 与牌表里 `effect_type == "equip"` 的集合必须一致的守卫，因为 `_equip()` 是直接查这张表的。
- 实现要点：
  - `play_card_for()` 在扣能量、pop 手牌之后、进弃牌堆之前插入 `equip` 分支，早期返回；`discard_pile.append()` 那行挪到分支之后。装备走 `_equip()` → `setattr(participant, EQUIP_SLOTS[key], definition)`。
  - 新增 `_attack_damage(attacker, definition)`：长剑 + 本回合未用 + 打的是斩击，三者同时成立才 `+2` 并置标记。它在 `_open_response()` 里调用，所以**加成只算一次**，同时决定了 `PendingAttack.damage`、日志数字和实际伤害。
  - 新增 `_deal_damage(defender, damage)` 作为唯一伤害漏斗：铁甲先减伤（`max(0, damage - 2)`，命中即置标记），再调 `apply_damage()` 走护盾优先。`use_skill_for()` 的 `damage` / `damage_draw` 两处技能伤害、`_resolve_damage()` 全部改走它。返回值是**减伤后、护盾吸收前**的数字，日志按它报伤害——和原先"日志报打出值、护盾另算"的口径一致。
  - `_take_pending_attack()` 改用 `pending.damage`，不再回查 `CARDS[pending.card_key]`。
  - `_format_card_log()` 增加 `dealt` 参数（仅伤害牌使用，缺省仍取 `definition.value`）。
  - `start_turn()` 连同 `skill_used_this_turn` 一起重置 `weapon_used_this_turn` / `armor_used_this_turn`。
- **与计划的一处偏离**：计划写的漏斗签名是 `_deal_damage(attacker, defender, damage)`，实现成 `_deal_damage(defender, damage) -> int`。攻击方不参与任何减伤逻辑，留着就是死参数；同时调用方需要"减伤后、护盾前"的数字来写日志，所以让它把 `damage` 返回出来。
- 门禁：`compileall` 通过、`ruff check .` 通过、`ruff format --check .` 23 文件通过、`pytest -q` **193 passed**（Task 1 结束时 174），连跑 3 轮稳定。新增 19 个测试：`tests/test_battle.py` 18 个、`tests/test_catalog.py` 1 个。RED→GREEN：实现前 13 个新用例失败，另外 5 个（能量不足拒绝、非本方回合拒绝、装备不进响应窗口、长剑不影响重击、被闪避不消耗铁甲）当时就已经成立，作为回归守卫留着。
- **第二个被证伪的预设风险**：计划 Step 7 写"牌库 13→15 张会改变所有固定种子对局的发牌结果，`tests/test_acceptance_scenarios.py` 等依赖整局轨迹的用例可能漂移"。实测**一条都没漂移**，不需要重新校准任何断言——和 Task 1 的结论一致：现有用例断言的是不变量与相对性质，没有一条钉死牌序。这个风险第二次出现在计划里，应视为已关闭，Task 4 不再重复预留校准时间。
- **四区不变量不是空转**：`assert_consistent()` 扩成四区后，用随机策略探针跑 60 局，实际打出长剑 67 次、铁甲 67 次——装备槽确实被填上过，守恒断言有真实覆盖面，不是"永远为空的第四项"。
- **本任务结束时的中间状态（Task 3 才修）**：玩家一侧的装备已经完全可用；电脑一侧只是"不会用"——装备进不了它的评分池（`_base_score` 返回 0.0，输给空过 0.5），所以实测 12/12 个种子都选择空过，装备卡死在电脑手牌里占位。这是 Task 3 的直接输入。

### Task 3: 让 AI 会装备

**Files:**
- Modify: `game/ai.py`
- Modify: `game/battle.py`
- Test: `tests/test_ai.py`

**Interfaces:**
- Consumes: Task 1 的装备字段、Task 2 的装备结算。
- Produces: 带装备字段的 `PublicParticipantState`、`score_equip()`、计入长剑的 `score_damage()`、计入铁甲的 `estimate_player_threat()`。

- [x] **Step 1: 写 AI 装备决策的失败测试**

```python
def test_enemy_offers_an_equipment_card_as_a_normal_candidate():
    # 电脑手上有长剑时，候选里出现它，kind 仍然是 "card"。


def test_enemy_never_re_offers_gear_it_already_wears():
    # 已经装了长剑的电脑不会再把另一张长剑当成候选。


def test_weapon_raises_the_score_of_a_slash_but_not_of_a_fireball():
    # 装长剑后斩击评分变高，火球不变。


def test_armor_reduces_the_estimated_player_threat():
    # 电脑装上铁甲后，对玩家下回合伤害上界的估计下降 2 点。


def test_gear_on_an_opponent_is_public_information():
    # 观察视图里能读到对手装了什么，但读不到对手手牌。
```

- [x] **Step 2: 运行测试，确认 AI 现在完全不知道装备存在**

Run: `pytest tests/test_ai.py -q`

Expected: 新增断言因观察视图没有装备字段而失败。

- [x] **Step 3: 把装备放进观察视图**

`PublicParticipantState` 增加装备相关字段，`BattleState.enemy_observation()` 填充它们。**同步更新 `tests/test_ai.py` 里那份逐字钉死的字段集合清单**——这份测试的用意是"观察视图里没有藏着对手手牌的位置"，加公开的装备字段是它的设计允许的，但清单必须手动跟进，这样任何一次字段变动都必须是有意识的。

- [x] **Step 4: 给装备定价**

新增 `score_equip()`。长剑的估值取"手上还有几张斩击 × 加成值"（封顶 2 张的量，因为它每回合只能触发一次），铁甲的估值取"减伤值 × 当前失血风险系数"，复用 `score_heal()` 已经在用的那个风险系数口径，避免又造一套。装备是跨回合收益，`score_pass()` 的"留能量给闪避"加分逻辑不受影响。

注意 `ActionCandidate.kind` **不新增类型**：装备就是打牌，沿用现有的 `"card"`，`_run_enemy_actions()` 一行都不用改。

- [x] **Step 5: 让长剑和铁甲进入现有评分**

`score_damage()` 在计算斩击伤害时计入长剑加成（与自己回合内是否已触发保持一致）；`estimate_player_threat()` 在对手装铁甲时把威胁上界减 2。威胁估算仍然只看公开信息，不许因此去读玩家手牌。

- [x] **Step 6: 运行测试**

Run: `pytest tests/test_ai.py tests/test_battle.py -q`

Expected: 电脑会主动装备、不会重复装备、装了长剑之后更愿意打斩击、装了铁甲之后更保守。

- [x] **Step 7: 提交 AI 装备决策**

```bash
git add game/ai.py game/battle.py tests/test_ai.py
git commit -m "feat: teach the AI to value and use equipment"
```

**验收记录（Task 3）**

- 实际改动文件：`game/ai.py`、`game/battle.py`、`tests/test_ai.py`，与计划一致。
- 实现要点：
  - `PublicParticipantState` 加 `weapon_key` / `armor_key` / `weapon_used_this_turn` / `armor_used_this_turn` 四个字段，`_public_participant()` 填充。`tests/test_ai.py` 那份逐字钉死的字段清单同步更新并注明"装备挂在身上是公开信息"，边界仍然是"装不下对手手牌"。
  - `score_equip()`：武器按 `min(手里吃加成的牌数, WEAPON_EATERS_PER_TURN) × 加成值` 计价，护甲按 `减伤值 × _risk_multiplier(自己)`。`_base_score()` 加 `equip` 分支；`ActionCandidate.kind` 不新增类型，`_run_enemy_actions()` 一行未改。
  - `_damage_with_weapon()` 让 `score_damage()` 与结算口径对齐（长剑加成只在没触发过时计入，用掉即回落）；`_after_own_armor()` 让 `estimate_player_threat()` 把自己身上还没用掉的铁甲从威胁上界里减掉。
- **计划里没有、实施中补的一个口径漏洞**：`score_dodge()` 读的是含长剑加成的 `pending.damage`，却整段绕过了铁甲——会以为自己要挨 10 点（护盾吸 4 → 救回 6），实际放弃响应只会掉 4 点，于是高估闪避的价值。补了 `test_dodge_scores_only_what_the_armor_would_let_through`，并单独验证过它在旧口径下确实变红（旧公式 6.0、新公式 4.0），不是写完就绿的假测试。
- **与计划的两处偏离**：
  1. 计划 Step 1 里的 `test_enemy_never_re_offers_gear_it_already_wears` **没有实现**，因为它描述的是一个到不了的状态：每种装备只有 1 张，装上之后那张牌永远在槽里、不会回到手牌，所以"手上又出现一张同名装备"根本不可能发生——这条和 Task 1 已经判死的"替换 / 同名拒绝"是同一族死代码。真正阻止重复装备的机制是"牌已经不在手上了"，不需要额外代码。
  2. 计划 Step 5 写的"`estimate_player_threat()` 在**对手**装铁甲时把威胁上界减 2"字面上说不通：玩家的铁甲不会减少玩家打出的伤害。按计划自己的用例描述（"电脑装上铁甲后，对玩家下回合伤害上界的估计下降 2 点"）实现成了**自己**身上的铁甲。
- 门禁：`compileall` 通过、`ruff check .` 通过、`ruff format --check .` 23 文件通过、`pytest -q` **205 passed**（Task 2 结束时 193），连跑 3 轮稳定。新增 12 个测试（全在 `tests/test_ai.py`）。RED→GREEN：实现前 9 个失败，另外 3 个（装备作为 `kind="card"` 候选、没斩击时武器评分为 0、已用掉的铁甲不减威胁）当时就成立，作为回归守卫留着。
- **实测电脑真的会装备**（200 局/难度，随机玩家策略 + 电脑 AI）：出现过电脑装备的对局 **简单 43% / 中等 34% / 困难 26.5%**；其中铁甲 64 / 54 / 41 次，长剑只有 31 / 20 / 13 次。长剑明显偏少的原因是它在数学上很难赢过直接打斩击：手里 1 张斩击时武器值 2.0 分，而那张斩击自己至少值 2.4 分（面对 12 点护盾的极端值），只有攒到 2 张斩击（4.0 分）时装备才排到第一。**难度越高装备越少**也不是 bug：困难模式是确定性的 top-1，中等难度会给第二顺位 12% 的权重，长剑偶尔从这里被选中。这是"电脑按自己的估值理性地少穿剑"，不是"不会穿"；是否要给它加权重属于数值问题，留给 Task 4 的平衡探针一起看。
- 本任务结束时的中间状态：玩家和电脑都已经能用装备，规则内核完成；剩下的是公开 JSON 状态与文档（Task 4）。

### Task 4: 公开状态、文档与验收

**Files:**
- Modify: `game/public_state.py`
- Modify: `docs/产品方案/基础规则/interaction-design.md`
- Modify: `docs/接口契约/本地对局/api-contract.md`
- Modify: `docs/验收/MVP/MVP验收与质量门槛.md`
- Modify: `README.md`
- Test: `tests/test_api.py`
- Test: `tests/test_frontend_contract.py`

**Interfaces:**
- Consumes: Tasks 1–3 的装备模型、结算与 AI。
- Produces: 双方对称的装备公开字段；更新后的规则文档与验收清单。

- [x] **Step 1: 写公开状态装备字段的失败测试**

```python
def test_public_state_shows_both_sides_equipment_symmetrically(client):
    # player 和 enemy 都有 equipment.weapon / equipment.armor，
    # 没有装备时为 None；电脑手牌仍然不出现。
```

- [x] **Step 2: 运行测试，确认公开状态还没有装备字段**

Run: `pytest tests/test_api.py -q`

- [x] **Step 3: 在公开状态里对称输出装备**

`_side_to_dict()` 给双方各加一个 `equipment` 字段，形状与 `hero` / `skill` 的嵌套风格一致（决策 10）：

```json
"equipment": {
  "weapon": {"key": "longsword", "name": "长剑", "cost": 1, "value": 2} ,
  "armor": null
}
```

`weapon` 和 `armor` 两个字段**任何时刻都必须存在**，没装备时为 `null`，不能整个键消失——前端要能无条件读它们。装备是公开信息，两边都能看见对面装了什么，这延续了对等改动里"公开信息对称"的原则。**不新增任何路由**：装备仍然走 `POST /api/game/actions/card`。

- [x] **Step 4: 更新文档**

`docs/产品方案/基础规则/interaction-design.md` 补装备的规则章节（两个槽位、1 费、长剑只加成斩击、铁甲先于护盾减伤、每回合首次、装备跨回合保留、装备牌不进弃牌堆）；`docs/接口契约/本地对局/api-contract.md` 补公开状态的 `equipment` 字段和示例；`docs/验收/MVP/MVP验收与质量门槛.md` 补装备的自动化验收项；`README.md` 把"13 张固定卡组"改成 15 张并写清装备规则。**删掉所有"13 张"的旧描述。**

- [x] **Step 5: 跑全套门槛**

Run: `python -X utf8 -m compileall app.py api_routes.py demo_routes.py web_support.py game && ruff check . && ruff format --check . && pytest -q`

Expected: 全绿。全量测试连跑多轮（路由测试用非种子 RNG）。

- [x] **Step 6: 真实 HTTP 冒烟与平衡探针**

启动单个本地实例（`use_reloader=False`），用 `urllib` 脚本走 `/api`：验证装备能从接口打出、公开状态的 `equipment` 双方对称、电脑会自己装备、电脑手牌仍然不泄露。然后跑 120 局/格的平衡探针，**重点看铁甲是否让战士的拖平率上升**（决策 8 记录的已知风险），把结果写进验收记录。探针脚本沿用 `%TEMP%\balance_probe7.py` 的玩家策略，保证跨任务可比。

- [x] **Step 7: 提交公开状态与验收改动**

```bash
git add game/public_state.py tests/test_api.py tests/test_frontend_contract.py README.md docs/产品方案/基础规则/interaction-design.md docs/接口契约/本地对局/api-contract.md docs/验收/MVP/MVP验收与质量门槛.md
git commit -m "feat: publish equipment in the public state and document it"
```

**验收记录（Task 4）**

- 实际改动文件：`game/public_state.py`、`tests/test_api.py`、`README.md`、`docs/产品方案/基础规则/interaction-design.md`、`docs/接口契约/本地对局/api-contract.md`、`docs/验收/MVP/MVP验收与质量门槛.md`，与计划一致；**`tests/test_frontend_contract.py` 未改**，理由见下。
- 实现要点：
  - `_side_to_dict()` 新增 `equipment`，槽位值走新的 `_slot_to_dict()`、复用已有的 `_card_to_dict()`；`weapon` / `armor` 两个键任何时刻都在，空槽是 `null`。
  - 比计划 Step 3 的示例多带一个 `effect_type: "equip"`——直接用 `_card_to_dict()` 的完整结果，不给装备单写一份裁剪逻辑；前端要靠它区分装备牌和普通手牌。
  - 没有新增任何路由：装备照旧走 `POST /api/game/actions/card`。
- **偏离：没有动 `tests/test_frontend_contract.py`**（计划把它列进了本任务的测试文件）。那个文件断言的是 `static/game.js` / `game.css` 里的前端契约，而本轮前端明确不改（决策 10）——硬加一条"前端读得到 equipment"的断言，等于把一个没人实现的消费者写进契约。装备的前端契约留到前端那一轮，和读取它的代码一起加。
- 门禁：`compileall` 通过、`ruff check .` 通过、`ruff format --check .` 23 文件通过、`pytest -q` **207 passed**（Task 3 结束时 205），连跑 4 轮稳定。新增 2 个测试（都在 `tests/test_api.py`）。RED→GREEN：实现前两个都红在 `KeyError: 'equipment'`。
- **真实 HTTP 冒烟**（单个本地实例 `use_reloader=False`，`urllib` 走 `/api`，不碰 session）：
  - 双方 `equipment` 形状对称、两个键恒在、槽里是完整的卡牌定义；全程没有 `enemy_hand` / `enemy_draw_pile` / 电脑 `hand` 之类的键；
  - 第 2 局就抽到长剑：从接口打出后 weapon 槽回显一致、能量 -1、那张牌离开手牌、对面 `equipment` 不受影响；
  - **长剑加成在真实接口上落地**：装上长剑后打出的斩击让电脑掉 8 点（基础 6 + 武器 2），日志数字与扣血一致，不是只有单元测试说得通；
  - 40 局完整对局里 **26 局电脑自己装备**（护甲 23、长剑 7），装备确实在它的回合里通过接口出现。
- **平衡探针（120 局/格，玩家策略沿用 probe7 的贪心策略）——决策 8 记的"铁甲会不会加重拖平"答案是"分边"**：
  - **电脑穿铁甲不推高平局率**：战士 平 简单 69.2% / 中等 68.3% / 困难 65.8%，对比 Task 3 基线 68.3~70.8%，持平到略降（120 局下二项噪声约 ±4.4 点），平均回合 9.1~9.3 也没动。
  - **玩家主动穿铁甲才会推高**：同一个战士换成"没伤害牌可打时优先装备"的策略，平局率 65.8% → **80.0%**，负率 33.3% → 19.2%，回合 9.1 → 9.5。
  - 隔离实验（probe9，战士 vs 困难 AI，120 局/格）把归因钉死：只装长剑（且等伤害打完才装）与不装备**逐位相同**（平 65.8%），只装铁甲一个人就吃满全部效应（平 80.0%），铁甲优先 81.7%、长剑+铁甲 81.7%。所以不是"把能量花在装备上少打了输出"，就是减伤本身。
  - 绝对量很小：铁甲在玩家侧每局平均触发 2.42~2.75 次、合计 4.8~5.5 点减伤（120 局共 582~660 点），但战士对局本来就死在 9.1/10 回合的刀口上，2 点/回合够改变结局。
  - 法师、游侠几乎不受影响（法师困难 平 4.2% → 4.2%，游侠 0.8% → 4.2%）：这是**把已有的战士平局锁加深**，不是全局失衡，方向与决策 8 的预测一致。
  - 龟缩变体（只叠盾+技能）：战士 平 71.7% / 负 28.3%（Task 3 基线 平 65% / 负 35%），+6.7 点在 1.5σ 内，不当作结论。
  - 电脑穿装备的频率随对局长度变化：同样 120 局，电脑装备局 简单 91.7% / 中等 73.3% / 困难 69.2%，远高于 Task 3 记的 43% / 34% / 26.5%——Task 3 用的是随机玩家，常常 3~4 回合就结束，电脑没机会抽到装备；换成能撑到 9 回合的贪心玩家，它就有时间穿。两个读数的差异来自对局长度，不是 AI 行为变了。
- **按决策 9，本轮只交数据、不加限制**。要不要调是数值决策，可选方向（均未实施）：铁甲 2 点降到 1 点、把"每回合一次减伤"改成"整局一次"、或给跨回合护盾加上限。
- 一处刻意不动的历史文档：`docs/产品方案/基础规则/mvp.md` §4.2 仍写着"每个角色初始拥有 12 张固定卡牌"（原本就没算闪避，是 MVP 需求快照）。计划 Step 4 没列它，本轮不改；要不要同步是独立的一小步。
- 结束状态：装备功能的四个任务全部完成，后端机制打通并已通过公开接口暴露；前端展示、装备替换和数值调优留给后续。

## Completion Criteria

- 双方都能装备长剑和铁甲，走同一条 `play_card_for()` 通路，AI 零特例。
- 长剑只加成每回合第一次斩击，铁甲只减免每回合第一次受到的伤害（含技能伤害），两个标记在持有者自己的回合开始时重置。
- 装备跨回合保留，不进入弃牌堆；装备槽计入牌区守恒不变量。
- 电脑会自己装备，装备效果进入它的评分和威胁估算，且仍然读不到玩家手牌。
- 公开状态对称输出双方装备，电脑手牌仍然不泄露。
- 存档往返保留装备，旧存档读出空装备且不报错。
- 全量测试、ruff、compileall 全绿，真实 HTTP 冒烟与平衡探针结果记入验收记录。
- **本轮不实现**：装备的替换规则、前端展示、装备的视觉素材、多于两种装备、装备数量限制。
