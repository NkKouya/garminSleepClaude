# Garmin Sleep Reporter

Garmin Connect から前夜の睡眠データを取得し、Claude で分析・評価するシステム。

2つのモードがある:
- **無料・詳細モード（おすすめ）**: `claude -p`（Claude Code CLI）をサブスクで使い、
  生データを時系列（5分粒度）で分析し、HTMLメールで送信する。API従量課金なし。
- **有料・自動モード**: Claude API で集計値を自動分析し、Gmail で送信。

履歴蓄積用に `build_database.py`（rawdata → SQLite `sleep.db`）も同梱。

## 仕組み

### 無料・詳細モード（おすすめ）
```
タスクスケジューラ(毎朝8:00) → run_detailed_report.bat → detailed_report.py
  database.load_intermediate     : SQLite sleep.db の中間表現を参照（DB優先＝再DL不要）
    └ DBに無い日は build_database.ingest_date でその日だけ取り込み
      今日分は常に再取得してDBを最新化
  analyzer.analyze_free_detailed : claude -p で時系列分析（サブスク＝API課金なし）
  → output/sleep_detail_*.txt 保存
  ＆ emailer.py で HTMLメール送信（既定ON。--no-mail で抑止）
```

### 有料・自動モード
無料モードと同じ中間表現（5分粒度タイムライン）＋`_DETAILED_SYSTEM_PROMPT` を使い、
分析エンジンだけ Claude API（従量課金）に置き換えたもの。出力品質は無料モードと同等。
```
タスクスケジューラ → run_sleep_report.bat → main.py
  database.load_intermediate / build_database.ingest_date（中間表現）
  → analyzer.analyze_detailed_api()(Claude API) → emailer.py(HTMLメール送信)
```

## セットアップ

### 1. 依存パッケージのインストール
```powershell
cd C:\Users\mckou\garminSleep
pip install -r requirements.txt
```

### 2. .env の作成
`.env.example` を `.env` にコピーする。

| 項目 | 必須 | 内容 |
|------|------|------|
| `GARMIN_EMAIL` / `GARMIN_PASSWORD` | ✅ | Garmin Connect のログイン情報 |
| `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` | メール送信時 | Gmail送信用（アプリパスワード）。`--no-mail` 実行時は不要 |
| `ANTHROPIC_API_KEY` | 有料モードのみ | https://console.anthropic.com で発行（従量課金） |

### 分析エンジンの選択（Claude のサブスク/課金が無くても使える）

`.env` の `BACKEND` で分析エンジンを切り替えられます。**Claude を持っていなくても、無料の
`ollama` / `gemini` で同じ分析（同一プロンプト・同一データ）が動きます。**

| `BACKEND` | 対象 | 費用 | データ送信先 | 準備 |
|------|------|------|------|------|
| `claude_cli`（既定） | Claude Code サブスク保有 | 無料(サブスク) | Anthropic | `claude` にログイン済み |
| **`ollama`（無料の本命）** | 非課金・プライバシー重視 | 無料 | **PC内（外に出ない）** | Ollama を起動し `ollama pull qwen2.5:7b` |
| `gemini` | 非課金・手軽さ重視 | 無料枠 | Google | `GEMINI_API_KEY` を https://aistudio.google.com で発行し記入 |
| `claude_api` | API課金OK | 従量 | Anthropic | `ANTHROPIC_API_KEY` を記入 |

**無料で確実に使うなら `ollama` を推奨します。** Gemini の無料枠は Google アカウント/地域に
よって付与されない（HTTP 429 / `limit: 0`）ことがあり、その場合は待っても回復しません。
`gemini` で 429 が出たら `GEMINI_MODEL=gemini-2.5-flash` を試すか、`BACKEND=ollama` に切り替えてください。

※ ローカルの小型モデル（`ollama`）は Claude より分析が浅くなる傾向があります。
「無料・データがPC外に出ない」価値と引き換えである点に留意してください。

### 3. 初回手動実行（Garminログイン & トークン生成）
```powershell
python fetch_rawdata.py
```
初回は Garmin の2段階認証コード入力を求められる場合があります。
成功すると `.garminconnect/` にトークンが保存され、以降は自動ログインされます。

## 使い方（無料・詳細モード）★おすすめ

`claude -p`（Claude Code CLI）をサブスクリプションで使うため、API従量課金は発生しません。

### 前提
- このPCで Claude Code にログイン済みであること（`claude` が使える状態）
- `.env` に **Gmail送信設定**を記入すること（既定でメール送信するため。送信しない場合は `--no-mail`）:
  - `GMAIL_ADDRESS` = 送信元/送信先の Gmail アドレス
  - `GMAIL_APP_PASSWORD` = Gmail の**アプリパスワード**（16文字。通常のPW不可。
    Google アカウント → セキュリティ → 2段階認証を有効化 → 「アプリパスワード」で発行）

### 手動実行
```powershell
python detailed_report.py              # 今日分（再取得して最新化、HTMLメール送信あり）
python detailed_report.py 2026-06-16   # 日付指定（DB参照、無ければ取込）
python detailed_report.py --no-mail    # 送信せずファイル保存のみ
```
DB(sleep.db)の中間表現を参照（過去日は再DL不要）→ Claude が時系列分析 →
`output/sleep_detail_YYYY-MM-DD.txt` 保存 →
`MAIL_TO`（既定は `GMAIL_ADDRESS`）宛に **HTMLメール**送信。

### 毎朝の全自動化（タスクスケジューラ）
1. 「タスク スケジューラ」→「基本タスクの作成」
2. 名前: `Garmin Sleep Auto`
3. トリガー: 「毎日」→ 開始時刻 `8:00`
4. 操作: 「プログラムの開始」→ `C:\Users\mckou\garminSleep\run_detailed_report.bat`
5. 「ユーザーがログオンしているときのみ実行」を選ぶ
   （Claude Code のログイン情報にアクセスするため）

これで毎朝、PCを起動していれば睡眠レポートが自動でメールに届きます。

### スリープ（ノートを閉じた状態）でも動かす設定

既定ではスリープ中はタスクが起動しません。スリープから自動復帰して実行させるには、
作成したタスクを右クリック →「プロパティ」で以下を設定します。

**①「条件」タブ**
- ☑ 「タスクの実行時にスリープを解除する」にチェック（最重要：スリープから復帰して実行）
- ☐ 「コンピューターをAC電源で使用している場合のみタスクを開始する」のチェックを外す
  （ノートを閉じてバッテリー運用する場合。外さないと実行されない）

**②「設定」タブ**
- ☑ 「スケジュールされた時刻にタスクを開始できなかった場合、すぐにタスクを開始する」に
  チェック（復帰に失敗しても、次にPCを開いた時に実行される保険）

**③ Windows の電源設定（スリープ解除タイマーの許可）**
- コントロールパネル → 電源オプション → プラン設定の変更 → 詳細な電源設定 →
  「スリープ」→「スリープ解除タイマーの許可」を **有効**（バッテリー/電源の両方）
  ※ ここが無効だと①にチェックしても起きない

**動作する状態の早見表**

| 状態 | 動作 |
|---|---|
| スリープ（上記設定あり） | ✅ 自動復帰して実行 |
| スリープ（設定なし） | ❌ 起動せず（次回ログオン時に②の保険で実行可） |
| 休止状態(hibernate) | ⚠️ 機種により復帰できず動かないことあり |
| シャットダウン | ❌ 動かない |

注意: 復帰直後はWi-Fi再接続に数秒かかり、その瞬間に実行されるとGarmin取得に失敗して
エラーメールが届くことがあります。頻発する場合は実行時刻をずらすか、リトライ処理の追加を検討。
確実性を最優先するなら「ノートを閉じてもスリープしない」設定にして定時実行する運用も手堅いです。

## 履歴の蓄積（任意）

過去の生データを `rawdata/` に集めて SQLite に取り込み、履歴分析に使える。

```powershell
python fetch_rawdata.py 2026-06-16   # 指定日の生データを rawdata/ に保存
python build_database.py             # rawdata/ → sleep.db に取り込み
```

## 動作確認（個別）

```powershell
python garmin_client.py        # 睡眠データがJSONで表示されるか
python detailed_report.py --no-mail   # 詳細レポートが生成されるか（送信なし・無料）
```

## （将来）有料・自動モードを使う場合
`.env` に `ANTHROPIC_API_KEY` と Gmail設定を追加し、以下を実行/登録する。

```powershell
python main.py            # 取得→分析(API)→メール送信まで通し実行
```

タスクスケジューラに `run_sleep_report.bat` を毎日8:00で登録すると全自動になる。

**Gmail アプリパスワード**: Google アカウント → セキュリティ → 2段階認証を有効化 →
「アプリパスワード」で16文字を発行（通常のログインPWは不可）。

## ログ
- `logs/sleep_report.log` : アプリのログ
- `logs/task.log`         : バッチ実行時の標準出力/エラー

## 留意点
- `garminconnect` は非公式APIのため、Garmin側仕様変更で動かなくなる可能性があります
  （`pip install -U garminconnect` で更新）。
- 起床直後は時計→スマホ→Garmin Connect の同期が未完了のことがあります。
  実行時刻は同期が済む 8:00 前後を推奨。未同期時はその旨をメール通知します。
- 秘密情報は `.env` のみに保持し、Git管理する場合も `.gitignore` で除外されます。
