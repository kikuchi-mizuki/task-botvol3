# LINE Calendar Bot

LINEで予定管理するAIボットです。ChatGPTを使った自然言語処理とGoogleカレンダーの連携により、直感的な予定管理が可能です。

## 機能

### 1. 複数日程の空き時間確認
- 複数の日程を送ると、正確に日時を抽出
- Googleカレンダーを確認して空き時間を返信
- 例: 「明日と明後日の空き時間を教えて」

### 2. 予定の追加
- 日時とタイトルを送ると、Googleカレンダーに予定を追加
- 成功時: 「✅予定を追加しました」と日時・タイトルを返信
- 例: 「明日の午前9時から会議を追加して」

### 3. 既存予定の確認
- 既に予定が入っている場合は「✅既に予定が入っています」と返信
- 既存の予定内容も表示

## セットアップ

### 1. 必要なアカウントとAPIキー

#### LINE Developers
1. [LINE Developers Console](https://developers.line.biz/)にアクセス
2. 新しいプロバイダーを作成
3. LINE Botチャネルを作成
4. チャネルアクセストークンとチャネルシークレットを取得

#### OpenAI
1. [OpenAI Platform](https://platform.openai.com/)にアクセス
2. APIキーを取得

#### Google Calendar API
1. [Google Cloud Console](https://console.cloud.google.com/)にアクセス
2. 新しいプロジェクトを作成
3. Google Calendar APIを有効化
4. 認証情報を作成（OAuth 2.0クライアントID）
5. credentials.jsonファイルをダウンロード

### 2. 環境設定

1. リポジトリをクローン
```bash
git clone <repository-url>
cd task_bot
```

2. 仮想環境を作成・有効化
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

3. 依存関係をインストール
```bash
pip install -r requirements.txt
```

4. 環境変数ファイルを作成
```bash
cp .env.example .env
```

5. .envファイルを編集して、実際の値を設定
```env
# LINE Bot設定
LINE_CHANNEL_ACCESS_TOKEN=your_line_channel_access_token_here
LINE_CHANNEL_SECRET=your_line_channel_secret_here

# OpenAI設定
OPENAI_API_KEY=your_openai_api_key_here

# Google Calendar設定
GOOGLE_CALENDAR_ID=primary
GOOGLE_CREDENTIALS_FILE=credentials.json

# Flask設定
FLASK_SECRET_KEY=your_flask_secret_key_here

# アプリケーション設定
TIMEZONE=Asia/Tokyo
DEFAULT_EVENT_DURATION=60
```

6. Google認証ファイルを配置
```bash
# credentials.jsonファイルをプロジェクトルートに配置
```

### 3. 初回認証

1. アプリケーションを起動
```bash
python app.py
```

2. 初回起動時にGoogle認証が実行されます
3. ブラウザが開くので、Googleアカウントで認証してください
4. 認証後、token.pickleファイルが作成されます

### 4. LINE Bot設定

1. LINE Developers ConsoleでWebhook URLを設定
```
https://your-domain.com/callback
```

2. Webhookを有効化

## 使用方法

### 基本的な使い方

#### 空き時間確認
```
明日と明後日の空き時間を教えて
来週月曜日から金曜日の予定は？
```

#### 予定追加
```
明日の午前9時から会議を追加して
来週月曜日の14時から打ち合わせ
今日の19時から食事の予定
```

### 対応する日時表現

#### 日付
- 今日、明日、明後日
- 来週月曜日、来週火曜日...
- 2024年1月15日、1月15日
- 1/15、01/15

#### 時間
- 午前9時、午後3時
- 9時、15時
- 9:30、15:30
- 朝、昼、夜

## 開発

### プロジェクト構造
```
task_bot/
├── app.py                 # メインアプリケーション
├── line_bot_handler.py    # LINE Bot処理
├── ai_service.py          # ChatGPT連携
├── calendar_service.py    # Google Calendar連携
├── config.py              # 設定管理
├── requirements.txt       # 依存関係
├── credentials.json       # Google認証ファイル
├── token.pickle          # Google認証トークン
└── README.md             # このファイル
```

### テスト

```bash
# 設定テスト
curl http://localhost:5000/test

# ヘルスチェック
curl http://localhost:5000/health
```

### ログ

アプリケーションのログは標準出力に出力されます。本番環境では適切なログ管理システムを使用してください。

## トラブルシューティング

### よくある問題

#### 1. Google認証エラー
- credentials.jsonファイルが正しく配置されているか確認
- 初回認証が完了しているか確認

#### 2. LINE Bot応答なし
- Webhook URLが正しく設定されているか確認
- チャネルアクセストークンとシークレットが正しいか確認

#### 3. ChatGPT応答エラー
- OpenAI APIキーが正しく設定されているか確認
- API使用量制限に達していないか確認

### エラーログの確認

```bash
# アプリケーションログを確認
python app.py 2>&1 | tee app.log
```

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。

## 貢献

プルリクエストやイシューの報告を歓迎します 