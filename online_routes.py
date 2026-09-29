from flask import Blueprint, render_template, request


def create_online_blueprint() -> Blueprint:
    online = Blueprint("online", __name__)

    @online.get("/online")
    @online.get("/join")
    def online_page():
        return render_template(
            "online.html",
            initial_room_code=(request.args.get("room_code") or "").strip().upper(),
        )

    return online
