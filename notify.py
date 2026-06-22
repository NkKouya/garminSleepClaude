"""レポートの配信層（メール / ブラウザ / 保存のみ）。

Gmail を必須にしないため、既定はHTMLを保存して既定ブラウザで開く。
利用者が Gmail を設定していればメール送信、明示的に none なら保存のみ。
"""
from __future__ import annotations

import glob
import os
import webbrowser

import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def _file_url(path: str) -> str:
    return "file:///" + os.path.abspath(path).replace(os.sep, "/")


def _save_html(html_body: str, date: str) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    html_path = os.path.join(OUTPUT_DIR, f"sleep_detail_{date}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_body)
    return html_path


def _toast(title: str, msg: str, launch_url: str) -> None:
    """Windows トースト通知（winotify）。未導入/失敗時は黙ってスキップ。

    クリックすると launch_url（保存HTMLの file URL）を既定ブラウザで開く。
    """
    try:
        from winotify import Notification

        toast = Notification(
            app_id="Garmin Sleep Reporter",
            title=title,
            msg=msg,
            launch=launch_url,
        )
        toast.show()
    except Exception:
        pass  # winotify 未導入や非対応環境でも本処理は継続


def deliver(
    subject: str,
    body: str,
    html_body: str,
    date: str,
    delivery: str | None = None,
) -> str:
    """設定された方法でレポートを配信する。戻り値は実施内容（パス or "mail"/"none"）。

    delivery: "browser" / "mail" / "none"。None なら config.effective_delivery()。
    HTML は全モードで output/ に保存する（トーストや「前回の結果」から開けるように）。
    """
    mode = (delivery or config.effective_delivery()).lower()
    # どのモードでもローカルにHTMLを残す（トースト/再表示の起点にする）。
    html_path = _save_html(html_body or body, date)

    if mode == "browser":
        try:
            webbrowser.open(_file_url(html_path))
        except Exception:
            pass  # ブラウザを開けなくても保存はできている
        return html_path

    if mode == "mail":
        from emailer import send_report

        send_report(subject, body, html_body=html_body)
        result = "mail"
    else:  # none
        result = "none"

    # browser 以外は（自動でブラウザが開かないため）トーストで知らせる。
    if getattr(config, "NOTIFY_TOAST", True):
        _toast(
            "睡眠 詳細レポートが届きました",
            "クリックで表示します。",
            _file_url(html_path),
        )
    return result


def open_latest() -> str | None:
    """最新のレポートHTMLを既定ブラウザで開く（GUIの「前回の結果を開く」用）。"""
    files = sorted(
        glob.glob(os.path.join(OUTPUT_DIR, "sleep_detail_*.html")),
        key=os.path.getmtime,
        reverse=True,
    )
    if not files:
        return None
    webbrowser.open(_file_url(files[0]))
    return files[0]
