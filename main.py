"""エントリポイント: 取得 → 分析 → メール送信 を順に実行する。

毎朝タスクスケジューラから呼ばれる想定。失敗時もエラー通知メールを送り、
無音の失敗を防ぐ。
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sys
import traceback

import config

LOG_DIR = os.path.join(config.base_dir(), "logs")
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
log = logging.getLogger("garminSleep")


def run() -> int:
    import database
    import build_database
    from emailer import send_report
    from analyzer import analyze_detailed_api
    from detailed_report import build_body, build_html_body

    today = dt.date.today().isoformat()
    log.info("睡眠レポート処理を開始: %s", today)

    conn = database.connect()
    database.init_schema(conn)

    # detailed_report と同じデータ経路: 当日を再取得してDBを最新化（無ければDB参照）
    inter, _, _ = build_database.ingest_date(conn, today, use_cache=False)
    if not inter:
        inter = database.load_intermediate(conn, today)

    if not inter:
        log.warning("睡眠データが未取得（未同期の可能性）。通知メールを送信します。")
        send_report(
            f"【睡眠レポート】{today} データ未取得",
            "本日分の睡眠データがGarmin Connectから取得できませんでした。\n"
            "時計とアプリの同期が完了していない可能性があります。\n"
            "同期後に再実行するか、しばらく待ってから確認してください。",
        )
        return 0

    score = (inter.get("features") or {}).get("sleep_score")
    log.info("睡眠データ取得OK (スコア=%s)。Claude API で分析します。", score)
    analysis = analyze_detailed_api(inter)

    score_part = f"（スコア {score}）" if score is not None else ""
    subject = f"【睡眠レポート】{today}{score_part}"
    body = build_body(inter, analysis)
    html = build_html_body(inter, analysis)

    send_report(subject, body, html_body=html)
    log.info("メール送信完了: %s", subject)
    return 0


def main() -> int:
    try:
        return run()
    except Exception:
        err = traceback.format_exc()
        log.error("処理中にエラー発生:\n%s", err)
        # エラー通知も送信を試みる（メール設定が壊れている場合は失敗するが許容）
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
