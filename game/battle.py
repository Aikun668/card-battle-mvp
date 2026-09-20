import random
import uuid

from game.ai import select_enemy_action
from game.catalog import CARDS, FIXED_DECK_KEYS, HEROES, STARTING_ENERGY
from game.models import (
    AIDifficulty,
    ActionResult,
    BattlePhase,
    CardDefinition,
    Combatant,
    HeroDefinition,
    ParticipantState,
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

    def __init__(
        self,
        participants: dict[Side, ParticipantState],
        round_number: int,
        phase: BattlePhase,
        log: list[str],
        pending_attack: dict | None = None,
        rng: random.Random | None = None,
        ai_difficulty: AIDifficulty = AIDifficulty.MEDIUM,
        starting_side: Side = Side.PLAYER,
    ) -> None:
        self.participants = participants
        self.round_number = round_number
        self.phase = phase
        self.log = log
        self.pending_attack = pending_attack
        self.rng = rng or random.Random()
        self.ai_difficulty = ai_difficulty
        self.starting_side = starting_side

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
    ) -> "BattleState":
        hero = HEROES[hero_key]
        enemy_hero = choose_enemy_hero(rng)
        first_side = starting_side or rng.choice(list(Side))
        state = cls(
            participants={
                Side.PLAYER: ParticipantState(
                    hero=hero,
                    combatant=Combatant(
                        name=hero.name, max_hp=hero.max_hp, hp=hero.max_hp
                    ),
                    hand=[],
                    draw_pile=_shuffled_deck(rng, FIXED_DECK_KEYS),
                    discard_pile=[],
                ),
                Side.ENEMY: ParticipantState(
                    hero=enemy_hero,
                    combatant=Combatant(
                        name=ENEMY_NAME,
                        max_hp=enemy_hero.max_hp,
                        hp=enemy_hero.max_hp,
                    ),
                    hand=[],
                    draw_pile=_shuffled_deck(rng, FIXED_DECK_KEYS),
                    discard_pile=[],
                ),
            },
            round_number=1,
            phase=TURN_PHASE[first_side],
            log=[],
            rng=rng,
            ai_difficulty=ai_difficulty,
            starting_side=first_side,
        )
        state.log.append(f"战斗开始，玩家选择角色：{hero.name}")
        state.log.append(f"电脑选择角色：{enemy_hero.name}")
        for side in (Side.PLAYER, Side.ENEMY):
            state.draw_cards_for(side, STARTING_HAND)
        if first_side is Side.ENEMY:
            # 电脑先手时在创建流程里同步跑完，调用方只需要处理玩家回合或终局；
            # 开局这一次攻击发生在玩家看到棋盘之前，按放弃响应结算。
            state.resolve_enemy_turn()
            while state.phase is BattlePhase.RESPONSE:
                state.respond("pass")
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

    def play_card(self, card_instance_id: str) -> ActionResult:
        if self.is_finished():
            return ActionResult(False, "本局已经结束，请重新开始")
        if self.phase is not BattlePhase.PLAYER_TURN:
            return ActionResult(False, "现在是电脑回合，请等待电脑行动")
        index = self._find_hand_index(self.hand, card_instance_id)
        if index == -1:
            return ActionResult(False, "这张卡牌已经不能使用")
        card = self.hand[index]
        definition = CARDS[card["key"]]
        if definition.effect_type == "dodge":
            return ActionResult(False, "闪避只能在敌人攻击时使用")
        if self.player.energy < definition.cost:
            shortage = definition.cost - self.player.energy
            return ActionResult(False, f"能量不足，还差 {shortage} 点")
        # Now perform the effect
        self.player.energy -= definition.cost
        self.hand.pop(index)
        self.discard_pile.append(definition.key)
        self._apply_card_effect(definition, source=self.player, target=self.enemy)
        self.log.append(self._format_card_log(definition))
        self._check_terminal()
        return ActionResult(True, "")

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

    def _format_card_log(self, definition: CardDefinition) -> str:
        if definition.effect_type == "damage":
            return f"使用【{definition.name}】，对电脑造成 {definition.value} 点伤害"
        if definition.effect_type == "shield":
            return f"使用【{definition.name}】，获得 {definition.value} 点护盾"
        if definition.effect_type == "heal":
            return f"使用【{definition.name}】，恢复 {definition.value} 点生命值"
        return f"使用【{definition.name}】"

    def use_skill(self) -> ActionResult:
        if self.is_finished():
            return ActionResult(False, "本局已经结束，请重新开始")
        if self.phase is not BattlePhase.PLAYER_TURN:
            return ActionResult(False, "现在是电脑回合，请等待电脑行动")
        if self.skill_used_this_turn:
            return ActionResult(False, "本回合技能已经使用过")
        if self.player.energy < 2:
            shortage = 2 - self.player.energy
            return ActionResult(False, f"能量不足，还差 {shortage} 点")
        skill = self.hero
        self.player.energy -= 2
        self.skill_used_this_turn = True
        if skill.skill_type == "shield":
            self.player.shield += skill.skill_value
            self.log.append(
                f"释放技能【{skill.skill_name}】，获得 {skill.skill_value} 点护盾"
            )
        elif skill.skill_type == "damage":
            self.apply_damage(self.enemy, skill.skill_value)
            self.log.append(
                f"释放技能【{skill.skill_name}】，对电脑造成 {skill.skill_value} 点伤害"
            )
        elif skill.skill_type == "damage_draw":
            self.apply_damage(self.enemy, skill.skill_value)
            drawn = self.draw_cards(1)
            extra = "并抽取 1 张牌" if drawn else "但手牌已满，未抽到牌"
            self.log.append(
                f"释放技能【{skill.skill_name}】，对电脑造成 {skill.skill_value} 点伤害，{extra}"
            )
        self._check_terminal()
        return ActionResult(True, "")

    def _check_terminal(self) -> None:
        if self.enemy.hp <= 0:
            self.phase = BattlePhase.VICTORY
        elif self.player.hp <= 0:
            self.phase = BattlePhase.DEFEAT

    def current_side(self) -> Side | None:
        return SIDE_PHASE.get(self.phase)

    def start_turn(self, side: Side, *, initial: bool = False) -> None:
        """回合开始：回满能量、重置技能次数；只有本局首回合不额外补牌。"""
        participant = self.participant(side)
        participant.skill_used_this_turn = False
        participant.combatant.energy = STARTING_ENERGY
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
            self.phase = BattlePhase.DRAW
            self.log.append(f"达到 {ROUND_LIMIT} 回合上限，本局平局")
            return ActionResult(True, "")
        next_side = OPPONENT_SIDE[side]
        if starts_new_round:
            self.round_number += 1
            self.log.append(f"第 {self.round_number} 回合开始")
        self.phase = TURN_PHASE[next_side]
        self.start_turn(next_side, initial=is_game_opening)
        return ActionResult(True, "")

    def end_player_turn(self) -> ActionResult:
        if self.is_finished():
            return ActionResult(False, "本局已经结束，请重新开始")
        if self.phase is not BattlePhase.PLAYER_TURN:
            return ActionResult(False, "现在是电脑回合，请等待电脑行动")
        self.log.append(f"第 {self.round_number} 回合结束，电脑开始行动")
        return self.advance_turn()

    def resolve_enemy_turn(self) -> ActionResult:
        if self.is_finished():
            return ActionResult(False, "本局已经结束，请重新开始")
        if self.phase is not BattlePhase.ENEMY_TURN:
            return ActionResult(False, "还没有进入电脑回合")
        return self._run_enemy_actions()

    def _run_enemy_actions(self) -> ActionResult:
        # 上限只是防止意外死循环，不是游戏规则：正常情况因无牌可打而结束回合。
        for _ in range(HAND_LIMIT + 1):
            if self.is_finished() or self.phase is BattlePhase.RESPONSE:
                return ActionResult(True, "")
            action = select_enemy_action(self, self.ai_difficulty, self.rng)
            if action.kind == "pass":
                break
            self._play_enemy_card(action.card_id)
            self._check_terminal()
        return self._complete_enemy_turn()

    def _resume_enemy_turn(self) -> ActionResult:
        # 响应结算完可能已经被 _check_terminal() 判定终局，此时不能再推进回合。
        if self.is_finished():
            return ActionResult(True, "")
        self.phase = BattlePhase.ENEMY_TURN
        return self._run_enemy_actions()

    def _complete_enemy_turn(self) -> ActionResult:
        if self.is_finished():
            return ActionResult(True, "")
        self.log.append(f"第 {self.round_number} 回合结束，玩家开始行动")
        return self.advance_turn()

    def _find_dodge_index(self) -> int:
        for index, card in enumerate(self.hand):
            if card["key"] == "dodge":
                return index
        return -1

    def _has_available_dodge(self) -> bool:
        return (
            self._find_dodge_index() != -1 and self.player.energy >= CARDS["dodge"].cost
        )

    def can_dodge(self) -> bool:
        return self.phase is BattlePhase.RESPONSE and self._has_available_dodge()

    def respond(self, action: str) -> ActionResult:
        if self.is_finished():
            return ActionResult(False, "本局已经结束，请重新开始")
        if self.phase is not BattlePhase.RESPONSE or self.pending_attack is None:
            return ActionResult(False, "当前没有需要响应的攻击")

        pending_attack = self.pending_attack
        if action == "dodge":
            dodge_index = self._find_dodge_index()
            dodge = CARDS["dodge"]
            if dodge_index == -1:
                return ActionResult(False, "当前没有可用的闪避")
            if self.player.energy < dodge.cost:
                return ActionResult(False, "能量不足，还差 1 点")
            self.player.energy -= dodge.cost
            self.hand.pop(dodge_index)
            self.discard_pile.append(dodge.key)
            self.log.append(f"电脑使用【{pending_attack['card_name']}】")
            self.log.append("玩家使用【闪避】，抵消了本次伤害")
            self.pending_attack = None
            return self._resume_enemy_turn()

        if action == "pass":
            self.apply_damage(self.player, pending_attack["damage"])
            self.log.append(
                f"电脑使用【{pending_attack['card_name']}】，对你造成 {pending_attack['damage']} 点伤害"
            )
            self.pending_attack = None
            self._check_terminal()
            return self._resume_enemy_turn()

        return ActionResult(False, "无效的响应操作")

    def _play_enemy_card(self, card_instance_id: str) -> None:
        for i, card in enumerate(self.enemy_hand):
            if card["id"] == card_instance_id:
                definition = CARDS[card["key"]]
                self.enemy.energy -= definition.cost
                self.enemy_discard_pile.append(definition.key)
                self.enemy_hand.pop(i)
                if definition.effect_type == "damage":
                    if self._has_available_dodge():
                        self.pending_attack = {
                            "card_key": definition.key,
                            "card_name": definition.name,
                            "damage": definition.value,
                        }
                        self.phase = BattlePhase.RESPONSE
                        return
                    self.apply_damage(self.player, definition.value)
                    self.log.append(
                        f"电脑使用【{definition.name}】，对你造成 {definition.value} 点伤害"
                    )
                elif definition.effect_type == "shield":
                    self.enemy.shield += definition.value
                    self.log.append(
                        f"电脑使用【{definition.name}】，获得 {definition.value} 点护盾"
                    )
                elif definition.effect_type == "heal":
                    self.apply_heal(self.enemy, definition.value)
                    self.log.append(
                        f"电脑使用【{definition.name}】，恢复 {definition.value} 点生命值"
                    )
                return

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
            "pending_attack": dict(self.pending_attack)
            if self.pending_attack
            else None,
            "ai_difficulty": self.ai_difficulty.value,
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
            pending_attack=payload.get("pending_attack"),
            ai_difficulty=AIDifficulty(
                payload.get("ai_difficulty", AIDifficulty.MEDIUM.value)
            ),
            starting_side=Side(payload.get("starting_side", Side.PLAYER.value)),
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
    }


def _participant_from_payload(payload: dict) -> ParticipantState:
    return ParticipantState(
        hero=HEROES[payload["hero_key"]],
        combatant=Combatant(**payload["combatant"]),
        hand=[dict(card) for card in payload["hand"]],
        draw_pile=list(payload["draw_pile"]),
        discard_pile=list(payload["discard_pile"]),
        skill_used_this_turn=payload["skill_used_this_turn"],
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
