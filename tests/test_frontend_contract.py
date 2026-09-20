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


def test_response_panel_is_positioned_as_a_central_overlay():
    styles = (PROJECT_ROOT / "static" / "game.css").read_text(encoding="utf-8")

    assert ".arena-center { position: relative; }" in styles
    assert "position: absolute; top: 50%; left: 50%;" in styles
