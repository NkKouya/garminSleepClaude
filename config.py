"""設定の集約。settings.json と .env を読み込み、各値を公開する。

優先順位: 環境変数(.env を load_dotenv で反映) > settings.json > 既定。
GUI(setup_gui.py) が settings.json に書き、CLI/スケジュール実行がそれを読む。

import 時には例外を投げない（設定が無くても GUI 初回起動を成立させるため）。
値の必須チェックは require_*() を呼んだ時にのみ行う。
"""
from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

CLAUDE_MODEL = "claude-opus-4-8"


def _app_dir() -> str:
    """設定ファイルを置くディレクトリ。

    PyInstaller で固めた場合は exe のあるフォルダ、ソース実行時はこのファイルの場所。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def settings_path() -> str:
    return os.path.join(_app_dir(), "settings.json")


def _load_settings() -> dict:
    try:
        with open(settings_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


_SETTINGS: dict = _load_settings()


def _get(name: str, default=None):
    """環境変数 > settings.json > 既定 の順で値を返す（空文字は未設定扱い）。"""
    val = os.environ.get(name)
    if val:
        return val
    val = _SETTINGS.get(name)
    if val not in (None, ""):
        return val
    return default


def _as_bool(val, default: bool = False) -> bool:
    """設定値（文字列/真偽/None）を bool に解釈する。"0"/"false"/"no" 等は偽。"""
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() not in ("0", "false", "no", "off", "")


def _reload() -> None:
    """モジュール公開値を settings/env から再計算する（save_settings 後に呼ぶ）。"""
    global GARMIN_EMAIL, GARMIN_PASSWORD, TOKEN_STORE
    global ANTHROPIC_API_KEY, CLAUDE_CMD
    global BACKEND, OLLAMA_HOST, OLLAMA_MODEL, GEMINI_API_KEY, GEMINI_MODEL
    global GMAIL_ADDRESS, GMAIL_APP_PASSWORD, MAIL_TO, DELIVERY
    global SCHEDULE_TIME, NOTIFY_TOAST

    # --- 必須: Garmin（import 時には検証しない。require_garmin() で検証）---
    GARMIN_EMAIL = _get("GARMIN_EMAIL")
    GARMIN_PASSWORD = _get("GARMIN_PASSWORD")
    TOKEN_STORE = _get("TOKEN_STORE", "./.garminconnect")

    # --- Claude API（有料・自動分析モード）---
    ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
    if ANTHROPIC_API_KEY:
        os.environ.setdefault("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY)
    # 無料・全自動モードの Claude Code CLI のパス（claude -p をサブスクで呼ぶ）
    CLAUDE_CMD = _get("CLAUDE_CMD", r"C:\Users\mckou\AppData\Roaming\npm\claude.cmd")

    # --- 分析バックエンド（claude_cli / claude_api / ollama / gemini）---
    BACKEND = str(_get("BACKEND", "claude_cli")).lower()
    OLLAMA_HOST = _get("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_MODEL = _get("OLLAMA_MODEL", "qwen2.5:7b")
    GEMINI_API_KEY = _get("GEMINI_API_KEY")
    GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-2.0-flash")

    # --- 配信: browser / mail / none（未設定なら effective_delivery() で決定）---
    DELIVERY = str(_get("DELIVERY", "")).lower()

    # --- Gmail（メール送信を使う場合のみ）---
    GMAIL_ADDRESS = _get("GMAIL_ADDRESS")
    GMAIL_APP_PASSWORD = _get("GMAIL_APP_PASSWORD")
    MAIL_TO = _get("MAIL_TO") or GMAIL_ADDRESS

    # --- 毎朝の自動実行・通知（Phase 3）---
    SCHEDULE_TIME = _get("SCHEDULE_TIME", "08:00")
    NOTIFY_TOAST = _as_bool(_get("NOTIFY_TOAST", "1"), default=True)


_reload()


def save_settings(values: dict) -> str:
    """GUI からの設定を settings.json に保存し、モジュール値を再読込する。

    値が空/None のキーは保存しない（既存値を消さないため）。既存内容にマージする。
    戻り値は保存先パス。
    """
    global _SETTINGS
    merged = dict(_SETTINGS)
    for k, v in values.items():
        if v is None or v == "":
            merged.pop(k, None)
        else:
            merged[k] = v
    path = settings_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    _SETTINGS = merged
    _reload()
    return path


def effective_delivery() -> str:
    """配信方法を決める。明示設定が無ければ Gmail 設定済→mail、無→browser。"""
    if DELIVERY in ("browser", "mail", "none"):
        return DELIVERY
    return "mail" if (GMAIL_ADDRESS and GMAIL_APP_PASSWORD) else "browser"


def require_garmin() -> None:
    if not GARMIN_EMAIL or not GARMIN_PASSWORD:
        raise RuntimeError(
            "GARMIN_EMAIL / GARMIN_PASSWORD が未設定です。"
            "設定画面（setup_gui.py）または .env で設定してください。"
        )


def require_anthropic() -> None:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY が未設定です（有料・自動分析モードに必要）。"
            "無料で使う場合は BACKEND=ollama / gemini / claude_cli を利用してください。"
        )


def require_gmail() -> None:
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        raise RuntimeError(
            "GMAIL_ADDRESS / GMAIL_APP_PASSWORD が未設定です（メール送信に必要）。"
        )
