"""睡眠データを分析・評価し、日本語のレポート文を生成する。

2系統の分析:
- analyze_free(): Claude Code CLI(`claude -p`)を使う。サブスク利用=追加費用なし。
- analyze():      Claude API を使う（有料・従量課金）。
"""
from __future__ import annotations

import os
import subprocess

import anthropic

import config

_LABELS = {
    "sleep_score": "睡眠スコア",
    "sleep_quality": "睡眠の質判定",
    "total_sleep": "総睡眠時間",
    "deep_sleep": "深い睡眠",
    "light_sleep": "浅い睡眠",
    "rem_sleep": "REM睡眠",
    "awake": "覚醒",
    "bed_time": "就寝時刻",
    "wake_time": "起床時刻",
    "resting_hr": "安静時心拍数(bpm)",
    "avg_hrv": "平均HRV(ms)",
    "avg_respiration": "平均呼吸数(回/分)",
    "avg_spo2": "平均SpO2(%)",
    "avg_stress": "睡眠中の平均ストレス",
}

_SYSTEM_PROMPT = (
    "あなたは睡眠の専門家です。提示されたGarminの睡眠指標をもとに、"
    "前夜の睡眠を評価し、利用者が朝に読んで役立つ簡潔な日本語レポートを書いてください。"
    "構成は次の3つの見出しで: 「① 総評」「② 良かった点・気になる点」"
    "「③ 今日へのアドバイス」。"
    "専門用語には軽い補足を添え、断定しすぎず、前向きで実行しやすい助言にしてください。"
    "全体で400〜600字程度。"
)


def format_metrics(summary: dict) -> str:
    """睡眠指標を読みやすい箇条書きテキストに整形する。"""
    lines = []
    for key, label in _LABELS.items():
        value = summary.get(key)
        if value is not None:
            lines.append(f"- {label}: {value}")
    return "\n".join(lines)


def build_prompt(summary: dict) -> str:
    """Claude Desktop にそのまま貼り付けられる分析プロンプトを返す（無料・手動モード）。

    分析指示と睡眠指標を1つのテキストにまとめる。
    """
    metrics_text = format_metrics(summary)
    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"対象日: {summary.get('date')}\n"
        f"以下は前夜のGarmin睡眠指標です。これを分析・評価してください。\n\n"
        f"{metrics_text}"
    )


def _run_claude_cli(prompt: str) -> str:
    """Claude Code CLI(`claude -p`)にプロンプトを渡し、応答テキストを返す。

    プロンプトは stdin 経由で渡す（複数行・特殊文字の安全性、シェル注入回避）。
    サブスクリプションで動作するため API 従量課金は発生しない。
    """
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
            "claude CLI から空の応答が返りました。"
            f"\nstderr: {proc.stderr.strip()}"
        )
    return output


def analyze_free(summary: dict) -> str:
    """Claude Code CLI で睡眠を分析し、評価レポート文（日本語）を返す（無料・サブスク）。"""
    prompt = build_prompt(summary)
    return _run_claude_cli(prompt)


def analyze(summary: dict) -> str:
    """睡眠サマリを Claude API に渡し、評価レポート文（日本語）を返す（有料・自動モード）。"""
    config.require_anthropic()
    metrics_text = format_metrics(summary)
    user_content = (
        f"対象日: {summary.get('date')}\n"
        f"以下は前夜の睡眠指標です。これを分析・評価してください。\n\n"
        f"{metrics_text}"
    )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=2000,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    return "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()


if __name__ == "__main__":
    from garmin_client import get_sleep_summary

    s = get_sleep_summary()
    if s:
        print(analyze(s))
    else:
        print("睡眠データが取得できませんでした。")
