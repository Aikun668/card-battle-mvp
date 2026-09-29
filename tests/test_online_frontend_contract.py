from pathlib import Path

from app import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_online_pages_render_a_separate_room_shell(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": str(tmp_path / "online-frontend.sqlite3"),
        }
    )
    client = app.test_client()

    page = client.get("/online")
    invite_page = client.get("/join?room_code=K7P4WQ")

    assert page.status_code == 200
    assert invite_page.status_code == 200
    assert 'id="online-shell"' in page.get_data(as_text=True)
    assert 'id="lobby-view"' in page.get_data(as_text=True)
    assert 'id="room-view"' in page.get_data(as_text=True)
    assert 'id="create-room-form"' in page.get_data(as_text=True)
    assert 'id="join-room-form"' in page.get_data(as_text=True)
    assert 'id="battle-view"' in page.get_data(as_text=True)
    assert 'src="/static/online-pvp.js"' in page.get_data(as_text=True)
    assert 'data-initial-room-code="K7P4WQ"' in invite_page.get_data(as_text=True)


def test_online_page_declares_all_room_states_and_private_battle_regions():
    template = (PROJECT_ROOT / "templates" / "online.html").read_text(
        encoding="utf-8"
    )

    for element_id in (
        "waiting-panel",
        "hero-select-panel",
        "battle-panel",
        "finished-panel",
        "expired-panel",
        "invite-link",
        "hero-options",
        "online-hand",
        "response-actions",
        "rematch-button",
    ):
        assert f'id="{element_id}"' in template

    assert "只显示自己的手牌" in template
    assert "在线 PvP" in template


def test_online_script_consumes_room_snapshot_and_never_submits_identity_fields():
    script = (PROJECT_ROOT / "static" / "online-pvp.js").read_text(encoding="utf-8")

    for path in (
        '"/api/rooms"',
        '"/api/rooms/join"',
        '"/hero"',
        '"/actions/card"',
        '"/actions/skill"',
        '"/actions/end-turn"',
        '"/actions/respond"',
        '"/rematch"',
    ):
        assert path in script

    for token in (
        "credentials: \"same-origin\"",
        "room.revision",
        "battle.viewer",
        "available_actions",
        "STALE_STATE",
        "ACTION_REJECTED",
        "schedulePoll",
        "replaceSnapshot",
    ):
        assert token in script

    assert "seat" not in script
    assert "viewer:" not in script
    assert "JSON.stringify({ seat" not in script


def test_online_styles_define_state_shell_and_battle_layout():
    styles = (PROJECT_ROOT / "static" / "online-pvp.css").read_text(
        encoding="utf-8"
    )

    for selector in (
        ".online-shell",
        ".room-card",
        ".online-battle-grid",
        ".online-hand",
        ".online-toast",
        ".is-hidden",
    ):
        assert selector in styles
