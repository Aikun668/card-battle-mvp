const cardAssets = {
  slash: "New/3f8072ff-4400-4edd-b4ac-745b97a7114f.png",
  heavy_strike: "New/936d5fc4-51f2-45f0-8e81-80ed5ae70a79.png",
  shield: "New/93a671c6-1d36-4719-93b7-994b63663898.png",
  heal: "New/91f5a0fb-dac5-4edd-bb5a-32238838b495.png",
  fireball: "New/5cd7bb88-da04-43cd-bd40-2856a50d792d.png",
  dodge: "New/93a671c6-1d36-4719-93b7-994b63663898.png",
  longsword: "New/longsword.png",
  iron_armor: "New/iron-armor.png",
  armor_break: "New/armor-break.png",
  charge: "New/charge.png",
  execute: "New/execute.png",
};

const heroSkillAssets = {
  warrior: cardAssets.shield,
  mage: cardAssets.fireball,
  ranger: cardAssets.slash,
};

const heroPortraitAssets = {
  player: {
    warrior: "warrior-portrait.png",
    mage: "mage-portrait.png",
    ranger: "ranger-portrait.png",
  },
  enemy: {
    warrior: "warrior-portrait.png",
    mage: "mage-portrait.png",
    ranger: "ranger-portrait.png",
  },
};

const fallbackPortraitAssets = {
  player: "warrior-portrait.png",
  enemy: "enemy-portrait.png",
};

const outcomeLabels = {
  VICTORY: "战斗结束",
  DEFEAT: "战斗结束",
  DRAW: "战斗结束",
};

const resultReasonLabels = {
  kill: "击倒结算",
  hp: "生命值结算",
  shield: "护盾结算",
  draw: "完全平局",
};

const difficultyLabels = {
  easy: "简单",
  medium: "中等",
  hard: "困难",
};

const difficultyDescriptions = {
  easy: "选牌更随意",
  medium: "默认难度",
  hard: "会预判斩杀",
};

const intentKindLabels = {
  attack: "攻击",
  defend: "防御",
  heal: "治疗",
  equip: "装备",
  charge: "蓄力",
  pass: "空过",
};

const intentSourceLabels = {
  card: "卡牌",
  skill: "技能",
  none: "无",
};

const cardTypeLabels = {
  damage: "攻击",
  shield: "防御",
  heal: "治疗",
  dodge: "响应",
  equip: "装备",
  charge: "蓄力",
};

const refs = {
  shell: document.getElementById("game-shell"),
  startOverlay: document.getElementById("start-overlay"),
  heroSelectionPanel: document.querySelector(".hero-selection-panel"),
  resultOverlay: document.getElementById("result-overlay"),
  handoffOverlay: document.getElementById("handoff-overlay"),
  handoffTitle: document.getElementById("handoff-title"),
  handoffCopy: document.getElementById("handoff-copy"),
  handoffConfirm: document.getElementById("handoff-confirm"),
  heroOptions: document.getElementById("hero-options"),
  heroOptions2: document.getElementById("hero-options-2"),
  modeOptions: document.getElementById("mode-options"),
  player2HeroSelection: document.getElementById("player2-hero-selection"),
  difficultyPicker: document.getElementById("difficulty-picker"),
  player1Label: document.getElementById("player1-label"),
  heroCardTrack: document.getElementById("hero-card-track"),
  heroCardPrev: document.getElementById("hero-card-prev"),
  heroCardNext: document.getElementById("hero-card-next"),
  heroCardTrack2: document.getElementById("hero-card-track-2"),
  heroCardPrev2: document.getElementById("hero-card-prev-2"),
  heroCardNext2: document.getElementById("hero-card-next-2"),
  difficultyToggle: document.getElementById("difficulty-toggle"),
  difficultySummary: document.getElementById("difficulty-summary"),
  difficultyOptions: document.getElementById("difficulty-options"),
  startGame: document.getElementById("start-game"),
  restartGame: document.getElementById("restart-game"),
  hand: document.getElementById("hand"),
  battleLog: document.getElementById("battle-log"),
  toast: document.getElementById("toast"),
  responsePanel: document.getElementById("response-panel"),
  responseDodge: document.getElementById("response-dodge"),
  responsePass: document.getElementById("response-pass"),
  skillButton: document.getElementById("skill-button"),
  skillIcon: document.getElementById("skill-icon"),
  enemyPortrait: document.getElementById("enemy-portrait"),
  playerPortrait: document.getElementById("player-portrait"),
  endTurn: document.getElementById("end-turn"),
  selectedCardPanel: document.getElementById("selected-card-panel"),
};

const DESIGN_WIDTH = 1920;
const DESIGN_HEIGHT = 1080;

let selectedHero = null;
let selectedOpponentHero = null;
let selectedDifficulty = "medium";
let gameMode = "pve";
let currentSeat = "player";
let currentState = null;
let toastTimer = null;
let previewedCardId = null;
let cardCatalog = {};
let availableHeroes = [];
const heroCardOffsets = { player1: 0, player2: 0 };

function fitStageToViewport() {
  if (!refs.shell) return;
  const viewportWidth = window.visualViewport?.width || window.innerWidth;
  const viewportHeight = window.visualViewport?.height || window.innerHeight;
  const scale = Math.min(viewportWidth / DESIGN_WIDTH, viewportHeight / DESIGN_HEIGHT);
  refs.shell.style.setProperty("--stage-scale", Math.max(scale, 0.01).toFixed(6));
}

window.addEventListener("resize", fitStageToViewport);
window.visualViewport?.addEventListener("resize", fitStageToViewport);
fitStageToViewport();

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    const error = new Error(payload.error?.message || "请求失败");
    error.payload = payload;
    throw error;
  }
  return payload;
}

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) element.textContent = value;
}

function setHealth(prefix, combatant) {
  setText(`${prefix}-health`, `${combatant.hp} / ${combatant.max_hp}`);
  const fill = document.getElementById(`${prefix}-health-fill`);
  if (fill) fill.style.width = `${Math.max(0, Math.min(100, (combatant.hp / combatant.max_hp) * 100))}%`;
}

function renderEnergy(prefix, energy) {
  setText(`${prefix}-energy`, energy);
  const pips = document.getElementById(`${prefix}-energy-pips`);
  pips.innerHTML = "";
  const pipCount = Math.max(3, energy);
  for (let index = 0; index < pipCount; index += 1) {
    const pip = document.createElement("span");
    pip.className = index < energy ? "energy-pip is-full" : "energy-pip";
    pips.appendChild(pip);
  }
}

function renderBonusEnergy(prefix, bonusEnergy) {
  const label = document.getElementById(`${prefix}-bonus-energy`);
  if (!label) return;
  const amount = Math.max(0, bonusEnergy || 0);
  label.classList.toggle("is-hidden", amount === 0);
  label.textContent = amount > 0 ? `下回合 +${amount}` : "";
}

function renderExhaustCount(prefix, exhaustPile) {
  const label = document.getElementById(`${prefix}-exhaust-count`);
  if (!label) return;
  const keys = Array.isArray(exhaustPile) ? exhaustPile : [];
  const names = keys.map((key) => cardCatalog[key]?.name || key);
  const hasCards = names.length > 0;
  label.classList.toggle("is-hidden", !hasCards);
  label.textContent = hasCards ? `已移除 ${names.length}` : "";
  label.title = hasCards ? `已移除：${names.join("、")}` : "";
  label.setAttribute("aria-label", hasCards ? label.title : "没有已移除卡牌");
}

function renderSkillState(prefix, skill) {
  setText(`${prefix}-skill`, `${skill.name} · ${skill.used_this_turn ? "本回合已使用" : "待用"}`);
}

function renderEquipment(side, equipment) {
  const slotLabels = { weapon: "武器", armor: "护甲" };
  Object.entries(slotLabels).forEach(([slotName, slotLabel]) => {
    const slot = document.getElementById(`${side}-${slotName}-slot`);
    if (!slot) return;
    const body = slot.querySelector(".equipment-slot-body");
    if (!body) return;
    const card = equipment?.[slotName];
    body.replaceChildren();
    body.classList.remove("has-art");
    slot.classList.toggle("is-equipped", Boolean(card));
    slot.classList.toggle("is-empty", !card);

    if (!card) {
      const status = document.createElement("span");
      status.className = "equipment-slot-status";
      status.textContent = "未装备";
      body.appendChild(status);
      return;
    }

    const asset = cardAssets[card.key];
    if (asset) {
      const image = document.createElement("img");
      image.className = "equipment-slot-art";
      image.src = `/static/assets/${asset}`;
      image.alt = `${card.name}图示`;
      body.appendChild(image);
      body.classList.add("has-art");
    }

    const copy = document.createElement("span");
    copy.className = "equipment-slot-copy";
    const name = document.createElement("strong");
    name.textContent = card.name || slotLabel;
    const effect = document.createElement("small");
    effect.textContent = effectCopy(card);
    copy.append(name, effect);
    body.appendChild(copy);
  });
}

function renderPortrait(side, hero) {
  const image = refs[`${side}Portrait`];
  if (!image) return;

  const fallbackAsset = fallbackPortraitAssets[side];
  const asset = heroPortraitAssets[side]?.[hero?.key] || fallbackAsset;
  image.src = `/static/assets/${asset}`;
  image.alt = `${hero?.name || (side === "player" ? "玩家角色" : "电脑对手")}头像`;
  image.dataset.heroKey = hero?.key || "";
  image.dataset.fallback = asset === fallbackAsset ? "true" : "false";
  image.onerror = () => {
    if (image.dataset.fallback === "true") return;
    image.dataset.fallback = "true";
    image.src = `/static/assets/${fallbackAsset}`;
  };
}

function renderEnemyIntent(intent) {
  const panel = document.getElementById("enemy-intent");
  const kind = document.getElementById("enemy-intent-kind");
  const name = document.getElementById("enemy-intent-name");
  const text = document.getElementById("enemy-intent-text");
  if (!panel || !kind || !name || !text) return;

  if (!intent) {
    panel.classList.add("is-hidden");
    panel.setAttribute("aria-hidden", "true");
    panel.dataset.kind = "";
    panel.dataset.source = "";
    panel.dataset.value = "";
    kind.textContent = "预计行动";
    name.textContent = "--";
    text.textContent = "";
    return;
  }

  panel.classList.remove("is-hidden");
  panel.setAttribute("aria-hidden", "false");
  panel.dataset.kind = intent.kind || "unknown";
  panel.dataset.source = intent.source || "";
  panel.dataset.value = String(intent.value ?? 0);
  kind.textContent = `${intentKindLabels[intent.kind] || "行动"} · ${intentSourceLabels[intent.source] || "预计"}`;
  name.textContent = intent.name || "未知行动";
  text.textContent = intent.text || "暂无行动说明";
}

function effectCopy(card) {
  return card.text || "暂无效果说明";
}

function cardTypeLabel(card) {
  return cardTypeLabels[card.effect_type] || "辅助";
}

function skillEffectCopy(skill) {
  if (skill.type === "shield") return `获得 ${skill.value} 点护盾`;
  if (skill.type === "damage_draw") return `造成 ${skill.value} 点伤害并抽 1 张牌`;
  if (skill.type === "damage") return `对对手造成 ${skill.value} 点伤害`;
  return "改变战斗状态";
}

function cardAvailability(card, energy, canPlay) {
  if (currentState?.phase === "RESPONSE" && card.effect_type === "dodge") {
    if (card.cost > energy) return `响应不可用（需要 ${card.cost}，当前 ${energy}）`;
    return `响应可用 · 消耗 ${card.cost} 点能量`;
  }
  if (!canPlay) return "当前不可出牌";
  if (card.cost > energy) return `能量不足（需要 ${card.cost}，当前 ${energy}）`;
  return `可使用 · 消耗 ${card.cost} 点能量`;
}

function renderSelectedCard(card, energy, canPlay) {
  const exhaustLabel = document.getElementById("selected-card-exhaust");
  if (!card) {
    exhaustLabel?.classList.add("is-hidden");
    setText("selected-card-cost", "⚡ --");
    setText("selected-card-name", "等待选择");
    setText("selected-card-type", "--");
    setText("selected-card-effect", "本回合没有可预览的手牌。");
    setText("selected-card-status", "等待下一个回合");
    return;
  }

  const availability = cardAvailability(card, energy, canPlay);
  previewedCardId = card.id;
  setText("selected-card-cost", `⚡ ${card.cost}`);
  setText("selected-card-name", card.name);
  setText("selected-card-type", cardTypeLabel(card));
  exhaustLabel?.classList.toggle("is-hidden", !card.exhaust);
  setText("selected-card-effect", effectCopy(card));
  setText("selected-card-status", availability);
  refs.selectedCardPanel.dataset.availability = card.cost > energy ? "energy" : canPlay ? "ready" : "blocked";
}

function renderHand(hand, canPlay, energy, isPlayerTurn) {
  refs.hand.innerHTML = "";
  setText("hand-count", `${hand.length} / 6`);
  const previewCard = hand.find((card) => card.id === previewedCardId) || hand[0];
  renderSelectedCard(previewCard, energy, canPlay);
  const handCenter = (hand.length - 1) / 2;
  const isResponsePhase = currentState?.phase === "RESPONSE";
  const responseActions = currentState?.available_actions?.respond || {};

  hand.forEach((card, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `battle-card card-${card.effect_type}`;
    const normalizedOffset = handCenter ? (index - handCenter) / handCenter : 0;
    button.style.setProperty("--hand-rotate", `${normalizedOffset * 3}deg`);
    button.style.setProperty("--hand-offset-y", `${Math.abs(normalizedOffset) * 8}px`);
    const unavailableByEnergy = card.cost > energy;
    const canUseAsResponse = isResponsePhase && card.effect_type === "dodge" && responseActions.dodge;
    button.disabled = isResponsePhase ? !canUseAsResponse : !isPlayerTurn;
    button.dataset.cardId = card.id;
    button.dataset.availability = canUseAsResponse ? "response" : unavailableByEnergy ? "energy" : canPlay ? "ready" : "blocked";
    button.title = cardAvailability(card, energy, canPlay);
    button.innerHTML = `
      <span class="card-face">
        <span class="card-cost" aria-label="消耗 ${card.cost} 点能量">${card.cost}</span>
        <span class="card-art-frame">
          <img class="card-art" src="/static/assets/${cardAssets[card.key]}" alt="">
        </span>
        <span class="card-copy">
          <span class="card-name">${card.name}</span>
          <span class="card-effect">${effectCopy(card)}</span>
          <span class="card-type-row">
            <span class="card-type">${cardTypeLabel(card)}</span>
            ${card.exhaust ? '<span class="card-exhaust">消耗</span>' : ""}
          </span>
        </span>
      </span>
    `;
    button.addEventListener("mouseenter", () => renderSelectedCard(card, energy, canPlay));
    button.addEventListener("focus", () => renderSelectedCard(card, energy, canPlay));
    button.addEventListener("click", () => {
      if (isResponsePhase) {
        if (canUseAsResponse) respondToAttack("dodge");
        return;
      }
      if (unavailableByEnergy) {
        showToast(`能量不足：需要 ${card.cost} 点，当前 ${energy} 点。`);
        return;
      }
      renderSelectedCard(card, energy, canPlay);
      playCard(card.id);
    });
    refs.hand.appendChild(button);
  });
}

function renderLog(log) {
  refs.battleLog.innerHTML = "";
  log.slice(-5).reverse().forEach((entry, index) => {
    const item = document.createElement("li");
    item.className = index === 0 ? "is-latest" : "";
    item.textContent = entry;
    refs.battleLog.appendChild(item);
  });
}

function viewerSide(state) {
  return state?.viewer || currentSeat;
}

function sideState(state, side) {
  if (side === "player") return state.player;
  return state.enemy;
}

function opponentSide(viewer) {
  return viewer === "player" ? "enemy" : "player";
}

function sideLabel(seat, mode) {
  if (mode === "pvp") {
    return seat === "player" ? "玩家 1" : "玩家 2";
  }
  return seat === "player" ? "你" : "电脑";
}

function phaseLabelText(state) {
  const mode = state?.mode || gameMode;
  const viewer = viewerSide(state);
  const phase = state?.phase;
  if (phase === "VICTORY" || phase === "DEFEAT" || phase === "DRAW") {
    return phase === "VICTORY" ? "胜利" : phase === "DEFEAT" ? "失败" : "平局";
  }
  const isMyTurn = (phase === "PLAYER_TURN" && viewer === "player") || (phase === "ENEMY_TURN" && viewer === "enemy");
  if (phase === "RESPONSE") return "响应窗口";
  if (isMyTurn) return "你的回合";
  return mode === "pvp" ? `${sideLabel(opponentSide(viewer), mode)}回合` : "对手行动";
}

function phaseHintText(state) {
  const mode = state?.mode || gameMode;
  const viewer = viewerSide(state);
  const phase = state?.phase;
  if (phase === "VICTORY" || phase === "DEFEAT" || phase === "DRAW") {
    return "本局战斗已结束";
  }
  const isMyTurn = (phase === "PLAYER_TURN" && viewer === "player") || (phase === "ENEMY_TURN" && viewer === "enemy");
  if (phase === "RESPONSE") return "选择是否响应这次攻击";
  if (isMyTurn) return "选择卡牌，发动技能，击败敌人";
  return mode === "pvp" ? `请把设备交给${sideLabel(opponentSide(viewer), mode)}` : "对手正在做出选择…";
}

function renderResponse(state) {
  const response = state.response || { active: false };
  const isActive = state.phase === "RESPONSE" && response.active;
  refs.responsePanel.classList.toggle("is-hidden", !isActive);
  refs.responseDodge.disabled = !isActive || !state.available_actions.respond.dodge;
  refs.responsePass.disabled = !isActive || !state.available_actions.respond.pass;
  if (!isActive) return;
  const attackerLabel = sideLabel(response.attacker || "player", state.mode);
  setText("response-prompt", `${attackerLabel}使用【${response.card_name}】，即将造成 ${response.damage} 点伤害`);
  setText("response-dodge-cost", `⚡ ${response.dodge_cost}`);
}

function renderState(state) {
  currentState = state;
  const viewer = viewerSide(state);
  const opponent = opponentSide(viewer);
  const self = sideState(state, viewer);
  const foe = sideState(state, opponent);

  renderPortrait("enemy", foe.hero);
  renderPortrait("player", self.hero);
  setText("round-number", state.round_number);
  setText("phase-label", phaseLabelText(state));
  setText("phase-hint", phaseHintText(state));
  setText("enemy-name", foe.name);

  if (state.mode === "pvp") {
    setText("enemy-hero", `${sideLabel(opponent, state.mode)}：${foe.hero.name}`);
    setText("enemy-difficulty", "双人热座");
  } else {
    setText("enemy-hero", `电脑英雄：${foe.hero.name}`);
    setText(
      "enemy-difficulty",
      `AI 对手 · ${difficultyLabels[state.ai_difficulty] || state.ai_difficulty}`,
    );
  }

  setText("player-name", self.hero.name);
  setHealth("enemy", foe);
  setHealth("player", self);
  setText("enemy-shield", foe.shield);
  setText("player-shield", self.shield);
  renderEnergy("enemy", foe.energy);
  renderEnergy("player", self.energy);
  renderBonusEnergy("enemy", foe.bonus_energy_next_turn);
  renderBonusEnergy("player", self.bonus_energy_next_turn);
  renderExhaustCount("enemy", foe.exhaust_pile);
  renderExhaustCount("player", self.exhaust_pile);
  renderEquipment("enemy", foe.equipment);
  renderEquipment("player", self.equipment);
  renderEnemyIntent(state.mode === "pve" ? foe.intent : null);
  renderSkillState("enemy", foe.skill);
  setText("skill-name", self.skill.name);
  setText("skill-effect", skillEffectCopy(self.skill));
  const skillUnavailableReason = self.skill.used_this_turn
    ? "本回合已使用"
    : self.energy < self.skill.cost
      ? `能量不足（需要 ${self.skill.cost}，当前 ${self.energy}）`
      : `消耗 ${self.skill.cost} 点能量 · 每回合限用一次`;
  setText("skill-description", skillUnavailableReason);
  setText("skill-cost", `⚡ ${self.skill.cost}`);
  renderResponse(state);
  const skillAsset = heroSkillAssets[self.hero.key];
  if (skillAsset && refs.skillIcon) {
    refs.skillIcon.src = `/static/assets/${skillAsset}`;
    refs.skillIcon.alt = `${self.skill.name}技能图示`;
  }
  refs.skillButton.disabled = !state.available_actions.use_skill;
  refs.skillButton.title = skillUnavailableReason;
  refs.skillButton.dataset.availability = state.available_actions.use_skill ? "ready" : "blocked";
  refs.endTurn.disabled = !state.available_actions.end_turn;
  const isViewerTurn = (viewer === "player" && state.phase === "PLAYER_TURN") || (viewer === "enemy" && state.phase === "ENEMY_TURN");
  renderHand(self.hand, state.available_actions.play_card, self.energy, isViewerTurn);
  renderLog(state.log);

  const phaseKey = state.phase === "PLAYER_TURN" ? "player" : state.phase === "ENEMY_TURN" ? "enemy" : state.phase === "RESPONSE" ? "response" : "finished";
  refs.shell.dataset.phase = phaseKey;

  if (state.phase === "VICTORY" || state.phase === "DEFEAT" || state.phase === "DRAW") {
    showResult(state);
  }
}

function showToast(message) {
  refs.toast.textContent = message;
  refs.toast.classList.add("is-visible");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => refs.toast.classList.remove("is-visible"), 2600);
}

function showResult(state) {
  const result = state.result || {};
  const self = sideState(state, currentSeat);
  const fallbackText = `第 ${state.round_number} 回合 · ${self.hero.name} 最终生命值 ${self.hp}`;
  const resultReason = document.getElementById("result-reason");

  document.getElementById("result-title").textContent = outcomeLabels[state.phase] || "战斗结束";
  document.getElementById("result-copy").textContent = result.text || fallbackText;
  resultReason.textContent = resultReasonLabels[result.reason] || "";
  resultReason.classList.toggle("is-hidden", !resultReason.textContent);
  refs.resultOverlay.classList.remove("is-hidden");
}

function clearHeroSelection(container) {
  container.querySelectorAll(".hero-option").forEach((item) => item.classList.remove("is-selected"));
}

function renderHeroCardPreview(hero) {
  renderHeroCardPreviewInto(hero, "player1");
}

function renderHeroCardPreviewInto(hero, previewKey) {
  const suffix = previewKey === "player2" ? "2" : "";
  const track = refs[`heroCardTrack${suffix}`];
  const previous = refs[`heroCardPrev${suffix}`];
  const next = refs[`heroCardNext${suffix}`];
  if (!track || !previous || !next) return;

  const deck = Array.isArray(hero?.deck) ? hero.deck : [];
  const offset = heroCardOffsets[previewKey] || 0;
  track.replaceChildren();
  if (deck.length === 0) {
    previous.disabled = true;
    next.disabled = true;
    return;
  }

  const visibleCount = Math.min(5, deck.length);
  const center = (visibleCount - 1) / 2;
  for (let index = 0; index < visibleCount; index += 1) {
    const card = deck[(offset + index) % deck.length];
    const item = document.createElement("div");
    item.className = "hero-card-thumb";
    item.style.setProperty("--preview-rotate", `${(index - center) * 1.25}deg`);
    item.style.setProperty("--preview-offset-y", `${Math.abs(index - center) * 3}px`);
    item.setAttribute("aria-label", `${card.name || cardCatalog[card.key]?.name || card.key}，${card.count || 1} 张`);

    const image = document.createElement("img");
    const asset = cardAssets[card.key];
    image.alt = "";
    if (asset) {
      image.src = `/static/assets/${asset}`;
    } else {
      item.classList.add("is-missing");
    }
    item.appendChild(image);
    track.appendChild(item);
  }

  const canRotate = deck.length > visibleCount;
  previous.disabled = !canRotate;
  next.disabled = !canRotate;
}

function renderHeroes(heroes, container, onSelect) {
  container.innerHTML = "";
  heroes.forEach((hero) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "hero-option";
    button.dataset.heroKey = hero.key;
    const portrait = heroPortraitAssets.player?.[hero.key] || fallbackPortraitAssets.player;
    button.innerHTML = `<span class="hero-option-portrait"><img src="/static/assets/${portrait}" alt=""></span><strong>${hero.name}</strong><span>${hero.max_hp} 生命值</span><small>技能：${hero.skill_name}</small>`;
    button.addEventListener("click", () => {
      onSelect?.(hero, button);
      updateStartButton();
    });
    container.appendChild(button);
  });
}

function updateDifficultySummary() {
  if (!refs.difficultySummary) return;
  refs.difficultySummary.textContent = `${difficultyLabels[selectedDifficulty]}（${difficultyDescriptions[selectedDifficulty]}）`;
}

function setDifficultyExpanded(isExpanded) {
  if (!refs.difficultyToggle || !refs.difficultyOptions) return;
  refs.difficultyToggle.setAttribute("aria-expanded", String(isExpanded));
  refs.difficultyOptions.classList.toggle("is-open", isExpanded);
  refs.difficultyOptions.setAttribute("aria-hidden", String(!isExpanded));
}

function updateStartButton() {
  const canStart = selectedHero && (gameMode === "pve" || selectedOpponentHero);
  refs.startGame.disabled = !canStart;
}

function selectMode(button) {
  gameMode = button.dataset.mode;
  refs.modeOptions.querySelectorAll(".mode-option").forEach((item) => {
    const isSelected = item === button;
    item.classList.toggle("is-selected", isSelected);
    item.setAttribute("aria-pressed", String(isSelected));
  });

  refs.player2HeroSelection.classList.toggle("is-hidden", gameMode === "pve");
  refs.difficultyPicker.classList.toggle("is-hidden", gameMode === "pvp");
  refs.heroSelectionPanel.classList.toggle("is-pvp", gameMode === "pvp");
  refs.player1Label.textContent = gameMode === "pvp" ? "玩家 1" : "你的英雄";

  if (gameMode === "pve") {
    selectedOpponentHero = null;
    clearHeroSelection(refs.heroOptions2);
  }
  updateStartButton();
}

function selectDifficulty(button) {
  selectedDifficulty = button.dataset.difficulty;
  refs.difficultyOptions.querySelectorAll(".difficulty-option").forEach((item) => {
    const isSelected = item === button;
    item.classList.toggle("is-selected", isSelected);
    item.setAttribute("aria-pressed", String(isSelected));
  });
  updateDifficultySummary();
  setDifficultyExpanded(false);
}

function gameUrl(path) {
  if (path === "/api/game" || path.startsWith("/api/game?")) {
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${separator}seat=${currentSeat}`;
  }
  return path;
}

async function fetchGameState() {
  const payload = await requestJson(gameUrl("/api/game"));
  renderState(payload.data);
  return payload.data;
}

async function beginGame() {
  if (!selectedHero) return;
  if (gameMode === "pvp" && !selectedOpponentHero) return;
  refs.startGame.disabled = true;
  currentSeat = "player";
  try {
    const payload = await requestJson("/api/game", {
      method: "POST",
      body: JSON.stringify({
        hero_key: selectedHero,
        ai_difficulty: selectedDifficulty,
        mode: gameMode,
        opponent_hero_key: gameMode === "pvp" ? selectedOpponentHero : undefined,
      }),
    });
    refs.startOverlay.classList.add("is-hidden");
    renderState(payload.data);
    if (gameMode === "pvp" && payload.data.phase === "ENEMY_TURN") {
      promptHandoff(payload.data);
    }
  } catch (error) {
    refs.startGame.disabled = false;
    showToast(error.message);
  }
}

async function playCard(cardId) {
  try {
    const payload = await requestJson("/api/game/actions/card", {
      method: "POST",
      body: JSON.stringify({ card_id: cardId, seat: currentSeat }),
    });
    renderState(payload.data);
    maybePromptHandoff(payload.data);
  } catch (error) {
    if (error.payload?.data) renderState(error.payload.data);
    showToast(error.message);
  }
}

async function useSkill() {
  try {
    const payload = await requestJson("/api/game/actions/skill", {
      method: "POST",
      body: JSON.stringify({ seat: currentSeat }),
    });
    renderState(payload.data);
    maybePromptHandoff(payload.data);
  } catch (error) {
    if (error.payload?.data) renderState(error.payload.data);
    showToast(error.message);
  }
}

async function endTurn() {
  try {
    const payload = await requestJson("/api/game/actions/end-turn", {
      method: "POST",
      body: JSON.stringify({ seat: currentSeat }),
    });
    renderState(payload.data);
    maybePromptHandoff(payload.data);
  } catch (error) {
    if (error.payload?.data) renderState(error.payload.data);
    showToast(error.message);
  }
}

async function respondToAttack(action) {
  refs.responseDodge.disabled = true;
  refs.responsePass.disabled = true;
  try {
    const payload = await requestJson("/api/game/actions/respond", {
      method: "POST",
      body: JSON.stringify({ action, seat: currentSeat }),
    });
    renderState(payload.data);
    maybePromptHandoff(payload.data);
  } catch (error) {
    if (error.payload?.data) renderState(error.payload.data);
    showToast(error.message);
  }
}

function expectedSeatForPhase(phase) {
  if (phase === "PLAYER_TURN") return "player";
  if (phase === "ENEMY_TURN") return "enemy";
  return null;
}

function maybePromptHandoff(state) {
  if (state.mode !== "pvp" || state.phase === "VICTORY" || state.phase === "DEFEAT" || state.phase === "DRAW") return;
  const expected = expectedSeatForPhase(state.phase);
  if (expected && expected !== currentSeat) {
    promptHandoff(state);
  }
}

function promptHandoff(state) {
  const expected = expectedSeatForPhase(state.phase);
  if (!expected) return;
  const label = sideLabel(expected, "pvp");
  refs.handoffTitle.textContent = `轮到${label}`;
  refs.handoffCopy.textContent = `请把设备交给${label}，确认后继续。`;
  refs.handoffConfirm.dataset.targetSeat = expected;
  refs.handoffOverlay.classList.remove("is-hidden");
}

async function confirmHandoff() {
  const targetSeat = refs.handoffConfirm.dataset.targetSeat;
  if (!targetSeat) return;
  currentSeat = targetSeat;
  refs.handoffOverlay.classList.add("is-hidden");
  refs.handoffConfirm.dataset.targetSeat = "";
  try {
    await fetchGameState();
  } catch (error) {
    showToast(error.message);
  }
}

async function restartGame() {
  await requestJson("/api/game/restart", { method: "POST" });
  currentState = null;
  currentSeat = "player";
  selectedHero = null;
  selectedOpponentHero = null;
  clearHeroSelection(refs.heroOptions);
  clearHeroSelection(refs.heroOptions2);
  refs.resultOverlay.classList.add("is-hidden");
  refs.startOverlay.classList.remove("is-hidden");
  refs.startGame.disabled = true;
  selectedDifficulty = "medium";
  refs.difficultyOptions.querySelectorAll(".difficulty-option").forEach((item) => {
    const isSelected = item.dataset.difficulty === selectedDifficulty;
    item.classList.toggle("is-selected", isSelected);
    item.setAttribute("aria-pressed", String(isSelected));
  });
  updateDifficultySummary();
  setDifficultyExpanded(false);
  heroCardOffsets.player1 = 0;
  heroCardOffsets.player2 = 0;
  renderHeroCardPreview(availableHeroes[0]);
  renderHeroCardPreviewInto(availableHeroes[0], "player2");
  updateStartButton();
}

async function initialise() {
  const [heroesPayload, cardsPayload] = await Promise.all([
    requestJson("/api/heroes"),
    requestJson("/api/cards"),
  ]);
  cardCatalog = Object.fromEntries(cardsPayload.data.map((card) => [card.key, card]));
  availableHeroes = heroesPayload.data;
  renderHeroes(availableHeroes, refs.heroOptions, (hero, button) => {
    selectedHero = hero.key;
    clearHeroSelection(refs.heroOptions);
    button.classList.add("is-selected");
    heroCardOffsets.player1 = 0;
    renderHeroCardPreview(hero);
  });
  renderHeroes(availableHeroes, refs.heroOptions2, (hero, button) => {
    selectedOpponentHero = hero.key;
    clearHeroSelection(refs.heroOptions2);
    button.classList.add("is-selected");
    heroCardOffsets.player2 = 0;
    renderHeroCardPreviewInto(hero, "player2");
  });
  renderHeroCardPreview(availableHeroes[0]);
  renderHeroCardPreviewInto(availableHeroes[0], "player2");
  updateDifficultySummary();
  setDifficultyExpanded(false);
  if (refs.shell.dataset.hasGame !== "true") {
    refs.startOverlay.classList.remove("is-hidden");
    return;
  }
  try {
    const gamePayload = await fetchGameState();
    refs.startOverlay.classList.add("is-hidden");
    renderState(gamePayload);
    maybePromptHandoff(gamePayload);
  } catch (error) {
    refs.startOverlay.classList.remove("is-hidden");
  }
}

refs.modeOptions.addEventListener("click", (event) => {
  const button = event.target.closest(".mode-option");
  if (button) selectMode(button);
});
refs.difficultyOptions.addEventListener("click", (event) => {
  const button = event.target.closest(".difficulty-option");
  if (button) selectDifficulty(button);
});
refs.difficultyToggle.addEventListener("click", () => {
  const isExpanded = refs.difficultyToggle.getAttribute("aria-expanded") === "true";
  setDifficultyExpanded(!isExpanded);
});
refs.heroCardPrev.addEventListener("click", () => {
  const hero = availableHeroes.find((item) => item.key === selectedHero) || availableHeroes[0];
  const deck = Array.isArray(hero?.deck) ? hero.deck : [];
  if (deck.length <= 5) return;
  heroCardOffsets.player1 = (heroCardOffsets.player1 - 1 + deck.length) % deck.length;
  renderHeroCardPreview(hero);
});
refs.heroCardNext.addEventListener("click", () => {
  const hero = availableHeroes.find((item) => item.key === selectedHero) || availableHeroes[0];
  const deck = Array.isArray(hero?.deck) ? hero.deck : [];
  if (deck.length <= 5) return;
  heroCardOffsets.player1 = (heroCardOffsets.player1 + 1) % deck.length;
  renderHeroCardPreview(hero);
});
refs.heroCardPrev2.addEventListener("click", () => {
  const hero = availableHeroes.find((item) => item.key === selectedOpponentHero) || availableHeroes[0];
  const deck = Array.isArray(hero?.deck) ? hero.deck : [];
  if (deck.length <= 5) return;
  heroCardOffsets.player2 = (heroCardOffsets.player2 - 1 + deck.length) % deck.length;
  renderHeroCardPreviewInto(hero, "player2");
});
refs.heroCardNext2.addEventListener("click", () => {
  const hero = availableHeroes.find((item) => item.key === selectedOpponentHero) || availableHeroes[0];
  const deck = Array.isArray(hero?.deck) ? hero.deck : [];
  if (deck.length <= 5) return;
  heroCardOffsets.player2 = (heroCardOffsets.player2 + 1) % deck.length;
  renderHeroCardPreviewInto(hero, "player2");
});
refs.startGame.addEventListener("click", beginGame);
refs.restartGame.addEventListener("click", restartGame);
refs.handoffConfirm.addEventListener("click", confirmHandoff);
refs.skillButton.addEventListener("click", useSkill);
refs.endTurn.addEventListener("click", endTurn);
refs.responseDodge.addEventListener("click", () => respondToAttack("dodge"));
refs.responsePass.addEventListener("click", () => respondToAttack("pass"));
initialise().catch((error) => showToast(error.message));
