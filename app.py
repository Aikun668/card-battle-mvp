import os
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

from api_routes import create_api_blueprint
from demo_routes import create_demo_blueprint
from game.repository import init_db

DEFAULT_INSTANCE_DIR = Path(__file__).resolve().parent / "instance"


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

    app.register_blueprint(create_api_blueprint())
    app.register_blueprint(create_demo_blueprint())

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
