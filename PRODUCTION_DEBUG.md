# 本番環境デバッグ手順

## 概要
ローカルでは動作するが本番環境でAI抽出が正しく動作しない問題を特定するための手順です。

## 手順

### 1. 本番環境に接続
```bash
# RailwayのWebシェルを使用するか、SSH接続
# Railwayの場合: ダッシュボード → プロジェクト → Deployments → 最新のデプロイ → View Logs → Terminal
```

### 2. 現在のコードを確認
```bash
# 作業ディレクトリに移動
cd /app

# 現在のai_service.pyの内容を確認
cat ai_service.py

# ファイルの最終更新日時を確認
ls -la ai_service.py
```

### 3. 環境変数を確認
```bash
# 環境変数の確認
echo "OPENAI_API_KEY: ${OPENAI_API_KEY:0:10}..."  # 先頭10文字のみ表示
echo "LINE_CHANNEL_ACCESS_TOKEN: ${LINE_CHANNEL_ACCESS_TOKEN:0:10}..."
echo "LINE_CHANNEL_SECRET: ${LINE_CHANNEL_SECRET:0:10}..."
```

### 4. デバッグスクリプトを実行
```bash
# 基本的なテスト
python debug_production.py

# 詳細なデバッグテスト
python ai_service_debug.py
```

### 5. ログを確認
```bash
# アプリケーションログを確認
# Railwayの場合: ダッシュボード → View Logs
# または
tail -f /app/logs/app.log  # ログファイルのパスは環境によって異なる
```

## 問題の特定

### A. コードが古い場合
```bash
# 最新のコードに更新
git pull origin main
# または手動でファイルを更新
```

### B. 環境変数が設定されていない場合
- Railwayダッシュボードで環境変数を設定
- 設定後、アプリケーションを再起動

### C. サーバーが再起動されていない場合
```bash
# Railwayの場合: ダッシュボード → Deployments → Redeploy
# または
# プロセスを手動で再起動
```

### D. OpenAI APIの問題の場合
```bash
# APIキーの有効性を確認
python -c "
import openai
from config import Config
client = openai.OpenAI(api_key=Config.OPENAI_API_KEY)
response = client.chat.completions.create(
    model='gpt-3.5-turbo',
    messages=[{'role': 'user', 'content': 'test'}],
    temperature=0.1
)
print('API接続成功:', response.choices[0].message.content)
"
```

## 期待される結果

### 正常な場合
```
=== AI抽出機能テスト開始 ===
現在時刻: 2025-01-XX XX:XX:XX+09:00
OpenAI API Key: 設定済み
API Key 先頭10文字: sk-xxxxxxxxxx
✅ AIサービス初期化成功

--- テストケース 1: 7/10 9-10時 ---
結果: {'task_type': 'availability_check', 'dates': [{'date': '2025-07-10', 'time': '09:00', 'end_time': '10:00'}]}

--- テストケース 2: ・7/10 9-10時\n・7/11 9-10時 ---
結果: {'task_type': 'availability_check', 'dates': [{'date': '2025-07-10', 'time': '09:00', 'end_time': '10:00'}, {'date': '2025-07-11', 'time': '09:00', 'end_time': '10:00'}]}
```

### 問題がある場合
```
--- テストケース 2: ・7/10 9-10時\n・7/11 9-10時 ---
結果: {'task_type': 'availability_check', 'dates': [{'date': '2025-07-10', 'time': '09:00', 'end_time': '10:00'}, {'date': '2025-07-11', 'time': '18:00', 'end_time': '23:59'}]}
```

## 次のステップ

1. **コードが古い場合**: 最新のコードに更新して再デプロイ
2. **環境変数が問題の場合**: Railwayダッシュボードで設定を確認・修正
3. **OpenAI APIが問題の場合**: APIキーやモデルの設定を確認
4. **それでも解決しない場合**: 詳細なログを収集して分析

## ログの収集

問題が解決しない場合は、以下の情報を収集してください：

1. `debug_production.py`の出力結果
2. `ai_service_debug.py`の出力結果（特に生のAIレスポンス）
3. アプリケーションログ
4. 現在の`ai_service.py`の内容
5. 環境変数の設定状況

これらの情報があれば、問題の根本原因を特定できます。 