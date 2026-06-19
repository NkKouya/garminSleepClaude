"""DB の中間表現を使った週間睡眠レポートモード（無料・サブスク）。

SQLite(sleep.db) から直近7日分の中間表現を参照 → Python で週次集計（週平均・
ばらつき・夜別の黄金90分指標）→ Claude Code CLI で解析 → ファイル保存
（＋任意でメール送信）。

detailed_report.py（1夜分の詳細レポート）の週次版。データ源は DB 優先。
過去日は DB から読むため再ダウンロード不要。今日分が DB に無い場合のみ取得を試みる
（フル遡及はしない）。

使い方:
    python weekly_report.py            # 今日を末尾とする直近7日（HTMLメール送信あり）
    python weekly_report.py 2026-06-15 # 指定日を末尾とする直近7日（DB参照）
    python weekly_report.py 2026-06-15 --no-mail  # 送信せずファイル保存のみ
"""
from __future__ import annotations

import datetime as dt
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def build_body(weekly: dict, analysis: str) -> str:
    """週次集計の整形＋分析文を結合した本文を作る。"""
    from analyzer import format_weekly

    return (
        f"■ {weekly.get('start_date')} 〜 {weekly.get('end_date')} の睡眠 週間レポート\n\n"
        f"【分析・評価】\n{analysis}\n\n"
        f"{'-' * 40}\n【元データ（週次集計）】\n{format_weekly(weekly)}\n\n"
        f"{'-' * 40}\nGarmin Sleep Reporter（週間分析モード）による自動生成\n"
    )


def build_html_body(weekly: dict, analysis: str) -> str:
    """分析文（Markdown）をHTML化し、週次集計を等幅<pre>で添えたHTML本文を作る。"""
    import markdown
    from html import escape

    from analyzer import format_weekly

    analysis_html = markdown.markdown(analysis, extensions=["extra", "sane_lists"])
    data_text = escape(format_weekly(weekly))
    title = f"{escape(str(weekly.get('start_date')))} 〜 {escape(str(weekly.get('end_date')))}"
    return (
        "<!DOCTYPE html>\n"
        '<html lang="ja"><head><meta charset="utf-8"><style>\n'
        ' body { font-family: -apple-system, "Segoe UI", "Hiragino Sans",'
        ' "Yu Gothic UI", sans-serif; line-height: 1.7; color: #222;'
        " margin: 0 auto; max-width: 760px; padding: 16px; }\n"
        " h1, h2, h3, h4 { color: #1a7f5a; line-height: 1.3; }\n"
        " pre { font-family: Consolas, \"Courier New\", monospace; font-size: 12px;"
        " background: #f6f8fa; border: 1px solid #e1e4e8; border-radius: 6px;"
        " padding: 12px; overflow-x: auto; }\n"
        " hr { border: none; border-top: 1px solid #e1e4e8; margin: 24px 0; }\n"
        " .meta { color: #888; font-size: 12px; }\n"
        "</style></head><body>\n"
        f"<h2>■ {title} の睡眠 週間レポート</h2>\n"
        f"{analysis_html}\n"
        "<hr>\n"
        "<h3>元データ（週次集計）</h3>\n"
        f"<pre>{data_text}</pre>\n"
        "<hr>\n"
        '<p class="meta">Garmin Sleep Reporter（週間分析モード）による自動生成</p>\n'
        "</body></html>\n"
    )


def run(end_date: str, send_mail: bool) -> int:
    import database
    import build_database
    import weekly as weekly_mod
    from analyzer import analyze_free_weekly

    end = dt.date.fromisoformat(end_date)
    start = end - dt.timedelta(days=6)
    today = dt.date.today().isoformat()
    print(f"週間睡眠レポート処理を開始: {start.isoformat()} 〜 {end.isoformat()}")

    conn = database.connect()
    database.init_schema(conn)

    inters = []
    missing = []
    for i in range(7):
        d = (start + dt.timedelta(days=i)).isoformat()
        inter = database.load_intermediate(conn, d)
        if inter is None and d == today:
            # 今日分のみDB未同期なら取得を試みる（過去日のフル遡及はしない）
            inter, _, _ = build_database.ingest_date(conn, d, use_cache=False)
        if inter is None:
            missing.append(d)
        else:
            inters.append(inter)

    if not inters:
        print(f"{start.isoformat()}〜{end.isoformat()} の睡眠データが見つかりませんでした。")
        return 0
    if missing:
        print(f"データ無しの日（不眠とみなす）: {', '.join(missing)}")

    weekly = weekly_mod.build_weekly(inters, missing=missing)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    avg_score = (weekly.get("score") or {}).get("avg")
    print(f"週次集計を生成（平均スコア={avg_score}, {weekly.get('days')}日）。"
          f"Claude Code で週平均を分析します。")
    analysis = analyze_free_weekly(weekly)
    body = build_body(weekly, analysis)

    out_path = os.path.join(
        OUTPUT_DIR, f"sleep_weekly_{start.isoformat()}_{end.isoformat()}.txt"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"レポートを保存: {out_path}\n")
    print(body)

    if send_mail:
        from emailer import send_report

        score_part = f"（平均スコア {avg_score}）" if avg_score is not None else ""
        html = build_html_body(weekly, analysis)
        send_report(
            f"【睡眠 週間レポート】{start.isoformat()}〜{end.isoformat()}{score_part}",
            body, html_body=html,
        )
        print("メール送信完了。")
    return 0


def main() -> int:
    # Windows で stdout がリダイレクト/非コンソールだと cp932 になり、
    # 日本語や em dash 等の出力で UnicodeEncodeError → 異常終了する。UTF-8 に固定する。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = [a for a in sys.argv[1:]]
    send_mail = "--no-mail" not in args
    args = [a for a in args if a not in ("--mail", "--no-mail")]

    end_date = args[0] if args else dt.date.today().isoformat()
    try:
        dt.date.fromisoformat(end_date)
    except ValueError:
        print(f"日付の形式が不正です: {end_date!r}（YYYY-MM-DD で指定してください）")
        return 1

    return run(end_date, send_mail)


if __name__ == "__main__":
    sys.exit(main())
