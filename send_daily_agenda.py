from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from calendar_service import GoogleCalendarService
from db import DBHelper
from linebot import LineBotApi
from linebot.models import TextSendMessage
from config import Config
import logging
logging.basicConfig(level=logging.INFO)

JST = ZoneInfo("Asia/Tokyo")

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
    logging.info(f"[DEBUG] 日次予定送信開始: {datetime.now(JST)}")
    db = DBHelper()
    calendar_service = GoogleCalendarService()
    line_bot_api = LineBotApi(Config.LINE_CHANNEL_ACCESS_TOKEN)
    
    # JST基準で「明日」
    now_jst = datetime.now(JST)
    target_date = (now_jst + timedelta(days=1)).date().isoformat()  # 'YYYY-MM-DD'
    logging.info(f"[DEBUG] 明日の日付(JST): {target_date}")
    
    user_ids = db.get_all_user_ids()  # 認証済みユーザーのみ
    logging.info(f"[DEBUG] 送信対象ユーザー: {user_ids}")

    for user_id in user_ids:
        try:
            # 二重送信チェック
            if db.daily_send_already_sent(user_id, target_date):
                logging.info(f"[DEBUG] ユーザー {user_id} は既に送信済み（{target_date}）、スキップ")
                continue
            
            tomorrow = datetime.fromisoformat(target_date).date()
            events_info = calendar_service.get_events_for_dates([tomorrow], user_id)
            logging.info(f"[DEBUG] ユーザー: {user_id} の取得した予定: {events_info}")
            message = format_rich_agenda(events_info, is_tomorrow=True)
            logging.info(f"[DEBUG] 送信先: {user_id}, メッセージ: {message}")
            line_bot_api.push_message(user_id, TextSendMessage(text=message))
            
            # 送信済みマーク
            db.mark_daily_sent(user_id, target_date)
            logging.info(f"[DEBUG] ユーザー {user_id} への送信完了")
        except Exception as e:
            logging.error(f"[ERROR] ユーザー {user_id} への送信中にエラー: {e}")
            # 認証エラー時はLINEで再認証案内を送信
            onetime_code = db.generate_onetime_code(user_id)
            import os
            base_url = os.getenv('BASE_URL', 'https://task-bot-production.up.railway.app')
            auth_message = (
                "Googleカレンダー連携の認証が切れています。\n"
                "下記URLから再認証をお願いします。\n\n"
                f"🔐 ワンタイムコード: {onetime_code}\n\n"
                f"{base_url}/onetime_login\n"
                "（上記ページでワンタイムコードを入力してください）"
            )
            try:
                line_bot_api.push_message(user_id, TextSendMessage(text=auth_message))
                logging.info(f"[DEBUG] ユーザー {user_id} に再認証案内を送信（ワンタイムコード付き）")
            except Exception as e2:
                logging.error(f"[ERROR] ユーザー {user_id} への再認証案内送信エラー: {e2}")
    
    logging.info(f"[DEBUG] 日次予定送信完了: {datetime.now(JST)}")

if __name__ == "__main__":
    send_daily_agenda() 