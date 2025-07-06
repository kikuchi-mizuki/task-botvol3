from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import os
import pickle
import pytz
from config import Config
from dateutil import parser
from db import DBHelper
import logging

logger = logging.getLogger("calendar_service")
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

class GoogleCalendarService:
    def __init__(self):
        self.SCOPES = ['https://www.googleapis.com/auth/calendar']
        self.db_helper = DBHelper()
        self.creds = None
        self.service = None
        self._authenticate()
    
    def _authenticate(self):
        """Google Calendar APIの認証を行います"""
        # トークンファイルが存在する場合は読み込み
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                self.creds = pickle.load(token)
        # 有効な認証情報がない場合はWebフローで認証する（run_local_serverは呼ばない）
        if self.creds and self.creds.expired and self.creds.refresh_token:
            self.creds.refresh(Request())
        if self.creds:
            self.service = build('calendar', 'v3', credentials=self.creds)
        else:
            self.service = None  # 認証情報がなければserviceはNoneのまま
    
    def _get_user_credentials(self, line_user_id):
        """ユーザーの認証トークンをDBから取得"""
        token_data = self.db_helper.get_google_token(line_user_id)
        if not token_data:
            return None
        
        try:
            credentials = pickle.loads(token_data)
            
            # トークンの有効期限をチェック
            if credentials and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                # 更新されたトークンをDBに保存
                updated_token_data = pickle.dumps(credentials)
                self.db_helper.save_google_token(line_user_id, updated_token_data)
            
            return credentials
        except Exception as e:
            print(f"トークンの読み込みエラー: {e}")
            return None
    
    def _get_calendar_service(self, line_user_id):
        """ユーザーごとのGoogle Calendarサービスを取得"""
        credentials = self._get_user_credentials(line_user_id)
        if not credentials:
            raise Exception("ユーザーの認証トークンが見つかりません。認証を完了してください。")
        
        return build('calendar', 'v3', credentials=credentials)
    
    def check_availability(self, start_time, end_time):
        """指定された時間帯の空き時間を確認します"""
        try:
            if not self.service:
                return None, "Google認証が必要です。"
            # ISO文字列がタイムゾーン付きかどうかでZを付与しない
            def iso_no_z(dt):
                s = dt.isoformat()
                return s if s.endswith(("+09:00", "+00:00", "-0")) else s + "Z"
            # 指定された時間帯のイベントを取得
            events_result = self.service.events().list(
                calendarId=Config.GOOGLE_CALENDAR_ID,
                timeMin=iso_no_z(start_time),
                timeMax=iso_no_z(end_time),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])
            if not events:
                return True, "指定された時間帯は空いています。"
            # 既存のイベント情報を取得
            existing_events = []
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                title = event.get('summary', 'タイトルなし')
                existing_events.append({
                    'title': title,
                    'start': start,
                    'end': end
                })
            return False, existing_events
        except Exception as e:
            return None, f"エラーが発生しました: {str(e)}"
    
    def add_event(self, title, start_time, end_time, description="", line_user_id=None):
        """カレンダーにイベントを追加します"""
        try:
            if not line_user_id:
                return False, "ユーザーIDが必要です", None
            
            service = self._get_calendar_service(line_user_id)
            
            # 既存の予定をチェック
            events = self.get_events_for_time_range(start_time, end_time, line_user_id)
            logger.info(f"[DEBUG] add_event: 追加前に取得したevents = {events}")
            if events:
                conflicting_events = []
                for event in events:
                    conflicting_events.append({
                        'title': event.get('summary', '予定なし'),
                        'start': event['start'].get('dateTime', event['start'].get('date')),
                        'end': event['end'].get('dateTime', event['end'].get('date'))
                    })
                logger.info(f"[DEBUG] 既存の予定があるため追加しません: {conflicting_events}")
                return False, "指定された時間に既存の予定があります", conflicting_events
            
            # イベントを作成
            event = {
                'summary': title,
                'description': description,
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'Asia/Tokyo',
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'Asia/Tokyo',
                },
            }
            logger.info(f"[DEBUG] Google Calendar APIへイベント追加リクエスト: {event}")
            # イベントを追加
            event = service.events().insert(
                calendarId=Config.GOOGLE_CALENDAR_ID,
                body=event
            ).execute()
            logger.info(f"[DEBUG] Google Calendar APIレスポンス: {event}")
            return True, "✅予定を追加しました", {
                'title': title,
                'start': start_time.isoformat(),
                'end': end_time.isoformat()
            }
        except Exception as e:
            logger.error(f"[ERROR] add_eventで例外発生: {e}")
            return False, f"エラーが発生しました: {str(e)}", None
    
    def get_events_for_dates(self, dates):
        """指定された日付のイベントを取得します"""
        events_info = []
        
        for date in dates:
            start_of_day = datetime.combine(date, datetime.min.time())
            end_of_day = start_of_day + timedelta(days=1)
            
            try:
                if not self.service:
                    events_info.append({
                        'date': date.strftime('%Y-%m-%d'),
                        'events': [],
                        'error': 'Google認証が必要です。'
                    })
                    continue
                events_result = self.service.events().list(
                    calendarId=Config.GOOGLE_CALENDAR_ID,
                    timeMin=start_of_day.isoformat() + 'Z',
                    timeMax=end_of_day.isoformat() + 'Z',
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()
                
                events = events_result.get('items', [])
                
                if events:
                    day_events = []
                    for event in events:
                        start = event['start'].get('dateTime', event['start'].get('date'))
                        end = event['end'].get('dateTime', event['end'].get('date'))
                        title = event.get('summary', 'タイトルなし')
                        day_events.append({
                            'title': title,
                            'start': start,
                            'end': end
                        })
                    events_info.append({
                        'date': date.strftime('%Y-%m-%d'),
                        'events': day_events
                    })
                else:
                    events_info.append({
                        'date': date.strftime('%Y-%m-%d'),
                        'events': []
                    })
                    
            except Exception as e:
                events_info.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'error': str(e)
                })
        
        return events_info
    
    def get_events_for_time_range(self, start_time, end_time, line_user_id):
        """指定された時間範囲のイベントを取得します"""
        try:
            service = self._get_calendar_service(line_user_id)
            
            # タイムゾーンをUTCに変換
            utc_start = start_time.astimezone(pytz.UTC)
            utc_end = end_time.astimezone(pytz.UTC)
            
            events_result = service.events().list(
                calendarId=Config.GOOGLE_CALENDAR_ID,
                timeMin=utc_start.isoformat(),
                timeMax=utc_end.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            if not events:
                return []
            
            event_list = []
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                title = event.get('summary', 'タイトルなし')
                event_list.append({
                    'title': title,
                    'start': start,
                    'end': end
                })
            
            return event_list
            
        except Exception as e:
            logging.error(f"イベント取得エラー: {e}")
            return []
    
    def find_free_slots_for_day(self, date, events, day_start="09:00", day_end="18:00", line_user_id=None):
        """指定日の枠内で既存予定を除いた空き時間帯リストを返す"""
        try:
            # 枠の開始・終了時刻
            day_start_dt = datetime.combine(date, datetime.strptime(day_start, "%H:%M").time())
            day_end_dt = datetime.combine(date, datetime.strptime(day_end, "%H:%M").time())
            jst = pytz.timezone('Asia/Tokyo')
            day_start_dt = jst.localize(day_start_dt)
            day_end_dt = jst.localize(day_end_dt)
            # eventsがNoneや空の場合は必ず再取得
            if (events is None or len(events) == 0) and line_user_id:
                events = self.get_events_for_time_range(day_start_dt, day_end_dt, line_user_id)
                logger.info(f"[DEBUG] find_free_slots_for_day: 再取得したevents = {events}")
            # 既存予定を時間順にbusy_timesへ
            busy_times = []
            for event in events:
                start = event['start'] if isinstance(event['start'], str) else event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'] if isinstance(event['end'], str) else event['end'].get('dateTime', event['end'].get('date'))
                if 'T' in start:  # dateTime形式
                    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                    # 枠外の予定は除外
                    if end_dt <= day_start_dt or start_dt >= day_end_dt:
                        continue
                    # 枠内に収める
                    busy_times.append((max(start_dt, day_start_dt), min(end_dt, day_end_dt)))
            # 空き時間を計算
            free_slots = []
            current_time = day_start_dt
            for busy_start, busy_end in sorted(busy_times):
                if current_time < busy_start:
                    free_slots.append({
                        'start': current_time.strftime('%H:%M'),
                        'end': busy_start.strftime('%H:%M')
                    })
                current_time = max(current_time, busy_end)
            if current_time < day_end_dt:
                free_slots.append({
                    'start': current_time.strftime('%H:%M'),
                    'end': day_end_dt.strftime('%H:%M')
                })
            return free_slots
        except Exception as e:
            logger.error(f"空き時間検索エラー: {e}")
            return [] 