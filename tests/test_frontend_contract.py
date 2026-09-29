from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_p1_operation_rail_and_energy_feedback_contract_is_declared():
    template = (PROJECT_ROOT / "templates" / "game.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "static" / "game.js").read_text(encoding="utf-8")

    assert 'class="right-rail"' in template
    assert 'id="selected-card-panel"' in template
    assert 'id="selected-card-cost"' in template
    assert 'class="player-actions"' in template
    assert 'id="skill-cost"' in template
    assert 'id="skill-icon"' in template

    assert "function renderSelectedCard" in script
    assert "card.cost > energy" in script
    assert 'setText("skill-cost"' in script
    assert "heroSkillAssets" in script
    assert "skillIcon.src" in script


def test_new_card_art_assets_are_mapped_for_the_hand_renderer():
    script = (PROJECT_ROOT / "static" / "game.js").read_text(encoding="utf-8")

    for card_key in ("longsword", "iron_armor", "armor_break", "charge", "execute"):
        assert f"  {card_key}:" in script


def test_card_effect_copy_uses_backend_text_without_frontend_rule_judgement():
    script = (PROJECT_ROOT / "static" / "game.js").read_text(encoding="utf-8")
    effect_copy = script.split("function cardTypeLabel", 1)[0].split(
        "function effectCopy", 1
    )[1]

    assert "return card.text ||" in effect_copy
    assert "card.effect_type" not in effect_copy


def test_p2_card_type_anchor_contract_is_declared():
    script = (PROJECT_ROOT / "static" / "game.js").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    assert 'class="card-type"' in script
    assert "min-width: 76px" in styles
    assert "white-space: nowrap" in styles
    assert "border-radius" in styles


def test_p2_card_type_uses_reference_button_treatment():
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    assert "border-bottom: 1px solid" in styles
    assert "min-width: 104px" in styles
    assert "letter-spacing: .16em" in styles
    assert ".card-damage .card-type" not in styles
    assert ".card-shield .card-type" not in styles
    assert ".card-heal .card-type" not in styles


def test_p2_card_name_sits_below_artwork_edge():
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    assert "transform: translateY(6px)" in styles


def test_p2_hand_interaction_feedback_contract_is_declared():
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    assert (
        '.battle-card[data-availability="ready"]:is(:hover, :focus-visible)' in styles
    )
    assert (
        '.battle-card[data-availability="ready"]:is(:hover, :focus-visible) .card-face::after'
        in styles
    )
    assert '.battle-card[data-availability="energy"] {' in styles
    assert '.battle-card[data-availability="blocked"]:disabled' in styles


def test_battle_layout_keeps_end_turn_with_player_actions():
    template = (PROJECT_ROOT / "templates" / "game.html").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    player_zone = template.split('<section class="player-zone">', 1)[1].split("</section>", 1)[0]
    actions_start = player_zone.index('<div class="player-actions">')
    actions_end = player_zone.index("</div>", actions_start)
    end_turn_index = player_zone.index('id="end-turn"')

    assert actions_start < end_turn_index < actions_end
    assert "grid-template-rows: auto auto" not in styles
    assert "grid-template-columns: 136px minmax(220px, 1fr) minmax(470px, 520px);" in styles
    assert ".hand-zone { display: grid; gap: 9px; transform: translateY(-18px); }" in styles


def test_fixed_stage_uses_one_absolute_positioning_rule():
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")
    shell_rule = styles.split(".game-shell {", 1)[1].split("}", 1)[0]

    assert shell_rule.count("\n  position:") == 1
    assert "position: absolute;" in shell_rule


def test_fixed_stage_budget_leaves_room_for_the_full_hand():
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    assert "grid-template-rows: auto minmax(230px, 1fr) auto auto;" in styles
    assert ".arena-layout { --rail-width: 344px; --layout-gap: 24px; display: grid; grid-template-columns: minmax(0, 1fr) var(--rail-width); gap: var(--layout-gap); min-height: 230px; }" in styles


def test_hand_fan_layout_is_calculated_from_card_count():
    script = (PROJECT_ROOT / "static" / "game.js").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    assert "const handCenter = (hand.length - 1) / 2;" in script
    assert (
        "const normalizedOffset = handCenter ? (index - handCenter) / handCenter : 0;"
        in script
    )
    assert 'button.style.setProperty("--hand-rotate"' in script
    assert 'button.style.setProperty("--hand-offset-y"' in script
    assert "--hand-rotate" in styles
    assert "--hand-offset-y" in styles


def test_energy_insufficient_card_shows_toast_without_playing_card():
    script = (PROJECT_ROOT / "static" / "game.js").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    assert "function renderHand(hand, canPlay, energy, isPlayerTurn)" in script
    assert (
        "button.disabled = isResponsePhase ? !canUseAsResponse : !isPlayerTurn;"
        in script
    )
    assert 'button.setAttribute("aria-disabled"' not in script
    assert "if (unavailableByEnergy) {" in script
    assert "showToast(`能量不足：需要 ${card.cost} 点，当前 ${energy} 点。`);" in script
    assert 'state.phase === "PLAYER_TURN"' in script
    assert '.battle-card[data-availability="energy"] {' in styles


def test_enemy_response_contract_is_declared():
    template = (PROJECT_ROOT / "templates" / "game.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "static" / "game.js").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    assert 'id="response-panel"' in template
    assert 'id="response-dodge"' in template
    assert 'id="response-pass"' in template
    assert '"RESPONSE"' in script
    assert "function respondToAttack" in script
    assert '"/api/game/actions/respond"' in script
    assert "available_actions.respond.dodge" in script
    assert "响应可用" in script
    assert ".response-panel" in styles


def test_ai_difficulty_selector_contract_is_declared():
    template = (PROJECT_ROOT / "templates" / "game.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "static" / "game.js").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    assert 'id="difficulty-options"' in template
    assert 'data-difficulty="easy"' in template
    assert 'data-difficulty="medium"' in template
    assert 'data-difficulty="hard"' in template
    assert 'id="enemy-difficulty"' in template

    assert "selectedDifficulty" in script
    assert "ai_difficulty: selectedDifficulty" in script
    assert "difficultyLabels[state.ai_difficulty]" in script
    assert ".difficulty-option" in styles


def test_response_panel_layer_sits_above_player_zone():
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    assert ".arena-layout { z-index: 2; }" in styles


def test_both_sides_show_the_same_public_resources_contract_is_declared():
    template = (PROJECT_ROOT / "templates" / "game.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "static" / "game.js").read_text(encoding="utf-8")

    for element_id in (
        "enemy-hero",
        "enemy-energy",
        "enemy-energy-pips",
        "enemy-skill",
        "player-energy",
        "player-energy-pips",
    ):
        assert f'id="{element_id}"' in template

    assert 'setText("enemy-hero"' in script
    assert "function viewerSide(state)" in script
    assert "function sideState(state, side)" in script
    assert "function opponentSide(viewer)" in script
    assert 'renderSkillState("enemy", foe.skill)' in script
    assert "setText(`${prefix}-skill`" in script
    assert 'renderEnergy("enemy", foe.energy)' in script
    assert 'renderEnergy("player", self.energy)' in script
    assert "foe.hero.name" in script
    assert "self.hero.name" in script
    assert "foe.skill" in script
    assert "self.skill" in script
    # 电脑手牌与抽牌堆是私有信息：页面上没有它们的位置，脚本里也不许读。
    assert "enemy_hand" not in script
    assert "enemy.hand" not in script
    assert "enemy.draw_pile" not in script
    assert "enemy_draw_pile" not in script


def test_energy_pips_and_charge_reserve_follow_the_public_state_contract():
    template = (PROJECT_ROOT / "templates" / "game.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "static" / "game.js").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    for element_id in ("enemy-bonus-energy", "player-bonus-energy"):
        assert f'id="{element_id}"' in template

    assert "const pipCount = Math.max(3, energy);" in script
    assert "index < pipCount" in script
    assert "function renderBonusEnergy(prefix, bonusEnergy)" in script
    assert 'renderBonusEnergy("enemy", foe.bonus_energy_next_turn);' in script
    assert 'renderBonusEnergy("player", self.bonus_energy_next_turn);' in script
    assert ".bonus-energy" in styles
    assert ".bonus-energy.is-hidden" in styles


def test_equipment_slots_render_both_public_equipment_fields_for_both_sides():
    template = (PROJECT_ROOT / "templates" / "game.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "static" / "game.js").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    for side in ("enemy", "player"):
        assert f'id="{side}-equipment"' in template
        assert f'id="{side}-weapon-slot"' in template
        assert f'id="{side}-armor-slot"' in template

    assert 'renderEquipment("enemy", foe.equipment);' in script
    assert 'renderEquipment("player", self.equipment);' in script

    assert "function renderEquipment(side, equipment)" in script
    assert "equipment?.[slotName]" in script
    assert "cardAssets[card.key]" in script
    assert ".equipment-slots" in styles
    assert ".equipment-slot.is-equipped" in styles
    assert ".equipment-slot.is-empty" in styles


def test_enemy_intent_panel_reads_public_fields_and_clears_when_intent_is_null():
    template = (PROJECT_ROOT / "templates" / "game.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "static" / "game.js").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    for element_id in (
        "enemy-intent",
        "enemy-intent-kind",
        "enemy-intent-name",
        "enemy-intent-text",
    ):
        assert f'id="{element_id}"' in template

    assert "function renderEnemyIntent(intent)" in script
    assert 'renderEnemyIntent(state.mode === "pve" ? foe.intent : null);' in script
    assert "if (!intent)" in script
    assert "intent.kind" in script
    assert "intent.source" in script
    assert "intent.name" in script
    assert "intent.value" in script
    assert "intent.text" in script
    for kind in ("attack", "defend", "heal", "equip", "charge", "pass"):
        assert f"{kind}:" in script

    assert ".enemy-intent" in styles
    assert ".enemy-intent.is-hidden" in styles
    assert '.enemy-intent[data-kind="attack"]' in styles


def test_exhaust_and_card_type_labels_use_public_card_catalog_and_piles():
    template = (PROJECT_ROOT / "templates" / "game.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "static" / "game.js").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    for element_id in (
        "enemy-exhaust-count",
        "player-exhaust-count",
        "selected-card-exhaust",
    ):
        assert f'id="{element_id}"' in template

    assert "const cardTypeLabels" in script
    for effect_type, label in (
        ("damage", "攻击"),
        ("shield", "防御"),
        ("heal", "治疗"),
        ("dodge", "响应"),
        ("equip", "装备"),
        ("charge", "蓄力"),
    ):
        assert f'{effect_type}: "{label}"' in script
    assert "card.exhaust" in script
    assert "function renderExhaustCount(prefix, exhaustPile)" in script
    assert 'renderExhaustCount("enemy", foe.exhaust_pile);' in script
    assert 'renderExhaustCount("player", self.exhaust_pile);' in script
    assert 'requestJson("/api/cards")' in script
    assert "cardCatalog" in script
    assert "已移除" in script
    assert "title" in script

    assert ".card-exhaust" in styles
    assert ".card-type-row" in styles
    assert ".exhaust-count" in styles
    assert ".selected-card-exhaust" in styles


def test_demo_battle_page_carries_a_response_form_contract_is_declared():
    template = (PROJECT_ROOT / "templates" / "battle.html").read_text(encoding="utf-8")

    assert "url_for('demo.battle_respond')" in template
    assert 'name="action" value="dodge"' in template
    assert 'name="action" value="pass"' in template
    assert "电脑英雄" in template
    assert "电脑能量" in template


def test_response_panel_is_positioned_as_a_central_overlay():
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    assert ".arena-center { position: relative; }" in styles
    assert "position: absolute; top: 50%; left: 50%;" in styles


def test_hero_selection_and_mode_picker_contract_is_declared():
    template = (PROJECT_ROOT / "templates" / "game.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "static" / "game.js").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    assert 'id="hero-options"' in template
    assert 'id="hero-options-2"' in template
    assert 'id="mode-options"' in template
    assert 'id="hero-card-preview"' in template
    assert 'id="hero-card-preview-2"' in template
    assert 'id="hero-card-track"' in template
    assert 'id="hero-card-prev"' in template
    assert 'id="hero-card-next"' in template
    assert 'id="difficulty-toggle"' in template
    assert 'id="difficulty-options"' in template
    assert "hero.deck" in script
    assert "function renderHeroes" in script
    assert "function renderHeroCardPreview" in script
    assert "heroCardOffsets" in script
    assert "function selectMode" in script
    assert "gameMode" in script
    assert "cardAssets[card.key]" in script
    assert "hero.description" not in script
    assert "heroDeckSummary" not in script
    assert ".hero-option" in styles
    assert ".hero-card-thumb" in styles
    assert ".difficulty-options.is-open" in styles
    assert ".mode-option" in styles
    assert ".difficulty-option" in styles


def test_pvp_role_selection_uses_a_compact_only_layout():
    script = (PROJECT_ROOT / "static" / "game.js").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    assert "heroSelectionPanel" in script
    assert "refs.heroSelectionPanel.classList.toggle(\"is-pvp\", gameMode === \"pvp\")" in script
    assert ".hero-selection-panel.is-pvp" in styles
    assert ".hero-selection-panel.is-pvp .hero-card-thumb" in styles
    assert ".difficulty-picker.is-hidden" in styles


def test_result_overlay_prefers_backend_result_text_and_explains_four_outcome_reasons():
    template = (PROJECT_ROOT / "templates" / "game.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "static" / "game.js").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    assert 'id="result-reason"' in template
    assert "const resultReasonLabels" in script
    for reason, label in (
        ("kill", "击倒结算"),
        ("hp", "生命值结算"),
        ("shield", "护盾结算"),
        ("draw", "完全平局"),
    ):
        assert f'{reason}: "{label}"' in script
    assert "const result = state.result || {};" in script
    assert "result.text ||" in script
    assert "result.reason" in script
    assert ".result-reason" in styles


def test_portraits_follow_public_hero_keys_and_keep_safe_fallbacks():
    template = (PROJECT_ROOT / "templates" / "game.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "static" / "game.js").read_text(encoding="utf-8")

    for element_id in ("enemy-portrait", "player-portrait"):
        assert f'id="{element_id}"' in template

    assert "const heroPortraitAssets" in script
    assert 'warrior: "warrior-portrait.png"' in script
    assert 'mage: "mage-portrait.png"' in script
    assert 'ranger: "ranger-portrait.png"' in script
    assert 'enemy: {\n    warrior: "warrior-portrait.png",\n    mage: "mage-portrait.png",\n    ranger: "ranger-portrait.png",' in script
    assert "const fallbackPortraitAssets" in script
    assert 'enemy: "enemy-portrait.png"' in script
    assert 'player: "warrior-portrait.png"' in script
    assert "function renderPortrait(side, hero)" in script
    assert "heroPortraitAssets[side]?.[hero?.key]" in script
    assert "fallbackPortraitAssets[side]" in script
    assert 'renderPortrait("enemy", foe.hero);' in script
    assert 'renderPortrait("player", self.hero);' in script
