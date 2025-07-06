import os
# Railway環境でcredentials.jsonを書き出す
if "GOOGLE_CREDENTIALS_FILE" in os.environ:
    with open("credentials.json", "w") as f:
        f.write(os.environ["GOOGLE_CREDENTIALS_FILE"])

from flask import Flask, request, abort, render_template_string, redirect, url_for, session
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from line_bot_handler import LineBotHandler
from config import Config
import logging
import json
from datetime import datetime
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from db import DBHelper

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')

# 設定の検証
try:
    Config.validate_config()
    logger.info("設定の検証が完了しました")
except ValueError as e:
    logger.error(f"設定エラー: {e}")
    raise

# LINEボットハンドラーを初期化
try:
    line_bot_handler = LineBotHandler()
    handler = line_bot_handler.get_handler()
    logger.info("LINEボットハンドラーの初期化が完了しました")
except Exception as e:
    logger.error(f"LINEボットハンドラーの初期化に失敗しました: {e}")
    raise

print("DEBUG: OPENAI_API_KEY =", os.getenv("OPENAI_API_KEY"))

# DBヘルパーの初期化
db_helper = DBHelper()

@app.route("/callback", methods=['POST'])
def callback():
    """LINE Webhookのコールバックエンドポイント"""
    # リクエストヘッダーからX-Line-Signatureを取得
    signature = request.headers['X-Line-Signature']

    # リクエストボディを取得
    body = request.get_data(as_text=True)
    logger.info("Request body: " + body)

    try:
        # 署名を検証し、問題なければhandleに定義されている関数を呼び出す
        handler.handle(body, signature)
    except InvalidSignatureError:
        # 署名検証で失敗したときは例外をあげる
        logger.error("署名検証に失敗しました")
        abort(400)

    # 正常終了時は200を返す
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """テキストメッセージを処理"""
    try:
        logger.info(f"メッセージを受信: {event.message.text}")
        
        # メッセージを処理してレスポンスを取得
        response = line_bot_handler.handle_message(event)
        
        # LINEにメッセージを送信
        line_bot_handler.line_bot_api.reply_message(
            event.reply_token,
            response
        )
        
        logger.info("メッセージの処理が完了しました")
        
    except Exception as e:
        logger.error(f"メッセージ処理でエラーが発生しました: {e}")
        # エラーが発生した場合はエラーメッセージを送信
        try:
            line_bot_handler.line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="申し訳ございません。エラーが発生しました。しばらく時間をおいて再度お試しください。")
            )
        except Exception as reply_error:
            logger.error(f"エラーメッセージの送信に失敗しました: {reply_error}")

@app.route("/", methods=['GET'])
def index():
    """ヘルスチェック用エンドポイント"""
    return "LINE Calendar Bot is running!"

@app.route("/health", methods=['GET'])
def health():
    """ヘルスチェック用エンドポイント"""
    return {"status": "healthy", "service": "line-calendar-bot"}

@app.route("/test", methods=['GET'])
def test():
    """テスト用エンドポイント"""
    return {
        "message": "LINE Calendar Bot Test",
        "config": {
            "line_configured": bool(Config.LINE_CHANNEL_ACCESS_TOKEN and Config.LINE_CHANNEL_SECRET),
            "openai_configured": bool(Config.OPENAI_API_KEY),
            "google_configured": bool(os.path.exists(Config.GOOGLE_CREDENTIALS_FILE))
        }
    }

@app.route('/onetime_login', methods=['GET', 'POST'])
def onetime_login():
    """ワンタイムコード認証ページ"""
    if request.method == 'GET':
        # ワンタイムコード入力フォームを表示
        html = '''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Google Calendar 認証</title>
            <meta charset="utf-8">
            <style>
                body { font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto; padding: 20px; }
                .form-group { margin-bottom: 20px; }
                label { display: block; margin-bottom: 5px; font-weight: bold; }
                input[type="text"] { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 4px; }
                button { background: #4285f4; color: white; padding: 12px 24px; border: none; border-radius: 4px; cursor: pointer; }
                button:hover { background: #3367d6; }
                .error { color: red; margin-top: 10px; }
                .success { color: green; margin-top: 10px; }
            </style>
        </head>
        <body>
            <h1>Google Calendar 認証</h1>
            <p>LINE BotでGoogle Calendarを利用するために認証が必要です。</p>
            <form method="POST">
                <div class="form-group">
                    <label for="code">ワンタイムコード:</label>
                    <input type="text" id="code" name="code" placeholder="8文字のコードを入力" required>
                </div>
                <button type="submit">認証を開始</button>
            </form>
            {% if error %}
            <div class="error">{{ error }}</div>
            {% endif %}
            {% if success %}
            <div class="success">{{ success }}</div>
            {% endif %}
        </body>
        </html>
        '''
        return render_template_string(html, error=None, success=None)
    
    elif request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        
        # ワンタイムコードを検証
        line_user_id = db_helper.verify_onetime_code(code)
        if not line_user_id:
            html = '''
            <!DOCTYPE html>
            <html>
            <head>
                <title>認証エラー</title>
                <meta charset="utf-8">
                <style>
                    body { font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto; padding: 20px; }
                    .error { color: red; margin: 20px 0; }
                    .back-link { margin-top: 20px; }
                </style>
            </head>
            <body>
                <h1>認証エラー</h1>
                <div class="error">
                    無効なワンタイムコードです。<br>
                    コードが正しいか、有効期限が切れていないか確認してください。
                </div>
                <div class="back-link">
                    <a href="/onetime_login">戻る</a>
                </div>
            </body>
            </html>
            '''
            return render_template_string(html)
        
        # ワンタイムコードを使用済みにマーク
        db_helper.mark_onetime_used(code)
        
        try:
            # Google OAuth認証フローを開始
            SCOPES = ['https://www.googleapis.com/auth/calendar']
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            
            # 認証URLを生成（リダイレクトURIを設定）
            flow.redirect_uri = request.url_root.rstrip('/') + '/oauth2callback'
            auth_url, _ = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true'
            )
            
            # セッションにLINEユーザーIDとフロー情報を保存
            session['line_user_id'] = line_user_id
            session['flow'] = pickle.dumps(flow)
            
            return redirect(auth_url)
            
        except Exception as e:
            logging.error(f"Google OAuth認証エラー: {e}")
            html = '''
            <!DOCTYPE html>
            <html>
            <head>
                <title>認証エラー</title>
                <meta charset="utf-8">
                <style>
                    body { font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto; padding: 20px; }
                    .error { color: red; margin: 20px 0; }
                </style>
            </head>
            <body>
                <h1>認証エラー</h1>
                <div class="error">
                    Google認証の初期化に失敗しました。<br>
                    しばらく時間をおいて再度お試しください。
                </div>
            </body>
            </html>
            '''
            return render_template_string(html)

@app.route('/oauth2callback')
def oauth2callback():
    """Google OAuth認証コールバック"""
    try:
        # セッションから情報を取得
        line_user_id = session.get('line_user_id')
        flow_data = session.get('flow')
        
        if not line_user_id or not flow_data:
            return "認証セッションが無効です", 400
        
        flow = pickle.loads(flow_data)
        
        # 認証コードを取得してトークンを交換
        flow.fetch_token(authorization_response=request.url)
        credentials = flow.credentials
        
        # トークンをDBに保存
        token_data = pickle.dumps(credentials)
        db_helper.save_user_token(line_user_id, token_data)
        
        # セッションをクリア
        session.pop('line_user_id', None)
        session.pop('flow', None)
        
        html = '''
        <!DOCTYPE html>
        <html>
        <head>
            <title>認証完了</title>
            <meta charset="utf-8">
            <style>
                body { font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto; padding: 20px; text-align: center; }
                .success { color: green; margin: 20px 0; }
                .message { margin: 20px 0; }
            </style>
        </head>
        <body>
            <h1>認証完了</h1>
            <div class="success">
                ✅ Google Calendar認証が完了しました！
            </div>
            <div class="message">
                LINE BotでGoogle Calendar機能をご利用いただけます。<br>
                このページは閉じて、LINEに戻ってください。
            </div>
        </body>
        </html>
        '''
        return render_template_string(html)
        
    except Exception as e:
        logging.error(f"OAuth2コールバックエラー: {e}")
        html = '''
        <!DOCTYPE html>
        <html>
        <head>
            <title>認証エラー</title>
            <meta charset="utf-8">
            <style>
                body { font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto; padding: 20px; }
                .error { color: red; margin: 20px 0; }
            </style>
            </head>
            <body>
                <h1>認証エラー</h1>
                <div class="error">
                    認証処理中にエラーが発生しました。<br>
                    しばらく時間をおいて再度お試しください。
                </div>
            </body>
            </html>
        '''
        return render_template_string(html)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info("LINE Calendar Bot を起動しています...")
    app.run(debug=True, host='0.0.0.0', port=port) 