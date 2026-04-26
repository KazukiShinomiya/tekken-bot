"""
Discord スラッシュコマンド Bot。

コマンド一覧:
  /tekken today  — 今日の戦績を即時取得・投稿
  /tekken weekly — 週次サマリーを即時投稿
  /tekken status — Bot 稼働状況を確認
  /tekken trend  — レーティング推移グラフを表示
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import Counter
from datetime import datetime, timedelta

import discord
from discord import app_commands

import bot.db as db
import main as _bot_main
from bot.config import DISCORD_BOT_TOKEN as BOT_TOKEN, DISCORD_GUILD_ID, JST
from bot.graph import generate_rating_chart
from bot.stats import count_wins, count_losses, get_most_common, detect_winning_streak, detect_losing_streak

logger = logging.getLogger(__name__)

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

tekken_group = app_commands.Group(name="tekken", description="鉄拳Bot コマンド")


@tekken_group.command(name="today", description="戦績を取得して投稿する（省略時は今日、日付指定も可）")
@app_commands.describe(date="対象日 YYYY-MM-DD（省略すると今日）")
async def cmd_today(interaction: discord.Interaction, date: str | None = None) -> None:
    await interaction.response.defer(thinking=True)
    try:
        if date is not None:
            datetime.strptime(date, "%Y-%m-%d")  # バリデーション
            target_date = date
        else:
            target_date = datetime.now(JST).strftime("%Y-%m-%d")
        await _bot_main.main(target_date=target_date)
        await interaction.followup.send(f"✅ {target_date} の戦績を投稿しました。")
    except ValueError:
        await interaction.followup.send("❌ 日付形式が正しくありません（YYYY-MM-DD）。")
    except Exception as e:
        logger.error(f"[slash_commands] /tekken today エラー: {e}")
        await interaction.followup.send(f"❌ エラーが発生しました: {e}")


@tekken_group.command(name="weekly", description="週次サマリーを投稿する")
async def cmd_weekly(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    try:
        await _bot_main.weekly()
        await interaction.followup.send("✅ 週次サマリーを投稿しました。")
    except Exception as e:
        logger.error(f"[slash_commands] /tekken weekly エラー: {e}")
        await interaction.followup.send(f"❌ エラーが発生しました: {e}")


@tekken_group.command(name="status", description="Bot の稼働状況を確認する")
async def cmd_status(interaction: discord.Interaction) -> None:
    now = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
    await interaction.response.send_message(f"✅ Bot 稼働中 | {now} JST")


@tekken_group.command(name="trend", description="レーティング推移グラフを表示する")
@app_commands.describe(days="期間（日数、デフォルト30日）")
async def cmd_trend(interaction: discord.Interaction, days: int = 30) -> None:
    await interaction.response.defer(thinking=True)
    try:
        since_ts = (datetime.now(JST) - timedelta(days=days)).timestamp()
        players  = _bot_main.get_players()
        if not players:
            await interaction.followup.send("❌ プレイヤーが設定されていません。")
            return

        player_name, _ = players[0]
        battles = db.get_battles_since(since_ts, player_name=player_name)
        chart   = generate_rating_chart(battles, player_name=player_name)

        if chart is None:
            await interaction.followup.send(
                "❌ グラフを生成できませんでした（データ不足またはライブラリ未インストール）。"
            )
            return

        file  = discord.File(chart, filename="rating_trend.png")
        embed = discord.Embed(
            title=f"📈 {player_name} レーティング推移（直近{days}日）",
            color=0x5865F2,
        )
        embed.set_image(url="attachment://rating_trend.png")
        await interaction.followup.send(embed=embed, file=file)
    except Exception as e:
        logger.error(f"[slash_commands] /tekken trend エラー: {e}")
        await interaction.followup.send(f"❌ エラーが発生しました: {e}")


@tekken_group.command(name="vs", description="特定の対戦相手との通算成績を確認する")
@app_commands.describe(name="対戦相手の名前（部分一致）")
async def cmd_vs(interaction: discord.Interaction, name: str) -> None:
    await interaction.response.defer(thinking=True)
    battles = db.search_battles_vs_opponent(name)
    if not battles:
        await interaction.followup.send(f"❌ `{name}` との対戦記録が見つかりません。")
        return

    wins   = count_wins(battles)
    losses = count_losses(battles)
    total  = wins + losses
    wr     = wins / total * 100 if total else 0

    main_chara, _ = get_most_common(battles, "opp_chara")

    recent = sorted(battles, key=lambda x: x["battle_at"], reverse=True)[:5]
    recent_lines = []
    for b in recent:
        dt   = datetime.fromtimestamp(b["battle_at"], JST).strftime("%m/%d")
        icon = "✅" if b["won"] else "❌"
        recent_lines.append(f"{icon} {dt}  {b.get('my_chara','???')} vs {b.get('opp_chara','???')}")

    embed = discord.Embed(
        title=f"🔍 vs {name} の通算成績",
        color=0x57F287 if wr >= 50 else 0xED4245,
    )
    embed.add_field(name="通算", value=f"{wins}勝{losses}敗 ({wr:.0f}%)", inline=True)
    embed.add_field(name="対戦キャラ（最多）", value=main_chara, inline=True)
    if recent_lines:
        embed.add_field(name="直近5試合", value="\n".join(recent_lines), inline=False)
    await interaction.followup.send(embed=embed)


async def _chara_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """battles テーブルの実績キャラ名からオートコンプリート候補を返す。"""
    known = db.get_known_opp_charas()
    lower = current.lower()
    matches = [c for c in known if lower in c.lower()]
    return [app_commands.Choice(name=c, value=c) for c in matches[:25]]


@tekken_group.command(name="chara", description="特定キャラクターとの対戦成績を確認する")
@app_commands.describe(name="キャラクター名（例: Bryan, Jin）")
@app_commands.autocomplete(name=_chara_autocomplete)
async def cmd_chara(interaction: discord.Interaction, name: str) -> None:
    await interaction.response.defer(thinking=True)
    battles = db.get_battles_by_opp_chara(name)
    if not battles:
        await interaction.followup.send(f"❌ `{name}` との対戦記録が見つかりません。")
        return

    wins   = count_wins(battles)
    losses = count_losses(battles)
    total  = wins + losses
    wr     = wins / total * 100 if total else 0

    recent = sorted(battles, key=lambda x: x["battle_at"], reverse=True)[:10]
    recent_icons = " ".join("✅" if b["won"] else "❌" for b in recent)

    embed = discord.Embed(
        title=f"🥊 vs {name} の通算成績",
        color=0x57F287 if wr >= 50 else 0xED4245,
    )
    embed.add_field(name="通算",   value=f"{wins}勝{losses}敗", inline=True)
    embed.add_field(name="勝率",   value=f"{wr:.1f}%",          inline=True)
    embed.add_field(name="総試合", value=f"{total}戦",          inline=True)
    embed.add_field(name="直近10試合", value=recent_icons or "-", inline=False)
    await interaction.followup.send(embed=embed)


@tekken_group.command(name="top", description="キャラ別対戦成績ランキングを確認する（全期間）")
async def cmd_top(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    stats = db.get_matchup_ranking(min_battles=2)
    if not stats:
        await interaction.followup.send("❌ 対戦データが足りません（各キャラ2戦以上必要）。")
        return

    lines = []
    for row in stats[:20]:
        chara  = row["opp_chara"] or "???"
        wins   = row["wins"]
        total  = row["total"]
        losses = total - wins
        wr     = wins / total * 100
        icon   = "✅" if wr > 50 else ("❌" if wr < 50 else "➖")
        lines.append(f"{icon} {chara:<12} {wins}勝{losses}敗 ({wr:.0f}%)")

    embed = discord.Embed(
        title="📊 キャラ別対戦成績（試合数順）",
        description="```\n" + "\n".join(lines) + "\n```",
        color=0x5865F2,
    )
    await interaction.followup.send(embed=embed)


@tekken_group.command(name="rival", description="特定の対戦相手との詳細な通算成績・傾向を確認する")
@app_commands.describe(name="対戦相手の名前（部分一致）")
async def cmd_rival(interaction: discord.Interaction, name: str) -> None:
    await interaction.response.defer(thinking=True)
    battles = db.search_battles_vs_opponent(name)
    if not battles:
        await interaction.followup.send(f"❌ `{name}` との対戦記録が見つかりません。")
        return

    wins   = count_wins(battles)
    losses = count_losses(battles)
    total  = wins + losses
    wr     = wins / total * 100 if total else 0

    # 使用キャラ一覧（多い順）
    chara_counts = Counter(b.get("opp_chara") or "???" for b in battles)
    chara_list = " / ".join(f"{c}({n}戦)" for c, n in chara_counts.most_common(5))

    # 累積レーティング変動
    rated = [b for b in battles if b.get("rating_change") is not None]
    net_rating = sum(b.get("rating_change") or 0 for b in rated) if rated else None

    # 現在の対面ストリーク（末尾から）
    sorted_b = sorted(battles, key=lambda x: x["battle_at"])
    win_streak  = detect_winning_streak(sorted_b)
    lose_streak = detect_losing_streak(sorted_b)
    if win_streak >= 2:
        streak_str = f"✅ {win_streak} 連勝中"
    elif lose_streak >= 2:
        streak_str = f"❌ {lose_streak} 連敗中"
    else:
        streak_str = "連続なし"

    # 直近10戦
    recent_icons = " ".join("✅" if b["won"] else "❌" for b in sorted_b[-10:])
    last_dt = datetime.fromtimestamp(sorted_b[-1]["battle_at"], JST).strftime("%Y/%m/%d")

    embed = discord.Embed(
        title=f"⚔️ ライバル分析: {name}",
        color=0x57F287 if wr >= 50 else 0xED4245,
    )
    embed.add_field(name="通算成績",   value=f"{wins}勝{losses}敗 ({wr:.0f}%)", inline=True)
    embed.add_field(name="対戦回数",   value=f"{total}戦",                       inline=True)
    embed.add_field(name="最終対戦",   value=last_dt,                            inline=True)
    embed.add_field(name="使用キャラ", value=chara_list or "-",                  inline=False)
    if net_rating is not None:
        sign = "+" if net_rating >= 0 else ""
        embed.add_field(name="累積レーティング変動", value=f"{sign}{net_rating}", inline=True)
    embed.add_field(name="現在の流れ", value=streak_str, inline=True)
    if recent_icons:
        embed.add_field(name=f"直近{min(total, 10)}戦", value=recent_icons, inline=False)

    await interaction.followup.send(embed=embed)


@tekken_group.command(name="filter", description="キャラ名・日付でバトルログを絞り込んで表示する")
@app_commands.describe(
    chara="対戦相手キャラ名（例: Bryan, Jin）",
    date="対象日 YYYY-MM-DD（例: 2026-04-10）",
    days="直近N日間に絞り込む（chara 指定時のみ有効、省略で全期間）",
)
@app_commands.autocomplete(chara=_chara_autocomplete)
async def cmd_filter(
    interaction: discord.Interaction,
    chara: str | None = None,
    date: str | None = None,
    days: int | None = None,
) -> None:
    await interaction.response.defer(thinking=True)

    if chara is None and date is None:
        await interaction.followup.send("❌ `chara` または `date` のどちらか一方は指定してください。")
        return

    if days is not None and days > 365:
        await interaction.followup.send("❌ `days` は 365 以下で指定してください。")
        return

    players = _bot_main.get_players()
    player_name = players[0][0] if players else None

    # date 単独: 指定日の全バトルを表示
    if date is not None and chara is None:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            await interaction.followup.send("❌ 日付形式が正しくありません（YYYY-MM-DD）。")
            return
        battles = db.get_battles_on_date(date, player_name=player_name)
        if not battles:
            await interaction.followup.send(f"❌ `{date}` の対戦データが見つかりません。")
            return
        wins   = count_wins(battles)
        losses = count_losses(battles)
        total  = wins + losses
        wr     = wins / total * 100 if total else 0
        lines  = []
        for b in sorted(battles, key=lambda x: x["battle_at"]):
            icon = "✅" if b["won"] else "❌"
            dt   = datetime.fromtimestamp(b["battle_at"], JST).strftime("%H:%M")
            btype = "🏆" if b.get("battle_type") == "ranked" else "⚡"
            lines.append(f"{btype} {icon} {b.get('my_chara','???')} vs {b.get('opp_chara','???')}  {b['my_rounds']}-{b['opp_rounds']}  {dt}")
        embed = discord.Embed(
            title=f"📅 {date} の対戦ログ",
            description="\n".join(lines)[:4096],
            color=0x57F287 if wr >= 50 else 0xED4245,
        )
        embed.add_field(name="通算", value=f"{wins}勝{losses}敗 ({wr:.0f}%)", inline=True)
        await interaction.followup.send(embed=embed)
        return

    # chara あり: キャラ + 期間フィルタ
    since_ts = 0
    period_label = "全期間"
    if date is not None:
        try:
            since_dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=JST)
        except ValueError:
            await interaction.followup.send("❌ 日付形式が正しくありません（YYYY-MM-DD）。")
            return
        since_ts    = int(since_dt.timestamp())
        period_label = f"{date} 以降"
    elif days is not None:
        since_ts    = int((datetime.now(JST) - timedelta(days=days)).timestamp())
        period_label = f"直近{days}日間"

    assert chara is not None  # 関数先頭の検証で保証済み
    battles = db.get_battles_by_opp_chara(chara, player_name=player_name, since_ts=since_ts)
    if not battles:
        await interaction.followup.send(f"❌ `{chara}` との対戦記録が見つかりません（{period_label}）。")
        return

    wins   = count_wins(battles)
    losses = count_losses(battles)
    total  = wins + losses
    wr     = wins / total * 100 if total else 0

    recent = sorted(battles, key=lambda x: x["battle_at"], reverse=True)[:10]
    recent_lines = []
    for b in recent:
        icon = "✅" if b["won"] else "❌"
        dt   = datetime.fromtimestamp(b["battle_at"], JST).strftime("%m/%d %H:%M")
        recent_lines.append(f"{icon} {b.get('my_chara','???')} vs {b.get('opp_chara','???')}  {b['my_rounds']}-{b['opp_rounds']}  {dt}")

    embed = discord.Embed(
        title=f"🔍 vs {chara} フィルタ結果（{period_label}）",
        color=0x57F287 if wr >= 50 else 0xED4245,
    )
    embed.add_field(name="通算", value=f"{wins}勝{losses}敗 ({wr:.0f}%)", inline=True)
    embed.add_field(name="対戦数", value=f"{total}戦", inline=True)
    if recent_lines:
        embed.add_field(name=f"直近{len(recent_lines)}試合", value="\n".join(recent_lines), inline=False)
    await interaction.followup.send(embed=embed)


@tekken_group.command(name="monthly", description="月次サマリーを投稿する")
@app_commands.describe(month="対象月 YYYY-MM（省略すると先月）")
async def cmd_monthly(interaction: discord.Interaction, month: str | None = None) -> None:
    await interaction.response.defer(thinking=True)
    try:
        if month is not None:
            datetime.strptime(month, "%Y-%m")  # バリデーション
        await _bot_main.monthly(month=month)
        await interaction.followup.send("✅ 月次サマリーを投稿しました。")
    except ValueError:
        await interaction.followup.send("❌ 月形式が正しくありません（YYYY-MM）。")
    except Exception as e:
        logger.error(f"[slash_commands] /tekken monthly エラー: {e}")
        await interaction.followup.send(f"❌ エラーが発生しました: {e}")


@tekken_group.command(name="help", description="使用可能なコマンド一覧を表示する")
async def cmd_help(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="📖 /tekken コマンド一覧",
        color=0x5865F2,
    )
    embed.add_field(
        name="📊 戦績確認",
        value=(
            "`/tekken today [date]` — 当日または指定日の戦績を投稿\n"
            "`/tekken weekly` — 週次サマリーを投稿\n"
            "`/tekken monthly [month]` — 月次サマリーを投稿（省略で先月）\n"
            "`/tekken trend [days]` — レーティング推移グラフ（デフォルト30日）"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔍 検索・分析",
        value=(
            "`/tekken vs <name>` — 対戦相手との通算成績（部分一致）\n"
            "`/tekken chara <name>` — キャラ別対戦成績\n"
            "`/tekken top` — キャラ別対戦成績ランキング\n"
            "`/tekken rival <name>` — ライバル詳細分析\n"
            "`/tekken filter [chara] [date] [days]` — バトルログ絞り込み"
        ),
        inline=False,
    )
    embed.add_field(
        name="⚙️ その他",
        value=(
            "`/tekken status` — Bot 稼働状況を確認\n"
            "`/tekken help` — このヘルプを表示"
        ),
        inline=False,
    )
    embed.set_footer(text="chara / rival の引数はタイプすると候補が表示されます")
    await interaction.response.send_message(embed=embed)


tree.add_command(tekken_group)


@client.event
async def on_ready() -> None:
    if DISCORD_GUILD_ID:
        guild = discord.Object(id=int(DISCORD_GUILD_ID))
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
        logger.info(f"[slash_commands] Bot ログイン完了: {client.user} | ギルド同期済み (即時反映)")
    else:
        await tree.sync()
        logger.info(f"[slash_commands] Bot ログイン完了: {client.user} | グローバル同期済み（反映まで最大1時間）")


def start_bot() -> None:
    if not BOT_TOKEN:
        logger.warning("[slash_commands] DISCORD_BOT_TOKEN が未設定。スラッシュコマンドは無効。")
        return
    try:
        client.run(BOT_TOKEN, log_handler=None)
    except Exception as e:
        logger.error(f"[slash_commands] Bot 起動失敗: {e}")


def start_bot_thread() -> threading.Thread:
    """スラッシュコマンド Bot をバックグラウンドスレッドで起動する。"""
    t = threading.Thread(target=start_bot, daemon=True, name="discord-bot")
    t.start()
    return t
