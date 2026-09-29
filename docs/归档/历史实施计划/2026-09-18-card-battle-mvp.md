# Card Battle MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a playable local Flask card-battle MVP where one player chooses a hero, plays cards against a deterministic computer opponent, and receives a win, loss, or draw result.

**Architecture:** Keep every battle rule in a pure-Python `game` package. Flask only stores a JSON-safe battle snapshot in the session, maps HTTP requests to battle operations, and renders templates. SQLite persists finished-match summaries only; it must not own live battle state.

**Tech Stack:** Python 3.11+, Flask, built-in `sqlite3`, pytest, HTML, CSS, and minimal browser JavaScript.

**Spec:** `docs/产品方案/基础规则/mvp.md` and `docs/产品方案/基础规则/interaction-design.md`

## Global Constraints

- Keep the implementation single-player and local; do not add accounts, networking, multiplayer, payments, rankings, or external AI APIs.
- Use only the three heroes, five cards, card costs, effects, deck composition, turn cap, and computer priority specified in the two spec documents.
- Each completed `POST` action must redirect to a `GET` page so browser refresh does not repeat a move.
- Core rule tests must not import Flask or create a database.
- Use Python type hints and clear Chinese UI copy.
- Keep all battle actions deterministic in tests by injecting a seeded `random.Random` instance.

---

## Planned File Structure

```text
app.py
requirements.txt
game/
  __init__.py
  catalog.py
  models.py
  battle.py
  ai.py
  session_state.py
  repository.py
templates/
  base.html
  index.html
  heroes.html
  battle.html
  result.html
static/
  style.css
tests/
  conftest.py
  test_catalog.py
  test_battle.py
  test_ai.py
  test_session_state.py
  test_repository.py
  test_app.py
instance/
  .gitkeep
```

## Shared Interfaces

The following names are the contract between tasks. Do not rename them after implementation.

```python
# game/models.py
class BattlePhase(StrEnum):
    START = "START"
    HERO_SELECTION = "HERO_SELECTION"
    PLAYER_TURN = "PLAYER_TURN"
    ENEMY_TURN = "ENEMY_TURN"
    VICTORY = "VICTORY"
    DEFEAT = "DEFEAT"
    DRAW = "DRAW"

@dataclass(frozen=True)
class CardDefinition:
    key: str
    name: str
    cost: int
    effect_type: str
    value: int

@dataclass(frozen=True)
class HeroDefinition:
    key: str
    name: str
    max_hp: int
    skill_name: str
    skill_type: str
    skill_value: int

@dataclass
class Combatant:
    name: str
    max_hp: int
    hp: int
    shield: int = 0
    energy: int = 3

@dataclass
class ActionResult:
    ok: bool
    message: str

# game/battle.py
class BattleState:
    @classmethod
    def create(cls, hero_key: str, rng: random.Random) -> "BattleState": ...
    def play_card(self, card_instance_id: str) -> ActionResult: ...
    def use_skill(self) -> ActionResult: ...
    def end_player_turn(self) -> ActionResult: ...
    def resolve_enemy_turn(self) -> ActionResult: ...
    def is_finished(self) -> bool: ...
    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, payload: dict) -> "BattleState": ...
```

### Task 1: Establish the package, definitions, and test runner

**Files:**

- Create: `requirements.txt`
- Create: `game/__init__.py`
- Create: `game/models.py`
- Create: `game/catalog.py`
- Create: `tests/conftest.py`
- Create: `tests/test_catalog.py`
- Create: `instance/.gitkeep`
- Modify: `.gitignore`

**Interfaces:**

- Produces `BattlePhase`, `CardDefinition`, `HeroDefinition`, `Combatant`, and `ActionResult` for all later tasks.
- Produces `HEROES`, `CARDS`, and `FIXED_DECK_KEYS` for battle construction.

- [ ] **Step 1: Add dependencies and package directories**

Create `requirements.txt` with exactly:

```text
Flask>=3.0,<4.0
pytest>=8.0,<9.0
ruff>=0.6,<1.0
```

Create the package and test directories shown in the planned file structure. Add an empty `game/__init__.py` and `instance/.gitkeep`.

- [ ] **Step 2: Write the first failing catalog tests**

Create `tests/test_catalog.py`:

```python
from game.catalog import CARDS, FIXED_DECK_KEYS, HEROES


def test_catalog_has_the_three_specified_heroes():
    assert set(HEROES) == {"warrior", "mage", "ranger"}
    assert HEROES["warrior"].max_hp == 32
    assert HEROES["mage"].max_hp == 24
    assert HEROES["ranger"].max_hp == 27


def test_fixed_deck_matches_the_twelve_card_mvp_deck():
    assert len(FIXED_DECK_KEYS) == 12
    assert FIXED_DECK_KEYS.count("slash") == 4
    assert FIXED_DECK_KEYS.count("heavy_strike") == 2
    assert FIXED_DECK_KEYS.count("shield") == 3
    assert FIXED_DECK_KEYS.count("heal") == 2
    assert FIXED_DECK_KEYS.count("fireball") == 1
    assert {card.key for card in CARDS.values()} == set(FIXED_DECK_KEYS)
```

- [ ] **Step 3: Run the test to prove the package is missing**

Run:

```bash
pytest tests/test_catalog.py -v
```

Expected result: collection or import failure because `game.catalog` does not exist yet.

- [ ] **Step 4: Implement models and the fixed catalog**

In `game/models.py`, implement the shared dataclasses and enum shown above.

In `game/catalog.py`, define exactly these data values:

```python
HEROES = {
    "warrior": HeroDefinition("warrior", "战士", 32, "守护", "shield", 8),
    "mage": HeroDefinition("mage", "法师", 24, "火球术", "damage", 10),
    "ranger": HeroDefinition("ranger", "游侠", 27, "连射", "damage_draw", 6),
}

CARDS = {
    "slash": CardDefinition("slash", "斩击", 1, "damage", 6),
    "heavy_strike": CardDefinition("heavy_strike", "重击", 2, "damage", 10),
    "shield": CardDefinition("shield", "护盾", 1, "shield", 6),
    "heal": CardDefinition("heal", "治疗", 2, "heal", 6),
    "fireball": CardDefinition("fireball", "火球", 3, "damage", 14),
}

FIXED_DECK_KEYS = [
    "slash", "slash", "slash", "slash",
    "heavy_strike", "heavy_strike",
    "shield", "shield", "shield",
    "heal", "heal", "fireball",
]
```

- [ ] **Step 5: Run the catalog tests**

Run:

```bash
pytest tests/test_catalog.py -v
```

Expected result: 2 passing tests.

- [ ] **Step 6: Commit the catalog layer**

```bash
git add .gitignore requirements.txt game tests/test_catalog.py instance/.gitkeep
git commit -m "feat: add battle catalog definitions"
```

### Task 2: Implement pure battle state and player actions

**Files:**

- Create: `game/battle.py`
- Create: `tests/test_battle.py`

**Interfaces:**

- Consumes `CARDS`, `FIXED_DECK_KEYS`, `HEROES`, and models from Task 1.
- Produces a `BattleState` whose public state includes `phase`, `player`, `enemy`, `hand`, `draw_pile`, `discard_pile`, `round_number`, `skill_used_this_turn`, and `log`.

- [ ] **Step 1: Write failing battle tests**

Create `tests/test_battle.py`:

```python
import random

from game.battle import BattleState
from game.models import BattlePhase


def make_battle(hero_key="warrior"):
    return BattleState.create(hero_key, random.Random(7))


def test_new_battle_has_five_cards_three_energy_and_player_turn():
    battle = make_battle()
    assert battle.phase is BattlePhase.PLAYER_TURN
    assert battle.player.hp == 32
    assert battle.enemy.hp == 28
    assert battle.player.energy == 3
    assert len(battle.hand) == 5
    assert battle.round_number == 1


def test_damage_uses_shield_before_health():
    battle = make_battle()
    battle.enemy.shield = 4
    battle.apply_damage(battle.enemy, 6)
    assert battle.enemy.shield == 0
    assert battle.enemy.hp == 26


def test_playing_a_card_spends_energy_moves_card_and_writes_log():
    battle = make_battle()
    battle.hand = [{"id": "player-slash", "key": "slash"}]
    result = battle.play_card("player-slash")
    assert result.ok is True
    assert battle.player.energy == 2
    assert len(battle.hand) == 4
    assert len(battle.discard_pile) == 1
    assert battle.enemy.hp == 22
    assert "斩击" in battle.log[-1]


def test_insufficient_energy_does_not_mutate_battle():
    battle = make_battle()
    battle.player.energy = 1
    battle.hand = [{"id": "player-fireball", "key": "fireball"}]
    before = battle.to_dict()
    result = battle.play_card("player-fireball")
    assert result.ok is False
    assert result.message == "能量不足，还差 2 点"
    assert battle.to_dict() == before


def test_skill_can_only_be_used_once_per_player_turn():
    battle = make_battle("warrior")
    first = battle.use_skill()
    second = battle.use_skill()
    assert first.ok is True
    assert battle.player.shield == 8
    assert second.ok is False
    assert second.message == "本回合技能已经使用过"
```

- [ ] **Step 2: Run the battle tests to verify they fail**

Run:

```bash
pytest tests/test_battle.py -v
```

Expected result: import failure because `BattleState` has not been implemented.

- [ ] **Step 3: Implement the minimal `BattleState`**

Implement these rules in `game/battle.py`:

- `create()` copies and shuffles `FIXED_DECK_KEYS`, creates unique card instances such as `{"id": "card-1", "key": "slash"}`, draws five cards, and sets phase to `PLAYER_TURN`.
- `apply_damage(target, amount)` consumes target shield first, then clamps health at zero.
- `apply_heal(target, amount)` clamps health at target maximum.
- `draw_cards(count)` never exceeds six cards in hand; it shuffles the discard pile into the draw pile only when drawing requires a card and the draw pile is empty.
- `play_card()` verifies player turn, card existence, and energy before mutating anything. It applies the effect, moves the card to discard, writes one log entry, and checks victory.
- `use_skill()` costs two energy, is allowed once per player turn, and supports the three hero skills. The ranger skill deals six damage then calls `draw_cards(1)`.
- If enemy health reaches zero, set phase to `VICTORY`; if player health reaches zero, set phase to `DEFEAT`.

- [ ] **Step 4: Run the battle tests**

Run:

```bash
pytest tests/test_battle.py -v
```

Expected result: all 5 tests pass.

- [ ] **Step 5: Add terminal-state coverage**

Append this test and make it pass:

```python
def test_finished_battle_rejects_further_card_actions():
    battle = make_battle()
    battle.enemy.hp = 1
    battle.hand = [{"id": "player-slash", "key": "slash"}]
    assert battle.play_card("player-slash").ok is True
    result = battle.play_card("player-slash")
    assert result.ok is False
    assert result.message == "本局已经结束，请重新开始"
```

Run:

```bash
pytest tests/test_battle.py -v
```

- [ ] **Step 6: Commit the battle core**

```bash
git add game/battle.py tests/test_battle.py
git commit -m "feat: implement player battle actions"
```

### Task 3: Implement deterministic computer turns and turn progression

**Files:**

- Create: `game/ai.py`
- Create: `tests/test_ai.py`
- Modify: `game/battle.py`
- Modify: `tests/test_battle.py`

**Interfaces:**

- Consumes `BattleState` from Task 2.
- Produces `choose_enemy_card(state: BattleState) -> str | None`, returning a card instance id or `None`.
- `BattleState.end_player_turn()` changes phase to `ENEMY_TURN`; `resolve_enemy_turn()` performs at most one computer action and either finishes the battle or begins the next player turn.

- [ ] **Step 1: Write failing AI tests**

Create `tests/test_ai.py`:

```python
import random

from game.ai import choose_enemy_card
from game.battle import BattleState


def make_battle():
    return BattleState.create("warrior", random.Random(3))


def test_ai_heals_when_its_health_is_at_or_below_eight():
    battle = make_battle()
    battle.enemy.hp = 8
    battle.enemy_hand = [
        {"id": "enemy-heal", "key": "heal"},
        {"id": "enemy-slash", "key": "slash"},
    ]
    assert choose_enemy_card(battle) == "enemy-heal"


def test_ai_uses_highest_damage_when_player_is_low():
    battle = make_battle()
    battle.player.hp = 10
    battle.enemy_hand = [
        {"id": "enemy-slash", "key": "slash"},
        {"id": "enemy-fireball", "key": "fireball"},
    ]
    assert choose_enemy_card(battle) == "enemy-fireball"


def test_end_turn_runs_one_enemy_action_then_returns_to_player():
    battle = make_battle()
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]
    initial_hp = battle.player.hp
    assert battle.end_player_turn().ok is True
    result = battle.resolve_enemy_turn()
    assert result.ok is True
    assert battle.player.hp == initial_hp - 6
    assert battle.phase.value == "PLAYER_TURN"
    assert battle.round_number == 2
    assert battle.player.energy == 3
```

- [ ] **Step 2: Run the AI tests to verify they fail**

Run:

```bash
pytest tests/test_ai.py -v
```

Expected result: import failure because `game.ai` does not exist.

- [ ] **Step 3: Implement AI selection and enemy action**

Implement `choose_enemy_card()` in this exact priority order:

1. healing card if enemy health is at most 8;
2. highest-damage affordable card if player health is at most 10;
3. shield card if enemy health is at most 16;
4. highest-damage affordable card;
5. `None` if no affordable card exists.

Implement one `enemy_hand` at battle creation. Use the same 12-card composition as the player, hide it from browser output, and give the computer three energy for each enemy turn.

Implement `resolve_enemy_turn()` so it can call the same effect helpers as player cards but only once. When the battle survives:

```python
self.round_number += 1
self.phase = BattlePhase.PLAYER_TURN
self.player.energy = 3
self.skill_used_this_turn = False
self.draw_cards(1)
```

After incrementing to round 11, set phase to `DRAW` instead of starting another player turn.

- [ ] **Step 4: Run all core rule tests**

Run:

```bash
pytest tests/test_catalog.py tests/test_battle.py tests/test_ai.py -v
```

Expected result: all tests pass.

- [ ] **Step 5: Commit turn progression**

```bash
git add game/ai.py game/battle.py tests/test_ai.py tests/test_battle.py
git commit -m "feat: add computer turn logic"
```

### Task 4: Add session serialization and match-result persistence

**Files:**

- Create: `game/session_state.py`
- Create: `game/repository.py`
- Create: `tests/test_session_state.py`
- Create: `tests/test_repository.py`

**Interfaces:**

- Consumes `BattleState.to_dict()` and `BattleState.from_dict()` from Task 2.
- Produces `load_battle(session: dict) -> BattleState | None`, `save_battle(session: dict, battle: BattleState) -> None`, and `clear_battle(session: dict) -> None`.
- Produces `init_db(database_path: str) -> None` and `save_match_result(database_path: str, hero_key: str, outcome: str, turns: int) -> None`.

- [ ] **Step 1: Write failing serialization and repository tests**

Create `tests/test_session_state.py`:

```python
import random

from game.battle import BattleState
from game.session_state import load_battle, save_battle


def test_saved_battle_round_trips_without_losing_cards_or_phase():
    battle = BattleState.create("mage", random.Random(9))
    session = {}
    save_battle(session, battle)
    restored = load_battle(session)
    assert restored is not None
    assert restored.to_dict() == battle.to_dict()
```

Create `tests/test_repository.py`:

```python
import sqlite3

from game.repository import init_db, save_match_result


def test_save_match_result_creates_a_queryable_row(tmp_path):
    database_path = tmp_path / "card_battle.sqlite3"
    init_db(str(database_path))
    save_match_result(str(database_path), "warrior", "VICTORY", 4)
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT hero_key, outcome, turns FROM match_results"
        ).fetchone()
    assert row == ("warrior", "VICTORY", 4)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_session_state.py tests/test_repository.py -v
```

Expected result: import failures because the two modules do not exist.

- [ ] **Step 3: Implement JSON-safe session persistence**

`save_battle()` must write `battle.to_dict()` under `session["battle"]`. `load_battle()` must return `None` if that key is absent, otherwise call `BattleState.from_dict()`. `clear_battle()` must remove `"battle"` with `session.pop("battle", None)`.

`to_dict()` must contain only strings, integers, booleans, lists, and dictionaries. Do not put dataclass instances or enum instances directly into Flask session data.

- [ ] **Step 4: Implement the SQLite result table**

`init_db()` must create this table if it does not exist:

```sql
CREATE TABLE IF NOT EXISTS match_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hero_key TEXT NOT NULL,
    outcome TEXT NOT NULL,
    turns INTEGER NOT NULL,
    created_at TEXT NOT NULL
)
```

`save_match_result()` must insert a single row with UTC ISO-8601 time from `datetime.now(timezone.utc).isoformat()`.

- [ ] **Step 5: Run persistence tests**

Run:

```bash
pytest tests/test_session_state.py tests/test_repository.py -v
```

Expected result: 2 passing tests.

- [ ] **Step 6: Commit session and persistence work**

```bash
git add game/session_state.py game/repository.py tests/test_session_state.py tests/test_repository.py
git commit -m "feat: persist battles and match results"
```

### Task 5: Add Flask routes and route-level tests

**Files:**

- Create: `app.py`
- Create: `tests/test_app.py`
- Modify: `game/session_state.py`
- Modify: `game/repository.py`

**Interfaces:**

- Consumes `BattleState`, session helpers, and repository helpers.
- Produces `create_app(test_config: dict | None = None) -> Flask`.
- Uses the route boundaries specified in `docs/产品方案/基础规则/interaction-design.md`.

- [ ] **Step 1: Write failing Flask test-client tests**

Create `tests/test_app.py`:

```python
from app import create_app


def make_client(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "DATABASE": str(tmp_path / "test.sqlite3"),
    })
    return app.test_client()


def test_start_page_and_hero_page_render(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/").status_code == 200
    response = client.get("/heroes")
    assert response.status_code == 200
    assert "战士" in response.get_data(as_text=True)


def test_selecting_a_hero_redirects_to_battle(tmp_path):
    client = make_client(tmp_path)
    response = client.post("/heroes", data={"hero_key": "warrior"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/battle")
    assert "当前回合" in client.get("/battle").get_data(as_text=True)


def test_card_post_redirects_and_refresh_does_not_repeat_action(tmp_path):
    client = make_client(tmp_path)
    client.post("/heroes", data={"hero_key": "warrior"})
    page = client.get("/battle").get_data(as_text=True)
    assert "手牌" in page
    with client.session_transaction() as session:
        card_id = session["battle"]["hand"][0]["id"]
        enemy_hp_before = session["battle"]["enemy"]["hp"]
    response = client.post(f"/battle/card/{card_id}")
    assert response.status_code == 302
    first_get = client.get("/battle")
    second_get = client.get("/battle")
    assert first_get.status_code == 200
    assert second_get.status_code == 200
    with client.session_transaction() as session:
        assert session["battle"]["enemy"]["hp"] <= enemy_hp_before
```

- [ ] **Step 2: Run route tests to verify they fail**

Run:

```bash
pytest tests/test_app.py -v
```

Expected result: import failure because `app.py` does not exist.

- [ ] **Step 3: Implement the application factory and routes**

Implement `create_app()` with:

- a configurable `SECRET_KEY` and `DATABASE`;
- `init_db(app.config["DATABASE"])` during startup;
- `GET /`, `GET /heroes`, `POST /heroes`, `GET /battle`, `POST /battle/card/<card_id>`, `POST /battle/skill`, `POST /battle/end-turn`, `GET /result`, and `POST /restart`;
- `flash(result.message)` for failed actions and user-visible feedback;
- session persistence after every battle mutation;
- a result save exactly once when the battle first reaches `VICTORY`, `DEFEAT`, or `DRAW`;
- redirects after every `POST` request.

If a route needs a live battle and none exists, redirect to `/heroes` with a message instead of raising an exception.

- [ ] **Step 4: Run route tests and all existing tests**

Run:

```bash
pytest -v
```

Expected result: every test passes.

- [ ] **Step 5: Commit Flask flow**

```bash
git add app.py game tests/test_app.py
git commit -m "feat: add Flask game flow"
```

### Task 6: Build the four required pages and visual interaction states

**Files:**

- Create: `templates/base.html`
- Create: `templates/index.html`
- Create: `templates/heroes.html`
- Create: `templates/battle.html`
- Create: `templates/result.html`
- Create: `static/style.css`
- Modify: `tests/test_app.py`

**Interfaces:**

- Consumes template context supplied by the Flask routes: `battle`, `heroes`, `flash` messages, and terminal outcome.
- Produces accessible form controls for every legal battle action.

- [ ] **Step 1: Add failing page-content tests**

Append these tests to `tests/test_app.py`:

```python
def test_hero_page_has_a_disabled_confirm_button_before_selection(tmp_path):
    client = make_client(tmp_path)
    body = client.get("/heroes").get_data(as_text=True)
    assert "确认角色" in body
    assert "hero-card" in body


def test_battle_page_exposes_player_state_hand_and_end_turn(tmp_path):
    client = make_client(tmp_path)
    client.post("/heroes", data={"hero_key": "mage"})
    body = client.get("/battle").get_data(as_text=True)
    assert "生命值" in body
    assert "护盾" in body
    assert "能量" in body
    assert "结束回合" in body
    assert "战斗日志" in body
```

- [ ] **Step 2: Run page tests to verify they fail**

Run:

```bash
pytest tests/test_app.py -v
```

Expected result: at least the new assertions fail because templates do not exist.

- [ ] **Step 3: Implement page structure and disabled states**

Implement:

- `base.html`: page title, flash-message area, and a single content block;
- `index.html`: game title, one-sentence rule, and a start link;
- `heroes.html`: three role cards, role details, selection highlighting with small JavaScript, and a confirm form that remains disabled until a role is selected;
- `battle.html`: enemy panel, round/action label, player panel, hand-card forms, skill form, end-turn form, and battle-log list;
- `result.html`: outcome, hero, round count, and a form posting to `/restart`;
- `style.css`: clear contrast, readable card buttons, disabled-button styling, and responsive layout without animation dependencies.

For each card, add the HTML `disabled` attribute whenever `battle.phase != "PLAYER_TURN"` or `card.cost > battle.player.energy`. Disable the skill button when the phase is not player turn, energy is below two, or `skill_used_this_turn` is true.

- [ ] **Step 4: Run the full test suite**

Run:

```bash
pytest -v
```

Expected result: every test passes.

- [ ] **Step 5: Perform a local browser smoke test**

Run:

```bash
flask --app app:create_app run --debug
```

In the browser, verify: start page → hero selection → battle page → play a card → end turn → result or next player turn. Stop the server after this manual check.

- [ ] **Step 6: Commit the UI**

```bash
git add templates static tests/test_app.py
git commit -m "feat: add playable game pages"
```

### Task 7: Final verification and project handoff

**Files:**

- Modify: `README.md`
- Modify: `docs/产品方案/基础规则/mvp.md` only if a documented rule changed during implementation; otherwise do not modify it.

**Interfaces:**

- Consumes the full implementation from Tasks 1–6.
- Produces documented local setup and verified classroom-demo steps.

- [ ] **Step 1: Update README run instructions**

Add an exact local setup section:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
flask --app app:create_app run --debug
```

Add an exact test command:

```bash
pytest -v
```

Add a five-step demo script: select a role, play a card, attempt an unavailable action, end the turn, and restart after a terminal result.

- [ ] **Step 2: Run the final automated verification**

Run:

```bash
python -m compileall app.py game
ruff check .
ruff format --check .
pytest -v
```

Expected result: no syntax errors, no Ruff errors, no formatting differences, and zero test failures.

- [ ] **Step 3: Run the final manual smoke test**

Run the Flask command from Task 6 and play a complete battle through at least one terminal result. Check that refreshing `/battle` after a completed POST does not repeat the prior action.

- [ ] **Step 4: Inspect Git status and commit the handoff documentation**

Run:

```bash
git status --short
```

Expected result: only intended README or documentation changes remain. Then commit them:

```bash
git add README.md docs
git commit -m "docs: add local run and demo instructions"
```

## Plan Self-Review

- Spec coverage: Tasks 1–3 cover heroes, cards, fixed deck, damage, shield, healing, turn limits, terminal states, and computer priority. Task 4 covers session safety and result persistence. Tasks 5–6 cover all four required pages, POST/Redirect/GET behavior, disabled controls, and feedback. Task 7 covers testing and classroom demonstration.
- Placeholder scan: this plan uses concrete files, public interfaces, test names, commands, card values, hero values, and acceptance checks. It does not require any unlisted feature decisions.
- Interface consistency: `BattleState`, `ActionResult`, `BattlePhase`, `choose_enemy_card`, session helpers, and `create_app` use the same names in every task.
