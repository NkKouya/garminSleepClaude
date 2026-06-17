"""raw データを使った詳細睡眠分析モード（無料・サブスク）。

raw（get_sleep_data 生レスポンス）→ 中間表現（特徴量＋5分粒度タイムライン）→
Claude Code CLI で時系列分析 → ファイル保存（＋任意でメール送信）。

集計値だけの簡易レポートとは別系統で、夜間の経過に踏み込んだ
詳細レポートを生成する（無料・サブスクのメインモード）。

使い方:
    python detailed_report.py            # 今日分（HTMLメール送信あり）
    python detailed_report.py 2026-06-14 # 日付指定（HTMLメール送信あり）
    python detailed_report.py 2026-06-14 --no-mail  # 送信せずファイル保存のみ
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")


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
    from garmin_client import get_sleep_raw
    from intermediate import build_intermediate
    from analyzer import analyze_free_detailed

    print(f"詳細睡眠レポート処理を開始: {date}")
    raw = get_sleep_raw(date)
    inter = build_intermediate(raw)
    if not inter:
        print(f"{date} の睡眠データが取得できませんでした（未同期の可能性）。")
        return 0

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 中間表現を保存（中身確認・デバッグ用）
    inter_path = os.path.join(OUTPUT_DIR, f"sleep_intermediate_{date}.json")
    with open(inter_path, "w", encoding="utf-8") as f:
        json.dump(inter, f, ensure_ascii=False, indent=2)
    print(f"中間表現を保存: {inter_path}")

    score = (inter.get("features") or {}).get("sleep_score")
    print(f"中間表現を生成（スコア={score}）。Claude Code で時系列分析します。")
    analysis = analyze_free_detailed(inter)
    body = build_body(inter, analysis)

    out_path = os.path.join(OUTPUT_DIR, f"sleep_detail_{date}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"レポートを保存: {out_path}\n")
    print(body)

    if send_mail:
        from emailer import send_report

        score_part = f"（スコア {score}）" if score is not None else ""
        html = build_html_body(inter, analysis)
        send_report(f"【睡眠 詳細レポート】{date}{score_part}", body, html_body=html)
        print("メール送信完了。")
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:]]
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
