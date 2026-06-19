"""睡眠データを分析・評価し、日本語のレポート文を生成する。

2系統の分析:
- analyze_free_detailed(): Claude Code CLI(`claude -p`)で時系列を分析（無料・サブスク）。
- analyze():               Claude API を使う（有料・従量課金）。
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
    "# 役割\n"
    "あなたは睡眠科学に基づいて睡眠データを解析するアナリストです。"
    "スタンフォード大学・西野精治氏が提唱する「黄金の90分」（入眠直後の最初の"
    "ノンレム睡眠周期＝睡眠全体の質を決める最重要区間）の観点を中心に、"
    "添付した睡眠データを解析してください。\n"
    "\n"
    "# 前提知識（この枠組みで評価すること）\n"
    "- 「黄金の90分」＝入眠後の最初の睡眠周期（おおむね最初の90〜120分）。"
    "ここで深いノンレム睡眠（N3/徐波睡眠）がまとまって出現できているかが鍵。\n"
    "- 評価の主眼:\n"
    "1. 入眠のスムーズさ（入眠潜時 SL）\n"
    "2. 入眠後、最初の周期で深睡眠（N3）に素早く・深く・連続的に入れているか\n"
    "3. 最初の周期が中途覚醒や浅い睡眠（N1/覚醒）で分断されていないか\n"
    "4. 周期がその後リズムよく4〜5回繰り返されているか\n"
    "- 「何時に寝たか」自体は質の良し悪しに直結しない（時刻ではなく入眠後の"
    "最初の90分の質を見る）点に注意。\n"
    "\n"
    "# 解析手順\n"
    "1. データから次を抽出・推定する（取得できないものは「データなし」と明記）:\n"
    "- 就床時刻 / 入眠時刻 / 起床時刻 / 総睡眠時間(TST)\n"
    "- 入眠潜時(SL)\n"
    "- 各睡眠段階（覚醒・REM・N1/N2軽睡眠・N3深睡眠）の時間と割合\n"
    "- 中途覚醒回数・中途覚醒時間(WASO)\n"
    "- 入眠から最初の深睡眠到達までの時間、最初の深睡眠の持続\n"
    "2. 「黄金の90分」区間（入眠から最初の約90分）を切り出し、その区間内の"
    "深睡眠の量・割合・連続性・覚醒による分断の有無を重点的に評価する。\n"
    "3. 上記をもとに、黄金の90分が「うまく取れた／不十分」を理由とともに判定する。\n"
    "\n"
    "# 出力フォーマット（結論を先に）\n"
    "1. 結論: 黄金の90分の質を一言で（例: 良好／やや不十分／不十分）＋一文の根拠\n"
    "2. 黄金の90分スコア: 0〜100の概算スコアと、その内訳（SL・初回深睡眠の"
    "深さ/速さ/連続性・分断の有無）\n"
    "3. 主要指標の一覧（数値とその一般的な目安との比較）\n"
    "4. 観察された問題点・懸念（追従や過度な賞賛はせず率直に）\n"
    "5. 改善のための具体的アクション（深部体温・入浴タイミング・就床前行動など、"
    "黄金の90分の質を上げる介入に絞る）\n"
    "\n"
    "# 注意\n"
    "- 推測で断定しない。データから読み取れない箇所は明示する。\n"
    "- 医療的診断はしない。気になる所見があれば受診を勧める程度に留める。\n"
    "- これは一般的な睡眠科学の枠組みに基づく解析であり、医療行為ではない。\n"
)


_WEEKLY_SYSTEM_PROMPT = (
    "# 役割\n"
    "あなたは睡眠科学に基づいて睡眠データを解析するアナリストです。"
    "スタンフォード大学・西野精治氏が提唱する「黄金の90分」（入眠直後の最初の"
    "ノンレム睡眠周期＝睡眠全体の質を決める最重要区間）の観点を中心に、"
    "添付した直近1週間の睡眠データ（週次集計＋夜別指標）を解析してください。"
    "単一の夜ではなく、1週間を通した『平均』『ばらつき（一貫性）』『傾向』を評価します。\n"
    "\n"
    "# 前提知識（この枠組みで評価すること）\n"
    "- 「黄金の90分」＝入眠後の最初の睡眠周期。ここで深いノンレム睡眠（N3/徐波睡眠）が"
    "まとまって出現できているかが鍵。本データの『黄金90分の深睡眠量』は、各夜の入眠後"
    "90分以内に観測された深睡眠の分数（最大90分）。週平均が大きいほど、初回周期で"
    "深く眠れている夜が多いことを示す。\n"
    "- 就寝・起床時刻の『ばらつき（標準偏差）』は睡眠リズムの一貫性の指標。"
    "ばらつきが大きいほど体内時計が乱れやすく、黄金の90分の再現性を下げやすい。\n"
    "- 「何時に寝たか」自体より、入眠後最初の90分の質と、その週内での安定性を見る。\n"
    "\n"
    "# 解析手順\n"
    "1. 週平均の主要指標（睡眠スコア・各睡眠段階・総睡眠時間・黄金90分の深睡眠量・HRV・"
    "安静時心拍・SpO2・呼吸・ボディバッテリー回復・中途覚醒）を一般的な目安と比較する。\n"
    "2. 夜別の値から、週内の傾向（改善/悪化/横ばい）と、特に良かった夜・崩れた夜を特定する。\n"
    "3. 就寝・起床のばらつきから睡眠リズムの一貫性を評価する。\n"
    "4. 黄金の90分が週を通して安定して取れているか/不十分かを、理由とともに判定する。\n"
    "\n"
    "# 出力フォーマット（結論を先に）\n"
    "1. 週の結論: 今週の睡眠の質を一言で（例: 安定して良好／ばらつき大／週後半に悪化）＋一文の根拠\n"
    "2. 週間黄金90分スコア: 0〜100の概算スコアと内訳（深睡眠量の週平均・一貫性・週内トレンド）\n"
    "3. 週平均の主要指標一覧（数値と一般的な目安との比較、夜別のレンジにも触れる）\n"
    "4. 週内で観察された問題点・懸念（追従や過度な賞賛はせず率直に。反復する課題を重視）\n"
    "5. 来週への具体的アクション（深部体温・入浴タイミング・就床リズムの一貫性など、"
    "黄金の90分の質と再現性を上げる介入に絞る）\n"
    "\n"
    "# 注意\n"
    "- 推測で断定しない。データから読み取れない箇所は明示する。\n"
    "- 医療的診断はしない。気になる所見があれば受診を勧める程度に留める。\n"
    "- これは一般的な睡眠科学の枠組みに基づく解析であり、医療行為ではない。\n"
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


def format_weekly(weekly: dict) -> str:
    """週次集計（週平均＋夜別の黄金90分指標）をLLM向けの簡潔テキストに整形する。"""
    sc = weekly.get("score") or {}
    st = weekly.get("stages") or {}
    bt = weekly.get("bed_time") or {}
    wt = weekly.get("wake_time") or {}

    lines = [
        f"対象期間: {weekly.get('start_date')} 〜 {weekly.get('end_date')}"
        f"（データのある夜: {_fmt(weekly.get('days'))} 日）",
        "",
        "【週次集計（平均）】",
        f"- 睡眠スコア: 平均 {_fmt(sc.get('avg'))} "
        f"(範囲 {_fmt(sc.get('min'))}〜{_fmt(sc.get('max'))}, σ {_fmt(sc.get('std'))})",
        f"- ステージ(分): 深い {_fmt(st.get('deep_min'))} / 浅い {_fmt(st.get('light_min'))} "
        f"/ REM {_fmt(st.get('rem_min'))} / 覚醒 {_fmt(st.get('awake_min'))}  "
        f"総睡眠 {_fmt(st.get('total_sleep_min'))}",
        f"- 黄金90分の深睡眠量: 平均 {_fmt(weekly.get('golden90_deep_avg'))} 分 "
        f"(入眠後90分以内の深睡眠, 最大90)",
        f"- 就寝: 平均 {_fmt(bt.get('avg'))} (ばらつき σ{_fmt(bt.get('std_min'))}分)  "
        f"起床: 平均 {_fmt(wt.get('avg'))} (σ{_fmt(wt.get('std_min'))}分)",
        f"- HRV平均 {_fmt(weekly.get('hrv_avg'))}ms / 安静時HR {_fmt(weekly.get('hr_resting_avg'))} "
        f"/ SpO2 {_fmt(weekly.get('spo2_avg'))}% / 呼吸 {_fmt(weekly.get('resp_avg'))}回/分",
        f"- 回復(BB変化) 平均 +{_fmt(weekly.get('bb_change_avg'))} / 睡眠中ストレス平均 "
        f"{_fmt(weekly.get('stress_avg'))} / 中途覚醒 平均 {_fmt(weekly.get('awakenings_avg'))} 回",
        "",
        "【夜別 × 黄金90分】",
        "日付         score 深  REM 黄金90分の深睡眠(分)",
    ]
    for n in weekly.get("nights") or []:
        lines.append(
            f"{_fmt(n.get('date')):10} {_fmt(n.get('score')):5} "
            f"{_fmt(n.get('deep_min')):3} {_fmt(n.get('rem_min')):3} "
            f"{_fmt(n.get('golden90_deep_min')):>4}"
        )
    return "\n".join(lines)


def analyze_free_weekly(weekly: dict) -> str:
    """週次集計を Claude Code CLI で分析し、週間レポート文（日本語）を返す。"""
    body = format_weekly(weekly)
    prompt = (
        f"{_WEEKLY_SYSTEM_PROMPT}\n\n"
        f"以下は直近1週間のGarmin睡眠データを集計したものです（週平均と夜別の指標）。"
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
