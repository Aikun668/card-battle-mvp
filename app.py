import os
import random
from pathlib import Path

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from game.battle import BattleState
from game.catalog import CARDS, HEROES
from game.repository import init_db, save_match_result
from game.session_state import clear_battle, load_battle, save_battle

DEFAULT_INSTANCE_DIR = Path(__file__).resolve().parent / "instance"
RESULT_SAVED_KEY = "match_result_saved"


def _resolve_database_path(config: dict) -> str:
    if "DATABASE" in config and config["DATABASE"]:
        return config["DATABASE"]
    instance_dir = Path(config.get("INSTANCE", DEFAULT_INSTANCE_DIR))
    instance_dir.mkdir(parents=True, exist_ok=True)
    return str(instance_dir / "card_battle.sqlite3")


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret"),
        DATABASE=str(DEFAULT_INSTANCE_DIR / "card_battle.sqlite3"),
    )
    if test_config:
        app.config.update(test_config)

    database_path = _resolve_database_path(app.config)
    app.config["DATABASE"] = database_path
    init_db(database_path)

    def _require_battle() -> BattleState | None:
        return load_battle(session)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/heroes")
    def heroes_select():
        return render_template("heroes.html", heroes=HEROES)

    @app.post("/heroes")
    def heroes_confirm():
        hero_key = request.form.get("hero_key", "")
        if hero_key not in HEROES:
            flash("请选择一个角色")
            return redirect(url_for("heroes_select"))
        battle = BattleState.create(hero_key, random.Random())
        session.pop(RESULT_SAVED_KEY, None)
        save_battle(session, battle)
        return redirect(url_for("battle_view"))

    @app.get("/battle")
    def battle_view():
        battle = _require_battle()
        if battle is None:
            flash("请先选择角色")
            return redirect(url_for("heroes_select"))
        return render_template("battle.html", battle=battle, cards=CARDS)

    @app.post("/battle/card/<card_id>")
    def battle_play_card(card_id: str):
        battle = _require_battle()
        if battle is None:
            return redirect(url_for("heroes_select"))
        result = battle.play_card(card_id)
        if not result.ok:
            flash(result.message)
        _persist_and_maybe_save(battle)
        return redirect(url_for("battle_view"))

    @app.post("/battle/skill")
    def battle_use_skill():
        battle = _require_battle()
        if battle is None:
            return redirect(url_for("heroes_select"))
        result = battle.use_skill()
        if not result.ok:
            flash(result.message)
        _persist_and_maybe_save(battle)
        return redirect(url_for("battle_view"))

    @app.post("/battle/end-turn")
    def battle_end_turn():
        battle = _require_battle()
        if battle is None:
            return redirect(url_for("heroes_select"))
        result = battle.end_player_turn()
        if not result.ok:
            flash(result.message)
            _persist_and_maybe_save(battle)
            return redirect(url_for("battle_view"))
        enemy_result = battle.resolve_enemy_turn()
        if not enemy_result.ok:
            flash(enemy_result.message)
        _persist_and_maybe_save(battle)
        if battle.is_finished():
            return redirect(url_for("result_view"))
        return redirect(url_for("battle_view"))

    @app.get("/result")
    def result_view():
        battle = _require_battle()
        if battle is None:
            flash("请先选择角色")
            return redirect(url_for("heroes_select"))
        return render_template("result.html", battle=battle)

    @app.post("/restart")
    def restart():
        clear_battle(session)
        session.pop(RESULT_SAVED_KEY, None)
        flash("新一轮战斗已开始")
        return redirect(url_for("heroes_select"))

    def _persist_and_maybe_save(battle: BattleState) -> None:
        save_battle(session, battle)
        if battle.is_finished() and not session.get(RESULT_SAVED_KEY):
            save_match_result(
                app.config["DATABASE"],
                battle.hero.key,
                battle.phase.value,
                battle.round_number,
            )
            session[RESULT_SAVED_KEY] = True

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
