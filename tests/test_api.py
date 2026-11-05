import fake_1c
from conftest import ADMIN, STAFF, STRANGER, as_user, sign_init_data
from fastapi.testclient import TestClient

from app.main import create_app


def update(user_id: int, text: str, chat_type: str = "private") -> dict:
    return {"message": {"text": text, "from": {"id": user_id}, "chat": {"id": user_id, "type": chat_type}}}


def post_update(web, settings, payload) -> None:
    response = web.post(
        "/telegram/webhook",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": settings.webhook_secret},
    )
    assert response.status_code == 200


def test_no_header_is_rejected(web):
    response = web.get("/api/search", params={"q": "CS-6060"})
    assert response.status_code == 401
    assert fake_1c.state.calls == []


def test_forged_signature_is_rejected(web):
    headers = {"Authorization": f"tma {sign_init_data(ADMIN, token='999:OTHER')}"}
    assert web.get("/api/search", params={"q": "CS-6060"}, headers=headers).status_code == 401
    assert fake_1c.state.calls == []


def test_stranger_is_refused_and_told_their_id(web):
    response = web.get("/api/search", params={"q": "CS-6060"}, headers=as_user(STRANGER))
    assert response.status_code == 403
    assert response.json()["detail"] == {"code": "no_access", "user_id": STRANGER}
    assert fake_1c.state.calls == []


def test_search_then_stock(web):
    found = web.get("/api/search", params={"q": "CS-6060-GR"}, headers=as_user(STAFF)).json()
    assert found["truncated"] is False
    item = found["items"][0]
    assert item["article"] == "CS-6060-GR"

    stock = web.get(f"/api/stock/{item['id']}", headers=as_user(STAFF)).json()
    assert stock["total_quantity"] == 848.8
    assert stock["warehouses"][0]["name"] == "Негізгі қойма"


def test_short_and_long_queries_never_reach_1c(web):
    assert web.get("/api/search", params={"q": " a "}, headers=as_user(STAFF)).status_code == 422
    assert web.get("/api/search", params={"q": "x" * 65}, headers=as_user(STAFF)).status_code == 422
    assert fake_1c.state.calls == []


def test_bad_item_id_never_reaches_1c(web):
    assert web.get("/api/stock/not-a-guid", headers=as_user(STAFF)).status_code == 422
    assert fake_1c.state.calls == []


def test_1c_down_gives_503_without_details(web):
    fake_1c.state.fail_with = (502, "<html>internal server name</html>")
    response = web.get("/api/search", params={"q": "CS-6060"}, headers=as_user(STAFF))
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "onec_unavailable"}}


def test_1c_query_error_gives_502_without_details(web):
    fake_1c.state.fail_with = (400, '{"odata.error":{"message":"secret table names"}}')
    response = web.get("/api/search", params={"q": "CS-6060"}, headers=as_user(STAFF))
    assert response.status_code == 502
    assert response.json() == {"detail": {"code": "onec_query"}}


def test_only_get_requests_touch_1c(web):
    web.get("/api/search", params={"q": "6060"}, headers=as_user(STAFF))
    web.post("/api/search", params={"q": "6060"}, headers=as_user(STAFF))
    web.delete("/api/stock/bbbbbbbb-0000-0000-0000-000000000001", headers=as_user(STAFF))
    assert len(fake_1c.state.calls) == 2  # exact, then partial, both from the single GET


def test_page_is_served_with_security_headers(web):
    response = web.get("/")
    assert response.status_code == 200
    assert "Қойма қалдығы" in response.text
    csp = response.headers["content-security-policy"]
    assert "frame-ancestors https://web.telegram.org" in csp
    assert response.headers["x-content-type-options"] == "nosniff"


def test_api_answers_are_not_cached(web):
    response = web.get("/api/me", headers=as_user(STAFF))
    assert response.headers["cache-control"] == "no-store"


def test_secrets_are_not_in_static_files(web):
    for path in ("/", "/app.js", "/style.css"):
        assert "test-password" not in web.get(path).text


def test_webhook_needs_the_secret(web):
    assert web.post("/telegram/webhook", json=update(ADMIN, "/add 42")).status_code == 401
    wrong = {"X-Telegram-Bot-Api-Secret-Token": "wrong"}
    assert web.post("/telegram/webhook", json=update(ADMIN, "/add 42"), headers=wrong).status_code == 401


def test_startup_registers_webhook_with_secret(web, telegram, settings):
    webhook = next(payload for method, payload in telegram.sent if method == "setWebhook")
    assert webhook["url"] == "https://stock.test/telegram/webhook"
    assert webhook["secret_token"] == settings.webhook_secret


def test_allowed_user_gets_the_button(web, telegram, settings):
    post_update(web, settings, update(STAFF, "/start"))
    button = telegram.messages()[-1]["reply_markup"]["inline_keyboard"][0][0]
    assert button["web_app"]["url"] == "https://stock.test"


def test_stranger_gets_their_id_and_no_button(web, telegram, settings):
    post_update(web, settings, update(STRANGER, "/start"))
    message = telegram.messages()[-1]
    assert str(STRANGER) in message["text"]
    assert "reply_markup" not in message


def test_admin_grants_and_removes_access(web, telegram, settings):
    assert web.get("/api/me", headers=as_user(STRANGER)).status_code == 403

    post_update(web, settings, update(ADMIN, f"/add {STRANGER}"))
    assert web.get("/api/me", headers=as_user(STRANGER)).status_code == 200

    post_update(web, settings, update(ADMIN, "/users"))
    assert str(STRANGER) in telegram.messages()[-1]["text"]

    post_update(web, settings, update(ADMIN, f"/remove {STRANGER}"))
    assert web.get("/api/me", headers=as_user(STRANGER)).status_code == 403


def test_only_the_admin_can_grant(web, telegram, settings):
    post_update(web, settings, update(STAFF, f"/add {STRANGER}"))
    post_update(web, settings, update(STRANGER, f"/add {STRANGER}"))
    assert web.get("/api/me", headers=as_user(STRANGER)).status_code == 403


def test_admin_cannot_be_locked_out_and_bad_ids_are_refused(web, telegram, settings):
    post_update(web, settings, update(ADMIN, f"/remove {ADMIN}"))
    assert web.get("/api/me", headers=as_user(ADMIN)).status_code == 200
    post_update(web, settings, update(ADMIN, "/add abc"))
    assert "сан түрінде" in telegram.messages()[-1]["text"]


def test_group_chats_are_ignored(web, telegram, settings):
    before = len(telegram.messages())
    post_update(web, settings, update(ADMIN, f"/add {STRANGER}", chat_type="group"))
    assert len(telegram.messages()) == before
    assert web.get("/api/me", headers=as_user(STRANGER)).status_code == 403


def restarted(settings, onec_transport, telegram):
    return TestClient(create_app(settings, onec_transport, telegram))


def test_access_survives_a_restart_without_any_disk(settings, onec_transport, telegram):
    with restarted(settings, onec_transport, telegram) as first:
        post_update(first, settings, update(ADMIN, f"/add {STRANGER}"))
    assert str(STRANGER) in telegram.pinned_text()

    with restarted(settings, onec_transport, telegram) as second:
        assert second.get("/api/me", headers=as_user(STRANGER)).status_code == 200
        post_update(second, settings, update(ADMIN, f"/remove {STRANGER}"))

    with restarted(settings, onec_transport, telegram) as third:
        assert third.get("/api/me", headers=as_user(STRANGER)).status_code == 403


def test_list_is_edited_in_place_not_reposted(web, telegram, settings):
    post_update(web, settings, update(ADMIN, "/add 111"))
    pinned = telegram.pinned
    post_update(web, settings, update(ADMIN, "/add 222"))
    post_update(web, settings, update(ADMIN, "/add 222"))
    assert telegram.pinned == pinned
    assert "111\n222" in telegram.pinned_text()


def test_deleted_pinned_message_is_rewritten(web, telegram, settings):
    post_update(web, settings, update(ADMIN, "/add 111"))
    telegram.stored.pop(telegram.pinned)
    post_update(web, settings, update(ADMIN, "/add 222"))
    assert "111\n222" in telegram.pinned_text()


def test_unrelated_pinned_message_grants_nothing(settings, onec_transport, telegram):
    telegram.stored[1] = f"Жазба\n{STRANGER}"
    telegram.pinned = 1
    with restarted(settings, onec_transport, telegram) as client:
        assert client.get("/api/me", headers=as_user(STRANGER)).status_code == 403
        assert client.get("/api/me", headers=as_user(ADMIN)).status_code == 200


def test_pin_by_a_person_is_not_trusted(settings, onec_transport, telegram):
    from app.bot import ACCESS_HEADER

    telegram.stored[1] = f"{ACCESS_HEADER}\n{STRANGER}"
    telegram.pinned = 1
    telegram.pinned_by_bot = False
    with restarted(settings, onec_transport, telegram) as client:
        assert client.get("/api/me", headers=as_user(STRANGER)).status_code == 403


def test_first_run_before_the_admin_opened_the_bot(settings, onec_transport, telegram):
    telegram.failing["getChat"] = "Bad Request: chat not found"
    with restarted(settings, onec_transport, telegram) as client:
        assert client.get("/api/me", headers=as_user(ADMIN)).status_code == 200
        assert client.get("/api/me", headers=as_user(STRANGER)).status_code == 403


def test_telegram_outage_never_wipes_the_list(settings, onec_transport, telegram):
    with restarted(settings, onec_transport, telegram) as first:
        post_update(first, settings, update(ADMIN, f"/add {STRANGER}"))
    saved = telegram.pinned_text()

    telegram.failing["getChat"] = "Internal Server Error"
    with restarted(settings, onec_transport, telegram) as second:
        assert second.get("/api/me", headers=as_user(STRANGER)).status_code == 403
        post_update(second, settings, update(ADMIN, "/add 999"))
        assert "оқи алмадым" in telegram.messages()[-1]["text"]
        assert telegram.pinned_text() == saved

        telegram.failing.clear()
        assert second.get("/api/me", headers=as_user(STRANGER)).status_code == 200


def test_failed_save_is_reported_to_the_admin(web, telegram, settings):
    post_update(web, settings, update(ADMIN, "/add 111"))
    telegram.failing["editMessageText"] = "Too Many Requests"
    telegram.failing["pinChatMessage"] = "Too Many Requests"
    post_update(web, settings, update(ADMIN, "/add 222"))
    assert "сақталмады" in telegram.messages()[-1]["text"]
