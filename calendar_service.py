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

class GoogleCalendarService:
    def __init__(self):
        self.SCOPES = ['https://www.googleapis.com/auth/calendar']
        self.creds = None
        self.service = None
        self._authenticate()
    
    def _authenticate(self):
        """Google Calendar APIの認証を行います"""
        # トークンファイルが存在する場合は読み込み
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                self.creds = pickle.load(token)
        
        # 有効な認証情報がない場合は認証フローを実行
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', self.SCOPES)
                self.creds = flow.run_local_server(port=0)
            
            # 認証情報を保存
            with open('token.pickle', 'wb') as token:
                pickle.dump(self.creds, token)
        
        self.service = build('calendar', 'v3', credentials=self.creds)
    
    def check_availability(self, start_time, end_time):
        """指定された時間帯の空き時間を確認します"""
        try:
            # ISO文字列がタイムゾーン付きかどうかでZを付与しない
            def iso_no_z(dt):
                s = dt.isoformat()
                return s if s.endswith(('+09:00', '+00:00', '-00:00')) else s + 'Z'
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
    
    def add_event(self, title, start_time, end_time, description=""):
        """カレンダーにイベントを追加します"""
        try:
            print(f"[DEBUG] add_event: title={title}, start={start_time}, end={end_time}, desc={description}")
            # まず空き時間をチェック
            is_available, result = self.check_availability(start_time, end_time)
            print(f"[DEBUG] check_availability: is_available={is_available}, result={result}")
            if is_available is False:
                # 既存の予定がある場合
                print(f"[DEBUG] 既存の予定があるため追加しません: {result}")
                return False, "✅既に予定が入っています", result
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
            print(f"[DEBUG] Google Calendar APIへイベント追加リクエスト: {event}")
            # イベントを追加
            event = self.service.events().insert(
                calendarId=Config.GOOGLE_CALENDAR_ID,
                body=event
            ).execute()
            print(f"[DEBUG] Google Calendar APIレスポンス: {event}")
            return True, "✅予定を追加しました", {
                'title': title,
                'start': start_time.isoformat(),
                'end': end_time.isoformat()
            }
        except Exception as e:
            print(f"[ERROR] add_eventで例外発生: {e}")
            return False, f"エラーが発生しました: {str(e)}", None
    
    def get_events_for_dates(self, dates):
        """指定された日付のイベントを取得します"""
        events_info = []
        
        for date in dates:
            start_of_day = datetime.combine(date, datetime.min.time())
            end_of_day = start_of_day + timedelta(days=1)
            
            try:
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
    
    def get_events_for_time_range(self, start_time, end_time):
        """指定された時間範囲のイベントを取得します"""
        try:
            events_result = self.service.events().list(
                calendarId=Config.GOOGLE_CALENDAR_ID,
                timeMin=start_time.isoformat() + 'Z',
                timeMax=end_time.isoformat() + 'Z',
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
            return []
    
    def find_free_slots_for_day(self, date, events, day_start="08:00", day_end="22:00"):
        """
        指定日のイベントリストから空き時間帯を抽出します。
        - date: datetime.date オブジェクト
        - events: [{"start": iso, "end": iso, ...}]
        - day_start, day_end: 営業時間帯（デフォルト8:00-22:00）
        戻り値: [(start_time, end_time), ...] いずれもdatetime
        """
        jst = pytz.timezone('Asia/Tokyo')
        day = date
        start_of_day = jst.localize(datetime.combine(day, datetime.strptime(day_start, "%H:%M").time()))
        end_of_day = jst.localize(datetime.combine(day, datetime.strptime(day_end, "%H:%M").time()))
        # イベントを開始時刻でソート
        sorted_events = sorted(events, key=lambda e: e['start'])
        free_slots = []
        current = start_of_day
        for event in sorted_events:
            event_start = parser.parse(event['start']).astimezone(jst)
            event_end = parser.parse(event['end']).astimezone(jst)
            if current < event_start:
                free_slots.append((current, event_start))
            current = max(current, event_end)
        if current < end_of_day:
            free_slots.append((current, end_of_day))
        return free_slots 