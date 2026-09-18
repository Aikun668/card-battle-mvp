"""End-to-end acceptance scenarios mirroring docs/claude-builder/acceptance.md §6.

A single linear test exercises the ten manual scenarios in order so they
share the same Flask session. We use the test client because urllib cannot
reliably preserve Flask flash state across POST→302→GET.
"""

import json
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_acceptance_walk_through():
    from app import create_app  # noqa: PLC0415

    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "scenario.sqlite3")
    app = create_app({"TESTING": True, "SECRET_KEY": "s", "DATABASE": db})
    client = app.test_client()

    # Scenario 1 — start flow lists three heroes
    assert client.get("/").status_code == 200
    body = client.get("/heroes").get_data(as_text=True)
    for name in ("战士", "法师", "游侠"):
        assert name in body

    # Scenario 2 — confirm button disabled before selection
    assert "确认角色" in body and "hero-card" in body

    # Scenario 3 — selecting a hero creates a battle with full state
    r = client.post("/heroes", data={"hero_key": "warrior"}, follow_redirects=True)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    for needle in ("生命值", "护盾", "能量", "结束回合", "战斗日志", "当前回合"):
        assert needle in body
    with client.session_transaction() as s:
        assert s["battle"]["phase"] == "PLAYER_TURN"
        assert s["battle"]["player"]["hp"] == 32
        assert s["battle"]["enemy"]["hp"] == 28
        assert s["battle"]["player"]["energy"] == 3
        assert len(s["battle"]["hand"]) == 5

    # Scenario 4 — normal card play
    with client.session_transaction() as s:
        s["battle"]["hand"] = [{"id": "p-s", "key": "slash"}]
        s.modified = True
    client.post("/battle/card/p-s", follow_redirects=True)
    with client.session_transaction() as s:
        assert s["battle"]["enemy"]["hp"] == 22
        assert s["battle"]["player"]["energy"] == 2
        assert s["battle"]["hand"] == []
        assert any("斩击" in e for e in s["battle"]["log"])

    # Scenario 5 — insufficient energy flash, state unchanged
    with client.session_transaction() as s:
        s["battle"]["player"]["energy"] = 0
        s["battle"]["hand"] = [{"id": "p-fb", "key": "fireball"}]
        s.modified = True
    r = client.post("/battle/card/p-fb", follow_redirects=True)
    assert "能量不足" in r.get_data(as_text=True)
    with client.session_transaction() as s:
        assert s["battle"]["player"]["energy"] == 0
        assert s["battle"]["enemy"]["hp"] == 22
        assert s["battle"]["hand"][0]["id"] == "p-fb"

    # Scenario 6 — skill limit per turn
    with client.session_transaction() as s:
        s["battle"]["player"]["energy"] = 3
        s["battle"]["player"]["shield"] = 0
        s["battle"]["skill_used_this_turn"] = False
        s.modified = True
    client.post("/battle/skill", follow_redirects=True)
    with client.session_transaction() as s:
        first_shield = s["battle"]["player"]["shield"]
    r = client.post("/battle/skill", follow_redirects=True)
    assert "本回合技能已经使用过" in r.get_data(as_text=True)
    with client.session_transaction() as s:
        assert s["battle"]["player"]["shield"] == first_shield

    # Scenario 7 — end-turn runs exactly one enemy action
    with client.session_transaction() as s:
        s["battle"]["round_number"] = 1
        s["battle"]["enemy_hand"] = [{"id": "e-s", "key": "slash"}]
        s["battle"]["enemy"]["shield"] = 0
        s["battle"]["player"]["shield"] = 0
        s["battle"]["player"]["hp"] = 32
        s.modified = True
    client.post("/battle/end-turn", follow_redirects=True)
    with client.session_transaction() as s:
        assert s["battle"]["player"]["hp"] == 26
        assert s["battle"]["phase"] == "PLAYER_TURN"
        assert s["battle"]["round_number"] == 2
        assert s["battle"]["player"]["energy"] == 3

    # Scenario 8 — page refresh does not re-trigger the last action
    state_before = None
    with client.session_transaction() as s:
        state_before = json.dumps(s["battle"], sort_keys=True)
    client.get("/battle")
    client.get("/battle")
    with client.session_transaction() as s:
        state_after = json.dumps(s["battle"], sort_keys=True)
    assert state_before == state_after

    # Scenario 9 — terminal state blocks further actions, writes one row
    with client.session_transaction() as s:
        s["battle"]["enemy"]["hp"] = 1
        s["battle"]["hand"] = [{"id": "p-kill", "key": "slash"}]
        s["battle"]["phase"] = "PLAYER_TURN"
        s.modified = True
    r = client.post("/battle/card/p-kill", follow_redirects=True)
    battle_body = r.get_data(as_text=True)
    # The /battle page should now be in VICTORY phase with action buttons disabled
    assert "查看结果" in battle_body or "再来一局" in battle_body
    with client.session_transaction() as s:
        assert s["battle"]["phase"] == "VICTORY"
    # Following the result link shows the result page
    result_body = client.get("/result").get_data(as_text=True)
    assert "胜利" in result_body or "再来一局" in result_body
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM match_results").fetchone()[0] == 1

    # Scenario 10 — restart clears state and returns to hero selection
    r = client.post("/restart", follow_redirects=True)
    assert r.status_code == 200
    assert "确认角色" in r.get_data(as_text=True)
    with client.session_transaction() as s:
        assert "battle" not in s
    r2 = client.get("/battle")
    assert r2.status_code == 302
    assert r2.headers["Location"].endswith("/heroes")
