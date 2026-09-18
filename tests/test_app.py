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