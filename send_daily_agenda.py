from datetime import datetime
from calendar_service import GoogleCalendarService
from db import DBHelper
from linebot import LineBotApi
from linebot.models import TextSendMessage
from config import Config

def format_rich_agenda(events_info):
    if not events_info or not events_info[0]['events']:
        return "✅今日の予定はありません！"

    date = events_info[0]['date']
    dt = datetime.strptime(date, "%Y-%m-%d")
    weekday = "月火水木金土日"[dt.weekday()]
    header = f"✅今日の予定です！\n\n📅 {dt.strftime('%Y/%m/%d')} ({weekday})\n━━━━━━━━━━"
    lines = []
    for i, event in enumerate(events_info[0]['events'], 1):
        title = event['title']
        start = datetime.fromisoformat(event['start']).strftime('%H:%M')
        end = datetime.fromisoformat(event['end']).strftime('%H:%M')
        lines.append(f"{i}. {title}\n⏰ {start}～{end}\n")
    footer = "━━━━━━━━━━"
    return f"{header}\n" + "\n".join(lines) + footer

def send_daily_agenda():
    db = DBHelper()
    calendar_service = GoogleCalendarService()
    line_bot_api = LineBotApi(Config.LINE_CHANNEL_ACCESS_TOKEN)
    today = datetime.now().date()
    user_ids = db.get_all_user_ids()  # 認証済みユーザーのみ返すようにDBHelperを調整
    print(f"[DEBUG] 送信対象ユーザー: {user_ids}")

    for user_id in user_ids:
        events_info = calendar_service.get_events_for_dates([today])
        message = format_rich_agenda(events_info)
        print(f"[DEBUG] 送信先: {user_id}, メッセージ: {message}")
        line_bot_api.push_message(user_id, TextSendMessage(text=message))

if __name__ == "__main__":
    send_daily_agenda() 