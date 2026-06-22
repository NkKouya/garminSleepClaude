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


def deliver(
    subject: str,
    body: str,
    html_body: str,
    date: str,
    delivery: str | None = None,
) -> str:
    """設定された方法でレポートを配信する。戻り値は実施内容（パス or "mail"/"none"）。

    delivery: "browser" / "mail" / "none"。None なら config.effective_delivery()。
    """
    mode = (delivery or config.effective_delivery()).lower()

    if mode == "mail":
        from emailer import send_report

        send_report(subject, body, html_body=html_body)
        return "mail"

    if mode == "none":
        return "none"

    # browser（既定）: HTMLを保存して既定ブラウザで開く
    html_path = _save_html(html_body or body, date)
    try:
        webbrowser.open(_file_url(html_path))
    except Exception:
        pass  # ブラウザを開けなくても保存はできている
    return html_path


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
