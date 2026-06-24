"""DB の中間表現を使った詳細睡眠分析モード（無料・サブスク）。

SQLite(sleep.db) の中間表現（特徴量＋5分粒度タイムライン）を参照 →
Claude Code CLI で時系列分析 → ファイル保存（＋任意でメール送信）。

参照源は DB 優先。過去日は DB から読むため再ダウンロード不要。DB に無い日は
その日だけ取り込み（build_database.ingest_date）、今日分は常に再取得して
DB を最新化してから解析する。

集計値だけの簡易レポートとは別系統で、夜間の経過に踏み込んだ
詳細レポートを生成する（無料・サブスクのメインモード）。

使い方:
    python detailed_report.py            # 今日分（再取得して最新化、HTMLメール送信あり）
    python detailed_report.py 2026-06-14 # 日付指定（DB参照、無ければ取込）
    python detailed_report.py 2026-06-14 --no-mail  # 送信せずファイル保存のみ
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 書込先は config.base_dir()（frozen=exeフォルダ / ソース=リポジトリ）に統一。
OUTPUT_DIR = os.path.join(config.base_dir(), "output")
LOG_DIR = os.path.join(config.base_dir(), "logs")


def _redirect_to_logfile() -> None:
    """無人実行（pythonw / --log）時に標準出力/エラーを logs/task.log へ向ける。

    pythonw.exe では sys.stdout/stderr が None になり print で落ちるため、
    ファイルへ差し替える。スケジューラ経由の実行結果をここで追跡できる。
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, "task.log")
    f = open(log_path, "a", encoding="utf-8", errors="replace")
    sys.stdout = f
    sys.stderr = f
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    f.write(f"\n===== {stamp} 自動実行開始 =====\n")
    f.flush()


def build_body(inter: dict, analysis: str) -> str:
    """指標サマリ（中間表現の整形）＋分析文を結合した本文を作る。"""
    from analyzer import format_intermediate

    return (
        f"■ {inter.get('date')} の睡眠 詳細レポート\n\n"
        f"【分析・評価】\n{analysis}\n\n"
        f"{'-' * 40}\n【元データ（5分粒度の中間表現）】\n{format_intermediate(inter)}\n\n"
        f"{'-' * 40}\nGarmin Sleep Reporter（詳細分析モード）による自動生成\n"
    )


def build_html_body(inter: dict, analysis: str) -> str:
    """分析文（Markdown）をHTML化し、中間表現を等幅<pre>で添えたHTML本文を作る。"""
    import markdown
    from html import escape

    from analyzer import format_intermediate

    analysis_html = markdown.markdown(analysis, extensions=["extra", "sane_lists"])
    data_text = escape(format_intermediate(inter))
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
        f"<h2>■ {escape(str(inter.get('date')))} の睡眠 詳細レポート</h2>\n"
        f"{analysis_html}\n"
        "<hr>\n"
        "<h3>元データ（5分粒度の中間表現）</h3>\n"
        f"<pre>{data_text}</pre>\n"
        "<hr>\n"
        '<p class="meta">Garmin Sleep Reporter（詳細分析モード）による自動生成</p>\n'
        "</body></html>\n"
    )


def run(date: str, send_mail: bool) -> int:
    import database
    import build_database
    from analyzer import analyze_free_detailed

    print(f"詳細睡眠レポート処理を開始: {date}")
    conn = database.connect()
    database.init_schema(conn)

    if date == dt.date.today().isoformat():
        # 今日分: Garmin 側が日中更新され得るため常に再取得してDBを最新化
        inter, _, _ = build_database.ingest_date(conn, date, use_cache=False)
        if not inter:
            inter = database.load_intermediate(conn, date)  # 未同期なら既存DBにフォールバック
    else:
        # 過去日: DB優先。無ければその日だけ取り込む（フル遡及はしない）
        inter = database.load_intermediate(conn, date)
        if inter is None:
            inter, _, _ = build_database.ingest_date(conn, date)

    if not inter:
        print(f"{date} の睡眠データが取得できませんでした（未同期の可能性）。")
        return 0

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    score = (inter.get("features") or {}).get("sleep_score")
    print(f"中間表現を生成（スコア={score}）。Claude Code で時系列分析します。")
    analysis = analyze_free_detailed(inter)
    body = build_body(inter, analysis)

    out_path = os.path.join(OUTPUT_DIR, f"sleep_detail_{date}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"レポートを保存: {out_path}\n")
    print(body)

    # 配信: --no-mail は「保存のみ(none)」、それ以外は設定(config)に従う
    # （Gmail設定済→mail、未設定→browserでHTMLを開く）。
    from notify import deliver

    score_part = f"（スコア {score}）" if score is not None else ""
    html = build_html_body(inter, analysis)
    delivery = "none" if not send_mail else None
    result = deliver(f"【睡眠 詳細レポート】{date}{score_part}", body, html, date, delivery)
    if result == "mail":
        print("メール送信完了。")
    elif result == "none":
        print("（保存のみ。配信は行いません）")
    else:
        print(f"ブラウザで開きました: {result}")
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:]]

    # 無人実行: --log 指定、または pythonw 起動(stdout が None)なら logs/task.log へ。
    if "--log" in args or sys.stdout is None:
        _redirect_to_logfile()
    args = [a for a in args if a != "--log"]

    # Windows で stdout がリダイレクト/非コンソールだと cp932 になり、
    # 日本語や em dash 等の出力で UnicodeEncodeError → 異常終了する。UTF-8 に固定する。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    send_mail = "--no-mail" not in args
    args = [a for a in args if a not in ("--mail", "--no-mail")]

    date = args[0] if args else dt.date.today().isoformat()
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        print(f"日付の形式が不正です: {date!r}（YYYY-MM-DD で指定してください）")
        return 1

    return run(date, send_mail)


if __name__ == "__main__":
    sys.exit(main())
