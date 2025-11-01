from datetime import datetime, timedelta
import pytz
from calendar_service import GoogleCalendarService
from db import DBHelper
from linebot import LineBotApi
from linebot.models import TextSendMessage
from config import Config
import logging
logging.basicConfig(level=logging.INFO)

# JSTタイムゾーン
JST = pytz.timezone('Asia/Tokyo')

def format_rich_agenda(events_info, is_tomorrow=False):
    if not events_info or not events_info[0]['events']:
        return "✅明日の予定はありません！" if is_tomorrow else "✅今日の予定はありません！"

    date = events_info[0]['date']
    dt = datetime.strptime(date, "%Y-%m-%d")
    weekday = "月火水木金土日"[dt.weekday()]
    header = f"✅明日の予定です！\n\n📅 {dt.strftime('%Y/%m/%d')} ({weekday})\n━━━━━━━━━━" if is_tomorrow else f"✅今日の予定です！\n\n📅 {dt.strftime('%Y/%m/%d')} ({weekday})\n━━━━━━━━━━"
    lines = []
    for i, event in enumerate(events_info[0]['events'], 1):
        title = event['title']
        start = datetime.fromisoformat(event['start']).strftime('%H:%M')
        end = datetime.fromisoformat(event['end']).strftime('%H:%M')
        lines.append(f"{i}. {title}\n⏰ {start}～{end}\n")
    footer = "━━━━━━━━━━"
    return f"{header}\n" + "\n".join(lines) + footer

def send_daily_agenda():
    """明日の予定を全ユーザーに配信（二重送信防止付き、JST基準）"""
    logging.info(f"日次予定送信開始")
    db = DBHelper()
    calendar_service = GoogleCalendarService()
    line_bot_api = LineBotApi(Config.LINE_CHANNEL_ACCESS_TOKEN)
    
    # JST基準で「明日」を取得
    now_jst = datetime.now(JST)
    tomorrow = now_jst + timedelta(days=1)
    target_date = tomorrow.date().isoformat()  # 'YYYY-MM-DD'
    logging.info(f"対象日: {target_date}")
    
    user_ids = db.get_all_user_ids()
    logging.info(f"送信対象ユーザー数: {len(user_ids)}")

    for user_id in user_ids:
        try:
            # 二重送信チェック
            if db.already_sent_daily(user_id, target_date):
                logging.info(f"ユーザー {user_id} は既に配信済み: {target_date}")
                continue
            
            # 予定取得
            events_info = calendar_service.get_events_for_dates([tomorrow.date()], user_id)
            logging.info(f"ユーザー {user_id} の取得した予定: {events_info}")
            
            # メッセージ生成
            message = format_rich_agenda(events_info, is_tomorrow=True)
            logging.info(f"送信先: {user_id}, メッセージ長: {len(message)}")
            
            # 送信
            line_bot_api.push_message(user_id, TextSendMessage(text=message))
            
            # 送信完了をマーク
            db.mark_daily_sent(user_id, target_date)
            logging.info(f"ユーザー {user_id} への送信完了")
            
        except Exception as e:
            logging.exception(f"ユーザー {user_id} への送信中にエラー: {e}")
            # 認証エラー時は再認証案内を送信
            try:
                onetime_code = db.generate_onetime_code(user_id)
                auth_message = (
                    "Googleカレンダー連携の認証が切れています。\n"
                    "下記URLから再認証をお願いします。\n\n"
                    f"🔐 ワンタイムコード: {onetime_code}\n\n"
                    "https://task-bot-production.up.railway.app/onetime_login\n"
                    "（上記ページでワンタイムコードを入力してください）"
                )
                line_bot_api.push_message(user_id, TextSendMessage(text=auth_message))
                logging.info(f"ユーザー {user_id} に再認証案内を送信")
            except Exception as e2:
                logging.exception(f"ユーザー {user_id} への再認証案内送信エラー: {e2}")
    
    logging.info("日次予定送信完了")

if __name__ == "__main__":
    send_daily_agenda() 