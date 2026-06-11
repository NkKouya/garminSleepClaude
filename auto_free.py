"""無料・全自動モード: Garmin睡眠データ取得 → Claude Code CLIで分析 →
ファイル保存 + Gmail送信。

Claude Code(`claude -p`)をサブスクで使うため API 従量課金は発生しない。
Windowsタスクスケジューラから run_auto_free.bat 経由で毎朝実行する想定。
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sys
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(
            os.path.join(LOG_DIR, "sleep_report.log"), encoding="utf-8"
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("garminSleep.auto_free")


def build_body(summary: dict, analysis: str) -> str:
    """指標サマリ + 分析文 を結合した本文を作る。"""
    from analyzer import format_metrics

    return (
        f"■ {summary.get('date')} の睡眠レポート\n\n"
        f"【指標サマリ】\n{format_metrics(summary)}\n\n"
        f"【分析・評価】\n{analysis}\n\n"
        f"---\nGarmin Sleep Reporter（無料・全自動モード）による自動送信\n"
    )


def run() -> int:
    from emailer import send_report
    from garmin_client import get_sleep_summary
    from analyzer import analyze_free

    today = dt.date.today().isoformat()
    log.info("無料・全自動の睡眠レポート処理を開始: %s", today)

    summary = get_sleep_summary(today)
    if not summary:
        log.warning("睡眠データが未取得（未同期の可能性）。通知メールを送信します。")
        send_report(
            f"【睡眠レポート】{today} データ未取得",
            "本日分の睡眠データがGarmin Connectから取得できませんでした。\n"
            "時計とアプリの同期が完了していない可能性があります。",
        )
        return 0

    score = summary.get("sleep_score")
    log.info("睡眠データ取得OK (スコア=%s)。Claude Code で分析します。", score)
    analysis = analyze_free(summary)
    log.info("分析完了。")

    body = build_body(summary, analysis)

    # ファイル保存
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"sleep_report_{today}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(body)
    log.info("レポートを保存: %s", out_path)

    # メール送信
    score_part = f"（スコア {score}）" if score is not None else ""
    subject = f"【睡眠レポート】{today}{score_part}"
    send_report(subject, body)
    log.info("メール送信完了: %s", subject)
    return 0


def main() -> int:
    try:
        return run()
    except Exception:
        err = traceback.format_exc()
        log.error("処理中にエラー発生:\n%s", err)
        try:
            from emailer import send_report

            send_report(
                "【睡眠レポート】エラー発生",
                "睡眠レポート処理中にエラーが発生しました。\n\n" + err,
            )
        except Exception:
            log.error("エラー通知メールの送信にも失敗しました。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
