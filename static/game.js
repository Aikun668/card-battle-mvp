const cardAssets = {
  slash: "New/3f8072ff-4400-4edd-b4ac-745b97a7114f.png",
  heavy_strike: "New/936d5fc4-51f2-45f0-8e81-80ed5ae70a79.png",
  shield: "New/93a671c6-1d36-4719-93b7-994b63663898.png",
  heal: "New/91f5a0fb-dac5-4edd-bb5a-32238838b495.png",
  fireball: "New/5cd7bb88-da04-43cd-bd40-2856a50d792d.png",
  dodge: "New/93a671c6-1d36-4719-93b7-994b63663898.png",
};

const heroSkillAssets = {
  warrior: cardAssets.shield,
  mage: cardAssets.fireball,
  ranger: cardAssets.slash,
};

const phaseLabels = {
  PLAYER_TURN: ["玩家回合", "选择卡牌，发动技能，击败敌人"],
  ENEMY_TURN: ["电脑行动", "对手正在做出选择…"],
  RESPONSE: ["敌方攻击", "选择是否响应这次攻击"],
  VICTORY: ["胜利", "你赢下了这场对决"],
  DEFEAT: ["失败", "再调整一次出牌顺序"],
  DRAW: ["平局", "回合上限已到，双方未分胜负"],
};

const outcomeLabels = {
  VICTORY: "胜利",
  DEFEAT: "失败",
  DRAW: "平局",
};

const difficultyLabels = {
  easy: "简单",
  medium: "中等",
  hard: "困难",
};

const refs = {
  shell: document.getElementById("game-shell"),
  startOverlay: document.getElementById("start-overlay"),
  resultOverlay: document.getElementById("result-overlay"),
  heroOptions: document.getElementById("hero-options"),
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
  endTurn: document.getElementById("end-turn"),
  selectedCardPanel: document.getElementById("selected-card-panel"),
};

const DESIGN_WIDTH = 1920;
const DESIGN_HEIGHT = 1080;

let selectedHero = null;
let selectedDifficulty = "medium";
let currentState = null;
let toastTimer = null;
let previewedCardId = null;

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

function renderEnergy(energy) {
  setText("player-energy", energy);
  const pips = document.getElementById("energy-pips");
  pips.innerHTML = "";
  for (let index = 0; index < 3; index += 1) {
    const pip = document.createElement("span");
    pip.className = index < energy ? "energy-pip is-full" : "energy-pip";
    pips.appendChild(pip);
  }
}

function effectCopy(card) {
  if (card.effect_type === "damage") return `造成 ${card.value} 点伤害`;
  if (card.effect_type === "shield") return `获得 ${card.value} 点护盾`;
  if (card.effect_type === "heal") return `恢复 ${card.value} 点生命值`;
  if (card.effect_type === "dodge") return "抵消敌人当前一次攻击";
  return "改变战斗状态";
}

function cardTypeLabel(card) {
  if (card.effect_type === "dodge") return "响应";
  if (card.effect_type === "damage") return "攻击";
  if (card.effect_type === "shield") return "防御";
  return "辅助";
}

function skillEffectCopy(skill) {
  if (skill.type === "shield") return `获得 ${skill.value} 点护盾`;
  if (skill.type === "damage_draw") return `造成 ${skill.value} 点伤害并抽 1 张牌`;
  if (skill.type === "damage") return `对电脑造成 ${skill.value} 点伤害`;
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
  if (!card) {
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
          <span class="card-type">${cardTypeLabel(card)}</span>
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

function renderResponse(state) {
  const response = state.response || { active: false };
  const isActive = state.phase === "RESPONSE" && response.active;
  refs.responsePanel.classList.toggle("is-hidden", !isActive);
  refs.responseDodge.disabled = !isActive || !state.available_actions.respond.dodge;
  refs.responsePass.disabled = !isActive || !state.available_actions.respond.pass;
  if (!isActive) return;
  setText("response-prompt", `电脑使用【${response.card_name}】，即将造成 ${response.damage} 点伤害`);
  setText("response-dodge-cost", `⚡ ${response.dodge_cost}`);
}

function renderState(state) {
  currentState = state;
  const phase = phaseLabels[state.phase] || [state.phase, ""];
  setText("round-number", state.round_number);
  setText("phase-label", phase[0]);
  setText("phase-hint", phase[1]);
  setText("enemy-name", state.enemy.name);
  setText(
    "enemy-difficulty",
    `AI 对手 · ${difficultyLabels[state.ai_difficulty] || state.ai_difficulty}`,
  );
  setText("player-name", state.hero.name);
  setHealth("enemy", state.enemy);
  setHealth("player", state.player);
  setText("enemy-shield", state.enemy.shield);
  setText("player-shield", state.player.shield);
  renderEnergy(state.player.energy);
  setText("skill-name", state.skill.name);
  setText("skill-effect", skillEffectCopy(state.skill));
  const skillUnavailableReason = state.skill.used_this_turn
    ? "本回合已使用"
    : state.player.energy < state.skill.cost
      ? `能量不足（需要 ${state.skill.cost}，当前 ${state.player.energy}）`
      : `消耗 ${state.skill.cost} 点能量 · 每回合限用一次`;
  setText("skill-description", skillUnavailableReason);
  setText("skill-cost", `⚡ ${state.skill.cost}`);
  renderResponse(state);
  const skillAsset = heroSkillAssets[state.hero.key];
  if (skillAsset && refs.skillIcon) {
    refs.skillIcon.src = `/static/assets/${skillAsset}`;
    refs.skillIcon.alt = `${state.skill.name}技能图示`;
  }
  refs.skillButton.disabled = !state.available_actions.use_skill;
  refs.skillButton.title = skillUnavailableReason;
  refs.skillButton.dataset.availability = state.available_actions.use_skill ? "ready" : "blocked";
  refs.endTurn.disabled = !state.available_actions.end_turn;
  renderHand(state.hand, state.available_actions.play_card, state.player.energy, state.phase === "PLAYER_TURN");
  renderLog(state.log);

  if (state.phase === "PLAYER_TURN") refs.shell.dataset.phase = "player";
  else if (state.phase === "RESPONSE") refs.shell.dataset.phase = "response";
  else if (state.phase === "ENEMY_TURN") refs.shell.dataset.phase = "enemy";
  else refs.shell.dataset.phase = "finished";

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
  document.getElementById("result-title").textContent = outcomeLabels[state.phase];
  document.getElementById("result-copy").textContent = `第 ${state.round_number} 回合 · ${state.hero.name} 最终生命值 ${state.player.hp}`;
  refs.resultOverlay.classList.remove("is-hidden");
}

function renderHeroes(heroes) {
  refs.heroOptions.innerHTML = "";
  heroes.forEach((hero) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "hero-option";
    button.dataset.heroKey = hero.key;
    button.innerHTML = `<strong>${hero.name}</strong><span>${hero.max_hp} 生命值</span><small>${hero.skill_name}</small>`;
    button.addEventListener("click", () => {
      selectedHero = hero.key;
      document.querySelectorAll(".hero-option").forEach((item) => item.classList.remove("is-selected"));
      button.classList.add("is-selected");
      refs.startGame.disabled = false;
    });
    refs.heroOptions.appendChild(button);
  });
}

function selectDifficulty(button) {
  selectedDifficulty = button.dataset.difficulty;
  refs.difficultyOptions.querySelectorAll(".difficulty-option").forEach((item) => {
    const isSelected = item === button;
    item.classList.toggle("is-selected", isSelected);
    item.setAttribute("aria-pressed", String(isSelected));
  });
}

async function beginGame() {
  if (!selectedHero) return;
  refs.startGame.disabled = true;
  try {
    const payload = await requestJson("/api/game", {
      method: "POST",
      body: JSON.stringify({
        hero_key: selectedHero,
        ai_difficulty: selectedDifficulty,
      }),
    });
    refs.startOverlay.classList.add("is-hidden");
    renderState(payload.data);
  } catch (error) {
    refs.startGame.disabled = false;
    showToast(error.message);
  }
}

async function playCard(cardId) {
  try {
    const payload = await requestJson("/api/game/actions/card", {
      method: "POST",
      body: JSON.stringify({ card_id: cardId }),
    });
    renderState(payload.data);
  } catch (error) {
    if (error.payload?.data) renderState(error.payload.data);
    showToast(error.message);
  }
}

async function useSkill() {
  try {
    const payload = await requestJson("/api/game/actions/skill", { method: "POST" });
    renderState(payload.data);
  } catch (error) {
    if (error.payload?.data) renderState(error.payload.data);
    showToast(error.message);
  }
}

async function endTurn() {
  try {
    const payload = await requestJson("/api/game/actions/end-turn", { method: "POST" });
    renderState(payload.data);
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
      body: JSON.stringify({ action }),
    });
    renderState(payload.data);
  } catch (error) {
    if (error.payload?.data) renderState(error.payload.data);
    showToast(error.message);
  }
}

async function restartGame() {
  await requestJson("/api/game/restart", { method: "POST" });
  currentState = null;
  selectedHero = null;
  refs.resultOverlay.classList.add("is-hidden");
  refs.startOverlay.classList.remove("is-hidden");
  refs.startGame.disabled = true;
  document.querySelectorAll(".hero-option").forEach((item) => item.classList.remove("is-selected"));
}

async function initialise() {
  const heroesPayload = await requestJson("/api/heroes");
  renderHeroes(heroesPayload.data);
  if (refs.shell.dataset.hasGame !== "true") {
    refs.startOverlay.classList.remove("is-hidden");
    return;
  }
  try {
    const gamePayload = await requestJson("/api/game");
    refs.startOverlay.classList.add("is-hidden");
    renderState(gamePayload.data);
  } catch (error) {
    refs.startOverlay.classList.remove("is-hidden");
  }
}

refs.difficultyOptions.addEventListener("click", (event) => {
  const button = event.target.closest(".difficulty-option");
  if (button) selectDifficulty(button);
});
refs.startGame.addEventListener("click", beginGame);
refs.restartGame.addEventListener("click", restartGame);
refs.skillButton.addEventListener("click", useSkill);
refs.endTurn.addEventListener("click", endTurn);
refs.responseDodge.addEventListener("click", () => respondToAttack("dodge"));
refs.responsePass.addEventListener("click", () => respondToAttack("pass"));
initialise().catch((error) => showToast(error.message));
