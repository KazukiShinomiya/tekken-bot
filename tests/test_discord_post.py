"""
bot/discord_post.py の I/O 層（Webhook 送信・編集）テスト。
"""

import pytest
from unittest.mock import MagicMock, patch
from bot.discord_post import (
    _parse_webhook_id_token,
    post,
    post_weekly,
    post_monthly,
    post_rank_change,
    post_community_weekly,
    edit_llm_comment,
    notify,
    notify_error,
)


def _full_battle(battle_at: int = 1000, won: bool = True) -> dict:
    """post() テスト用の完全なバトルデータ。"""
    return {
        "battle_id": f"t{battle_at}",
        "battle_at": battle_at,
        "won": won,
        "battle_type": "ranked",
        "opp_chara": "Jin",
        "my_chara": "Lee",
        "my_rounds": 2,
        "opp_rounds": 1,
        "rating_before": 10000,
        "rating_change": 100,
        "my_power": None,
        "my_rank": None,
        "opp_polaris_id": "pid_opp",
        "opp_name": "Opp",
    }


def test_parse_webhook_id_token_valid():
    """正しい Discord Webhook URL から (id, token) を返す。"""
    url = "https://discord.com/api/webhooks/123456789/abcdefghijk"
    result = _parse_webhook_id_token(url)
    assert result == ("123456789", "abcdefghijk")


def test_parse_webhook_id_token_discordapp_valid():
    """discordapp.com の URL も解析できる。"""
    url = "https://discordapp.com/api/webhooks/999/mytoken"
    result = _parse_webhook_id_token(url)
    assert result == ("999", "mytoken")


def test_parse_webhook_id_token_invalid():
    """不正な URL → None を返す。"""
    assert _parse_webhook_id_token("https://example.com/not/a/webhook") is None


def test_parse_webhook_id_token_empty():
    """空文字 → None を返す。"""
    assert _parse_webhook_id_token("") is None


def test_post_community_weekly_skips_when_one_player():
    """プレイヤーが1人以下 → 投稿しない。"""
    players = [{"name": "Solo", "wins": 5, "losses": 3, "net_rating": 100}]
    with patch("bot.discord_post._webhook_session") as mock_sess:
        post_community_weekly(players, "2024/01/15")
    mock_sess.post.assert_not_called()


def test_post_community_weekly_posts_when_two_players():
    """プレイヤーが2人以上 → Webhook に POST する。"""
    players = [
        {"name": "A", "wins": 5, "losses": 3, "net_rating": 100},
        {"name": "B", "wins": 3, "losses": 5, "net_rating": -50},
    ]
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    with (
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/token"]),
    ):
        mock_sess.post.return_value = mock_resp
        post_community_weekly(players, "2024/01/15")
    mock_sess.post.assert_called_once()


def test_notify_posts_message():
    """notify → content を含む POST が行われる。"""
    mock_resp = MagicMock()
    with (
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/token"]),
    ):
        mock_sess.post.return_value = mock_resp
        notify("テスト通知")
    mock_sess.post.assert_called_once()
    call_kwargs = mock_sess.post.call_args[1]
    assert "テスト通知" in call_kwargs["json"]["content"]


def test_notify_error_prepends_warning():
    """notify_error → ⚠️ プレフィックス付きで投稿される（ERROR_WEBHOOK_URLS 未設定時は WEBHOOK_URLS へ）。"""
    mock_resp = MagicMock()
    with (
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.discord_post.ERROR_WEBHOOK_URLS", []),
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/token"]),
    ):
        mock_sess.post.return_value = mock_resp
        notify_error("エラーメッセージ")
    call_kwargs = mock_sess.post.call_args[1]
    assert "⚠️" in call_kwargs["json"]["content"]
    assert "エラーメッセージ" in call_kwargs["json"]["content"]


def test_notify_error_uses_error_webhook_when_set():
    """notify_error → ERROR_WEBHOOK_URLS が設定されていればそちらへ投稿する。"""
    error_url  = "https://discord.com/api/webhooks/error/token"
    normal_url = "https://discord.com/api/webhooks/normal/token"
    mock_resp = MagicMock()
    with (
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.discord_post.ERROR_WEBHOOK_URLS", [error_url]),
        patch("bot.discord_post.WEBHOOK_URLS", [normal_url]),
    ):
        mock_sess.post.return_value = mock_resp
        notify_error("エラーメッセージ")
    posted_url = mock_sess.post.call_args[0][0]
    assert posted_url == error_url


def test_notify_ignores_request_exception():
    """Webhook 投稿失敗しても例外を出さない。"""
    import requests
    with (
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/token"]),
    ):
        mock_sess.post.side_effect = requests.RequestException("network error")
        notify("test")  # should not raise


def test_post_returns_none_when_no_battles():
    """試合なし → None を返す。"""
    with patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]):
        result = post([], "2024/01/01")
    assert result is None


def test_post_returns_none_when_no_webhook_urls():
    """WEBHOOK_URLS 未設定 → ValueError を送出する。"""
    with (
        patch("bot.discord_post.WEBHOOK_URLS", []),
        pytest.raises(ValueError),
    ):
        post([_full_battle()], "2024/01/01")


def test_post_success_returns_message_ids():
    """投稿成功 → (message_ids, embed) タプルを返す。"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"id": "msg123"}

    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_rating_chart", return_value=None),
    ):
        mock_sess.post.return_value = mock_resp
        result = post(battles, "2024/01/01")

    assert result is not None
    message_ids, embed = result
    assert len(message_ids) == 1
    assert message_ids[0][0] == "msg123"
    assert isinstance(embed, dict)


def test_post_returns_none_when_all_webhooks_fail():
    """全 Webhook が RequestException → None を返す。"""
    import requests
    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_rating_chart", return_value=None),
    ):
        mock_sess.post.side_effect = requests.RequestException("error")
        result = post(battles, "2024/01/01")
    assert result is None


def test_post_with_chart():
    """グラフあり → files 付きで POST する。"""
    import io
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"id": "msg456"}

    fake_chart = io.BytesIO(b"\x89PNGdata")
    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_rating_chart", return_value=fake_chart),
    ):
        mock_sess.post.return_value = mock_resp
        result = post(battles, "2024/01/01")

    assert result is not None
    # files= で POST が呼ばれているはず
    call_kwargs = mock_sess.post.call_args[1]
    assert "files" in call_kwargs


def test_post_weekly_returns_none_when_no_battles():
    """試合なし → None を返す。"""
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.graph.generate_chara_usage_chart", return_value=None),
        patch("bot.db.get_weekly_my_chara_counts", return_value=[]),
    ):
        result = post_weekly([], "2024/01/15")
    assert result is None


def test_post_weekly_success():
    """投稿成功 → (message_ids, embed) を返す。"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"id": "weekly123"}

    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_chara_usage_chart", return_value=None),
        patch("bot.db.get_weekly_my_chara_counts", return_value=[]),
    ):
        mock_sess.post.return_value = mock_resp
        result = post_weekly(battles, "2024/01/15")

    assert result is not None
    message_ids, embed = result
    assert message_ids[0][0] == "weekly123"


def test_post_weekly_raises_when_no_webhook():
    """WEBHOOK_URLS 未設定 → ValueError を送出する。"""
    with (
        patch("bot.discord_post.WEBHOOK_URLS", []),
        pytest.raises(ValueError),
    ):
        post_weekly([_full_battle()], "2024/01/15")


def test_post_weekly_with_chart():
    """キャラグラフあり → files 付きで POST する。"""
    import io
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"id": "w789"}

    fake_chart = io.BytesIO(b"\x89PNGdata")
    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_chara_usage_chart", return_value=fake_chart),
        patch("bot.db.get_weekly_my_chara_counts", return_value=[]),
    ):
        mock_sess.post.return_value = mock_resp
        result = post_weekly(battles, "2024/01/15")

    assert result is not None
    call_kwargs = mock_sess.post.call_args[1]
    assert "files" in call_kwargs


def test_edit_llm_comment_patches_embed():
    """正常ケース → PATCH リクエストが発行され、LLM コメントが description 冒頭に追加される。"""
    get_resp = MagicMock()
    get_resp.raise_for_status.return_value = None
    get_resp.json.return_value = {"attachments": []}

    patch_resp = MagicMock()
    patch_resp.raise_for_status.return_value = None

    message_ids = [("msg123", "https://discord.com/api/webhooks/1/tok")]
    embed = {"title": "test", "color": 0, "description": "試合一覧"}

    with patch("bot.discord_post._webhook_session") as mock_sess:
        mock_sess.get.return_value  = get_resp
        mock_sess.patch.return_value = patch_resp
        edit_llm_comment(message_ids, embed, "LLM コメントです")

    mock_sess.patch.assert_called_once()
    patch_call = mock_sess.patch.call_args[1]
    updated_embed = patch_call["json"]["embeds"][0]
    assert "LLM コメントです" in updated_embed["description"]
    assert updated_embed["description"].startswith("💬")


def test_edit_llm_comment_preserves_attachments():
    """添付ファイルがある場合 → PATCH ボディに attachments を含める。"""
    get_resp = MagicMock()
    get_resp.raise_for_status.return_value = None
    get_resp.json.return_value = {"attachments": [{"id": "att1"}]}

    patch_resp = MagicMock()
    patch_resp.raise_for_status.return_value = None

    message_ids = [("msg123", "https://discord.com/api/webhooks/1/tok")]
    embed = {"title": "test", "color": 0}

    with patch("bot.discord_post._webhook_session") as mock_sess:
        mock_sess.get.return_value  = get_resp
        mock_sess.patch.return_value = patch_resp
        edit_llm_comment(message_ids, embed, "コメント")

    patch_call = mock_sess.patch.call_args[1]
    assert "attachments" in patch_call["json"]


def test_edit_llm_comment_skips_invalid_url():
    """Webhook URL が不正 → PATCH を発行しない。"""
    message_ids = [("msg123", "https://invalid.example.com/not/webhook")]
    embed = {"title": "test", "color": 0}
    with patch("bot.discord_post._webhook_session") as mock_sess:
        edit_llm_comment(message_ids, embed, "コメント")
    mock_sess.patch.assert_not_called()


def test_edit_llm_comment_skips_patch_on_get_error():
    """GET が3回すべて失敗した場合は PATCH をスキップする（attachment 不明のまま PATCH すると description が反映されない）。"""
    import requests
    get_resp = MagicMock()
    get_resp.raise_for_status.side_effect = requests.RequestException("timeout")

    message_ids = [("msg123", "https://discord.com/api/webhooks/1/tok")]
    embed = {"title": "test", "color": 0}

    with patch("bot.discord_post._webhook_session") as mock_sess, \
         patch("time.sleep"):
        mock_sess.get.return_value = get_resp
        edit_llm_comment(message_ids, embed, "コメント")

    mock_sess.patch.assert_not_called()


def test_edit_llm_comment_ignores_patch_error():
    """PATCH が失敗しても例外を出さない。"""
    import requests
    get_resp = MagicMock()
    get_resp.raise_for_status.return_value = None
    get_resp.json.return_value = {"attachments": []}

    message_ids = [("msg123", "https://discord.com/api/webhooks/1/tok")]
    embed = {"title": "test", "color": 0}

    with patch("bot.discord_post._webhook_session") as mock_sess:
        mock_sess.get.return_value = get_resp
        mock_sess.patch.return_value = MagicMock(
            raise_for_status=MagicMock(side_effect=requests.RequestException("patch error"))
        )
        edit_llm_comment(message_ids, embed, "コメント")  # should not raise


def test_post_uses_today_when_date_str_none():
    """date_str=None → 現在日付が使われて ValueError なし。"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"id": "msg_today"}

    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_rating_chart", return_value=None),
    ):
        mock_sess.post.return_value = mock_resp
        result = post(battles)  # date_str 省略

    assert result is not None


def test_post_continues_when_chart_raises():
    """グラフ生成が例外 → chart=None で続行する。"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"id": "msg_exc"}

    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_rating_chart", side_effect=RuntimeError("graph error")),
    ):
        mock_sess.post.return_value = mock_resp
        result = post(battles, "2024/01/01")

    assert result is not None  # グラフなしで続行


def test_post_community_weekly_handles_request_error():
    """Webhook 投稿失敗しても例外を出さない。"""
    import requests
    players = [
        {"name": "A", "wins": 5, "losses": 3, "net_rating": 100},
        {"name": "B", "wins": 3, "losses": 5, "net_rating": -50},
    ]
    with (
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
    ):
        mock_sess.post.side_effect = requests.RequestException("error")
        post_community_weekly(players, "2024/01/15")  # should not raise


def test_post_weekly_returns_none_when_all_fail():
    """全 Webhook が RequestException → None を返す。"""
    import requests
    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_chara_usage_chart", return_value=None),
        patch("bot.db.get_weekly_my_chara_counts", return_value=[]),
    ):
        mock_sess.post.side_effect = requests.RequestException("network")
        result = post_weekly(battles, "2024/01/15")
    assert result is None


def test_post_weekly_continues_when_chara_chart_raises():
    """キャラグラフ生成が例外 → chart=None で続行する。"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"id": "weekly_exc"}

    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_chara_usage_chart", side_effect=RuntimeError("chart error")),
        patch("bot.db.get_weekly_my_chara_counts", return_value=[]),
    ):
        mock_sess.post.return_value = mock_resp
        result = post_weekly(battles, "2024/01/15")

    assert result is not None


def _quick_full_battle(battle_at: int = 2000, won: bool = True) -> dict:
    """クイック種別の完全なバトルデータ。"""
    b = _full_battle(battle_at=battle_at, won=won)
    b["battle_type"] = "quick"
    b["rating_change"] = None
    b["opp_rank"] = 20
    return b


def test_post_weekly_quick_only_returns_none_but_posts():
    """クイックのみ → クイック投稿は行うが、LLM 追記対象（ランク）が無いので None を返す。"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"id": "q_only"}

    battles = [_quick_full_battle(), _quick_full_battle(battle_at=2100, won=False)]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_chara_usage_chart", return_value=None),
        patch("bot.db.get_weekly_my_chara_counts", return_value=[]),
    ):
        mock_sess.post.return_value = mock_resp
        result = post_weekly(battles, "2024/01/15")

    assert result is None             # ランク戦が無いので LLM 追記対象なし
    assert mock_sess.post.called      # だがクイック投稿は実行されている


def test_post_weekly_posts_both_rank_and_quick():
    """ランク＋クイック → 2 つの Embed を別々に投稿し、ランク結果を返す。"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"id": "both"}

    battles = [_full_battle(), _quick_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_chara_usage_chart", return_value=None),
        patch("bot.db.get_weekly_my_chara_counts", return_value=[]),
    ):
        mock_sess.post.return_value = mock_resp
        result = post_weekly(battles, "2024/01/15")

    assert result is not None
    _, rank_embed = result
    assert "ランク戦" in rank_embed["title"]
    # ランク・クイックで計 2 回（Webhook 1 件 × Embed 2 種）投稿される
    assert mock_sess.post.call_count == 2


def test_post_rank_change_no_webhook_urls():
    """WEBHOOK_URLS 未設定 → 何も送信しない（例外も出さない）。"""
    with (
        patch("bot.discord_post.WEBHOOK_URLS", []),
        patch("bot.discord_post._send_to_webhooks") as mock_send,
    ):
        post_rank_change("Alice", 15, 16)
    mock_send.assert_not_called()


def test_post_rank_change_sends_embed():
    """WEBHOOK_URLS 設定済み → _send_to_webhooks が呼ばれる。"""
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._send_to_webhooks") as mock_send,
    ):
        post_rank_change("Alice", 15, 16)
    mock_send.assert_called_once()


def test_post_monthly_returns_none_when_no_battles():
    """試合なし → None を返す。"""
    with patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]):
        result = post_monthly([], "2024年1月")
    assert result is None


def test_post_monthly_raises_when_no_webhook():
    """WEBHOOK_URLS 未設定 → ValueError を送出する。"""
    with (
        patch("bot.discord_post.WEBHOOK_URLS", []),
        pytest.raises(ValueError),
    ):
        post_monthly([_full_battle()], "2024年1月")


def test_post_monthly_success():
    """投稿成功 → (message_ids, embed) タプルを返す。"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"id": "monthly123"}

    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
    ):
        mock_sess.post.return_value = mock_resp
        result = post_monthly(battles, "2024年1月")

    assert result is not None
    message_ids, embed = result
    assert message_ids[0][0] == "monthly123"
    assert isinstance(embed, dict)
