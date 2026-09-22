# 留牌策略：消耗机制 Implementation Plan

**Goal:** 让"这张牌现在用还是留着"变成一次真实选择——引入「消耗」机制：带该属性的牌打出后**从本局移除**（不进弃牌堆、洗牌也回不来）。首张受益牌是游侠的「处决」，数值同步补偿为 8/16。

**Spec:** `docs/队友宏观计划/游戏玩法路线优先级.md` 的「第六优先：让留牌变成策略」。

**Architecture:** 卡牌属性进 `game/catalog.py`（`EXHAUST_KEYS` 集合，风格对齐 `CONDITIONAL_DAMAGE`）；参与者新增第五个牌区 `exhaust_pile`（`game/models.py`）；`game/battle.py` 打出时按属性分流、序列化往返；`game/public_state.py` 公开卡牌的 `exhaust` 标记与双方的移除区；AI 无需新折扣（评分天然只在斩杀区优先处决）。**不碰响应、装备、蓄力与既有数值。**

**Tech Stack:** Python 3、Flask、pytest。

## Decisions (2026-09-22)

1. **只做「消耗」，不做「延迟强化」。** 路线文档列了四个方向：「保留」（现状手牌本来就全保留，机制已存在）、「消耗」、「一次性」（与消耗语义重复，合并）、「延迟强化」（需要给每张手牌追踪"滞留回合数"，是新的状态维度）。本轮做消耗——它最小、最直接地把"时机"变成资源；延迟强化的体验已由「蓄力」部分覆盖，留待以后。
2. **只给「处决」加消耗，机制通用。** 收割牌"一击定生死、用完即逝"符合风味，也天然强化"留到斩杀区"的动机；将来想给更多牌加消耗，只需要往 `EXHAUST_KEYS` 里加 key。
3. **数值补偿：处决 6/12 → 8/16。** 消耗砍掉了"抽回来再打一次"的复用价值，属性和数值必须一起设计（这不是平衡调整）：基础 8、斩杀区 16（2 费一次性的收割，回报明确）。**其余一切数值不动。**
4. **消耗牌进入第五个牌区 `exhaust_pile`**，而不是在弃牌堆里做例外标记：守恒不变量升级为"手牌 + 抽牌堆 + 弃牌堆 + 装备槽 + 移除区 = 整副 16 张"，简单可验证。
5. **移除区是公开信息**：打出过的牌本来就写在日志里、双方都能看到；`exhaust_pile` 与卡牌的 `exhaust` 标记一起进公开状态，契约同步。
6. **AI 不加折扣。** 处决在非斩杀区的评分（7.5）本来就低于斩击（9），斩杀区的击杀奖励确保"该出手时出手"；消耗只影响"用掉后它不再出现在四区"这个事实——AI 通过自己的手牌天然知道。
7. **威胁估算不动，但加注释钉住前提**：处决上限 16 仍低于"火球 14 + 斩杀区加成后"…… 实测处决 16 > 火球 14，**需要处理**：威胁上界应把处决的斩杀上限算进去（16），否则"玩家残血时电脑低估威胁"。本计划把 `estimate_player_threat` 的伤害来源改为按 `conditional_damage` 的**最坏情况**取值（破甲 8、处决 16），并在测试里钉住。

## 与上一轮读数的衔接

上一轮存档（困难档 2400 局）：战士 62.9% / 法师 39.9% / 游侠 46.9%；游侠 VS 战士 27.6%。本轮读数照常存档、只看不调；处决从"可复用"变"一次性"预期让游侠再弱一点，8/16 的补偿对冲一部分——具体以数据为准，留给平衡调整轮。

## Global Constraints

- **不改其他数值**：除处决外，`CARDS` / `HEROES` 一个数字不动；`HERO_DECKS` 构成不变（仍 16 张）。
- **不改规则**：能量、抽牌、手牌上限、响应、装备、蓄力不动；只加"打出后移除"这一条牌属性。
- **守恒升级**：五区守恒断言替换现有四区断言（`tests/test_battle.py` 的 `assert_consistent`、`tests/test_catalog.py` 的按英雄断言）。
- **存档兼容**：旧存档（没有移除区）读出空列表且不报错。
- **卡牌属性与结算一致**：`exhaust` 标记来自 `EXHAUST_KEYS` 这一唯一来源，公开状态、结算、测试都从它取值，不得各自硬编码。

## Review Focus

- **洗牌安全**：抽牌堆空时 `draw_cards_for` 会把弃牌堆洗回抽牌堆——消耗牌**必须不在弃牌堆里**，写一条"移除的牌永不再现"的测试（跑到洗牌发生）。
- **响应与消耗的先后**：伤害牌在挂起响应前就结清费用与去向（现有行为），消耗牌挂起时也应已进移除区；写一条"被闪避的消耗牌同样移除"的测试。
- **威胁估算的边界**：玩家残血（<30%）时威胁上界应为 16（处决）；满血时为 14（火球）。
- **AI 一致性**：处决的评分仍走 `_effective_damage`（8/16），与结算一致。
- **公开状态**：`/api` 的卡表带 `exhaust` 标记；双方参与者带 `exhaust_pile`；契约与验收文档同步。

---

### Task 1: 消耗机制与移除区

- [ ] **Step 1: 写失败测试（`tests/test_catalog.py`、`tests/test_battle.py`）**

卡表：`EXHAUST_KEYS == {"execute"}`、处决数值 8/16；结算：打出消耗牌后它出现在 `exhaust_pile`、不在 `discard_pile`；被闪避照样移除；抽牌堆抽空洗牌后移除的牌不再出现；五区守恒。

- [ ] **Step 2: 实现**（`catalog.EXHAUST_KEYS`、`models.exhaust_pile`、`battle.play_card_for` 分流与序列化）

- [ ] **Step 3: 提交**

```bash
git add game/catalog.py game/models.py game/battle.py tests/
git commit -m "feat: exhaust spent cards from the battle"
```

### Task 2: 威胁估算、AI 与公开状态

- [ ] **Step 4: 写失败测试（`tests/test_ai.py`、`tests/test_api.py`）**

威胁上界：玩家残血 16 / 满血 14；处决评分与结算一致（8/16）；卡表带 `exhaust`；公开状态双方带 `exhaust_pile`；只改隐藏手牌不影响。

- [ ] **Step 5: 实现**（`estimate_player_threat` 最坏情况取条件上限、`public_state` 输出）

- [ ] **Step 6: 提交**

```bash
git add game/ai.py game/public_state.py tests/ docs/api-contract.md
git commit -m "feat: publish exhaust information and price it into threats"
```

### Task 3: 文档与读数存档

- [ ] **Step 7: 同步文档**

`README.md`（处决 8/16 + 消耗说明）、`docs/interaction-design.md`（卡表 + 伤害/牌区规则 + AI 章节）、`docs/claude-builder/acceptance.md`（消耗验收项）、`docs/api-contract.md`（`exhaust` 与 `exhaust_pile`）、路线文档（第六优先标记完成）。

- [ ] **Step 8: 三档读数存档（只看不调）**

- [ ] **Step 9: 跑门禁并提交**

```bash
python -X utf8 -m compileall -q app.py api_routes.py demo_routes.py web_support.py game && ruff check . && ruff format --check . && pytest -q
```

---

## 验收记录（Task 1–3）

- 实际改动文件：`game/catalog.py`（`EXHAUST_KEYS`、处决 8）、`game/models.py`（`exhaust_pile`）、`game/battle.py`（去向分流、序列化）、`game/ai.py`（`_worst_case_damage`、威胁按当前局面展开）、`game/public_state.py`（`exhaust` 标记、移除区公开）、`api_routes.py`（卡表接口），以及 4 个测试文件与 6 份文档。
- 实现要点：
  - 打出消耗牌进入 `exhaust_pile`（第五个牌区），洗牌永不复现；被闪避照样移除（费用与去向在挂起前结清）。
  - 守恒不变量升级为五区；`test_exhausted_cards_never_come_back_when_the_discard_pile_is_shuffled` 覆盖洗牌路径。
  - 威胁上界改为按**对手当前公开状态**展开条件伤害：满血时处决是 8（上界仍是火球 14），残血时处决 16（新上界）。
  - `/api/cards` 与公开状态里的卡牌定义都带 `exhaust`；双方公开 `exhaust_pile`。
- 门禁：`compileall` / `ruff check .` / `ruff format --check .` / `pytest -q` **266 passed**（本轮前 257，新增 9）。
- 实施中修正的两处口径：
  1. 威胁上界最初写成"无条件取满"（处决永远 16），会让满血局也高估；改成按对手当前护盾 / 生命展开，测试钉住"满血 14 / 残血 16"。
  2. "处决在斩杀区评分更高"的对照场景改用 50% 生命——原用 33%，8 伤恰好也构成击杀，混入击杀奖励后无法对照。
- **三档读数存档**（2400 局/档）：

  | 难度 | 战士 | 法师 | 游侠 | 游侠 VS 战士 | 处决使用量 |
  |---|---|---|---|---|---|
  | 困难 | 61.3% | 39.0% | 49.4% | 32.3% | 738 |
  | 中等 | 60.9% | 40.5% | 48.4% | 31.9% | 681 |
  | 简单 | 60.4% | 39.6% | 49.7% | 34.3% | 694 |

  对照上一轮（困难档）：战士 62.9% / 法师 39.9% / 游侠 46.9%，游侠 VS 战士 27.6%，处决 687 次。
- **变化归因（平衡调整轮的输入）**：
  1. **游侠明显回升**（对战士 27.6% → 32.3%）：8/16 的数值补偿强度超过"一局一次"的削弱，处决使用量升到 738（评分更高、更常被选中）。
  2. 战士与法师各滑 1~2 点：对手变强的零和结果。
  3. "消耗"的体验目标达成：处决从"可循环资源"变成"一局一次的关键一击"。
- 结束状态：留牌策略（消耗机制）落地并通过全量测试与读数存档；路线图上的玩法项到此全部完成，下一步进入平衡调整轮。

## Completion Criteria

- 打出的消耗牌从本局移除：不进弃牌堆、洗牌不再出现、被闪避照样移除；五区守恒成立。
- 处决为 8/16；其余卡牌与英雄数值零改动。
- 威胁上界在玩家残血时为 16、满血时为 14。
- 公开状态与契约带 `exhaust` 标记与 `exhaust_pile`；旧存档读出空移除区。
- 全量测试、ruff、compileall 全绿；三档读数存档并写明变化。
- **本轮不做**：延迟强化、给处决以外的牌加消耗、平衡数值调整、前端素材。
