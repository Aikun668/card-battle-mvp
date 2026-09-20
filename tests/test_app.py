from app import create_app


def make_client(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": str(tmp_path / "test.sqlite3"),
        }
    )
    return app.test_client()


def side_state(session: dict, side: str) -> dict:
    """读取 session 里某个参与者的原始分区。"""
    return session["battle"]["participants"][side]


def test_start_page_and_hero_page_render(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/demo").status_code == 200
    response = client.get("/demo/heroes")
    assert response.status_code == 200
    assert "战士" in response.get_data(as_text=True)


def test_selecting_a_hero_redirects_to_battle(tmp_path):
    client = make_client(tmp_path)
    response = client.post("/demo/heroes", data={"hero_key": "warrior"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/demo/battle")
    assert "当前回合" in client.get("/demo/battle").get_data(as_text=True)


def test_card_post_redirects_and_refresh_does_not_repeat_action(tmp_path):
    client = make_client(tmp_path)
    client.post("/demo/heroes", data={"hero_key": "warrior"})
    page = client.get("/demo/battle").get_data(as_text=True)
    assert "手牌" in page
    with client.session_transaction() as session:
        card_id = side_state(session, "player")["hand"][0]["id"]
        enemy_hp_before = side_state(session, "enemy")["combatant"]["hp"]
    response = client.post(f"/demo/battle/card/{card_id}")
    assert response.status_code == 302
    first_get = client.get("/demo/battle")
    second_get = client.get("/demo/battle")
    assert first_get.status_code == 200
    assert second_get.status_code == 200
    with client.session_transaction() as session:
        assert side_state(session, "enemy")["combatant"]["hp"] <= enemy_hp_before


def test_hero_page_has_a_disabled_confirm_button_before_selection(tmp_path):
    client = make_client(tmp_path)
    body = client.get("/demo/heroes").get_data(as_text=True)
    assert "确认角色" in body
    assert "hero-card" in body


def test_battle_page_exposes_player_state_hand_and_end_turn(tmp_path):
    client = make_client(tmp_path)
    client.post("/demo/heroes", data={"hero_key": "mage"})
    body = client.get("/demo/battle").get_data(as_text=True)
    assert "生命值" in body
    assert "护盾" in body
    assert "能量" in body
    assert "结束回合" in body
    assert "战斗日志" in body


def test_routes_redirect_to_heroes_when_no_live_battle(tmp_path):
    client = make_client(tmp_path)
    r = client.get("/demo/battle")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/demo/heroes")
    r = client.post("/demo/battle/card/anything")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/demo/heroes")
    r = client.post("/demo/battle/skill")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/demo/heroes")
    r = client.post("/demo/battle/end-turn")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/demo/heroes")
    r = client.get("/demo/result")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/demo/heroes")


def test_match_result_written_to_sqlite_exactly_once(tmp_path):
    client = make_client(tmp_path)
    client.post("/demo/heroes", data={"hero_key": "warrior"})
    with client.session_transaction() as s:
        enemy = side_state(s, "enemy")
        enemy["combatant"]["hp"] = 1
        enemy["combatant"]["shield"] = 0
        side_state(s, "player")["hand"] = [{"id": "x", "key": "slash"}]
        s.modified = True
    client.post("/demo/battle/card/x")  # kills enemy -> VICTORY -> writes to DB
    client.post("/demo/battle/card/x")  # rejected (not in hand)
    client.post("/demo/battle/card/x")
    import sqlite3

    db_path = tmp_path / "test.sqlite3"
    with sqlite3.connect(db_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM match_results").fetchone()[0]
    assert count == 1


def test_restart_clears_battle_and_returns_to_heroes(tmp_path):
    client = make_client(tmp_path)
    client.post("/demo/heroes", data={"hero_key": "warrior"})
    assert client.get("/demo/battle").status_code == 200
    r = client.post("/demo/restart")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/demo/heroes")
    with client.session_transaction() as s:
        assert "battle" not in s
    r = client.get("/demo/battle")
    assert r.status_code == 302


def test_invalid_hero_key_redirects_to_heroes_with_flash(tmp_path):
    client = make_client(tmp_path)
    r = client.post("/demo/heroes", data={"hero_key": "unknown"})
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/demo/heroes")
