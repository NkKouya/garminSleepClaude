"""分析バックエンド（LLMエンジン）の差し替え層。

統一インターフェース run(system_prompt, user_content) -> str を提供し、
config.BACKEND に応じて実エンジンへ委譲する。これにより Claude のサブスクや
API課金が無くても（ollama=ローカル無料 / gemini=無料枠）同じ分析が動く。

HTTP は依存を増やさないため標準ライブラリ urllib を使う。
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request

import config


def run(system_prompt: str, user_content: str, backend: str | None = None) -> str:
    """system と user を、選択されたバックエンドで分析しテキストを返す。

    backend を明示すればそれを使い、未指定なら config.BACKEND に従う。
    """
    name = (backend or config.BACKEND or "claude_cli").lower()
    fn = _BACKENDS.get(name)
    if fn is None:
        raise RuntimeError(
            f"未知の分析バックエンドです: {name!r}"
            f"（利用可能: {', '.join(_BACKENDS)}）。config の BACKEND を確認してください。"
        )
    return fn(system_prompt, user_content)


def _claude_cli(system_prompt: str, user_content: str) -> str:
    """Claude Code CLI(`claude -p`)に渡す（サブスク・API課金なし）。

    CLI は system ロールを持たないため本文に連結する。プロンプトは stdin 経由
    （複数行・特殊文字の安全性、シェル注入回避）。
    """
    prompt = f"{system_prompt}\n\n{user_content}"
    comspec = os.environ.get("COMSPEC", "cmd.exe")
    proc = subprocess.run(
        [comspec, "/c", config.CLAUDE_CMD, "-p"],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude CLI がエラー終了しました (code={proc.returncode}):\n"
            f"{proc.stderr.strip()}"
        )
    output = (proc.stdout or "").strip()
    if not output:
        raise RuntimeError(
            f"claude CLI から空の応答が返りました。\nstderr: {proc.stderr.strip()}"
        )
    return output


def _claude_api(system_prompt: str, user_content: str) -> str:
    """Claude API で分析する（従量課金）。"""
    config.require_anthropic()
    import anthropic  # claude_api 選択時のみ必要なので遅延 import

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=3000,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    return "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()


def _http_post_json(url: str, payload: dict, timeout: int) -> dict:
    """JSON を POST して JSON を返す（urllib ラッパ）。"""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ollama(system_prompt: str, user_content: str) -> str:
    """ローカルの Ollama で分析する（無料・データはPC外に出ない）。"""
    url = f"{config.OLLAMA_HOST.rstrip('/')}/api/chat"
    payload = {
        "model": config.OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    try:
        body = _http_post_json(url, payload, timeout=600)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise RuntimeError(
            f"Ollama がエラーを返しました (HTTP {e.code}): {detail}\n"
            f"モデル {config.OLLAMA_MODEL!r} を pull 済みか確認してください"
            f"（例: `ollama pull {config.OLLAMA_MODEL}`）。"
        )
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Ollama に接続できませんでした（{config.OLLAMA_HOST}）。"
            f"Ollama が起動しているか確認してください。\n詳細: {e}"
        )
    output = ((body.get("message") or {}).get("content") or "").strip()
    if not output:
        raise RuntimeError(f"Ollama から空の応答が返りました: {body}")
    return output


def _gemini_quota_all_zero(body: dict) -> bool:
    """RESOURCE_EXHAUSTED かつ無料枠の上限が0（＝恒久的に枠が未付与）か判定する。

    上限0は「使いすぎ」ではなく、そのプロジェクト/モデルに無料枠が無い状態。
    待っても回復しないため、リトライではなく切替を案内すべきケース。
    """
    err = body.get("error") or {}
    if err.get("status") != "RESOURCE_EXHAUSTED":
        return False
    return "limit: 0" in (err.get("message") or "")


def _gemini_transient_retry_delay(raw: str) -> float | None:
    """一時的な429ならリトライ秒数を返す。恒久(limit:0)/解析不能なら None。"""
    try:
        body = json.loads(raw)
    except ValueError:
        return None
    if _gemini_quota_all_zero(body):
        return None  # 待っても無駄
    for detail in ((body.get("error") or {}).get("details") or []):
        if str(detail.get("@type", "")).endswith("RetryInfo"):
            try:
                return float(str(detail.get("retryDelay", "")).rstrip("s"))
            except ValueError:
                return None
    return None


def _explain_gemini_429(raw: str) -> str:
    """429 を利用者向けの実用的な案内文に変換する（生JSONは出さない）。"""
    try:
        body = json.loads(raw)
    except ValueError:
        body = {}
    if _gemini_quota_all_zero(body):
        return (
            "Gemini の無料枠がこの Google プロジェクト/モデルに付与されていません"
            f"（モデル {config.GEMINI_MODEL!r}, 無料枠の上限=0）。"
            "待っても回復しません。次のいずれかで対応してください:\n"
            "  1) 別モデルを試す: .env に GEMINI_MODEL=gemini-2.5-flash\n"
            "  2) ローカル無料に切替（推奨）: .env に BACKEND=ollama"
            f"（要 `ollama pull {config.OLLAMA_MODEL}`）\n"
            "詳細: https://ai.google.dev/gemini-api/docs/rate-limits"
        )
    return (
        "Gemini API が利用枠超過(429)を返しました。"
        "しばらく待って再実行するか、BACKEND=ollama（ローカル無料）への切替を検討してください。\n"
        "詳細: https://ai.google.dev/gemini-api/docs/rate-limits"
    )


def _gemini(system_prompt: str, user_content: str) -> str:
    """Google Gemini の無料枠で分析する（無料・キーを貼るだけ）。"""
    key = config.GEMINI_API_KEY
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY が未設定です（無料APIモードに必要）。"
            "https://aistudio.google.com で無料発行できます。"
        )
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.GEMINI_MODEL}:generateContent?key={key}"
    )
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_content}]}],
    }

    def _post() -> dict:
        return _http_post_json(url, payload, timeout=120)

    try:
        body = _post()
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        if e.code != 429:
            raise RuntimeError(f"Gemini API エラー (HTTP {e.code}): {raw}")
        # 一時的な429のみ1回だけリトライ（恒久=limit:0 は待っても無駄）
        delay = _gemini_transient_retry_delay(raw)
        if delay is None or delay > 60:
            raise RuntimeError(_explain_gemini_429(raw))
        time.sleep(delay + 1)
        try:
            body = _post()
        except urllib.error.HTTPError as e2:
            raw2 = e2.read().decode("utf-8", "replace")
            raise RuntimeError(_explain_gemini_429(raw2))
        except urllib.error.URLError as e2:
            raise RuntimeError(f"Gemini API に接続できませんでした: {e2}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Gemini API に接続できませんでした: {e}")

    candidates = body.get("candidates") or []
    if not candidates:
        # プロンプトブロック等で candidates が空になることがある
        raise RuntimeError(f"Gemini から応答候補が返りませんでした: {body}")
    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    output = "".join(p.get("text", "") for p in parts).strip()
    if not output:
        raise RuntimeError(f"Gemini から空の応答が返りました: {body}")
    return output


_BACKENDS = {
    "claude_cli": _claude_cli,
    "claude_api": _claude_api,
    "ollama": _ollama,
    "gemini": _gemini,
}
