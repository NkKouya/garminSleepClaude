"""設定の集約。.env を読み込み、各値を公開する。

Garmin の認証情報のみ必須。Claude API / Gmail は使う機能でのみ必要
（手動 Claude Desktop モードでは不要）。
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"環境変数 {name} が設定されていません。.env を確認してください"
            "（.env.example をコピーして値を記入）。"
        )
    return value


# --- 必須: Garmin ---
GARMIN_EMAIL = _require("GARMIN_EMAIL")
GARMIN_PASSWORD = _require("GARMIN_PASSWORD")

# garth トークンキャッシュ
TOKEN_STORE = os.getenv("TOKEN_STORE") or "./.garminconnect"

# --- 任意: Claude API（有料・自動分析モードでのみ使用）---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if ANTHROPIC_API_KEY:
    os.environ.setdefault("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY)
CLAUDE_MODEL = "claude-opus-4-8"

# --- 無料・全自動モード: Claude Code CLI のパス ---
# claude -p（非対話）をサブスクで呼ぶ。API従量課金は発生しない。
CLAUDE_CMD = os.getenv("CLAUDE_CMD") or r"C:\Users\mckou\AppData\Roaming\npm\claude.cmd"

# --- 分析バックエンド（LLMエンジン）の選択 ---
# claude_cli : Claude Code CLI（サブスク・無料）。既定。既存ユーザーの挙動を維持。
# claude_api : Claude API（従量課金）。
# ollama     : ローカルLLM（無料・データがPC外に出ない）。要 Ollama 起動＋モデル pull。
# gemini     : Google Gemini の無料枠（無料・キーを貼るだけ）。
# → Claude のサブスク/課金が無くても ollama / gemini で同じ分析が動く。
BACKEND = (os.getenv("BACKEND") or "claude_cli").lower()

# ollama 設定（BACKEND=ollama のとき使用）
OLLAMA_HOST = os.getenv("OLLAMA_HOST") or "http://localhost:11434"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL") or "qwen2.5:7b"

# gemini 設定（BACKEND=gemini のとき使用）。キーは https://aistudio.google.com で無料発行。
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-2.0-flash"

# --- 任意: Gmail（メール送信を使う場合のみ）---
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
MAIL_TO = os.getenv("MAIL_TO") or GMAIL_ADDRESS


def require_anthropic() -> None:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY が未設定です（有料・自動分析モードに必要）。"
            "無料で使う場合は detailed_report.py（無料・詳細モード）を利用してください。"
        )


def require_gmail() -> None:
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        raise RuntimeError(
            "GMAIL_ADDRESS / GMAIL_APP_PASSWORD が未設定です（メール送信に必要）。"
        )
