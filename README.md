# Garmin Sleep Reporter

Garmin Connect から前夜の睡眠データを取得し、Claude で分析・評価するシステム。

3つのモードがある:
- **無料・全自動モード（おすすめ）**: `claude -p`（Claude Code CLI）をサブスクで使い、
  取得→分析→ファイル保存→Gmail送信まで全自動。API従量課金なし。
- **無料・手動モード**: APIを使わず貼り付け用プロンプトを生成し、Claude Desktop に貼る。
- **有料・自動モード（将来用）**: Claude API で自動分析し、Gmail で送信。

## 仕組み

### 無料・全自動モード（おすすめ）
```
タスクスケジューラ(毎朝8:00) → run_auto_free.bat → auto_free.py
  garmin_client.py     : Garminから睡眠データ取得
  analyzer.analyze_free: claude -p で分析（サブスク利用＝API課金なし）
  → output/sleep_report_*.txt 保存 ＆ emailer.py(Gmail送信)
```

### 無料・手動モード
```
manual_report.py
  garmin_client.py : Garminから睡眠データ取得
  analyzer.py      : build_prompt() で貼り付け用プロンプト生成
  → クリップボード / output/*.txt / 画面 に出力
  → あなたが Claude Desktop に Ctrl+V
```

### 有料・自動モード
```
タスクスケジューラ → run_sleep_report.bat → main.py
  garmin_client.py → analyzer.analyze()(Claude API) → emailer.py(Gmail送信)
```

## セットアップ

### 1. 依存パッケージのインストール
```powershell
cd C:\Users\mckou\garminSleep
pip install -r requirements.txt
```

### 2. .env の作成
`.env.example` を `.env` にコピーする。**無料・手動モードでは Garmin の情報だけ**でOK。

| 項目 | 必須 | 内容 |
|------|------|------|
| `GARMIN_EMAIL` / `GARMIN_PASSWORD` | ✅ | Garmin Connect のログイン情報 |
| `ANTHROPIC_API_KEY` | 自動モードのみ | https://console.anthropic.com で発行（従量課金） |
| `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` | 自動モードのみ | Gmail送信用（アプリパスワード） |

### 3. 初回手動実行（Garminログイン & トークン生成）
```powershell
python manual_report.py
```
初回は Garmin の2段階認証コード入力を求められる場合があります。
成功すると `.garminconnect/` にトークンが保存され、以降は自動ログインされます。

## 使い方（無料・全自動モード）★おすすめ

`claude -p`（Claude Code CLI）をサブスクリプションで使うため、API従量課金は発生しません。

### 前提
- このPCで Claude Code にログイン済みであること（`claude` が使える状態）
- `.env` に **Gmail送信設定**を記入すること（このモードはメール送信するため）:
  - `GMAIL_ADDRESS` = 送信元/送信先の Gmail アドレス
  - `GMAIL_APP_PASSWORD` = Gmail の**アプリパスワード**（16文字。通常のPW不可。
    Google アカウント → セキュリティ → 2段階認証を有効化 → 「アプリパスワード」で発行）

### 手動実行
```powershell
python auto_free.py
```
Garmin取得 → Claude分析 → `output/sleep_report_YYYY-MM-DD.txt` 保存 →
`MAIL_TO`（既定は `GMAIL_ADDRESS`）宛にメール送信。

### 毎朝の全自動化（タスクスケジューラ）
1. 「タスク スケジューラ」→「基本タスクの作成」
2. 名前: `Garmin Sleep Auto`
3. トリガー: 「毎日」→ 開始時刻 `8:00`
4. 操作: 「プログラムの開始」→ `C:\Users\mckou\garminSleep\run_auto_free.bat`
5. 「ユーザーがログオンしているときのみ実行」を選ぶ
   （Claude Code のログイン情報にアクセスするため）

これで毎朝、PCを起動していれば睡眠レポートが自動でメールに届きます。

## 使い方（無料・手動モード）

```powershell
python manual_report.py
```
または `run_manual_report.bat` をダブルクリック。

実行すると:
1. Garmin から当日の睡眠データを取得
2. 「分析指示＋睡眠指標」の貼り付け用プロンプトを生成
3. クリップボードにコピー（＋ `output/sleep_prompt_YYYY-MM-DD.txt` に保存＋画面表示）

あとは **Claude Desktop を開いて Ctrl+V → 送信** すれば、睡眠の評価・アドバイスが
無料で得られます。

毎朝決まった時刻に自動で「プロンプト準備」までやっておきたい場合は、タスクスケジューラに
`run_manual_report.bat` を毎日8:00で登録できます（分析の貼り付けは手動）。

## 動作確認（個別）

```powershell
python garmin_client.py   # 睡眠データがJSONで表示されるか
python manual_report.py   # 貼り付け用プロンプトが生成されるか（無料）
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
