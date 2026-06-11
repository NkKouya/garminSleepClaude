"""Claude API で睡眠データを分析・評価し、日本語のレポート文を生成する。"""
from __future__ import annotations

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
