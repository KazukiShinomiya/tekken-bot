"""
bot/evaluator.py のユニットテスト。
"""

import pytest

from bot.evaluator import (
    evaluate_comment,
    _check_length,
    _check_chara_validity,
    _check_action_presence,
    MAX_COMMENT_LENGTH,
)


# ---------------------------------------------------------------------------
# テストヘルパー
# ---------------------------------------------------------------------------

def _battle(opp_chara: str = "Jin", my_chara: str = "Lee", won: bool = True) -> dict:
    return {
        "battle_id":   "test",
        "battle_at":   0,
        "won":         won,
        "opp_chara":   opp_chara,
        "my_chara":    my_chara,
        "battle_type": "ranked",
        "my_rounds":   2,
        "opp_rounds":  1,
    }


# ---------------------------------------------------------------------------
# _check_length
# ---------------------------------------------------------------------------

class TestCheckLength:
    def test_exactly_150_chars_passes(self):
        comment = "あ" * 150
        result = _check_length(comment)
        assert result["score"] == 40
        assert result["max"]   == 40
        assert "OK" in result["message"]

    def test_under_150_chars_passes(self):
        comment = "今日は良い日だった。"
        result = _check_length(comment)
        assert result["score"] == 40

    def test_151_chars_fails(self):
        comment = "あ" * 151
        result = _check_length(comment)
        assert result["score"] == 0
        assert "超過" in result["message"]

    def test_empty_string_passes(self):
        result = _check_length("")
        assert result["score"] == 40

    def test_message_contains_length(self):
        comment = "abc"
        result = _check_length(comment)
        assert "3文字" in result["message"]

    def test_over_length_message_contains_threshold(self):
        comment = "x" * 200
        result = _check_length(comment)
        assert str(MAX_COMMENT_LENGTH) in result["message"]


# ---------------------------------------------------------------------------
# _check_chara_validity
# ---------------------------------------------------------------------------

class TestCheckCharaValidity:
    def test_no_hallucination_passes(self):
        battles = [_battle(opp_chara="Jin")]
        comment = "Jin戦は安定している。対策を続けよう。"
        result = _check_chara_validity(comment, battles)
        assert result["score"] == 40
        assert result["hallucinated"] == []

    def test_my_chara_mention_is_valid(self):
        """自分のキャラ（my_chara）への言及はハルシネーションではない。"""
        battles = [_battle(opp_chara="Jin", my_chara="Lee")]
        comment = "Leeの試合運びは良かった。"
        result = _check_chara_validity(comment, battles)
        assert result["score"] == 40

    def test_hallucinated_chara_detected(self):
        """対戦していないキャラクター名がコメントにあれば 0点。"""
        battles = [_battle(opp_chara="Jin", my_chara="Lee")]
        # Paul は対戦していない
        comment = "Paul戦が課題だ。対策しよう。"
        result = _check_chara_validity(comment, battles)
        assert result["score"] == 0
        assert "Paul" in result["hallucinated"]

    def test_multiple_hallucinations_detected(self):
        battles = [_battle(opp_chara="Jin", my_chara="Lee")]
        comment = "Paul戦とKazuya戦に注意が必要だ。"
        result = _check_chara_validity(comment, battles)
        assert result["score"] == 0
        assert len(result["hallucinated"]) >= 2
        assert "Paul"   in result["hallucinated"]
        assert "Kazuya" in result["hallucinated"]

    def test_empty_battles_all_charas_are_hallucination(self):
        """対戦なしのバトルリストで既知キャラ言及すると 0点。"""
        comment = "Kazuya戦が厳しかった。"
        result = _check_chara_validity(comment, [])
        assert result["score"] == 0
        assert "Kazuya" in result["hallucinated"]

    def test_comment_with_no_chara_names_passes(self):
        """キャラ名を含まないコメントは常に合格。"""
        battles = []
        comment = "今日は調子が良かった。全体的に反応が早かった。"
        result = _check_chara_validity(comment, battles)
        assert result["score"] == 40

    def test_opp_chara_none_is_skipped(self):
        """opp_chara が None のバトルは無視する。"""
        battle = {
            "battle_id": "x", "battle_at": 0, "won": True,
            "opp_chara": None, "my_chara": "Lee",
            "battle_type": "ranked",
        }
        comment = "今日は問題なし。"
        result = _check_chara_validity(comment, [battle])
        assert result["score"] == 40

    def test_hallucinated_list_is_sorted(self):
        battles = [_battle(opp_chara="Jin", my_chara="Lee")]
        comment = "Steve、King、Kazuya戦の対策が必要だ。"
        result = _check_chara_validity(comment, battles)
        assert result["hallucinated"] == sorted(result["hallucinated"])

    def test_returns_max_40(self):
        battles = [_battle()]
        result = _check_chara_validity("問題なし", battles)
        assert result["max"] == 40


# ---------------------------------------------------------------------------
# _check_action_presence
# ---------------------------------------------------------------------------

class TestCheckActionPresence:
    def test_action_word_detected(self):
        comment = "Bryan戦は対策が必要だ。"
        result = _check_action_presence(comment)
        assert result["score"] == 20
        assert "対策" in result["found"]

    def test_multiple_action_words_detected(self):
        comment = "Kazuya戦は練習と対策を優先しよう。"
        result = _check_action_presence(comment)
        assert result["score"] == 20
        assert len(result["found"]) >= 2

    def test_no_action_word_fails(self):
        comment = "今日は3勝2敗だった。"
        result = _check_action_presence(comment)
        assert result["score"] == 0
        assert result["found"] == []
        assert "アクションワード" in result["message"]

    def test_returns_max_20(self):
        result = _check_action_presence("今日は改善の余地あり")
        assert result["max"] == 20

    def test_message_shows_found_keywords(self):
        comment = "対策と練習と意識が必要だ。"
        result = _check_action_presence(comment)
        assert "OK" in result["message"]

    def test_more_than_3_keywords_shows_ellipsis(self):
        """4つ以上のキーワードがある場合、表示は省略される。"""
        comment = "対策・練習・意識・改善・強化が必要だ。"
        result = _check_action_presence(comment)
        assert "..." in result["message"]

    def test_partial_match_in_word_counts(self):
        """「意識」が文中の一部として出現しても検出される。"""
        comment = "常に意識を高く保つこと。"
        result = _check_action_presence(comment)
        assert result["score"] == 20


# ---------------------------------------------------------------------------
# evaluate_comment (統合)
# ---------------------------------------------------------------------------

class TestEvaluateComment:
    def test_perfect_score_100(self):
        """全軸合格で 100点。"""
        battles = [_battle(opp_chara="Bryan", my_chara="Lee")]
        comment = "Bryan戦は苦戦したが対策を続けよう。ヒートスマッシュ後の二択を意識すること。"
        result = evaluate_comment(comment, battles)
        assert result["score"] == 100

    def test_score_structure(self):
        battles = [_battle()]
        result = evaluate_comment("今日は調子が良かった。", battles)
        assert "score"   in result
        assert "details" in result
        assert "length"      in result["details"]
        assert "chara_valid" in result["details"]
        assert "has_action"  in result["details"]

    def test_long_comment_loses_40_points(self):
        battles = [_battle(opp_chara="Jin", my_chara="Lee")]
        comment = "対策" + "あ" * 149  # 151文字（'対策'2文字 + 149文字 = 151文字）
        result = evaluate_comment(comment, battles)
        assert result["details"]["length"]["score"] == 0
        assert result["score"] <= 60

    def test_hallucination_loses_40_points(self):
        battles = [_battle(opp_chara="Jin", my_chara="Lee")]
        comment = "Paul戦を対策しよう。"  # Paul は未対戦
        result = evaluate_comment(comment, battles)
        assert result["details"]["chara_valid"]["score"] == 0
        assert result["score"] <= 60

    def test_no_action_loses_20_points(self):
        battles = [_battle(opp_chara="Jin", my_chara="Lee")]
        comment = "Jin戦だった。"  # アクションワードなし
        result = evaluate_comment(comment, battles)
        assert result["details"]["has_action"]["score"] == 0
        assert result["score"] <= 80

    def test_zero_score_all_fail(self):
        """全軸失敗: 長すぎ + ハルシネーション + アクションなし。"""
        battles = [_battle(opp_chara="Jin", my_chara="Lee")]
        # 151文字、Paul（未対戦）を言及、アクションワードなし
        comment = "Paul" + "今日は" * 50  # 154文字
        result = evaluate_comment(comment, battles)
        assert result["score"] == 0

    def test_score_is_sum_of_details(self):
        """score が details の合計と一致する。"""
        battles = [_battle()]
        comment = "Jin戦の対策を続けよう。今日は良かった。"
        result = evaluate_comment(comment, battles)
        detail_sum = sum(d["score"] for d in result["details"].values())
        assert result["score"] == detail_sum

    def test_empty_battles_list(self):
        """バトルなしでもクラッシュしない。"""
        result = evaluate_comment("今日は調子が良かった。対策しよう。", [])
        assert isinstance(result["score"], int)
        assert 0 <= result["score"] <= 100
