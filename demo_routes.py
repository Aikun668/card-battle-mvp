import random

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from game.battle import BattleState
from game.catalog import CARDS, HEROES
from game.models import BattlePhase
from game.session_state import clear_battle, load_battle
from web_support import RESULT_SAVED_KEY, persist_battle


def create_demo_blueprint() -> Blueprint:
    demo = Blueprint("demo", __name__, url_prefix="/demo")

    def require_battle() -> BattleState | None:
        return load_battle(session)

    @demo.get("")
    def index():
        return render_template("game.html", has_battle=require_battle() is not None)

    @demo.get("/heroes")
    def heroes_select():
        return render_template("heroes.html", heroes=HEROES)

    @demo.post("/heroes")
    def heroes_confirm():
        hero_key = request.form.get("hero_key", "")
        if hero_key not in HEROES:
            flash("请选择一个角色")
            return redirect(url_for("demo.heroes_select"))
        battle = BattleState.create(hero_key, random.Random())
        session.pop(RESULT_SAVED_KEY, None)
        persist_battle(session, battle)
        return redirect(url_for("demo.battle_view"))

    @demo.get("/battle")
    def battle_view():
        battle = require_battle()
        if battle is None:
            flash("请先选择角色")
            return redirect(url_for("demo.heroes_select"))
        return render_template("battle.html", battle=battle, cards=CARDS)

    @demo.post("/battle/card/<card_id>")
    def battle_play_card(card_id: str):
        battle = require_battle()
        if battle is None:
            return redirect(url_for("demo.heroes_select"))
        result = battle.play_card(card_id)
        if not result.ok:
            flash(result.message)
        persist_battle(session, battle)
        return redirect(url_for("demo.battle_view"))

    @demo.post("/battle/skill")
    def battle_use_skill():
        battle = require_battle()
        if battle is None:
            return redirect(url_for("demo.heroes_select"))
        result = battle.use_skill()
        if not result.ok:
            flash(result.message)
        persist_battle(session, battle)
        return redirect(url_for("demo.battle_view"))

    @demo.post("/battle/respond")
    def battle_respond():
        battle = require_battle()
        if battle is None:
            return redirect(url_for("demo.heroes_select"))
        result = battle.respond(request.form.get("action", ""))
        if not result.ok:
            flash(result.message)
        persist_battle(session, battle)
        if battle.is_finished():
            return redirect(url_for("demo.result_view"))
        return redirect(url_for("demo.battle_view"))

    @demo.post("/battle/end-turn")
    def battle_end_turn():
        battle = require_battle()
        if battle is None:
            return redirect(url_for("demo.heroes_select"))
        result = battle.end_player_turn()
        if not result.ok:
            flash(result.message)
            persist_battle(session, battle)
            return redirect(url_for("demo.battle_view"))
        # 打满回合上限时玩家结束回合就直接收尾判出胜负，没有电脑回合可跑。
        if battle.phase is BattlePhase.ENEMY_TURN:
            battle.resolve_enemy_turn()
        persist_battle(session, battle)
        if battle.is_finished():
            return redirect(url_for("demo.result_view"))
        return redirect(url_for("demo.battle_view"))

    @demo.get("/result")
    def result_view():
        battle = require_battle()
        if battle is None:
            flash("请先选择角色")
            return redirect(url_for("demo.heroes_select"))
        return render_template("result.html", battle=battle)

    @demo.post("/restart")
    def restart():
        clear_battle(session)
        session.pop(RESULT_SAVED_KEY, None)
        flash("新一轮战斗已开始")
        return redirect(url_for("demo.heroes_select"))

    return demo
