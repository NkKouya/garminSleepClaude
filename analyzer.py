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


_DETAILED_SYSTEM_PROMPT = (
    "あなたは睡眠の専門家です。提示されるのはGarminの一晩の睡眠を時系列で表した"
    "データです。集計値だけでなく『夜の経過』に踏み込んで分析してください。"
    "特に次の観点を活用すること: "
    "(1) 睡眠ステージの遷移とサイクル（深い睡眠が前半に出ているか、REMの位置）、"
    "(2) 心拍の低下とHRV（自律神経）の回復の推移、"
    "(3) SpO2の低下イベントと呼吸の安定性、"
    "(4) 中途覚醒・体動のタイミングと他指標との関連、"
    "(5) ボディバッテリーの回復効率とストレス推移。"
    "出力は次の4見出しで: 「① 総評」「② 夜の経過（時系列で気づいた点）」"
    "「③ 良かった点・気になる点」「④ 今日へのアドバイス」。"
    "専門用語には軽い補足を添え、データから言えることに限って断定しすぎず、"
    "前向きで実行しやすい助言にすること。SpO2や呼吸の所見は医療診断ではない旨を一言添える。"
    "全体で600〜900字程度。"
)


def _fmt(value) -> str:
    """None を空欄に、数値は簡潔に整形する。"""
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.0f}" if value.is_integer() else f"{value:.1f}"
    return str(value)


def format_intermediate(inter: dict) -> str:
    """中間表現（features + timeline）をLLM向けの簡潔なテキストに整形する。"""
    f = inter.get("features") or {}
    st = f.get("stages") or {}
    hr = f.get("hr") or {}
    hrv = f.get("hrv") or {}
    spo2 = f.get("spo2") or {}
    desat = spo2.get("desaturation") or {}
    resp = f.get("respiration") or {}
    rec = f.get("recovery") or {}
    awk = f.get("awakenings") or {}

    lines = [
        f"対象日: {inter.get('date')}",
        f"睡眠スコア: {_fmt(f.get('sleep_score'))} ({_fmt(f.get('sleep_quality'))})  "
        f"就寝 {_fmt(f.get('bed_time'))} / 起床 {_fmt(f.get('wake_time'))}",
        "",
        "【特徴量】",
        f"- ステージ(分): 深い {_fmt(st.get('deep_min'))} / 浅い {_fmt(st.get('light_min'))} "
        f"/ REM {_fmt(st.get('rem_min'))} / 覚醒 {_fmt(st.get('awake_min'))}  "
        f"REM出現 {_fmt(st.get('cycles'))} 回",
        f"- 中途覚醒: {_fmt(awk.get('count'))} 回 "
        f"({', '.join(awk.get('times') or []) or '-'})  体動(restless) {_fmt(rec.get('restless_moments'))} 回",
        f"- 心拍: 入眠時 {_fmt(hr.get('onset'))} → 最低 {_fmt(hr.get('nadir'))}bpm "
        f"({_fmt(hr.get('nadir_time'))})  安静時 {_fmt(hr.get('resting'))}",
        f"- HRV: {_fmt(hrv.get('start'))} → {_fmt(hrv.get('end'))}ms (傾向 {_fmt(hrv.get('trend'))}) "
        f"平均 {_fmt(hrv.get('avg_overnight'))}  ステータス {_fmt(hrv.get('status'))}",
        f"- SpO2: 平均 {_fmt(spo2.get('avg'))}% / 最低 {_fmt(spo2.get('lowest'))}%  "
        f"90%未満イベント {_fmt(desat.get('count'))} 回 (合計 {_fmt(desat.get('total_min'))}分)",
        f"- 呼吸: 平均 {_fmt(resp.get('avg'))} / 範囲 {_fmt(resp.get('low'))}〜{_fmt(resp.get('high'))} 回/分  "
        f"乱れ {_fmt(resp.get('disruptions'))} 回",
        f"- 回復: ボディバッテリー {_fmt(rec.get('body_battery_start'))} → "
        f"{_fmt(rec.get('body_battery_end'))} (+{_fmt(rec.get('body_battery_change'))})  "
        f"睡眠中平均ストレス {_fmt(rec.get('avg_stress'))}",
        "",
        f"【5分粒度タイムライン】(stage/HR/HRV/SpO2/resp/stress/BB)",
        "時刻  stage HR  HRV SpO2 resp str BB",
    ]
    for r in inter.get("timeline") or []:
        lines.append(
            f"{_fmt(r.get('t')):5} {(_fmt(r.get('stage'))):5} "
            f"{_fmt(r.get('hr')):3} {_fmt(r.get('hrv')):3} {_fmt(r.get('spo2')):4} "
            f"{_fmt(r.get('resp')):3} {_fmt(r.get('stress')):3} {_fmt(r.get('bb')):3}"
        )
    return "\n".join(lines)


def analyze_free_detailed(inter: dict) -> str:
    """中間表現を Claude Code CLI で時系列分析し、詳細レポート文（日本語）を返す。"""
    body = format_intermediate(inter)
    prompt = (
        f"{_DETAILED_SYSTEM_PROMPT}\n\n"
        f"以下は前夜のGarmin睡眠データ（時系列を5分粒度に圧縮したもの）です。"
        f"これを分析・評価してください。\n\n"
        f"{body}"
    )
    return _run_claude_cli(prompt)


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
