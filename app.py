import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

from api_routes import create_api_blueprint
from demo_routes import create_demo_blueprint
from game.online_battle_service import OnlineBattleService
from game.online_rooms import OnlineRoomStore
from game.repository import init_db
from online_routes import create_online_blueprint

DEFAULT_INSTANCE_DIR = Path(__file__).resolve().parent / "instance"

# 房间有效期统一由这一个配置产生；只读轮询不续期，成功写入才顺延。
DEFAULT_ONLINE_ROOM_TTL = timedelta(hours=2)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_database_path(config: dict) -> str:
    if "DATABASE" in config and config["DATABASE"]:
        return config["DATABASE"]
    instance_dir = Path(config.get("INSTANCE", DEFAULT_INSTANCE_DIR))
    instance_dir.mkdir(parents=True, exist_ok=True)
    return str(instance_dir / "card_battle.sqlite3")


def _resolve_room_ttl(config: dict) -> timedelta:
    """把配置解析成 timedelta；允许测试直接传秒数或 timedelta。"""
    value = config.get("ONLINE_ROOM_TTL", DEFAULT_ONLINE_ROOM_TTL)
    if isinstance(value, timedelta):
        return value
    if isinstance(value, (int, float)) and value > 0:
        return timedelta(seconds=value)
    return DEFAULT_ONLINE_ROOM_TTL


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

    # 时钟与 RNG 都从配置取，测试可注入固定时钟与固定种子。
    online_store = OnlineRoomStore(
        database_path,
        now=app.config.get("ONLINE_NOW") or _utc_now,
        room_ttl=_resolve_room_ttl(app.config),
    )
    online_service = OnlineBattleService(
        online_store, rng_factory=app.config.get("ONLINE_RNG_FACTORY")
    )
    app.extensions["online_store"] = online_store
    app.extensions["online_service"] = online_service

    app.register_blueprint(create_api_blueprint(online_service))
    app.register_blueprint(create_demo_blueprint())
    app.register_blueprint(create_online_blueprint())

    @app.get("/")
    def service_metadata():
        return jsonify(
            {
                "service": "card-battle",
                "status": "ok",
                "api_base": "/api",
                "demo": "/demo",
            }
        )

    @app.get("/favicon.ico")
    def favicon():
        return send_from_directory(app.static_folder, "assets/card-shield.png")

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
