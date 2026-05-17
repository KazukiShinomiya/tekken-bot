"""
bot/analyzer.py の純粋関数テスト。
"""

import pytest
import requests
from unittest.mock import MagicMock, patch

from bot.analyzer import (
    _build_messages, _build_system_prompt, _build_user_message,
    _compute_coaching_insights,
    _build_summary_text, _build_rematch_section, _call_ollama, _call_gemini, analyze,
)


def _battle(won: bool, opp_chara: str = "Jin", battle_type: str = "ranked",
            battle_at: int = 0) -> dict:
    return {
        "won": won,
        "opp_chara": opp_chara,
        "battle_type": battle_type,
        "my_rounds": 2,
        "opp_rounds": 1,
        "battle_at": battle_at,
    }


def test_build_user_message_contains_date():
    battles = [_battle(True)]
    msg = _build_user_message(battles, "2024/01/15")
    assert "2024/01/15" in msg


def test_build_user_message_contains_player_name():
    battles = [_battle(True)]
    msg = _build_user_message(battles, "2024/01/15", player_name="TestPlayer")
    assert "TestPlayer" in msg


def test_build_user_message_default_player_name():
    """player_name 未指定時でも例外なく有効な文字列を返す。"""
    battles = [_battle(True)]
    msg = _build_user_message(battles, "2024/01/15")
    assert isinstance(msg, str)
    assert len(msg) > 0
    assert "ExodusOverseer" not in msg


def test_build_user_message_contains_win_loss():
    battles = [_battle(True), _battle(True), _battle(False)]
    msg = _build_user_message(battles, "2024/01/15")
    assert "2勝1敗" in msg


def test_build_user_message_contains_opp_chara():
    battles = [_battle(True, "Dragunov"), _battle(False, "Dragunov")]
    msg = _build_user_message(battles, "2024/01/15")
    assert "Dragunov" in msg


def test_build_user_message_ranked_quick_split():
    battles = [
        _battle(True, battle_type="ranked"),
        _battle(False, battle_type="quick"),
    ]
    msg = _build_user_message(battles, "2024/01/15")
    assert "ランク戦" in msg
    assert "クイック" in msg


def test_build_user_message_empty_battles():
    """空のバトルリストでも例外を出さない。"""
    msg = _build_user_message([], "2024/01/15")
    assert isinstance(msg, str)
    assert len(msg) > 0


def test_build_user_message_round_win_rate():
    battles = [_battle(True)]  # my_rounds=2, opp_rounds=1
    msg = _build_user_message(battles, "2024/01/15")
    assert "ラウンド勝率" in msg


def test_build_system_prompt_150_chars_instruction():
    """システムプロンプトに 150文字以内 の制約が含まれる。"""
    prompt = _build_system_prompt()
    assert "150文字以内" in prompt


def test_build_user_message_shows_streak():
    """3連勝の場合、最長連勝がユーザーメッセージに含まれる。"""
    battles = [_battle(True, battle_at=i) for i in range(3)]
    msg = _build_user_message(battles, "2024/01/15")
    assert "最長連勝: 3" in msg


def test_build_user_message_omits_streak_when_less_than_2():
    """1連勝は表示されない。"""
    battles = [_battle(True, battle_at=1), _battle(False, battle_at=2)]
    msg = _build_user_message(battles, "2024/01/15")
    assert "最長連勝" not in msg
    assert "最長連敗" not in msg


def test_build_user_message_with_rating_change():
    """ランク戦にレーティング変動がある場合、ユーザーメッセージに含まれる。"""
    battle = _battle(True, battle_type="ranked")
    battle["rating_change"] = 50
    msg = _build_user_message([battle], "2024/01/15")
    assert "レーティング変動" in msg
    assert "+50" in msg


# ---------------------------------------------------------------------------
# _compute_coaching_insights
# ---------------------------------------------------------------------------

def _battle_with_ts(won: bool, opp_chara: str = "Jin", battle_at: int = 0) -> dict:
    return {
        "won": won,
        "opp_chara": opp_chara,
        "battle_type": "ranked",
        "my_rounds": 2,
        "opp_rounds": 1,
        "battle_at": battle_at,
    }


def test_coaching_insights_weak_chara():
    """2戦以上で勝率 40% 未満のキャラが weak に入る。"""
    battles = [
        _battle_with_ts(False, "Dragunov", 0),
        _battle_with_ts(False, "Dragunov", 1),
        _battle_with_ts(False, "Dragunov", 2),
    ]
    insights = _compute_coaching_insights(battles, None)
    weak_charas = [c for c, _, _ in insights["weak"]]
    assert "Dragunov" in weak_charas


def test_coaching_insights_strong_chara():
    """2戦以上で勝率 70% 以上のキャラが strong に入る。"""
    battles = [
        _battle_with_ts(True, "Jin", 0),
        _battle_with_ts(True, "Jin", 1),
        _battle_with_ts(True, "Jin", 2),
    ]
    insights = _compute_coaching_insights(battles, None)
    strong_charas = [c for c, _, _ in insights["strong"]]
    assert "Jin" in strong_charas


def test_coaching_insights_no_weak_when_few_battles():
    """1戦のみのキャラは weak/strong に入らない。"""
    battles = [_battle_with_ts(False, "Dragunov", 0)]
    insights = _compute_coaching_insights(battles, None)
    assert insights["weak"] == []
    assert insights["strong"] == []


def test_coaching_insights_trend_positive():
    """前日比勝率が10pt以上上昇した場合、trend に ↑ が含まれる。"""
    today    = [_battle_with_ts(True, "Jin", i) for i in range(8)] + \
               [_battle_with_ts(False, "Jin", 100 + i) for i in range(2)]  # 80%
    prev     = [_battle_with_ts(False, "Jin", i) for i in range(6)] + \
               [_battle_with_ts(True, "Jin", 100 + i) for i in range(4)]   # 40%
    insights = _compute_coaching_insights(today, prev)
    assert insights["trend"] is not None
    assert "↑" in insights["trend"]


def test_coaching_insights_trend_negative():
    """前日比勝率が10pt以上低下した場合、trend に ↓ が含まれる。"""
    today    = [_battle_with_ts(False, "Jin", i) for i in range(6)] + \
               [_battle_with_ts(True, "Jin", 100 + i) for i in range(4)]   # 40%
    prev     = [_battle_with_ts(True, "Jin", i) for i in range(8)] + \
               [_battle_with_ts(False, "Jin", 100 + i) for i in range(2)]  # 80%
    insights = _compute_coaching_insights(today, prev)
    assert insights["trend"] is not None
    assert "↓" in insights["trend"]


def test_coaching_insights_trend_none_when_small_diff():
    """前日比の差が小さい場合は trend が None。"""
    today = [_battle_with_ts(True, "Jin", i) for i in range(5)] + \
            [_battle_with_ts(False, "Jin", 100 + i) for i in range(5)]  # 50%
    prev  = [_battle_with_ts(True, "Jin", i) for i in range(5)] + \
            [_battle_with_ts(False, "Jin", 100 + i) for i in range(5)]  # 50%
    insights = _compute_coaching_insights(today, prev)
    assert insights["trend"] is None


def test_coaching_insights_no_trend_without_prev():
    """prev_battles が None の場合、trend は None。"""
    battles = [_battle_with_ts(True, "Jin", i) for i in range(5)]
    insights = _compute_coaching_insights(battles, None)
    assert insights["trend"] is None


def test_build_user_message_includes_weak_chara():
    """苦手キャラがあればユーザーメッセージに '苦手キャラ' が含まれる。"""
    battles = [_battle(False, "Dragunov", battle_at=i) for i in range(3)]
    msg = _build_user_message(battles, "2024/01/15")
    assert "苦手キャラ" in msg
    assert "Dragunov" in msg


def test_build_user_message_includes_strong_chara():
    """得意キャラがあればユーザーメッセージに '得意キャラ' が含まれる。"""
    battles = [_battle(True, "Jin", battle_at=i) for i in range(3)]
    msg = _build_user_message(battles, "2024/01/15")
    assert "得意キャラ" in msg
    assert "Jin" in msg


def test_build_user_message_includes_rematch_data():
    """rematch_data があれば通算成績がユーザーメッセージに含まれる。"""
    battles = [_battle(True)]
    rematch = {
        "pid1": {
            "name": "RivalPlayer",
            "chara": "Paul",
            "history": [{"won": True}, {"won": False}, {"won": True}],
        }
    }
    msg = _build_user_message(battles, "2024/01/15", rematch_data=rematch)
    assert "繰り返し対戦" in msg
    assert "RivalPlayer" in msg


# ---------------------------------------------------------------------------
# _build_summary_text
# ---------------------------------------------------------------------------

def _make_stats(
    wins: int = 3,
    losses: int = 2,
    net_rating: int | None = None,
    max_win: int = 1,
    max_lose: int = 1,
    matchups: list[str] | None = None,
) -> dict:
    return {
        "wins": wins, "losses": losses,
        "ranked": [], "quick": [],
        "round_wr": "60%",
        "net_rating": net_rating,
        "max_win": max_win, "max_lose": max_lose,
        "matchups": matchups or [],
    }


def test_build_summary_text_contains_date():
    text = _build_summary_text(_make_stats(), "2024/01/15")
    assert "2024/01/15" in text


def test_build_summary_text_contains_win_loss():
    text = _build_summary_text(_make_stats(wins=4, losses=1), "2024/01/15")
    assert "4勝1敗" in text


def test_build_summary_text_with_positive_rating():
    text = _build_summary_text(_make_stats(net_rating=200), "2024/01/15")
    assert "+200" in text


def test_build_summary_text_with_negative_rating():
    text = _build_summary_text(_make_stats(net_rating=-50), "2024/01/15")
    assert "-50" in text


def test_build_summary_text_no_rating_when_none():
    text = _build_summary_text(_make_stats(net_rating=None), "2024/01/15")
    assert "レーティング変動" not in text


def test_build_summary_text_shows_win_streak():
    text = _build_summary_text(_make_stats(max_win=3), "2024/01/15")
    assert "最長連勝: 3" in text


def test_build_summary_text_shows_lose_streak():
    text = _build_summary_text(_make_stats(max_lose=4), "2024/01/15")
    assert "最長連敗: 4" in text


def test_build_summary_text_omits_streak_below_2():
    text = _build_summary_text(_make_stats(max_win=1, max_lose=1), "2024/01/15")
    assert "最長連勝" not in text
    assert "最長連敗" not in text


def test_build_summary_text_includes_matchups():
    text = _build_summary_text(_make_stats(matchups=["  Jin: 2勝1敗"]), "2024/01/15")
    assert "Jin" in text


# ---------------------------------------------------------------------------
# _build_rematch_section
# ---------------------------------------------------------------------------

def test_build_rematch_section_empty():
    result = _build_rematch_section({})
    assert result == ""


def test_build_rematch_section_with_data():
    data = {
        "pid_a": {
            "name": "Rival",
            "chara": "Jin",
            "history": [{"won": True}, {"won": False}, {"won": True}],
        }
    }
    result = _build_rematch_section(data)
    assert "Rival(Jin)" in result
    assert "2勝1敗" in result
    assert "繰り返し対戦" in result


def test_build_rematch_section_multiple_opponents():
    data = {
        "pid_a": {"name": "Alpha", "chara": "Jin",  "history": [{"won": True}]},
        "pid_b": {"name": "Beta",  "chara": "Paul", "history": [{"won": False}]},
    }
    result = _build_rematch_section(data)
    assert "Alpha" in result
    assert "Beta" in result


# ---------------------------------------------------------------------------
# _call_ollama
# ---------------------------------------------------------------------------

_TEST_MESSAGES = [{"role": "user", "content": "test"}]


def _ollama_resp(comment: str) -> MagicMock:
    """Ollama Chat API（/api/chat）のレスポンスモックを生成する。"""
    import json
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {
        "message": {"role": "assistant", "content": json.dumps({"comment": comment})}
    }
    return mock


def test_call_ollama_parses_json_comment():
    """Chat API レスポンスの message.content から comment フィールドを抽出して返す。"""
    with patch("requests.post", return_value=_ollama_resp("良い調子です")):
        result = _call_ollama("testmodel", _TEST_MESSAGES)
    assert result == "良い調子です"


def test_call_ollama_fallback_on_invalid_json():
    """JSON 解析失敗時は生テキストにフォールバックして返す。"""
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"message": {"role": "assistant", "content": "これはJSONではない"}}
    with patch("requests.post", return_value=mock):
        result = _call_ollama("testmodel", _TEST_MESSAGES)
    assert result == "これはJSONではない"


def test_call_ollama_returns_none_for_empty_response():
    """空コンテンツは None を返す。"""
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"message": {"role": "assistant", "content": ""}}
    with patch("requests.post", return_value=mock):
        result = _call_ollama("testmodel", _TEST_MESSAGES)
    assert result is None


def test_call_ollama_returns_none_for_empty_comment_field():
    """JSON の comment が空文字の場合も None を返す。"""
    import json
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"message": {"role": "assistant", "content": json.dumps({"comment": ""})}}
    with patch("requests.post", return_value=mock):
        result = _call_ollama("testmodel", _TEST_MESSAGES)
    assert result is None


def test_call_ollama_raises_on_http_error():
    """HTTP エラー時は例外を再送出する。"""
    with patch("requests.post", side_effect=requests.RequestException("connection error")):
        with pytest.raises(requests.RequestException):
            _call_ollama("testmodel", _TEST_MESSAGES)


def test_call_ollama_uses_chat_endpoint():
    """Chat API エンドポイント（/api/chat）を呼び出す。"""
    with patch("requests.post", return_value=_ollama_resp("テスト")) as mock_post:
        _call_ollama("testmodel", _TEST_MESSAGES)
    url = mock_post.call_args[0][0]
    assert url.endswith("/api/chat")


def test_call_ollama_sends_messages_array():
    """requests.post に messages リストが渡される。"""
    with patch("requests.post", return_value=_ollama_resp("テスト")) as mock_post:
        _call_ollama("testmodel", _TEST_MESSAGES)
    payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
    assert "messages" in payload
    assert payload["messages"] == _TEST_MESSAGES


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------

def _ranked_battle(won: bool = True, battle_at: int = 0) -> dict:
    return {
        "won": won, "opp_chara": "Jin", "battle_type": "ranked",
        "my_rounds": 2, "opp_rounds": 1, "battle_at": battle_at,
    }


def test_analyze_empty_battles_returns_none():
    assert analyze([], "2024/01/15") is None


def test_analyze_calls_primary_model_and_returns_comment():
    battles = [_ranked_battle()]
    with patch("requests.post", return_value=_ollama_resp("今日は好調")):
        result = analyze(battles, "2024/01/15", "TestPlayer")
    assert result == "今日は好調"


def test_analyze_fallback_on_primary_failure():
    """プライマリモデル失敗 → フォールバックモデルで成功。"""
    battles = [_ranked_battle()]
    with (
        patch("bot.analyzer.OLLAMA_FALLBACK_MODEL", "fallback_model"),
        patch("requests.post", side_effect=[
            requests.RequestException("primary fail"),
            _ollama_resp("フォールバック結果"),
        ]),
    ):
        result = analyze(battles, "2024/01/15", "TestPlayer")
    assert result == "フォールバック結果"


def test_analyze_both_models_fail_returns_none():
    """両モデルとも失敗 → None。"""
    battles = [_ranked_battle()]
    with (
        patch("bot.analyzer.OLLAMA_FALLBACK_MODEL", "fallback_model"),
        patch("requests.post", side_effect=requests.RequestException("all fail")),
    ):
        result = analyze(battles, "2024/01/15", "TestPlayer")
    assert result is None


def test_analyze_no_fallback_configured_returns_none():
    """フォールバックモデル未設定でプライマリ失敗 → None。"""
    battles = [_ranked_battle()]
    with (
        patch("bot.analyzer.OLLAMA_FALLBACK_MODEL", ""),
        patch("requests.post", side_effect=requests.RequestException("primary fail")),
    ):
        result = analyze(battles, "2024/01/15", "TestPlayer")
    assert result is None


def test_analyze_with_prev_battles():
    """prev_battles を渡しても例外なく動作する。"""
    battles = [_ranked_battle(won=True,  battle_at=200)]
    prev    = [_ranked_battle(won=False, battle_at=100)]
    with patch("requests.post", return_value=_ollama_resp("前日比コメント")):
        result = analyze(battles, "2024/01/15", "TestPlayer", prev_battles=prev)
    assert result == "前日比コメント"


def test_analyze_invalid_date_format():
    """日付フォーマットが不正でも例外を出さない。"""
    battles = [_ranked_battle()]
    with patch("requests.post", return_value=_ollama_resp("OK")):
        result = analyze(battles, "invalid-date", "TestPlayer")
    assert result is not None


def test_build_messages_returns_two_messages():
    """_build_messages() は system + user の2要素リストを返す。"""
    battles = [_battle(True)]
    msgs = _build_messages(battles, "2024/01/15")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"


def test_build_messages_system_contains_xml_tags():
    """システムメッセージに examples / constraints / output_format タグが含まれる。"""
    system_content = _build_messages([_battle(True)], "2024/01/15")[0]["content"]
    for tag in ["<examples>", "<constraints>", "<output_format>"]:
        assert tag in system_content


def test_build_messages_user_contains_xml_tags():
    """ユーザーメッセージに battle_data / insights タグが含まれる。"""
    user_content = _build_messages([_battle(True)], "2024/01/15")[1]["content"]
    for tag in ["<battle_data>", "<insights>"]:
        assert tag in user_content


def test_build_system_prompt_contains_few_shot_examples():
    """システムプロンプトに Few-shot サンプルが含まれる。"""
    prompt = _build_system_prompt()
    assert "<example>" in prompt
    assert "Bryan" in prompt  # サンプル内のキャラ名


def test_build_system_prompt_no_player_specific_data():
    """システムプロンプトにプレイヤー固有データ（ExodusOverseer）は含まれない。"""
    prompt = _build_system_prompt()
    assert "ExodusOverseer" not in prompt


# ---------------------------------------------------------------------------
# _call_gemini
# ---------------------------------------------------------------------------

def _gemini_client_mock(comment_text: str) -> MagicMock:
    """google.genai.Client モックを返す。"""
    import json
    mock_response = MagicMock()
    mock_response.text = json.dumps({"comment": comment_text})
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


def test_call_gemini_returns_comment():
    """Gemini API が正常な JSON を返した場合に comment を抽出して返す。"""
    mock_client = _gemini_client_mock("Geminiコメント")
    with (
        patch("bot.analyzer.GEMINI_API_KEY", "test-key"),
        patch("google.genai.Client", return_value=mock_client),
    ):
        result = _call_gemini("system prompt", "user message")
    assert result == "Geminiコメント"


def test_call_gemini_fallback_on_invalid_json():
    """JSON 解析失敗時は生テキストにフォールバックして返す。"""
    mock_response = MagicMock()
    mock_response.text = "これはJSONではない"
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    with (
        patch("bot.analyzer.GEMINI_API_KEY", "test-key"),
        patch("google.genai.Client", return_value=mock_client),
    ):
        result = _call_gemini("system prompt", "user message")
    assert result == "これはJSONではない"


def test_call_gemini_returns_none_for_empty_response():
    """空レスポンスは None を返す。"""
    mock_response = MagicMock()
    mock_response.text = ""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    with (
        patch("bot.analyzer.GEMINI_API_KEY", "test-key"),
        patch("google.genai.Client", return_value=mock_client),
    ):
        result = _call_gemini("system prompt", "user message")
    assert result is None


def test_call_gemini_raises_on_api_error():
    """API エラー時は例外を再送出する。"""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("API error")
    with (
        patch("bot.analyzer.GEMINI_API_KEY", "test-key"),
        patch("google.genai.Client", return_value=mock_client),
    ):
        with pytest.raises(Exception):
            _call_gemini("system prompt", "user message")


# ---------------------------------------------------------------------------
# analyze — Gemini フォールバック統合テスト
# ---------------------------------------------------------------------------

def test_analyze_gemini_fallback_when_both_ollama_fail():
    """Ollama 両モデル失敗 + GEMINI_API_KEY あり → Gemini が成功してコメントを返す。"""
    battles = [_ranked_battle()]
    with (
        patch("bot.analyzer.OLLAMA_FALLBACK_MODEL", "fallback_model"),
        patch("bot.analyzer.GEMINI_API_KEY", "test-key"),
        patch("requests.post", side_effect=requests.RequestException("all ollama fail")),
        patch("bot.analyzer._call_gemini", return_value="Geminiコメント"),
    ):
        result = analyze(battles, "2024/01/15", "TestPlayer")
    assert result == "Geminiコメント"


def test_analyze_gemini_not_called_without_api_key():
    """GEMINI_API_KEY 未設定では Ollama 失敗後も Gemini は呼ばれない。"""
    battles = [_ranked_battle()]
    with (
        patch("bot.analyzer.OLLAMA_FALLBACK_MODEL", "fallback_model"),
        patch("bot.analyzer.GEMINI_API_KEY", ""),
        patch("requests.post", side_effect=requests.RequestException("all ollama fail")),
        patch("bot.analyzer._call_gemini") as mock_gemini,
    ):
        result = analyze(battles, "2024/01/15", "TestPlayer")
    assert result is None
    mock_gemini.assert_not_called()


def test_analyze_returns_none_when_gemini_also_fails():
    """Ollama 両モデル + Gemini すべて失敗 → None。"""
    battles = [_ranked_battle()]
    with (
        patch("bot.analyzer.OLLAMA_FALLBACK_MODEL", "fallback_model"),
        patch("bot.analyzer.GEMINI_API_KEY", "test-key"),
        patch("requests.post", side_effect=requests.RequestException("all ollama fail")),
        patch("bot.analyzer._call_gemini", side_effect=Exception("gemini fail")),
    ):
        result = analyze(battles, "2024/01/15", "TestPlayer")
    assert result is None


# ---------------------------------------------------------------------------
# analyze — GEMINI_FIRST フラグ
# ---------------------------------------------------------------------------

def test_analyze_gemini_first_calls_gemini_before_ollama():
    """GEMINI_FIRST=True のとき Gemini が最初に呼ばれ、成功すれば Ollama は呼ばれない。"""
    battles = [_ranked_battle()]
    with (
        patch("bot.analyzer.GEMINI_FIRST", True),
        patch("bot.analyzer.GEMINI_API_KEY", "test-key"),
        patch("bot.analyzer._call_gemini", return_value="Gemini優先コメント"),
        patch("bot.analyzer._call_ollama") as mock_ollama,
    ):
        result = analyze(battles, "2024/01/15", "TestPlayer")
    assert result == "Gemini優先コメント"
    mock_ollama.assert_not_called()


def test_analyze_gemini_first_falls_back_to_ollama_on_failure():
    """GEMINI_FIRST=True で Gemini 失敗 → Ollama にフォールバック。"""
    battles = [_ranked_battle()]
    with (
        patch("bot.analyzer.GEMINI_FIRST", True),
        patch("bot.analyzer.GEMINI_API_KEY", "test-key"),
        patch("bot.analyzer._call_gemini", side_effect=Exception("gemini fail")),
        patch("requests.post", return_value=_ollama_resp("Ollama代替コメント")),
    ):
        result = analyze(battles, "2024/01/15", "TestPlayer")
    assert result == "Ollama代替コメント"
