import random
import uuid

from game.ai import (
    AIObservation,
    PublicParticipantState,
    choose_enemy_response,
    select_enemy_action,
)
from game.catalog import (
    CARDS,
    CATALOG_KEYS,
    EQUIP_SLOTS,
    EXHAUST_KEYS,
    HERO_DECKS,
    HEROES,
    LONGSWORD_BOOST_KEYS,
    SKILL_COST,
    STARTING_ENERGY,
    conditional_damage,
)
from game.models import (
    AIDifficulty,
    ActionResult,
    BattlePhase,
    CardDefinition,
    Combatant,
    HeroDefinition,
    ParticipantState,
    PendingAttack,
    Side,
)

HAND_LIMIT = 6
STARTING_HAND = 5
ROUND_LIMIT = 10
ENEMY_NAME = "电脑"
# 旧 session 缺少电脑英雄信息时使用的默认英雄，见 _migrate_legacy_participants()。
LEGACY_ENEMY_HERO_KEY = "warrior"

OPPONENT_SIDE = {Side.PLAYER: Side.ENEMY, Side.ENEMY: Side.PLAYER}
TURN_PHASE = {Side.PLAYER: BattlePhase.PLAYER_TURN, Side.ENEMY: BattlePhase.ENEMY_TURN}
SIDE_PHASE = {phase: side for side, phase in TURN_PHASE.items()}
# 日志措辞沿用既有文案：玩家出手不写主语，受击写"你"；电脑出手写"电脑"。
ACTOR_LABEL = {Side.PLAYER: "", Side.ENEMY: "电脑"}
HIT_LABEL = {Side.PLAYER: "电脑", Side.ENEMY: "你"}
# 回合交接和闪避响应都用完整称呼，玩家一侧也显式写"玩家"。
SIDE_LABEL = {Side.PLAYER: "玩家", Side.ENEMY: "电脑"}

# 双人热座：日志是两边共享的一份，称呼必须中性——"你 / 电脑"对其中一方总是错的。
# 座位 player 记为玩家1，座位 enemy 记为玩家2，两侧读数一致。
PVP_ACTOR_LABEL = {Side.PLAYER: "玩家1", Side.ENEMY: "玩家2"}
PVP_HIT_LABEL = {Side.PLAYER: "玩家2", Side.ENEMY: "玩家1"}
PVP_SIDE_LABEL = {Side.PLAYER: "玩家1", Side.ENEMY: "玩家2"}

PVE_MODE = "pve"
PVP_MODE = "pvp"


def choose_enemy_hero(rng: random.Random) -> HeroDefinition:
    """电脑从不依赖玩家英雄进行反选，只用一个 RNG 从同一英雄池里抽。"""
    return rng.choice(list(HEROES.values()))


def _shuffled_deck(rng: random.Random, keys: list[str]) -> list[str]:
    deck = list(keys)
    rng.shuffle(deck)
    return deck


def _zone_alias(side: Side, attribute: str):
    """过渡期别名：把旧的扁平字段名映射到对应参与者的分区。"""

    def getter(self):
        return getattr(self.participants[side], attribute)

    def setter(self, value):
        setattr(self.participants[side], attribute, value)

    return property(getter, setter)


class BattleState:
    hand = _zone_alias(Side.PLAYER, "hand")
    draw_pile = _zone_alias(Side.PLAYER, "draw_pile")
    discard_pile = _zone_alias(Side.PLAYER, "discard_pile")
    enemy_hand = _zone_alias(Side.ENEMY, "hand")
    enemy_draw_pile = _zone_alias(Side.ENEMY, "draw_pile")
    enemy_discard_pile = _zone_alias(Side.ENEMY, "discard_pile")
    skill_used_this_turn = _zone_alias(Side.PLAYER, "skill_used_this_turn")
    enemy_skill_used_this_turn = _zone_alias(Side.ENEMY, "skill_used_this_turn")

    def __init__(
        self,
        participants: dict[Side, ParticipantState],
        round_number: int,
        phase: BattlePhase,
        log: list[str],
        pending_attack: PendingAttack | None = None,
        rng: random.Random | None = None,
        ai_difficulty: AIDifficulty = AIDifficulty.MEDIUM,
        starting_side: Side = Side.PLAYER,
        mode: str = PVE_MODE,
    ) -> None:
        self.participants = participants
        self.round_number = round_number
        self.phase = phase
        self.log = log
        self.pending_attack = pending_attack
        self.rng = rng or random.Random()
        self.ai_difficulty = ai_difficulty
        self.starting_side = starting_side
        self.mode = mode

    def is_human_side(self, side: Side) -> bool:
        """这个座位由真人操作吗：人机模式只有玩家一侧，双人模式两边都是。"""
        return self.mode == PVP_MODE or side is Side.PLAYER

    def actor_label(self, side: Side) -> str:
        """出手方在日志里的称呼；双人模式用中性的"玩家1/玩家2"。"""
        return (PVP_ACTOR_LABEL if self.mode == PVP_MODE else ACTOR_LABEL)[side]

    def hit_label(self, side: Side) -> str:
        """被打方在日志里的称呼。"""
        return (PVP_HIT_LABEL if self.mode == PVP_MODE else HIT_LABEL)[side]

    def side_label(self, side: Side) -> str:
        """整句称呼（回合交接、结算宣告用）。"""
        return (PVP_SIDE_LABEL if self.mode == PVP_MODE else SIDE_LABEL)[side]

    def participant(self, side: Side) -> ParticipantState:
        return self.participants[side]

    def opponent_of(self, side: Side) -> ParticipantState:
        return self.participants[OPPONENT_SIDE[side]]

    @property
    def hero(self) -> HeroDefinition:
        return self.participants[Side.PLAYER].hero

    @property
    def enemy_hero(self) -> HeroDefinition:
        return self.participants[Side.ENEMY].hero

    @property
    def player(self) -> Combatant:
        return self.participants[Side.PLAYER].combatant

    @property
    def enemy(self) -> Combatant:
        return self.participants[Side.ENEMY].combatant

    @classmethod
    def create(
        cls,
        hero_key: str,
        rng: random.Random,
        ai_difficulty: AIDifficulty = AIDifficulty.MEDIUM,
        starting_side: Side | None = None,
        *,
        mode: str = PVE_MODE,
        opponent_hero_key: str | None = None,
    ) -> "BattleState":
        hero = HEROES[hero_key]
        # 双人模式里对位英雄由玩家2 选定（可选）；人机模式沿用随机抽取。
        enemy_hero = (
            HEROES[opponent_hero_key]
            if opponent_hero_key is not None
            else choose_enemy_hero(rng)
        )
        first_side = starting_side or rng.choice(list(Side))
        state = cls(
            participants={
                Side.PLAYER: ParticipantState(
                    hero=hero,
                    combatant=Combatant(
                        name=hero.name, max_hp=hero.max_hp, hp=hero.max_hp
                    ),
                    hand=[],
                    draw_pile=_shuffled_deck(rng, HERO_DECKS[hero.key]),
                    discard_pile=[],
                ),
                Side.ENEMY: ParticipantState(
                    hero=enemy_hero,
                    combatant=Combatant(
                        # 双人模式对面也是真人：用英雄名（与玩家侧对称）；
                        # 人机模式保持"电脑"，明示对手是 AI。
                        name=enemy_hero.name if mode == PVP_MODE else ENEMY_NAME,
                        max_hp=enemy_hero.max_hp,
                        hp=enemy_hero.max_hp,
                    ),
                    hand=[],
                    draw_pile=_shuffled_deck(rng, HERO_DECKS[enemy_hero.key]),
                    discard_pile=[],
                ),
            },
            round_number=1,
            phase=TURN_PHASE[first_side],
            log=[],
            rng=rng,
            ai_difficulty=ai_difficulty,
            starting_side=first_side,
            mode=mode,
        )
        if mode == PVP_MODE:
            state.log.append(f"战斗开始，玩家1选择角色：{hero.name}")
            state.log.append(f"玩家2选择角色：{enemy_hero.name}")
        else:
            state.log.append(f"战斗开始，玩家选择角色：{hero.name}")
            state.log.append(f"电脑选择角色：{enemy_hero.name}")
        for side in (Side.PLAYER, Side.ENEMY):
            state.draw_cards_for(side, STARTING_HAND)
        # 先手优势修正：先手方第 1 个回合只有 2 点能量（后手正常 3 点）。
        # 两条路径都在这一行覆盖——player 先手时它就是玩家看到的开局；
        # enemy 先手时它正好落在 create 内跑掉的那一回合上。
        state.participant(first_side).combatant.energy = STARTING_ENERGY - 1
        if first_side is Side.ENEMY and mode != PVP_MODE:
            # 电脑先手时在创建流程里把它这一回合推到"需要玩家决定的点"为止：
            # 要么回合跑完（返回玩家回合），要么停在响应窗口等调用方转交玩家。
            # 响应是玩家自己的决定，创建流程绝不替他放弃。
            # 双人热座没有电脑席位：先手是玩家2 时直接把 ENEMY_TURN 交给调用方。
            state.resolve_enemy_turn()
        return state

    def _new_card_id(self) -> str:
        return f"card-{uuid.uuid4().hex[:8]}"

    def draw_cards_for(self, side: Side, count: int) -> int:
        participant = self.participant(side)
        drawn = 0
        for _ in range(count):
            if len(participant.hand) >= HAND_LIMIT:
                self.log.append("手牌已满，本回合没有抽到新牌")
                break
            if not participant.draw_pile:
                if not participant.discard_pile:
                    break
                participant.draw_pile.extend(participant.discard_pile)
                participant.discard_pile.clear()
                self.rng.shuffle(participant.draw_pile)
            key = participant.draw_pile.pop()
            participant.hand.append({"id": self._new_card_id(), "key": key})
            drawn += 1
        return drawn

    def draw_cards(self, count: int) -> int:
        return self.draw_cards_for(Side.PLAYER, count)

    def apply_damage(self, target: Combatant, amount: int) -> int:
        if amount <= 0:
            return 0
        absorbed = min(target.shield, amount)
        target.shield -= absorbed
        remaining = amount - absorbed
        hp_before = target.hp
        target.hp = max(0, target.hp - remaining)
        return hp_before - target.hp

    def apply_heal(self, target: Combatant, amount: int) -> int:
        if amount <= 0:
            return 0
        before = target.hp
        target.hp = min(target.max_hp, target.hp + amount)
        return target.hp - before

    def _find_hand_index(self, hand: list[dict], card_instance_id: str) -> int:
        for i, c in enumerate(hand):
            if c["id"] == card_instance_id:
                return i
        return -1

    def _wrong_turn_message(self, side: Side) -> str:
        if self.mode == PVP_MODE:
            return "现在不是你的回合"
        if side is Side.PLAYER:
            return "现在是电脑回合，请等待电脑行动"
        return "现在不是电脑的回合"

    def play_card_for(self, side: Side, card_instance_id: str) -> ActionResult:
        if self.is_finished():
            return ActionResult(False, "本局已经结束，请重新开始")
        if self.current_side() is not side:
            return ActionResult(False, self._wrong_turn_message(side))
        participant = self.participant(side)
        index = self._find_hand_index(participant.hand, card_instance_id)
        if index == -1:
            return ActionResult(False, "这张卡牌已经不能使用")
        card = participant.hand[index]
        definition = CARDS[card["key"]]
        if definition.effect_type == "dodge":
            return ActionResult(False, "闪避只能在敌人攻击时使用")
        if participant.combatant.energy < definition.cost:
            shortage = definition.cost - participant.combatant.energy
            return ActionResult(False, f"能量不足，还差 {shortage} 点")
        participant.combatant.energy -= definition.cost
        participant.hand.pop(index)
        if definition.effect_type == "equip":
            # 装备是第四个牌区：留在槽里跨回合生效，不进弃牌堆。
            self._equip(participant, definition)
            self.log.append(self._format_card_log(side, definition))
            return ActionResult(True, "")
        if definition.key in EXHAUST_KEYS:
            # 消耗牌用掉即从本局移除：不进弃牌堆，洗牌也回不来。
            participant.exhaust_pile.append(definition.key)
        else:
            participant.discard_pile.append(definition.key)
        if definition.effect_type == "damage":
            # 费用与弃牌在挂起前就结清，响应窗口里只决定这次伤害落不落地。
            return self._open_response(side, definition)
        if definition.effect_type == "charge":
            # 蓄力没有即时效果：把能量记到下个自己的回合。
            participant.bonus_energy_next_turn += definition.value
        else:
            self._apply_card_effect(
                definition,
                source=participant.combatant,
                target=self.opponent_of(side).combatant,
            )
        self.log.append(self._format_card_log(side, definition))
        self._check_terminal()
        return ActionResult(True, "")

    def _equip(self, participant: ParticipantState, definition: CardDefinition) -> None:
        setattr(participant, EQUIP_SLOTS[definition.key], definition)

    def play_card(self, card_instance_id: str) -> ActionResult:
        return self.play_card_for(Side.PLAYER, card_instance_id)

    def _apply_card_effect(
        self,
        definition: CardDefinition,
        source: Combatant,
        target: Combatant,
    ) -> None:
        if definition.effect_type == "damage":
            self.apply_damage(target, definition.value)
        elif definition.effect_type == "shield":
            source.shield += definition.value
        elif definition.effect_type == "heal":
            self.apply_heal(source, definition.value)

    def _format_card_log(
        self, side: Side, definition: CardDefinition, dealt: int | None = None
    ) -> str:
        """`dealt` 只有伤害牌会用：长剑加成和铁甲减伤都改变真正落下的数字。"""
        actor = self.actor_label(side)
        if definition.effect_type == "damage":
            target = self.hit_label(side)
            amount = definition.value if dealt is None else dealt
            return f"{actor}使用【{definition.name}】，对{target}造成 {amount} 点伤害"
        if definition.effect_type == "shield":
            return f"{actor}使用【{definition.name}】，获得 {definition.value} 点护盾"
        if definition.effect_type == "heal":
            return f"{actor}使用【{definition.name}】，恢复 {definition.value} 点生命值"
        if definition.effect_type == "charge":
            return (
                f"{actor}使用【{definition.name}】，"
                f"下回合获得 {definition.value} 点额外能量"
            )
        return f"{actor}使用【{definition.name}】"

    def use_skill_for(self, side: Side) -> ActionResult:
        if self.is_finished():
            return ActionResult(False, "本局已经结束，请重新开始")
        if self.current_side() is not side:
            return ActionResult(False, self._wrong_turn_message(side))
        participant = self.participant(side)
        if participant.skill_used_this_turn:
            return ActionResult(False, "本回合技能已经使用过")
        if participant.combatant.energy < SKILL_COST:
            shortage = SKILL_COST - participant.combatant.energy
            return ActionResult(False, f"能量不足，还差 {shortage} 点")
        skill = participant.hero
        participant.combatant.energy -= SKILL_COST
        participant.skill_used_this_turn = True
        actor = self.actor_label(side)
        if skill.skill_type == "shield":
            participant.combatant.shield += skill.skill_value
            self.log.append(
                f"{actor}释放技能【{skill.skill_name}】，"
                f"获得 {skill.skill_value} 点护盾"
            )
        elif skill.skill_type == "damage":
            dealt = self._deal_damage(OPPONENT_SIDE[side], skill.skill_value)
            self.log.append(
                f"{actor}释放技能【{skill.skill_name}】，"
                f"对{self.hit_label(side)}造成 {dealt} 点伤害"
            )
        elif skill.skill_type == "damage_draw":
            dealt = self._deal_damage(OPPONENT_SIDE[side], skill.skill_value)
            drawn = self.draw_cards_for(side, 1)
            extra = "并抽取 1 张牌" if drawn else "但手牌已满，未抽到牌"
            self.log.append(
                f"{actor}释放技能【{skill.skill_name}】，"
                f"对{self.hit_label(side)}造成 {dealt} 点伤害，{extra}"
            )
        self._check_terminal()
        return ActionResult(True, "")

    def use_skill(self) -> ActionResult:
        return self.use_skill_for(Side.PLAYER)

    def _check_terminal(self) -> None:
        if self.enemy.hp <= 0:
            self.phase = BattlePhase.VICTORY
        elif self.player.hp <= 0:
            self.phase = BattlePhase.DEFEAT

    def _settle_round_limit(self) -> None:
        """打满回合上限的收尾：血多者胜，血同看护盾，两者都同才算平局。"""
        player_hp, enemy_hp = self.player.hp, self.enemy.hp
        player_shield, enemy_shield = self.player.shield, self.enemy.shield
        if player_hp != enemy_hp:
            player_wins, reason = player_hp > enemy_hp, "生命值更高"
        elif player_shield != enemy_shield:
            player_wins, reason = player_shield > enemy_shield, "护盾更厚"
        else:
            self.phase = BattlePhase.DRAW
            self.log.append(
                f"达到 {ROUND_LIMIT} 回合上限，双方生命值与护盾相同，本局平局"
            )
            return
        self.phase = BattlePhase.VICTORY if player_wins else BattlePhase.DEFEAT
        winner = self.side_label(Side.PLAYER if player_wins else Side.ENEMY)
        self.log.append(f"达到 {ROUND_LIMIT} 回合上限，{winner}{reason}，本局获胜")

    def current_side(self) -> Side | None:
        return SIDE_PHASE.get(self.phase)

    def start_turn(self, side: Side, *, initial: bool = False) -> None:
        """回合开始：回满能量并结算蓄力结余、重置技能与装备次数；首回合不额外补牌。"""
        participant = self.participant(side)
        participant.skill_used_this_turn = False
        participant.weapon_used_this_turn = False
        participant.armor_used_this_turn = False
        participant.combatant.energy = (
            STARTING_ENERGY + participant.bonus_energy_next_turn
        )
        participant.bonus_energy_next_turn = 0
        if not initial:
            self.draw_cards_for(side, 1)

    def advance_turn(self) -> ActionResult:
        side = self.current_side()
        if side is None:
            return ActionResult(False, "当前没有行动方")
        # 后手方打完才轮到先手方开新回合，所以 10 回合上限等于双方各行动 10 次。
        starts_new_round = side is not self.starting_side
        is_game_opening = side is self.starting_side and self.round_number == 1
        if starts_new_round and self.round_number >= ROUND_LIMIT:
            self._settle_round_limit()
            return ActionResult(True, "")
        next_side = OPPONENT_SIDE[side]
        if starts_new_round:
            self.round_number += 1
            self.log.append(f"第 {self.round_number} 回合开始")
        self.phase = TURN_PHASE[next_side]
        self.start_turn(next_side, initial=is_game_opening)
        return ActionResult(True, "")

    def end_turn_for(self, side: Side) -> ActionResult:
        if self.is_finished():
            return ActionResult(False, "本局已经结束，请重新开始")
        if self.current_side() is not side:
            return ActionResult(False, self._wrong_turn_message(side))
        next_actor = self.side_label(OPPONENT_SIDE[side])
        self.log.append(f"第 {self.round_number} 回合结束，{next_actor}开始行动")
        return self.advance_turn()

    def end_player_turn(self) -> ActionResult:
        return self.end_turn_for(Side.PLAYER)

    def resolve_enemy_turn(self) -> ActionResult:
        if self.is_finished():
            return ActionResult(False, "本局已经结束，请重新开始")
        if self.mode == PVP_MODE:
            return ActionResult(False, "双人模式下没有电脑回合")
        if self.phase is not BattlePhase.ENEMY_TURN:
            return ActionResult(False, "还没有进入电脑回合")
        return self._run_enemy_actions()

    def _run_enemy_actions(self) -> ActionResult:
        # 上限只是防止意外死循环，不是游戏规则：正常情况因无牌可打而结束回合。
        # 它是"每次续跑"的上限：攻击挂起后由 _finish_response() 重新进入本函数，
        # 计数从头开始。当前所有动作都消耗能量或牌，所以不会真的转圈。
        for _ in range(HAND_LIMIT + 1):
            if self.is_finished() or self.phase is BattlePhase.RESPONSE:
                # 攻击挂起等玩家响应时先收工，剩下的行动由 _finish_response() 续跑。
                return ActionResult(True, "")
            action = select_enemy_action(
                self.enemy_observation(), self.ai_difficulty, self.rng
            )
            if action.kind == "pass":
                break
            if action.kind == "skill":
                result = self.use_skill_for(Side.ENEMY)
            else:
                result = self.play_card_for(Side.ENEMY, action.card_id)
            if not result.ok:
                break
            self._check_terminal()
        return self._complete_enemy_turn()

    def _complete_enemy_turn(self) -> ActionResult:
        if self.is_finished():
            return ActionResult(True, "")
        self.log.append(f"第 {self.round_number} 回合结束，玩家开始行动")
        return self.advance_turn()

    def enemy_observation(self) -> AIObservation:
        """电脑一次决策能看到的全部信息，形如一道信息边界。

        对手的手牌与抽牌堆不进来：困难模式的一步前瞻只能靠公开牌表、公开弃牌
        记录和对手的公开能量估算威胁，看不到他手里握着哪一张。
        """
        return AIObservation(
            self_state=_public_participant(self.participant(Side.ENEMY)),
            opponent_state=_public_participant(self.participant(Side.PLAYER)),
            own_hand=tuple(dict(card) for card in self.enemy_hand),
            public_discard_keys=tuple(self.discard_pile),
            catalog_keys=CATALOG_KEYS,
            pending_attack=self.pending_attack,
        )

    def _find_dodge_index(self, side: Side) -> int:
        for index, card in enumerate(self.participant(side).hand):
            if card["key"] == "dodge":
                return index
        return -1

    def _has_available_dodge(self, side: Side) -> bool:
        dodge = CARDS["dodge"]
        return (
            self._find_dodge_index(side) != -1
            and self.participant(side).combatant.energy >= dodge.cost
        )

    def can_respond_dodge(self, side: Side) -> bool:
        """这个座位现在能不能用闪避响应挂起的攻击。"""
        pending = self.pending_attack
        return (
            self.phase is BattlePhase.RESPONSE
            and pending is not None
            and pending.defender is side
            and self._has_available_dodge(side)
        )

    def can_dodge(self) -> bool:
        """兼容旧调用：玩家一侧的闪避可用性（人机页面长期只问这一个座位）。"""
        return self.can_respond_dodge(Side.PLAYER)

    def respond_for(self, side: Side, action: str) -> ActionResult:
        if self.is_finished():
            return ActionResult(False, "本局已经结束，请重新开始")
        pending = self.pending_attack
        if self.phase is not BattlePhase.RESPONSE or pending is None:
            return ActionResult(False, "当前没有需要响应的攻击")
        if pending.defender is not side:
            return ActionResult(False, "这次攻击不是针对你的")
        if action == "dodge":
            return self._dodge_pending_attack(side)
        if action == "pass":
            return self._take_pending_attack()
        return ActionResult(False, "无效的响应操作")

    def respond(self, action: str) -> ActionResult:
        """玩家对电脑攻击的响应；电脑做防御方时由 AI 在结算里当场决定。"""
        return self.respond_for(Side.PLAYER, action)

    def _dodge_pending_attack(self, side: Side) -> ActionResult:
        participant = self.participant(side)
        dodge = CARDS["dodge"]
        index = self._find_dodge_index(side)
        if index == -1:
            return ActionResult(False, "当前没有可用的闪避")
        if participant.combatant.energy < dodge.cost:
            shortage = dodge.cost - participant.combatant.energy
            return ActionResult(False, f"能量不足，还差 {shortage} 点")
        participant.combatant.energy -= dodge.cost
        participant.hand.pop(index)
        participant.discard_pile.append(dodge.key)
        self.log.append(
            f"{self.actor_label(self.pending_attack.attacker)}"
            f"使用【{self.pending_attack.card_name}】"
        )
        self.log.append(f"{self.side_label(side)}使用【{dodge.name}】，抵消了本次伤害")
        return self._finish_response()

    def _attack_damage(self, attacker: Side, definition: CardDefinition) -> int:
        """打出的瞬间结清这一击的全部加成：条件伤害与长剑，一起算进伤害值。"""
        participant = self.participant(attacker)
        defender = self.opponent_of(attacker).combatant
        damage = conditional_damage(
            definition.value,
            definition.key,
            target_shield=defender.shield,
            target_hp=defender.hp,
            target_max_hp=defender.max_hp,
        )
        weapon = participant.weapon
        boosted = (
            weapon is not None
            and not participant.weapon_used_this_turn
            and definition.key in LONGSWORD_BOOST_KEYS
        )
        if not boosted:
            return damage
        participant.weapon_used_this_turn = True
        return damage + weapon.value

    def _deal_damage(self, defender: Side, damage: int) -> int:
        """对角色造成伤害的唯一漏斗：铁甲先减伤，再交给护盾与血量。

        返回铁甲减伤之后、护盾吸收之前的数值，日志按它报伤害。
        """
        participant = self.participant(defender)
        armor = participant.armor
        if armor is not None and not participant.armor_used_this_turn:
            # 打出即消耗：这一下被护盾全吃掉也算用掉了本回合的铁甲。
            participant.armor_used_this_turn = True
            damage = max(0, damage - armor.value)
        self.apply_damage(participant.combatant, damage)
        return damage

    def _open_response(
        self, attacker: Side, definition: CardDefinition
    ) -> ActionResult:
        """伤害牌先挂起：能闪避的一方获得一次响应机会，否则当场按护盾优先结算。"""
        defender = OPPONENT_SIDE[attacker]
        damage = self._attack_damage(attacker, definition)
        if not self._has_available_dodge(defender):
            self._resolve_damage(attacker, definition, damage)
            return ActionResult(True, "")
        self.pending_attack = PendingAttack(
            attacker=attacker,
            defender=defender,
            card_key=definition.key,
            card_name=definition.name,
            damage=damage,
        )
        self.phase = BattlePhase.RESPONSE
        if not self.is_human_side(defender):
            # 电脑防御时不阻塞调用方，但阶段先如实置为响应，再当场定夺。
            # 双人热座里防守方是真人：挂起等对方的响应请求（走 seat=enemy）。
            self._resolve_enemy_response()
        return ActionResult(True, "")

    def _resolve_damage(
        self, attacker: Side, definition: CardDefinition, damage: int
    ) -> None:
        dealt = self._deal_damage(OPPONENT_SIDE[attacker], damage)
        self.log.append(self._format_card_log(attacker, definition, dealt))
        self._check_terminal()

    def _take_pending_attack(self) -> ActionResult:
        pending = self.pending_attack
        # 用挂起时的伤害值，不能回查牌表：长剑加成只存在于这一份记录里。
        self._resolve_damage(pending.attacker, CARDS[pending.card_key], pending.damage)
        return self._finish_response()

    def _finish_response(self) -> ActionResult:
        """响应结算完把回合交还攻击方；攻击方由电脑操作就接着跑完它剩下的行动。

        判断依据必须是 is_human_side 而不是"她是不是 ENEMY"：双人热座里
        attacker 是玩家2（ENEMY 座位）时，回合必须留在本人手里，AI 不得接管。
        """
        attacker = self.pending_attack.attacker
        self.pending_attack = None
        if self.is_finished():
            return ActionResult(True, "")
        self.phase = TURN_PHASE[attacker]
        if self.is_human_side(attacker):
            return ActionResult(True, "")
        return self._run_enemy_actions()

    def _resolve_enemy_response(self) -> None:
        action = choose_enemy_response(
            self.enemy_observation(), self.ai_difficulty, self.rng
        )
        self.respond_for(Side.ENEMY, action.kind)

    def is_finished(self) -> bool:
        return self.phase in (BattlePhase.VICTORY, BattlePhase.DEFEAT, BattlePhase.DRAW)

    def to_dict(self) -> dict:
        return {
            "participants": {
                side.value: _participant_to_payload(participant)
                for side, participant in self.participants.items()
            },
            "starting_side": self.starting_side.value,
            "round_number": self.round_number,
            "phase": self.phase.value,
            "log": list(self.log),
            "pending_attack": _pending_attack_to_payload(self.pending_attack),
            "ai_difficulty": self.ai_difficulty.value,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "BattleState":
        participants_payload = payload.get("participants")
        if participants_payload is None:
            participants = _migrate_legacy_participants(payload)
        else:
            participants = {
                side: _participant_from_payload(participants_payload[side.value])
                for side in (Side.PLAYER, Side.ENEMY)
            }
        return cls(
            participants=participants,
            round_number=payload["round_number"],
            phase=BattlePhase(payload["phase"]),
            log=list(payload["log"]),
            pending_attack=_pending_attack_from_payload(payload.get("pending_attack")),
            ai_difficulty=AIDifficulty(
                payload.get("ai_difficulty", AIDifficulty.MEDIUM.value)
            ),
            starting_side=Side(payload.get("starting_side", Side.PLAYER.value)),
            # 本次改动之前保存的对局没有模式字段，一律按人机模式读出。
            mode=payload.get("mode", PVE_MODE),
        )


def _public_participant(participant: ParticipantState) -> PublicParticipantState:
    combatant = participant.combatant
    return PublicParticipantState(
        hero_key=participant.hero.key,
        max_hp=combatant.max_hp,
        hp=combatant.hp,
        shield=combatant.shield,
        energy=combatant.energy,
        skill_used_this_turn=participant.skill_used_this_turn,
        weapon_key=participant.weapon.key if participant.weapon else None,
        armor_key=participant.armor.key if participant.armor else None,
        weapon_used_this_turn=participant.weapon_used_this_turn,
        armor_used_this_turn=participant.armor_used_this_turn,
        bonus_energy_next_turn=participant.bonus_energy_next_turn,
    )


def _combatant_to_payload(combatant: Combatant) -> dict:
    return {
        "name": combatant.name,
        "max_hp": combatant.max_hp,
        "hp": combatant.hp,
        "shield": combatant.shield,
        "energy": combatant.energy,
    }


def _participant_to_payload(participant: ParticipantState) -> dict:
    return {
        "hero_key": participant.hero.key,
        "combatant": _combatant_to_payload(participant.combatant),
        "hand": [{"id": c["id"], "key": c["key"]} for c in participant.hand],
        "draw_pile": list(participant.draw_pile),
        "discard_pile": list(participant.discard_pile),
        "skill_used_this_turn": participant.skill_used_this_turn,
        "weapon": participant.weapon.key if participant.weapon else None,
        "armor": participant.armor.key if participant.armor else None,
        "weapon_used_this_turn": participant.weapon_used_this_turn,
        "armor_used_this_turn": participant.armor_used_this_turn,
        "bonus_energy_next_turn": participant.bonus_energy_next_turn,
        "exhaust_pile": list(participant.exhaust_pile),
    }


def _equipped_card_from_payload(key: object) -> CardDefinition | None:
    """槽里只认装备牌：未知 key、普通牌、坏数据一律还原成空槽。"""
    if not isinstance(key, str):
        return None
    definition = CARDS.get(key)
    if definition is None or definition.effect_type != "equip":
        return None
    return definition


def _pending_attack_to_payload(pending: PendingAttack | None) -> dict | None:
    if pending is None:
        return None
    return {
        "attacker": pending.attacker.value,
        "defender": pending.defender.value,
        "card_key": pending.card_key,
        "card_name": pending.card_name,
        "damage": pending.damage,
    }


def _pending_attack_from_payload(payload: dict | None) -> PendingAttack | None:
    if payload is None:
        return None
    # 旧存档只可能存着"电脑打玩家"这一种待响应事件，缺字段时照此补齐。
    return PendingAttack(
        attacker=Side(payload.get("attacker", Side.ENEMY.value)),
        defender=Side(payload.get("defender", Side.PLAYER.value)),
        card_key=payload["card_key"],
        card_name=payload["card_name"],
        damage=payload["damage"],
    )


def _participant_from_payload(payload: dict) -> ParticipantState:
    return ParticipantState(
        hero=HEROES[payload["hero_key"]],
        combatant=Combatant(**payload["combatant"]),
        hand=[dict(card) for card in payload["hand"]],
        draw_pile=list(payload["draw_pile"]),
        discard_pile=list(payload["discard_pile"]),
        skill_used_this_turn=payload["skill_used_this_turn"],
        # 本次改动之前保存的对局没有装备字段，读到旧 session 不能崩。
        weapon=_equipped_card_from_payload(payload.get("weapon")),
        armor=_equipped_card_from_payload(payload.get("armor")),
        weapon_used_this_turn=bool(payload.get("weapon_used_this_turn", False)),
        armor_used_this_turn=bool(payload.get("armor_used_this_turn", False)),
        # 本次改动之前保存的对局没有蓄力和移除区字段，读出 0 和空列表。
        bonus_energy_next_turn=int(payload.get("bonus_energy_next_turn", 0)),
        exhaust_pile=list(payload.get("exhaust_pile", [])),
    )


def _migrate_legacy_participants(payload: dict) -> dict[Side, ParticipantState]:
    """把"玩家字段 + 电脑特例字段"的旧存档升级成两个对等参与者。"""
    enemy_hero = HEROES[LEGACY_ENEMY_HERO_KEY]
    legacy_enemy = payload["enemy"]
    return {
        Side.PLAYER: ParticipantState(
            hero=HEROES[payload["hero"]["key"]],
            combatant=Combatant(**payload["player"]),
            hand=[dict(card) for card in payload["hand"]],
            draw_pile=list(payload["draw_pile"]),
            discard_pile=list(payload["discard_pile"]),
            skill_used_this_turn=payload["skill_used_this_turn"],
        ),
        Side.ENEMY: ParticipantState(
            hero=enemy_hero,
            combatant=Combatant(
                name=legacy_enemy["name"],
                max_hp=enemy_hero.max_hp,
                hp=max(0, min(legacy_enemy["hp"], enemy_hero.max_hp)),
                shield=legacy_enemy["shield"],
                energy=legacy_enemy["energy"],
            ),
            hand=[dict(card) for card in payload["enemy_hand"]],
            draw_pile=list(payload["enemy_draw_pile"]),
            discard_pile=list(payload["enemy_discard_pile"]),
        ),
    }
