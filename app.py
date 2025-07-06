import os
# Railway環境でcredentials.jsonを書き出す
if "GOOGLE_CREDENTIALS_FILE" in os.environ:
    with open("credentials.json", "w") as f:
        f.write(os.environ["GOOGLE_CREDENTIALS_FILE"])

from flask import Flask, request, abort
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from line_bot_handler import LineBotHandler
from config import Config
import logging

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = Config.FLASK_SECRET_KEY

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info("LINE Calendar Bot を起動しています...")
    app.run(debug=True, host='0.0.0.0', port=port) 