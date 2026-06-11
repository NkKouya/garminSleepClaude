"""Gmail SMTP でレポートメールを送信する。"""
from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate

import config


def send_report(subject: str, body: str) -> None:
    """件名・本文（プレーンテキスト）でメールを送信する。"""
    config.require_gmail()
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = config.GMAIL_ADDRESS
    msg["To"] = config.MAIL_TO
    msg["Date"] = formatdate(localtime=True)

    # local_hostname を固定（PCのホスト名に非ASCII文字があるとEHLOで失敗するため）
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, local_hostname="localhost") as server:
        server.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
        server.send_message(msg)


if __name__ == "__main__":
    send_report("【テスト】睡眠レポート", "これはテスト送信です。")
    print(f"テストメールを {config.MAIL_TO} に送信しました。")
