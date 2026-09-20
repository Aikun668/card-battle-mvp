import random
import uuid

from game.ai import choose_enemy_card
from game.catalog import CARDS, FIXED_DECK_KEYS, HEROES
from game.models import (
    ActionResult,
    BattlePhase,
    CardDefinition,
    Combatant,
    HeroDefinition,
)

HAND_LIMIT = 6
STARTING_ENERGY = 3
ENEMY_STARTING_HP = 28
STARTING_HAND = 5
ROUND_LIMIT = 10


class BattleState:
    def __init__(
        self,
        hero: HeroDefinition,
        player: Combatant,
        enemy: Combatant,
        hand: list[dict],
        draw_pile: list[str],
        discard_pile: list[str],
        enemy_hand: list[dict],
        enemy_draw_pile: list[str],
        enemy_discard_pile: list[str],
        round_number: int,
        phase: BattlePhase,
        log: list[str],
        skill_used_this_turn: bool = False,
        pending_attack: dict | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.hero = hero
        self.player = player
        self.enemy = enemy
        self.hand = hand
        self.draw_pile = draw_pile
        self.discard_pile = discard_pile
        self.enemy_hand = enemy_hand
        self.enemy_draw_pile = enemy_draw_pile
        self.enemy_discard_pile = enemy_discard_pile
        self.round_number = round_number
        self.phase = phase
        self.log = log
        self.skill_used_this_turn = skill_used_this_turn
        self.pending_attack = pending_attack
        self.rng = rng or random.Random()

    @classmethod
    def create(cls, hero_key: str, rng: random.Random) -> "BattleState":
        hero = HEROES[hero_key]
        player = Combatant(name=hero.name, max_hp=hero.max_hp, hp=hero.max_hp)
        enemy = Combatant(name="电脑", max_hp=ENEMY_STARTING_HP, hp=ENEMY_STARTING_HP)
        draw_pile = list(FIXED_DECK_KEYS)
        rng.shuffle(draw_pile)
        enemy_draw_pile = list(FIXED_DECK_KEYS)
        rng.shuffle(enemy_draw_pile)
        state = cls(
            hero=hero,
            player=player,
            enemy=enemy,
            hand=[],
            draw_pile=draw_pile,
            discard_pile=[],
            enemy_hand=[],
            enemy_draw_pile=enemy_draw_pile,
            enemy_discard_pile=[],
            round_number=1,
            phase=BattlePhase.PLAYER_TURN,
            log=[],
            rng=rng,
        )
        state.log.append(f"战斗开始，玩家选择角色：{hero.name}")
        state.draw_cards(STARTING_HAND)
        state._draw_enemy_cards(STARTING_HAND)
        return state

    def _draw_enemy_cards(self, count: int) -> int:
        drawn = 0
        for _ in range(count):
            if len(self.enemy_hand) >= HAND_LIMIT:
                break
            if not self.enemy_draw_pile:
                if not self.enemy_discard_pile:
                    break
                self.enemy_draw_pile.extend(self.enemy_discard_pile)
                self.enemy_discard_pile.clear()
                self.rng.shuffle(self.enemy_draw_pile)
            key = self.enemy_draw_pile.pop()
            self.enemy_hand.append({"id": f"enemy-{uuid.uuid4().hex[:8]}", "key": key})
            drawn += 1
        return drawn

    def _new_card_id(self) -> str:
        return f"card-{uuid.uuid4().hex[:8]}"

    def draw_cards(self, count: int) -> int:
        drawn = 0
        for _ in range(count):
            if len(self.hand) >= HAND_LIMIT:
                self.log.append("手牌已满，本回合没有抽到新牌")
                break
            if not self.draw_pile:
                if not self.discard_pile:
                    break
                self.draw_pile.extend(self.discard_pile)
                self.discard_pile.clear()
                self.rng.shuffle(self.draw_pile)
            key = self.draw_pile.pop()
            self.hand.append({"id": self._new_card_id(), "key": key})
            drawn += 1
        return drawn

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

    def end_player_turn(self) -> ActionResult:
        if self.is_finished():
            return ActionResult(False, "本局已经结束，请重新开始")
        if self.phase is not BattlePhase.PLAYER_TURN:
            return ActionResult(False, "现在是电脑回合，请等待电脑行动")
        self.phase = BattlePhase.ENEMY_TURN
        self.log.append(f"第 {self.round_number} 回合结束，电脑开始行动")
        return ActionResult(True, "")

    def resolve_enemy_turn(self) -> ActionResult:
        if self.is_finished():
            return ActionResult(False, "本局已经结束，请重新开始")
        if self.phase is not BattlePhase.ENEMY_TURN:
            return ActionResult(False, "还没有进入电脑回合")
        self.enemy.energy = STARTING_ENERGY
        self.enemy.shield = 0
        card_id = choose_enemy_card(self)
        if card_id is not None:
            self._play_enemy_card(card_id)
            if self.phase is BattlePhase.RESPONSE:
                return ActionResult(True, "")
            self._check_terminal()
        return self._complete_enemy_turn()

    def _complete_enemy_turn(self) -> ActionResult:
        if self.is_finished():
            return ActionResult(True, "")
        if self.round_number >= ROUND_LIMIT:
            self.phase = BattlePhase.DRAW
            self.log.append(f"达到 {ROUND_LIMIT} 回合上限，本局平局")
            return ActionResult(True, "")
        self.round_number += 1
        self.phase = BattlePhase.PLAYER_TURN
        self.player.energy = STARTING_ENERGY
        self.skill_used_this_turn = False
        self.draw_cards(1)
        self._draw_enemy_cards(1)
        self.log.append(f"第 {self.round_number} 回合开始")
        return ActionResult(True, "")

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
            return self._complete_enemy_turn()

        if action == "pass":
            self.apply_damage(self.player, pending_attack["damage"])
            self.log.append(
                f"电脑使用【{pending_attack['card_name']}】，对你造成 {pending_attack['damage']} 点伤害"
            )
            self.pending_attack = None
            self._check_terminal()
            return self._complete_enemy_turn()

        return ActionResult(False, "无效的响应操作")

    def _play_enemy_card(self, card_instance_id: str) -> None:
        for i, card in enumerate(self.enemy_hand):
            if card["id"] == card_instance_id:
                definition = CARDS[card["key"]]
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
            "hero": {
                "key": self.hero.key,
                "name": self.hero.name,
                "max_hp": self.hero.max_hp,
                "skill_name": self.hero.skill_name,
                "skill_type": self.hero.skill_type,
                "skill_value": self.hero.skill_value,
            },
            "player": {
                "name": self.player.name,
                "max_hp": self.player.max_hp,
                "hp": self.player.hp,
                "shield": self.player.shield,
                "energy": self.player.energy,
            },
            "enemy": {
                "name": self.enemy.name,
                "max_hp": self.enemy.max_hp,
                "hp": self.enemy.hp,
                "shield": self.enemy.shield,
                "energy": self.enemy.energy,
            },
            "hand": [{"id": c["id"], "key": c["key"]} for c in self.hand],
            "draw_pile": list(self.draw_pile),
            "discard_pile": list(self.discard_pile),
            "enemy_hand": [{"id": c["id"], "key": c["key"]} for c in self.enemy_hand],
            "enemy_draw_pile": list(self.enemy_draw_pile),
            "enemy_discard_pile": list(self.enemy_discard_pile),
            "round_number": self.round_number,
            "phase": self.phase.value,
            "log": list(self.log),
            "skill_used_this_turn": self.skill_used_this_turn,
            "pending_attack": dict(self.pending_attack)
            if self.pending_attack
            else None,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "BattleState":
        hero_def = HEROES[payload["hero"]["key"]]
        player = Combatant(
            name=payload["player"]["name"],
            max_hp=payload["player"]["max_hp"],
            hp=payload["player"]["hp"],
            shield=payload["player"]["shield"],
            energy=payload["player"]["energy"],
        )
        enemy = Combatant(
            name=payload["enemy"]["name"],
            max_hp=payload["enemy"]["max_hp"],
            hp=payload["enemy"]["hp"],
            shield=payload["enemy"]["shield"],
            energy=payload["enemy"]["energy"],
        )
        return cls(
            hero=hero_def,
            player=player,
            enemy=enemy,
            hand=list(payload["hand"]),
            draw_pile=list(payload["draw_pile"]),
            discard_pile=list(payload["discard_pile"]),
            enemy_hand=list(payload["enemy_hand"]),
            enemy_draw_pile=list(payload["enemy_draw_pile"]),
            enemy_discard_pile=list(payload["enemy_discard_pile"]),
            round_number=payload["round_number"],
            phase=BattlePhase(payload["phase"]),
            log=list(payload["log"]),
            skill_used_this_turn=payload["skill_used_this_turn"],
            pending_attack=payload.get("pending_attack"),
        )
