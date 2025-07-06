from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from datetime import datetime, timedelta
from dateutil import parser
import pytz
from calendar_service import GoogleCalendarService
from ai_service import AIService
from config import Config
from db import DBHelper
import logging

logger = logging.getLogger("line_bot_handler")

class LineBotHandler:
    def __init__(self):
        # 一時的にダミー値を設定
        line_token = Config.LINE_CHANNEL_ACCESS_TOKEN or "dummy_token"
        line_secret = Config.LINE_CHANNEL_SECRET or "dummy_secret"
        
        self.line_bot_api = LineBotApi(line_token)
        self.handler = WebhookHandler(line_secret)
        
        # DBヘルパーの初期化
        self.db_helper = DBHelper()
        
        try:
            self.calendar_service = GoogleCalendarService()
        except Exception as e:
            print(f"Google Calendarサービス初期化エラー: {e}")
            self.calendar_service = None
            
        try:
            self.ai_service = AIService()
        except Exception as e:
            print(f"AIサービス初期化エラー: {e}")
            self.ai_service = None
            
        self.jst = pytz.timezone('Asia/Tokyo')
    
    def _check_user_auth(self, line_user_id):
        """ユーザーの認証状態をチェック"""
        return self.db_helper.user_exists(line_user_id)
    
    def _send_auth_guide(self, line_user_id):
        """認証案内メッセージを送信"""
        # ワンタイムコードを生成
        code = self.db_helper.generate_onetime_code(line_user_id)
        
        # 認証URLを生成（RailwayのURLを使用）
        base_url = "https://task-bot-production.up.railway.app"  # 実際のRailway URLに変更
        auth_url = f"{base_url}/onetime_login"
        
        message = f"""Google Calendar認証が必要です。

🔐 ワンタイムコード: {code}

📱 認証手順:
1. 下のURLをクリックまたはコピー
2. ワンタイムコードを入力
3. Googleアカウントで認証

🔗 認証URL:
{auth_url}

⚠️ コードの有効期限は10分です
"""
        return TextSendMessage(text=message)
    
    def handle_message(self, event):
        """メッセージを処理します"""
        user_message = event.message.text
        line_user_id = event.source.user_id
        
        try:
            # 環境変数が設定されていない場合の処理
            if not Config.LINE_CHANNEL_ACCESS_TOKEN or not Config.LINE_CHANNEL_SECRET:
                return TextSendMessage(text="LINE Botの設定が完了していません。環境変数を設定してください。")
            
            if not self.ai_service:
                return TextSendMessage(text="AIサービスの初期化に失敗しました。OpenAI APIキーを設定してください。")
            
            # AIを使ってメッセージの意図を判断
            ai_result = self.ai_service.extract_dates_and_times(user_message)
            print(f"[DEBUG] ai_result: {ai_result}")
            
            if 'error' in ai_result:
                # AI処理に失敗した場合、直接イベント追加を試行
                return self._handle_event_addition(user_message, line_user_id)
            
            # タスクタイプに基づいて処理
            task_type = ai_result.get('task_type', 'add_event')
            
            if task_type == 'availability_check':
                print(f"[DEBUG] dates_info: {ai_result.get('dates', [])}")
                return self._handle_availability_check(ai_result.get('dates', []), line_user_id)
            else:
                return self._handle_event_addition(user_message, line_user_id)
            
        except Exception as e:
            return TextSendMessage(text=f"エラーが発生しました: {str(e)}")
    
    def _handle_availability_check(self, dates_info, line_user_id):
        """空き時間確認を処理します"""
        try:
            # ユーザーの認証状態をチェック
            if not self._check_user_auth(line_user_id):
                return self._send_auth_guide(line_user_id)
            
            if not self.calendar_service:
                return TextSendMessage(text="Google Calendarサービスが初期化されていません。認証ファイルを確認してください。")
            if not dates_info:
                return TextSendMessage(text="日付を正しく認識できませんでした。\n\n例: 「明日7/7 15:00〜15:30の空き時間を教えて」")
            free_slots_by_date = {}
            for date_info in dates_info:
                date_str = date_info.get('date')
                start_time = date_info.get('time')
                end_time = date_info.get('end_time')
                if date_str and start_time and end_time:
                    jst = pytz.timezone('Asia/Tokyo')
                    start_dt = jst.localize(datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M"))
                    end_dt = jst.localize(datetime.strptime(f"{date_str} {end_time}", "%Y-%m-%d %H:%M"))
                    # 枠内の予定を取得
                    events = self.calendar_service.get_events_for_time_range(start_dt, end_dt, line_user_id)
                    # 枠内の空き時間を抽出
                    free_slots = self.calendar_service.find_free_slots_for_day(start_dt.date(), events, day_start=start_time, day_end=end_time, line_user_id=line_user_id)
                    free_slots_by_date[date_str] = free_slots
            response_text = self.ai_service.format_free_slots_response(free_slots_by_date)
            return TextSendMessage(text=response_text)
        except Exception as e:
            return TextSendMessage(text=f"空き時間確認でエラーが発生しました: {str(e)}")
    
    def _handle_event_addition(self, user_message, line_user_id):
        """イベント追加を処理します"""
        try:
            # ユーザーの認証状態をチェック
            if not self._check_user_auth(line_user_id):
                return self._send_auth_guide(line_user_id)
            
            if not self.calendar_service:
                return TextSendMessage(text="Google Calendarサービスが初期化されていません。認証ファイルを確認してください。")
            
            # AIを使ってイベント情報を抽出
            event_info = self.ai_service.extract_event_info(user_message)
            
            if 'error' in event_info:
                return TextSendMessage(text="イベント情報を正しく認識できませんでした。\n\n例: 「明日の午前9時から会議を追加して」\n「来週月曜日の14時から打ち合わせ」")
            
            # 日時をパース
            start_datetime = parser.parse(event_info['start_datetime'])
            end_datetime = parser.parse(event_info['end_datetime'])
            
            # タイムゾーンを設定
            start_datetime = self.jst.localize(start_datetime)
            end_datetime = self.jst.localize(end_datetime)
            
            # カレンダーにイベントを追加
            success, message, result = self.calendar_service.add_event(
                event_info['title'],
                start_datetime,
                end_datetime,
                event_info.get('description', '')
            )
            logger.info(f"[DEBUG] add_event result: success={success}, message={message}, result={result}")
            
            # AIを使ってレスポンスをフォーマット
            response_text = self.ai_service.format_event_confirmation(success, message, result)
            
            return TextSendMessage(text=response_text)
            
        except Exception as e:
            return TextSendMessage(text=f"イベント追加でエラーが発生しました: {str(e)}")
    
    def get_handler(self):
        """WebhookHandlerを取得します"""
        return self.handler 