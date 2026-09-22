import random
from dataclasses import dataclass, replace
from typing import Literal

from game.catalog import (
    CARDS,
    EQUIP_SLOTS,
    HEROES,
    LONGSWORD_BOOST_KEYS,
    SKILL_COST,
    STARTING_ENERGY,
    conditional_damage,
)
from game.models import AIDifficulty, CardDefinition, HeroDefinition, PendingAttack

# 闪避只能在响应时机使用，不进入主动出牌候选。
ENEMY_UNUSABLE_EFFECTS = frozenset({"dodge"})

LETHAL_BONUS = 1000.0
EFFICIENCY_WEIGHT = 0.5
PASS_SCORE = 0.5
# 手里留着闪避时，最后 1 点能量的价值高于任何低收益动作。
DODGE_HOLD_BONUS = 3.0
# 削掉护盾是通往击杀的进度，但本身不扣血，所以单价明显低于真实伤害；
# 若记 0 分，电脑面对高护盾玩家会永远选择空过，直接放弃获胜。
SHIELD_BREAK_WEIGHT = 0.4
SHIELD_SCALE = 12.0
# 平方增长：失血越多，治疗与护盾的边际价值上升越快，濒死时自然转向自保。
RISK_WEIGHT = 6.0
# 武器一回合只加成一次，手里再多能吃加成的牌也只按两张计价。
WEAPON_EATERS_PER_TURN = 2
# 困难模式发现玩家下回合能击杀自己时，对非防御行动的扣分。
DANGER_PENALTY = 100.0
# 蓄力（1 费换下回合 +2 能量）的估值：草案固定值，与护盾牌同档，平衡轮再校准。
CHARGE_SCORE = 6.0

DEFENSIVE_EFFECTS = frozenset({"shield", "heal"})

# 技能按等效卡牌参与评分：护盾类算护盾牌，其余（含伤害加抽牌）算伤害牌。
SKILL_EFFECT_TYPES = {"shield": "shield", "damage": "damage", "damage_draw": "damage"}

DIFFICULTY_SELECTION: dict[AIDifficulty, tuple[float, ...]] = {
    AIDifficulty.EASY: (0.60, 0.25, 0.15),
    AIDifficulty.MEDIUM: (0.88, 0.12),
}

# 伤害连招规划深度：简单不规划、中等看一手、困难规划到打光。
# 能量上限 3，最深序列是三张 1 费牌，深度 3 已经覆盖全部可达序列。
PLANNING_DEPTH: dict[AIDifficulty, int] = {
    AIDifficulty.EASY: 0,
    AIDifficulty.MEDIUM: 1,
    AIDifficulty.HARD: 3,
}


@dataclass(frozen=True)
class PublicParticipantState:
    """牌桌上一方看得见的状态：血条、护盾、能量、英雄，以及身上的装备。

    手牌、抽牌堆以及它们的顺序都不在这里——它们不属于公开信息；装备挂在
    角色身上是谁都看得见的东西，所以它属于这一侧。
    """

    hero_key: str
    max_hp: int
    hp: int
    shield: int
    energy: int
    skill_used_this_turn: bool
    weapon_key: str | None = None
    armor_key: str | None = None
    weapon_used_this_turn: bool = False
    armor_used_this_turn: bool = False
    bonus_energy_next_turn: int = 0


@dataclass(frozen=True)
class AIObservation:
    """电脑一次决策能拿到的全部信息。

    除自己的手牌外，其余每一项都是牌面上公开的东西：对手手牌和抽牌堆不在
    这里，也没有任何字段能反推出它们。待响应攻击（打出的牌、伤害值）是明牌，
    所以可以放进来。
    """

    self_state: PublicParticipantState
    opponent_state: PublicParticipantState
    own_hand: tuple[dict, ...]
    public_discard_keys: tuple[str, ...]
    catalog_keys: tuple[str, ...]
    pending_attack: PendingAttack | None = None


@dataclass(frozen=True)
class ActionCandidate:
    kind: Literal["card", "skill", "dodge", "pass"]
    card_id: str | None = None
    card_key: str | None = None
    score: float = 0.0


@dataclass(frozen=True)
class EnemyIntent:
    """电脑"下回合第一个动作"的预估：给玩家看的计划，不是承诺。"""

    kind: Literal["attack", "defend", "heal", "equip", "pass"]
    source: Literal["card", "skill", "none"]
    name: str | None
    value: int
    text: str


def get_available_enemy_actions(observation: AIObservation) -> list[ActionCandidate]:
    own = observation.self_state
    candidates = [
        ActionCandidate(kind="card", card_id=card["id"], card_key=card["key"])
        for card in observation.own_hand
        if CARDS[card["key"]].effect_type not in ENEMY_UNUSABLE_EFFECTS
        and CARDS[card["key"]].cost <= own.energy
    ]
    if not own.skill_used_this_turn and own.energy >= SKILL_COST:
        candidates.append(ActionCandidate(kind="skill"))
    candidates.append(ActionCandidate(kind="pass"))
    return candidates


def _skill_as_card(hero: HeroDefinition) -> CardDefinition:
    return CardDefinition(
        key=hero.key,
        name=hero.skill_name,
        cost=SKILL_COST,
        effect_type=SKILL_EFFECT_TYPES[hero.skill_type],
        value=hero.skill_value,
    )


def _definition_of(
    observation: AIObservation, candidate: ActionCandidate
) -> CardDefinition | None:
    if candidate.kind == "card":
        return CARDS[candidate.card_key]
    if candidate.kind == "skill":
        return _skill_as_card(HEROES[observation.self_state.hero_key])
    return None


def _risk_multiplier(public_state: PublicParticipantState) -> float:
    missing_ratio = 1 - public_state.hp / public_state.max_hp
    return 1 + missing_ratio**2 * RISK_WEIGHT


def score_damage(observation: AIObservation, definition: CardDefinition) -> float:
    # 超出剩余生命的部分完全浪费；打在护盾上的部分只算削盾价值，不算生命威胁。
    opponent = observation.opponent_state
    damage = _effective_damage(observation, definition)
    absorbed = min(damage, opponent.shield)
    effective = damage - absorbed
    useful = min(effective, opponent.hp)
    score = useful + useful / definition.cost * EFFICIENCY_WEIGHT
    score += absorbed * SHIELD_BREAK_WEIGHT
    if effective >= opponent.hp:
        score += LETHAL_BONUS
    return score


def _effective_damage(observation: AIObservation, definition: CardDefinition) -> int:
    """这一击真实会打出的伤害：条件加成与武器加成，口径与结算完全一致。

    条件（破甲看护盾、处决看斩杀线）走 `conditional_damage()` 这个唯一入口；
    武器一回合只加一次，用掉之后评分也跟着回落。
    """
    opponent = observation.opponent_state
    damage = conditional_damage(
        definition.value,
        definition.key,
        target_shield=opponent.shield,
        target_hp=opponent.hp,
        target_max_hp=opponent.max_hp,
    )
    own = observation.self_state
    if (
        own.weapon_key is None
        or own.weapon_used_this_turn
        or definition.key not in LONGSWORD_BOOST_KEYS
    ):
        return damage
    return damage + CARDS[own.weapon_key].value


def score_equip(observation: AIObservation, definition: CardDefinition) -> float:
    """装备的收益跨回合，按它眼下能兑现多少价值定价。

    武器按手里还有几张吃加成的牌算，封顶两张——一回合只触发一次，再多也吃不完；
    护甲按"减伤值 × 当前失血风险"算，与治疗、护盾共用同一个风险系数。
    """
    if EQUIP_SLOTS[definition.key] == "weapon":
        eaters = sum(
            1 for card in observation.own_hand if card["key"] in LONGSWORD_BOOST_KEYS
        )
        return min(eaters, WEAPON_EATERS_PER_TURN) * definition.value
    return definition.value * _risk_multiplier(observation.self_state)


def score_charge(observation: AIObservation, definition: CardDefinition) -> float:
    """蓄力：把 1 点能量换成下回合的更多能量。

    它是投资牌，价值随局面漂移很大，先给固定分（与护盾牌同档），
    保证"有蓄力就用"不会输给空过；精确校准留给平衡调整轮。
    """
    return CHARGE_SCORE


def score_heal(observation: AIObservation, definition: CardDefinition) -> float:
    own = observation.self_state
    restored = min(definition.value, own.max_hp - own.hp)
    return restored * _risk_multiplier(own)


def score_shield(observation: AIObservation, definition: CardDefinition) -> float:
    # 已有护盾越多，继续叠盾的边际收益越低。
    own = observation.self_state
    diminishing = 1 + own.shield / SHIELD_SCALE
    return definition.value / diminishing * _risk_multiplier(own)


def _holds_the_last_dodge_energy(observation: AIObservation) -> bool:
    """手里有闪避、能量又只够再打一张牌：再花掉就没法闪避了。"""
    if observation.self_state.energy > CARDS["dodge"].cost:
        return False
    return any(card["key"] == "dodge" for card in observation.own_hand)


def score_pass(observation: AIObservation, difficulty: AIDifficulty) -> float:
    # 高于任何零收益动作，低于任何有正收益的动作。
    if difficulty is AIDifficulty.EASY:
        return PASS_SCORE
    if _holds_the_last_dodge_energy(observation):
        return PASS_SCORE + DODGE_HOLD_BONUS
    return PASS_SCORE


def _base_score(
    observation: AIObservation, candidate: ActionCandidate, difficulty: AIDifficulty
) -> float:
    if candidate.kind == "pass":
        return score_pass(observation, difficulty)
    definition = _definition_of(observation, candidate)
    if definition.effect_type == "damage":
        return score_damage(observation, definition)
    if definition.effect_type == "heal":
        return score_heal(observation, definition)
    if definition.effect_type == "shield":
        return score_shield(observation, definition)
    if definition.effect_type == "equip":
        return score_equip(observation, definition)
    if definition.effect_type == "charge":
        return score_charge(observation, definition)
    return 0.0


def _worst_case_damage(
    definition: CardDefinition, opponent: PublicParticipantState
) -> int:
    """按对手当前的公开状态，这张伤害牌最狠能打多少。

    条件牌按"现在打"的口径展开：对手有盾时破甲就是 8、对手已在斩杀区时
    处决就是 16——上界跟着局面走，而不是无条件取满。
    """
    return conditional_damage(
        definition.value,
        definition.key,
        target_shield=opponent.shield,
        target_hp=opponent.hp,
        target_max_hp=opponent.max_hp,
    )


def estimate_player_threat(observation: AIObservation) -> int:
    """玩家下回合能打出的最高单体伤害，只用公开信息取一个最坏值。

    公开牌表里买得起的伤害牌一律算作可能，再加上玩家英雄的伤害技能；他手里
    究竟有哪张牌不看。公开弃牌记录也不参与：抽牌堆抽空时弃牌会洗回去，"这张
    已经打掉了"并不能排除它下回合回到玩家手上，拿它收窄上界会低估威胁。
    玩家的技能次数在轮到自己时会重置，所以这里按"下回合可用"计；自己身上的铁甲
    同理，本回合还没用掉的就按能挡下 2 点算。
    """
    opponent = observation.opponent_state
    hero = HEROES[opponent.hero_key]
    # 每张伤害牌按"公开信息下能打出的最高伤害"取上界：条件牌按最有利的分支
    # 展开（处决在斩杀区是 16，已经超过火球 14），不留低估的口子。
    threats = [
        _worst_case_damage(CARDS[key], opponent)
        for key in observation.catalog_keys
        if CARDS[key].effect_type == "damage" and CARDS[key].cost <= STARTING_ENERGY
    ]
    if SKILL_EFFECT_TYPES.get(hero.skill_type) == "damage":
        threats.append(hero.skill_value)
    return _after_own_armor(observation.self_state, max(threats, default=0))


def _after_own_armor(own: PublicParticipantState, damage: int) -> int:
    if own.armor_key is None or own.armor_used_this_turn:
        return damage
    return max(0, damage - CARDS[own.armor_key].value)


def _survivable_hp_after(observation: AIObservation, candidate: ActionCandidate) -> int:
    own = observation.self_state
    hp = own.hp
    shield = own.shield
    definition = _definition_of(observation, candidate)
    if definition is not None:
        if definition.effect_type == "shield":
            shield += definition.value
        elif definition.effect_type == "heal":
            hp = min(own.max_hp, hp + definition.value)
    return hp + shield


def hard_lookahead_adjustment(
    observation: AIObservation, candidate: ActionCandidate
) -> float:
    """只做一步估算：玩家下回合是否可能击杀自己。不执行动作、不递归模拟。"""
    threat = estimate_player_threat(observation)
    if threat <= 0:
        return 0.0
    if _survivable_hp_after(observation, candidate) > threat:
        return 0.0
    definition = _definition_of(observation, candidate)
    if definition is not None and definition.effect_type in DEFENSIVE_EFFECTS:
        return 0.0
    return -DANGER_PENALTY


def _tactical_score(
    observation: AIObservation, candidate: ActionCandidate, difficulty: AIDifficulty
) -> float:
    """单张战术分：基础评分 + 困难模式的一步生存前瞻；不含伤害连招规划。"""
    score = _base_score(observation, candidate, difficulty)
    if difficulty is AIDifficulty.HARD:
        score += hard_lookahead_adjustment(observation, candidate)
    return score


def _is_damage_action(observation: AIObservation, candidate: ActionCandidate) -> bool:
    definition = _definition_of(observation, candidate)
    return definition is not None and definition.effect_type == "damage"


def _plans_sequence(observation: AIObservation, candidate: ActionCandidate) -> bool:
    """参与连招规划的动作：伤害牌本身，以及能提升伤害的武器。

    护盾、治疗、护甲不产生伤害，不参与规划：它们的价值跨回合，
    塞进"本回合剩余能量"会诱导 AI 用它们填满资源来刷分。
    """
    definition = _definition_of(observation, candidate)
    if definition is None:
        return False
    if definition.effect_type == "damage":
        return True
    return definition.effect_type == "equip" and EQUIP_SLOTS[definition.key] == "weapon"


def _after_action(
    observation: AIObservation, candidate: ActionCandidate
) -> AIObservation | None:
    """把候选模拟执行成一份新的观察视图；pass 或打不出的动作返回 None。

    纯查询：只在不可变快照上替换字段，不触碰真实对局，也不引入新的信息。
    """
    own = observation.self_state
    if candidate.kind == "pass":
        return None
    if candidate.kind == "skill":
        return replace(
            observation,
            self_state=replace(
                own,
                energy=own.energy - SKILL_COST,
                skill_used_this_turn=True,
            ),
        )
    card = CARDS[candidate.card_key]
    if card.cost > own.energy:
        return None
    updates: dict[str, object] = {"energy": own.energy - card.cost}
    if card.effect_type == "equip":
        updates[EQUIP_SLOTS[card.key] + "_key"] = card.key
    elif (
        card.key in LONGSWORD_BOOST_KEYS
        and own.weapon_key is not None
        and not own.weapon_used_this_turn
    ):
        updates["weapon_used_this_turn"] = True
    hand = tuple(c for c in observation.own_hand if c["id"] != candidate.card_id)
    return replace(
        observation,
        self_state=replace(own, **updates),
        own_hand=hand,
    )


def _best_damage_value(
    observation: AIObservation,
    difficulty: AIDifficulty,
    remaining: int,
    boost_keys: frozenset[str] | None = None,
) -> float:
    """剩余资源还能兑现的最优伤害序列总价值。

    只遍历伤害牌与伤害技能。boost_keys 不为 None 时只统计其中的牌：
    武器只对它能加成的伤害负责，否则与武器无关的伤害也会被算进它的账上，
    "长剑配火球"会被误判成值得先穿剑。
    """
    if remaining <= 0:
        return 0.0
    best = 0.0
    for action in get_available_enemy_actions(observation):
        if not _is_damage_action(observation, action):
            continue
        if boost_keys is not None and action.card_key not in boost_keys:
            continue
        after = _after_action(observation, action)
        if after is None:
            continue
        value = _tactical_score(observation, action, difficulty)
        value += _best_damage_value(after, difficulty, remaining - 1, boost_keys)
        if value > best:
            best = value
    return best


def score_enemy_action(
    observation: AIObservation, candidate: ActionCandidate, difficulty: AIDifficulty
) -> float:
    """候选评分 = 战术分 + 伤害连招价值（按难度分层，简单难度不规划）。"""
    score = _tactical_score(observation, candidate, difficulty)
    depth = PLANNING_DEPTH.get(difficulty, 0)
    if depth <= 0 or not _plans_sequence(observation, candidate):
        return score
    after = _after_action(observation, candidate)
    if after is None:
        return score
    definition = _definition_of(observation, candidate)
    boost_keys = (
        LONGSWORD_BOOST_KEYS
        if definition is not None and definition.effect_type == "equip"
        else None
    )
    return score + _best_damage_value(after, difficulty, depth, boost_keys)


def score_dodge(observation: AIObservation) -> float:
    """电脑闪避这次攻击值多少分：救下护盾吸收之后真会掉的生命。

    伤害口径和结算保持一致：自己的铁甲先削 2 点，护盾再吸，剩下的才算救回来。
    """
    pending = observation.pending_attack
    own = observation.self_state
    incoming = _after_own_armor(own, pending.damage)
    absorbed = min(own.shield, incoming)
    saved = min(incoming - absorbed, own.hp)
    if saved <= 0:
        return 0.0
    return saved * _risk_multiplier(own)


def rank_enemy_responses(
    observation: AIObservation, difficulty: AIDifficulty
) -> list[ActionCandidate]:
    """响应窗口里电脑只有两个合法动作；分数与出牌共用同一套评分口径。"""
    candidates = [
        ActionCandidate(kind="dodge", score=score_dodge(observation)),
        ActionCandidate(kind="pass", score=score_pass(observation, difficulty)),
    ]
    return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)


def rank_enemy_actions(
    observation: AIObservation, difficulty: AIDifficulty
) -> list[ActionCandidate]:
    scored = [
        replace(candidate, score=score_enemy_action(observation, candidate, difficulty))
        for candidate in get_available_enemy_actions(observation)
    ]
    return sorted(scored, key=lambda candidate: candidate.score, reverse=True)


def _weighted_pick(
    ranked: list[ActionCandidate], difficulty: AIDifficulty, rng
) -> ActionCandidate:
    weights = DIFFICULTY_SELECTION.get(difficulty)
    if weights is None:
        return ranked[0]
    pool = ranked[: len(weights)]
    return rng.choices(pool, weights=weights[: len(pool)], k=1)[0]


def _select(
    ranked: list[ActionCandidate], difficulty: AIDifficulty, rng
) -> ActionCandidate:
    # 比空过更强的动作才参与抽取：简单难度可以选得差，但不该浪费整个回合不做任何事。
    # 战略空过（留能量闪避）分数高于 PASS_SCORE，靠评分自然进池，不是被塞进去的。
    usable = [candidate for candidate in ranked if candidate.score > PASS_SCORE]
    if not usable:
        return ranked[0]
    return _weighted_pick(usable, difficulty, rng)


def select_enemy_action(
    observation: AIObservation, difficulty: AIDifficulty, rng: random.Random
) -> ActionCandidate:
    return _select(rank_enemy_actions(observation, difficulty), difficulty, rng)


def _next_turn_observation(observation: AIObservation) -> AIObservation:
    """预演"自己的下个回合开始"：结算蓄力结余、回满能量、重置技能与装备标记。"""
    own = observation.self_state
    return replace(
        observation,
        self_state=replace(
            own,
            energy=STARTING_ENERGY + own.bonus_energy_next_turn,
            bonus_energy_next_turn=0,
            skill_used_this_turn=False,
            weapon_used_this_turn=False,
            armor_used_this_turn=False,
        ),
    )


def estimate_enemy_intent(
    observation: AIObservation, difficulty: AIDifficulty
) -> EnemyIntent:
    """预估电脑下回合的第一个动作，给玩家看的"计划"。

    纯查询 + 确定性：把电脑的资源按"下回合开始"预演（能量回满、蓄力结余、
    技能与装备标记重置），用同一套候选与评分排出第一名。不消耗对局 RNG、
    不修改任何状态；它下回合抽到的牌未知，所以按当前手牌预估——它是计划，
    不是承诺。
    """
    next_turn = _next_turn_observation(observation)
    candidate = rank_enemy_actions(next_turn, difficulty)[0]
    return _intent_from_candidate(next_turn, candidate)


def _intent_from_candidate(
    observation: AIObservation, candidate: ActionCandidate
) -> EnemyIntent:
    if candidate.kind == "pass":
        return EnemyIntent(
            kind="pass", source="none", name=None, value=0, text="预计按兵不动"
        )
    definition = _definition_of(observation, candidate)
    source: Literal["card", "skill"] = "skill" if candidate.kind == "skill" else "card"
    if definition.effect_type == "damage":
        damage = _effective_damage(observation, definition)
        return EnemyIntent(
            kind="attack",
            source=source,
            name=definition.name,
            value=damage,
            text=f"预计使用【{definition.name}】造成 {damage} 点伤害",
        )
    if definition.effect_type == "shield":
        return EnemyIntent(
            kind="defend",
            source=source,
            name=definition.name,
            value=definition.value,
            text=f"预计使用【{definition.name}】获得 {definition.value} 点护盾",
        )
    if definition.effect_type == "heal":
        return EnemyIntent(
            kind="heal",
            source=source,
            name=definition.name,
            value=definition.value,
            text=f"预计使用【{definition.name}】恢复 {definition.value} 点生命值",
        )
    return EnemyIntent(
        kind="equip",
        source=source,
        name=definition.name,
        value=definition.value,
        text=f"预计装备【{definition.name}】",
    )


def choose_enemy_response(
    observation: AIObservation, difficulty: AIDifficulty, rng: random.Random
) -> ActionCandidate:
    """电脑作为防御方的闪避 / 放弃选择。

    复用出牌的难度配置与评分，但不套用"别浪费整个回合"的过滤：
    放弃响应只是挨这一下，闪避牌还留在手里，本身就是合法选择。
    反过来要滤掉零收益的闪避：这一下全被护盾吃掉时闪避救不回任何生命，
    难度权重不该让它白扔 1 点能量和一张闪避牌——简单难度可以选得差，
    但不该浪费手里的资源，和出牌侧"不浪费整个回合"是同一个原则。
    """
    ranked = rank_enemy_responses(observation, difficulty)
    usable = [
        candidate
        for candidate in ranked
        if candidate.kind == "pass" or candidate.score > 0.0
    ]
    return _weighted_pick(usable, difficulty, rng)
