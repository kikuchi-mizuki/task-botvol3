from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from datetime import datetime, timedelta
from dateutil import parser
import pytz
import re
from calendar_service import GoogleCalendarService
from ai_service import AIService
from config import Config
from db import DBHelper
import logging

logger = logging.getLogger("line_bot_handler")

class LineBotHandler:
    def __init__(self):
        # LINE Bot API クライアント初期化（標準）
        if not Config.LINE_CHANNEL_ACCESS_TOKEN:
            raise ValueError("LINE_CHANNEL_ACCESS_TOKEN environment variable is not set")
        if not Config.LINE_CHANNEL_SECRET:
            raise ValueError("LINE_CHANNEL_SECRET environment variable is not set")
            
        self.line_bot_api = LineBotApi(Config.LINE_CHANNEL_ACCESS_TOKEN)
        self.handler = WebhookHandler(Config.LINE_CHANNEL_SECRET)
        
        # カスタムセッション設定をグローバルに適用
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        # リトライ戦略を設定（より詳細な設定）
        retry_strategy = Retry(
            total=5,  # 最大リトライ回数を増加
            backoff_factor=2,  # バックオフ係数を増加
            status_forcelist=[429, 500, 502, 503, 504, 520, 521, 522, 523, 524],  # リトライするHTTPステータスコードを拡張
            allowed_methods=["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE", "POST"],  # 全HTTPメソッドでリトライ
            raise_on_status=False,  # ステータスエラーで例外を発生させない
        )
        
        # アダプターを設定
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
        
        # グローバルセッション設定
        session = requests.Session()
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.timeout = (15, 45)  # (接続タイムアウト, 読み取りタイムアウト) を増加
        
        # LINE Bot SDKの内部セッションを置き換え
        self.line_bot_api._session = session
        
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
        
        # 認証URLを生成（環境変数から取得）
        import os
        base_url = os.getenv('BASE_URL', 'https://web-production-xxxx.up.railway.app')
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

        # Google認証未完了なら必ず認証案内を返す
        if not self._check_user_auth(line_user_id):
            return self._send_auth_guide(line_user_id)

        # 「はい」返答による強制追加判定
        if user_message.strip() in ["はい", "追加", "OK", "Yes", "yes"]:
            pending_json = self.db_helper.get_pending_event(line_user_id)
            if pending_json:
                import json
                events_data = json.loads(pending_json)
                
                # 単一イベントか複数イベントかを判定
                if isinstance(events_data, list):
                    # 複数イベント（移動時間含む）の場合
                    added_events = []
                    failed_events = []
                    
                    for event_info in events_data:
                        try:
                            from dateutil import parser
                            start_datetime = parser.parse(event_info['start_datetime'])
                            end_datetime = parser.parse(event_info['end_datetime'])
                            
                            # 既にタイムゾーンが設定されている場合はそのまま使用、そうでなければJSTを設定
                            if start_datetime.tzinfo is None:
                                start_datetime = self.jst.localize(start_datetime)
                            if end_datetime.tzinfo is None:
                                end_datetime = self.jst.localize(end_datetime)
                            
                            if not self.calendar_service:
                                failed_events.append({
                                    'title': event_info['title'],
                                    'reason': 'カレンダーサービスが初期化されていません'
                                })
                                continue
                            
                            success, message, result = self.calendar_service.add_event(
                                event_info['title'],
                                start_datetime,
                                end_datetime,
                                event_info.get('description', ''),
                                line_user_id=line_user_id,
                                force_add=True
                            )
                            
                            if success:
                                # 日時をフォーマット
                                from datetime import datetime
                                import pytz
                                jst = pytz.timezone('Asia/Tokyo')
                                start_dt = start_datetime.astimezone(jst)
                                end_dt = end_datetime.astimezone(jst)
                                weekday = "月火水木金土日"[start_dt.weekday()]
                                date_str = f"{start_dt.month}/{start_dt.day}（{weekday}）"
                                time_str = f"{start_dt.strftime('%H:%M')}〜{end_dt.strftime('%H:%M')}"
                                
                                added_events.append({
                                    'title': event_info['title'],
                                    'time': f"{date_str}{time_str}"
                                })
                            else:
                                failed_events.append({
                                    'title': event_info['title'],
                                    'reason': message
                                })
                        except Exception as e:
                            failed_events.append({
                                'title': event_info.get('title', '予定'),
                                'reason': str(e)
                            })
                    
                    self.db_helper.delete_pending_event(line_user_id)
                    
                    # 結果メッセージを構築（移動時間を含む場合は統一形式）
                    if added_events:
                        # 移動時間が含まれているかチェック
                        has_travel = any('移動時間' in event['title'] for event in added_events)
                        
                        if has_travel and len(added_events) > 1:
                            # 移動時間を含む場合は統一形式で表示
                            response_text = "✅予定を追加しました！\n\n"
                            
                            # 日付を取得（最初の予定から）
                            first_event = added_events[0]
                            time_str = first_event['time']
                            # "10/18 (土)19:00〜20:00" から "10/18 (土)" を抽出
                            date_match = re.search(r'(\d{1,2}/\d{1,2}\s*\([月火水木金土日]\)\s*)', time_str)
                            date_part = date_match.group(1).strip() if date_match else time_str
                            response_text += f"{date_part}\n"
                            response_text += "────────\n"
                            
                            # 時間順でソート（開始時間でソート）
                            def get_start_time(event):
                                time_str = event['time']
                                # "10/18 (土)19:00〜20:00" から "19:00〜20:00" を抽出
                                time_match = re.search(r'(\d{1,2}:\d{2}〜\d{1,2}:\d{2})', time_str)
                                time_part = time_match.group(1) if time_match else time_str
                                start_time = time_part.split('〜')[0]  # "19:00〜20:00" -> "19:00"
                                return start_time
                            
                            sorted_events = sorted(added_events, key=get_start_time)
                            
                            # 各予定を番号付きで表示
                            for i, event in enumerate(sorted_events, 1):
                                # 時間部分を抽出（"10:00~11:00" の形式）
                                time_str = event['time']
                                time_match = re.search(r'(\d{1,2}:\d{2}〜\d{1,2}:\d{2})', time_str)
                                time_part = time_match.group(1) if time_match else time_str
                                response_text += f"{i}. {event['title']}\n"
                                response_text += f"🕐 {time_part}\n"
                            
                            response_text += "────────"
                        else:
                            # 通常の表示形式
                            response_text = "✅予定を追加しました！\n\n"
                            for event in added_events:
                                response_text += f"📅{event['title']}\n{event['time']}\n"
                        
                        if failed_events:
                            response_text += "\n\n⚠️追加できなかった予定:\n"
                            for event in failed_events:
                                response_text += f"• {event['title']} - {event['reason']}\n"
                    else:
                        response_text = "❌予定を追加できませんでした。\n\n"
                        for event in failed_events:
                            response_text += f"• {event['title']} - {event['reason']}\n"
                    
                    return TextSendMessage(text=response_text)
                else:
                    # 単一イベントの場合（従来の処理）
                    event_info = events_data
                    from dateutil import parser
                    start_datetime = parser.parse(event_info['start_datetime'])
                    end_datetime = parser.parse(event_info['end_datetime'])
                    # 既にタイムゾーンが設定されている場合はそのまま使用、そうでなければJSTを設定
                    if start_datetime.tzinfo is None:
                        start_datetime = self.jst.localize(start_datetime)
                    if end_datetime.tzinfo is None:
                        end_datetime = self.jst.localize(end_datetime)
                    if not self.calendar_service or not self.ai_service:
                        return TextSendMessage(text="カレンダーサービスまたはAIサービスが初期化されていません。")
                    success, message, result = self.calendar_service.add_event(
                        event_info['title'],
                        start_datetime,
                        end_datetime,
                        event_info.get('description', ''),
                        line_user_id=line_user_id,
                        force_add=True
                    )
                    self.db_helper.delete_pending_event(line_user_id)
                    response_text = self.ai_service.format_event_confirmation(success, message, result)
                    return TextSendMessage(text=response_text)
        else:
            # 「はい」以外の返答でpending_eventsがあれば削除し、キャンセルメッセージを返す
            pending_json = self.db_helper.get_pending_event(line_user_id)
            if pending_json:
                self.db_helper.delete_pending_event(line_user_id)
                return TextSendMessage(text="予定追加をキャンセルしました。")
        
        try:
            # 環境変数が設定されていない場合の処理
            if not Config.LINE_CHANNEL_ACCESS_TOKEN or not Config.LINE_CHANNEL_SECRET:
                return TextSendMessage(text="LINE Botの設定が完了していません。環境変数を設定してください。")

            if not self.ai_service:
                return TextSendMessage(text="AIサービスの初期化に失敗しました。OpenAI APIキーを設定してください。")

            # 会話履歴を取得
            conversation_history = self.db_helper.get_recent_conversations(line_user_id, limit=10)
            print(f"[DEBUG] 会話履歴件数: {len(conversation_history)}")

            # === 新・秘書モード：意図判断から開始 ===
            # まずユーザーの意図を判断
            intent_result = self.ai_service.determine_intent(user_message, conversation_history)
            print(f"[DEBUG] 意図判断結果: {intent_result}")

            needs_calendar = intent_result.get('needs_calendar', True)
            intent_type = intent_result.get('intent_type', 'schedule_query')

            # ユーザーのメッセージを会話履歴に保存
            self.db_helper.save_conversation(line_user_id, "user", user_message)

            # スケジュール情報が必要な場合のみカレンダーを取得
            calendar_events_text = None

            if needs_calendar:
                print(f"[DEBUG] スケジュール情報が必要 - 日時抽出を開始")

                # 日時抽出（既存のロジック）
                ai_result = self.ai_service.extract_dates_and_times(user_message, conversation_history)
                print(f"[DEBUG] ai_result: {ai_result}")

                if 'error' not in ai_result:
                    task_type = ai_result.get('task_type', 'add_event')

                    # タスクタイプに基づいて処理
                    if task_type == 'availability_check':
                        # 空き時間確認の場合 → スケジュール情報を取得して秘書モードで応答
                        print(f"[DEBUG] dates_info: {ai_result.get('dates', [])}")
                        location = ai_result.get('location', '')
                        current_location = ai_result.get('current_location', '')
                        meeting_duration_hours = ai_result.get('meeting_duration_hours', None)
                        travel_time_minutes = ai_result.get('travel_time_minutes', None)

                        # スケジュール情報を取得（秘書モードで使用）
                        calendar_events_text = self._get_calendar_events_text(
                            ai_result.get('dates', []),
                            line_user_id,
                            location=location,
                            current_location=current_location,
                            meeting_duration_hours=meeting_duration_hours,
                            travel_time_minutes=travel_time_minutes
                        )
                        print(f"[DEBUG] カレンダー情報取得完了")

                    elif task_type == 'add_event':
                        # 予定追加の場合 → 既存の処理を維持
                        if not self.calendar_service:
                            return TextSendMessage(text="カレンダーサービスが初期化されていません。")

                        dates = ai_result.get('dates', [])
                        if not dates:
                            return TextSendMessage(text="イベント情報を正しく認識できませんでした。\n\n例: 「明日の午前9時から会議を追加して」\n「来週月曜日の14時から打ち合わせ」")

                        # 複数の予定を処理（既存の処理を継続）
                        return self._handle_multiple_events(dates, line_user_id)

            # === 秘書モードで応答生成 ===
            print(f"[DEBUG] 秘書モードで応答生成開始")
            ai_response = self.ai_service.chat_with_calendar_context(
                user_message,
                conversation_history,
                calendar_events=calendar_events_text
            )
            print(f"[DEBUG] 秘書モード応答: {ai_response}")

            # アシスタントの応答を会話履歴に保存
            self.db_helper.save_conversation(line_user_id, "assistant", ai_response)

            return TextSendMessage(text=ai_response)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return TextSendMessage(text=f"エラーが発生しました: {str(e)}")

    def _get_calendar_events_text(self, dates_info, line_user_id, location=None, current_location=None, meeting_duration_hours=None, travel_time_minutes=None):
        """
        日付情報からカレンダーイベントと空き時間をテキスト形式で取得します（秘書モード用）

        Args:
            dates_info: 日付情報のリスト
            line_user_id: LINEユーザーID
            location: 場所フィルタ（オプション）
            current_location: 現在地（オプション）
            meeting_duration_hours: 打ち合わせ時間（オプション）
            travel_time_minutes: 移動時間（オプション）

        Returns:
            str: カレンダー情報のテキスト（予定と空き時間を含む）
        """
        try:
            if not dates_info or not self.calendar_service:
                return None

            jst = pytz.timezone('Asia/Tokyo')
            calendar_info = ""

            # 各日付情報について処理
            for date_info in dates_info:
                try:
                    date_str = date_info.get('date')
                    time_start = date_info.get('time', '08:00')
                    time_end = date_info.get('end_time', '22:00')

                    if not date_str:
                        continue

                    # その日の指定時間範囲でイベントと空き時間を取得
                    start_dt = jst.localize(datetime.strptime(f"{date_str} {time_start}", "%Y-%m-%d %H:%M"))
                    end_dt = jst.localize(datetime.strptime(f"{date_str} {time_end}", "%Y-%m-%d %H:%M"))

                    # イベントを取得
                    events = self.calendar_service.get_events_for_time_range(start_dt, end_dt, line_user_id)

                    # 日付のヘッダー
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    weekday = "月火水木金土日"[dt.weekday()]
                    calendar_info += f"\n{dt.month}/{dt.day}（{weekday}）:\n"

                    # 予定を表示
                    non_all_day_events = []
                    if events:
                        calendar_info += "【予定】\n"
                        for event in events:
                            title = event.get('title', '予定なし')
                            start_time = event.get('start', '')
                            end_time_event = event.get('end', '')
                            is_all_day = event.get('is_all_day', False)

                            if is_all_day:
                                calendar_info += f"  - {title}（終日）\n"
                            else:
                                non_all_day_events.append(event)
                                # 時間をフォーマット
                                if 'T' in start_time:
                                    from dateutil import parser
                                    start_dt_event = parser.parse(start_time).astimezone(jst)
                                    end_dt_event = parser.parse(end_time_event).astimezone(jst)
                                    time_str = f"{start_dt_event.strftime('%H:%M')}〜{end_dt_event.strftime('%H:%M')}"
                                else:
                                    time_str = f"{start_time}〜{end_time_event}"

                                calendar_info += f"  - {time_str} {title}\n"
                    else:
                        calendar_info += "【予定】\n  - なし\n"

                    # 空き時間を計算
                    free_slots = self.calendar_service.find_free_slots_for_day(start_dt, end_dt, non_all_day_events)

                    if free_slots:
                        calendar_info += "【空き時間】\n"
                        for slot in free_slots:
                            slot_start = slot['start']
                            slot_end = slot['end']
                            calendar_info += f"  - {slot_start}〜{slot_end}\n"
                    else:
                        calendar_info += "【空き時間】\n  - なし\n"

                except Exception as e:
                    error_type = type(e).__name__
                    print(f"[ERROR] 日付 {date_str} の処理中にエラー ({error_type}): {e}")
                    import traceback
                    traceback.print_exc()

                    # タイムアウトエラーの場合は特別なメッセージを返す
                    if 'timeout' in str(e).lower() or 'timed out' in str(e).lower():
                        return "⚠️ Google Calendarへの接続がタイムアウトしました。しばらく待ってから再度お試しください。"
                    continue

            return calendar_info.strip() if calendar_info else None

        except Exception as e:
            error_type = type(e).__name__
            print(f"[ERROR] _get_calendar_events_text エラー ({error_type}): {e}")
            import traceback
            traceback.print_exc()

            # タイムアウトエラーの場合は特別なメッセージを返す
            if 'timeout' in str(e).lower() or 'timed out' in str(e).lower() or error_type in ['TimeoutError', 'timeout']:
                return "⚠️ Google Calendarへの接続がタイムアウトしました。ネットワークが不安定な可能性があります。しばらく待ってから再度お試しください。"
            return None

    def _handle_multiple_events(self, dates, line_user_id):
        """複数の予定を処理します"""
        try:
            from dateutil import parser
            import json
            
            added_events = []
            failed_events = []
            
            for date_info in dates:
                try:
                    # 日時を構築
                    date_str = date_info.get('date')
                    time_str = date_info.get('time')
                    end_time_str = date_info.get('end_time')
                    title = date_info.get('title', '予定')
                    description = date_info.get('description', '')
                    
                    if not date_str or not time_str:
                        print(f"[DEBUG] 不完全な予定情報をスキップ: {date_info}")
                        continue
                    
                    # 終了時間が設定されていない場合は1時間後に設定（元の設定を維持）
                    if not end_time_str or end_time_str == time_str:
                        from datetime import datetime, timedelta
                        time_obj = datetime.strptime(time_str, "%H:%M")
                        end_time_obj = time_obj + timedelta(hours=1)
                        end_time_str = end_time_obj.strftime("%H:%M")
                        print(f"[DEBUG] 終了時間を自動設定: {time_str} -> {end_time_str}")
                    
                    # 日時文字列を構築
                    start_datetime_str = f"{date_str}T{time_str}:00+09:00"
                    end_datetime_str = f"{date_str}T{end_time_str}:00+09:00"
                    
                    print(f"[DEBUG] 予定追加処理: {title} - {start_datetime_str} to {end_datetime_str}")
                    
                    # 日時をパース（タイムゾーン処理を改善）
                    start_datetime = parser.parse(start_datetime_str)
                    end_datetime = parser.parse(end_datetime_str)
                    
                    # 既にタイムゾーンが設定されている場合はそのまま使用、そうでなければJSTを設定
                    if start_datetime.tzinfo is None:
                        start_datetime = self.jst.localize(start_datetime)
                    if end_datetime.tzinfo is None:
                        end_datetime = self.jst.localize(end_datetime)
                    
                    # 既存予定をチェック
                    events = self.calendar_service.get_events_for_time_range(start_datetime, end_datetime, line_user_id)
                    if events:
                        print(f"[DEBUG] 重複予定を検出: {title}")
                        # 重複確認メッセージを表示
                        conflicting_events = []
                        for event in events:
                            conflicting_events.append({
                                'title': event.get('title', '予定なし'),
                                'start': event.get('start', ''),
                                'end': event.get('end', '')
                            })
                        
                        # 重複確認メッセージを構築
                        response_text = "⚠️ この時間帯に既に予定が存在します:\n"
                        for event in conflicting_events:
                            # 時間をフォーマット
                            start_time = event['start']
                            end_time = event['end']
                            if 'T' in start_time:
                                start_dt = parser.parse(start_time)
                                end_dt = parser.parse(end_time)
                                start_dt = start_dt.astimezone(self.jst)
                                end_dt = end_dt.astimezone(self.jst)
                                time_str = f"{start_dt.strftime('%H:%M')}~{end_dt.strftime('%H:%M')}"
                            else:
                                time_str = f"{start_time}~{end_time}"
                            
                            response_text += f"- {event['title']}\n({time_str})\n"
                        
                        response_text += "\nそれでも追加しますか？\n「はい」と返信してください。"
                        
                        # 全イベント（移動時間含む）をpending_eventsに保存
                        all_events = []
                        for date_info in dates:
                            event_date_str = date_info.get('date')
                            event_time_str = date_info.get('time')
                            event_end_time_str = date_info.get('end_time')
                            event_title = date_info.get('title', '予定')
                            event_description = date_info.get('description', '')
                            
                            if not event_date_str or not event_time_str:
                                continue
                            
                            # 終了時間が設定されていない場合は1時間後に設定
                            if not event_end_time_str or event_end_time_str == event_time_str:
                                from datetime import datetime, timedelta
                                time_obj = datetime.strptime(event_time_str, "%H:%M")
                                end_time_obj = time_obj + timedelta(hours=1)
                                event_end_time_str = end_time_obj.strftime("%H:%M")
                            
                            event_datetime_str = f"{event_date_str}T{event_time_str}:00+09:00"
                            event_end_datetime_str = f"{event_date_str}T{event_end_time_str}:00+09:00"
                            
                            all_events.append({
                                'title': event_title,
                                'start_datetime': event_datetime_str,
                                'end_datetime': event_end_datetime_str,
                                'description': event_description
                            })
                        
                        import json
                        self.db_helper.save_pending_event(line_user_id, json.dumps(all_events))
                        
                        return TextSendMessage(text=response_text)
                    
                    # 予定を追加
                    success, message, result = self.calendar_service.add_event(
                        title,
                        start_datetime,
                        end_datetime,
                        description,
                        line_user_id=line_user_id,
                        force_add=True
                    )
                    
                    if success:
                        # 元の表示形式に合わせて日時をフォーマット
                        from datetime import datetime
                        import pytz
                        jst = pytz.timezone('Asia/Tokyo')
                        start_dt = start_datetime.astimezone(jst)
                        end_dt = end_datetime.astimezone(jst)
                        weekday = "月火水木金土日"[start_dt.weekday()]
                        date_str = f"{start_dt.month}/{start_dt.day}（{weekday}）"
                        time_str = f"{start_dt.strftime('%H:%M')}〜{end_dt.strftime('%H:%M')}"
                        
                        added_events.append({
                            'title': title,
                            'time': f"{date_str}{time_str}"
                        })
                        print(f"[DEBUG] 予定追加成功: {title}")
                    else:
                        failed_events.append({
                            'title': title,
                            'time': f"{time_str}-{end_time_str}",
                            'reason': message
                        })
                        print(f"[DEBUG] 予定追加失敗: {title} - {message}")
                        
                except Exception as e:
                    print(f"[DEBUG] 予定処理エラー: {e}")
                    failed_events.append({
                        'title': date_info.get('title', '予定'),
                        'time': f"{date_info.get('time', '')}-{date_info.get('end_time', '')}",
                        'reason': str(e)
                    })
            
            # 結果メッセージを構築（移動時間を含む場合は統一形式）
            if added_events:
                # 移動時間が含まれているかチェック
                has_travel = any('移動時間' in event['title'] for event in added_events)
                
                if has_travel and len(added_events) > 1:
                    # 移動時間を含む場合は統一形式で表示
                    response_text = "✅予定を追加しました！\n\n"
                    
                    # 日付を取得（最初の予定から）
                    first_event = added_events[0]
                    time_str = first_event['time']
                    # "10/18 (土)19:00〜20:00" から "10/18 (土)" を抽出
                    date_match = re.search(r'(\d{1,2}/\d{1,2}\s*\([月火水木金土日]\)\s*)', time_str)
                    date_part = date_match.group(1).strip() if date_match else time_str
                    response_text += f"{date_part}\n"
                    response_text += "────────\n"
                    
                    # 時間順でソート（開始時間でソート）
                    def get_start_time(event):
                        time_str = event['time']
                        # "10/18 (土)19:00〜20:00" から "19:00〜20:00" を抽出
                        time_match = re.search(r'(\d{1,2}:\d{2}〜\d{1,2}:\d{2})', time_str)
                        time_part = time_match.group(1) if time_match else time_str
                        start_time = time_part.split('〜')[0]  # "19:00〜20:00" -> "19:00"
                        return start_time
                    
                    sorted_events = sorted(added_events, key=get_start_time)
                    
                    # 各予定を番号付きで表示
                    for i, event in enumerate(sorted_events, 1):
                        # 時間部分を抽出（"10:00~11:00" の形式）
                        # 日付と時間の区切りを正しく処理
                        time_str = event['time']
                        # "10/18 (土)19:00〜20:00" から "19:00〜20:00" を抽出
                        time_match = re.search(r'(\d{1,2}:\d{2}〜\d{1,2}:\d{2})', time_str)
                        time_part = time_match.group(1) if time_match else time_str
                        response_text += f"{i}. {event['title']}\n"
                        response_text += f"🕐 {time_part}\n"
                    
                    response_text += "────────"
                else:
                    # 通常の表示形式
                    response_text = "✅予定を追加しました！\n\n"
                    for event in added_events:
                        response_text += f"📅{event['title']}\n{event['time']}\n"
                
                if failed_events:
                    response_text += "\n\n⚠️追加できなかった予定:\n"
                    for event in failed_events:
                        response_text += f"• {event['title']} ({event['time']}) - {event['reason']}\n"
            else:
                response_text = "❌予定を追加できませんでした。\n\n"
                for event in failed_events:
                    response_text += f"• {event['title']} ({event['time']}) - {event['reason']}\n"
            
            return TextSendMessage(text=response_text)
            
        except Exception as e:
            print(f"[DEBUG] 複数予定処理エラー: {e}")
            return TextSendMessage(text=f"予定の処理中にエラーが発生しました: {str(e)}")
    
    def _handle_month_availability(self, month_num, line_user_id, location=None, travel_time_minutes=None, original_text=''):
        """月全体の空き時間を処理します"""
        import calendar
        try:
            now_jst = datetime.now(self.jst)
            
            # 現在年を取得、過去月の場合は来年
            year = now_jst.year
            if month_num < now_jst.month:
                year += 1
            elif month_num == now_jst.month and now_jst.day > 1:
                year = now_jst.year  # 今月以降
            
            # 月の日数と最初・最後の日を取得
            _, last_day = calendar.monthrange(year, month_num)
            first_date = datetime(year, month_num, 1)
            last_date = datetime(year, month_num, last_day)
            
            # dates_infoを作成（その月の全日付）
            dates_info = []
            current_date = first_date.date()
            while current_date <= last_date.date():
                date_str = current_date.isoformat()
                dates_info.append({
                    'date': date_str,
                    'time': '09:00',
                    'end_time': '18:00'
                })
                current_date += timedelta(days=1)
            
            print(f"[DEBUG] 月全体の空き時間処理: {year}年{month_num}月 ({len(dates_info)}日), location: {location}, travel_time_minutes: {travel_time_minutes}")

            # 通常の空き時間チェック処理を呼び出し
            return self._handle_availability_check(
                dates_info,
                line_user_id,
                location=location,
                current_location=None,
                meeting_duration_hours=None,
                travel_time_minutes=travel_time_minutes,
                original_text=original_text
            )
            
        except Exception as e:
            print(f"[DEBUG] 月全体の空き時間処理でエラー: {e}")
            import traceback
            traceback.print_exc()
            return TextSendMessage(text=f"月の空き時間確認でエラーが発生しました: {str(e)}")
    
    def _handle_availability_check(self, dates_info, line_user_id, location=None, current_location=None, meeting_duration_hours=None, travel_time_minutes=None, original_text=''):
        """空き時間確認を処理します（移動時間考慮）"""
        try:
            print(f"[DEBUG] _handle_availability_check開始")
            print(f"[DEBUG] dates_info: {dates_info}")
            print(f"[DEBUG] line_user_id: {line_user_id}")
            print(f"[DEBUG] location: {location}")
            print(f"[DEBUG] current_location: {current_location}")
            print(f"[DEBUG] meeting_duration_hours: {meeting_duration_hours}")
            print(f"[DEBUG] travel_time_minutes: {travel_time_minutes}")
            print(f"[DEBUG] original_text: {original_text}")
            
            # ユーザーの認証状態をチェック
            if not self._check_user_auth(line_user_id):
                print(f"[DEBUG] ユーザー認証未完了")
                return self._send_auth_guide(line_user_id)
            
            if not self.calendar_service:
                print(f"[DEBUG] カレンダーサービス未初期化")
                return TextSendMessage(text="Google Calendarサービスが初期化されていません。認証ファイルを確認してください。")
            
            if not self.ai_service:
                print(f"[DEBUG] AIサービス未初期化")
                return TextSendMessage(text="AIサービスが初期化されていません。")
            
            if not dates_info:
                print(f"[DEBUG] dates_infoが空")
                return TextSendMessage(text="日付を正しく認識できませんでした。\n\n例: 「明日7/7 15:00〜15:30の空き時間を教えて」")
            
            # 文脈に応じた時間範囲の調整
            # 夕食
            dinner_keywords = ['夕食', '夜食', 'ディナー', 'dinner', '夕飯', '夜ご飯', '晩ご飯', '夕ご飯']
            is_dinner_time = any(keyword in original_text for keyword in dinner_keywords)

            # ランチ・昼食
            lunch_keywords = ['ランチ', 'lunch', '昼食', '昼ご飯', 'お昼', 'ひるごはん']
            is_lunch_time = any(keyword in original_text for keyword in lunch_keywords)

            # 朝食・モーニング
            breakfast_keywords = ['朝食', 'モーニング', 'morning', '朝ご飯', 'あさごはん', 'ブレックファスト', 'breakfast']
            is_breakfast_time = any(keyword in original_text for keyword in breakfast_keywords)

            # カフェ・お茶
            cafe_keywords = ['カフェ', 'cafe', 'お茶', 'ティー', 'tea', 'コーヒー', 'coffee', '喫茶']
            is_cafe_time = any(keyword in original_text for keyword in cafe_keywords)

            # 午前・午後
            is_morning = '午前' in original_text
            is_afternoon = '午後' in original_text

            # 時間範囲を調整
            for date_info in dates_info:
                # デフォルト時間（08:00-22:00）の場合のみ変更
                if date_info.get('time') == '08:00' and date_info.get('end_time') == '22:00':
                    if is_breakfast_time:
                        date_info['time'] = '07:00'
                        date_info['end_time'] = '10:00'
                        print(f"[DEBUG] 朝食キーワードを検出、時間範囲を07:00~10:00に変更")
                    elif is_lunch_time:
                        date_info['time'] = '11:00'
                        date_info['end_time'] = '14:00'
                        print(f"[DEBUG] ランチキーワードを検出、時間範囲を11:00~14:00に変更")
                    elif is_dinner_time:
                        date_info['time'] = '18:00'
                        date_info['end_time'] = '22:00'
                        print(f"[DEBUG] 夕食キーワードを検出、時間範囲を18:00~22:00に変更")
                    elif is_morning:
                        date_info['time'] = '09:00'
                        date_info['end_time'] = '12:00'
                        print(f"[DEBUG] 午前キーワードを検出、時間範囲を09:00~12:00に変更")
                    elif is_afternoon:
                        date_info['time'] = '13:00'
                        date_info['end_time'] = '18:00'
                        print(f"[DEBUG] 午後キーワードを検出、時間範囲を13:00~18:00に変更")
            
            # 最小連続空き時間を抽出（例：「2時間空いてる」「3時間空いている」）
            min_free_hours = None
            import re
            # パターン: 「X時間空いている」「X時間空いてる」「X時間以上空いている」など
            time_patterns = [
                r'(\d+(?:\.\d+)?)\s*時間\s*空い(?:てる|ている|てる)',
                r'(\d+(?:\.\d+)?)\s*時間\s*以上\s*空い(?:てる|ている|てる)',
                r'(\d+(?:\.\d+)?)\s*時間\s*連続',
            ]
            for pattern in time_patterns:
                match = re.search(pattern, original_text)
                if match:
                    min_free_hours = float(match.group(1))
                    print(f"[DEBUG] 最小連続空き時間を検出: {min_free_hours}時間")
                    break
            
            # 上記で見つからない場合でも、「2時間」「3時間」のような表現があればそれを最小連続空き時間として扱う
            # ただし、meeting_duration_hours が指定されている場合は除外（移動時間計算で使用）
            if min_free_hours is None and meeting_duration_hours is None:
                generic_matches = re.findall(r'(\d+(?:\.\d+)?)\s*時間', original_text)
                if generic_matches:
                    # 複数ある場合はいちばん長い時間を条件として採用
                    hours_list = [float(h) for h in generic_matches]
                    min_free_hours = max(hours_list)
                    print(f"[DEBUG] 一般的な時間表現から最小連続空き時間を検出: {min_free_hours}時間")

            # meeting_duration_hoursが指定されているが、current_locationがない場合は
            # meeting_duration_hoursを最小連続空き時間として扱う
            if min_free_hours is None and meeting_duration_hours is not None and not current_location:
                min_free_hours = meeting_duration_hours
                print(f"[DEBUG] meeting_duration_hoursを最小連続空き時間として使用: {min_free_hours}時間")

            # カフェ・お茶の場合、最小連続空き時間が指定されていなければ1時間をデフォルトに
            if min_free_hours is None and is_cafe_time:
                min_free_hours = 1.0
                print(f"[DEBUG] カフェ・お茶キーワードを検出、最小連続空き時間を1時間に設定")

            # 移動時間を考慮した必要時間を計算
            if current_location and location and meeting_duration_hours:
                from travel_time_service import TravelTimeService
                travel_service = TravelTimeService()

                total_time_minutes, details = travel_service.calculate_total_required_time(
                    current_location,
                    location,
                    meeting_duration_hours
                )

                # 必要な連続空き時間（時間単位）
                min_free_hours = details['total_time_hours']

                print(f"[DEBUG] 移動時間計算完了:")
                print(f"  現在地: {current_location}")
                print(f"  目的地: {location}")
                print(f"  打ち合わせ時間: {meeting_duration_hours}時間")
                print(f"  往路移動時間: {details['outbound_time_minutes']}分")
                print(f"  復路移動時間: {details['return_time_minutes']}分")
                print(f"  必要な合計時間: {min_free_hours}時間")

            print(f"[DEBUG] 空き時間計算開始")
            free_slots_by_frame = []
            for i, date_info in enumerate(dates_info):
                print(f"[DEBUG] 日付{i+1}処理開始: {date_info}")
                date_str = date_info.get('date')
                start_time = date_info.get('time')
                end_time = date_info.get('end_time')
                
                print(f"[DEBUG] 日付{i+1}の抽出値: date={date_str}, start_time={start_time}, end_time={end_time}")
                
                if date_str and start_time and end_time:
                    try:
                        jst = pytz.timezone('Asia/Tokyo')
                        start_dt = jst.localize(datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M"))
                        end_dt = jst.localize(datetime.strptime(f"{date_str} {end_time}", "%Y-%m-%d %H:%M"))
                        
                        print(f"[DEBUG] 日付{i+1}のdatetime: start_dt={start_dt}, end_dt={end_dt}")
                        
                        # 枠内の予定を取得
                        print(f"[DEBUG] 日付{i+1}の予定取得開始")
                        all_events = self.calendar_service.get_events_for_time_range(start_dt, end_dt, line_user_id)
                        print(f"[DEBUG] 日付{i+1}の取得予定: {all_events}")
                        
                        # 場所フィルタリング
                        if location:
                            print(f"[DEBUG] 場所フィルタ適用: {location}")
                            # その日付に「場所」を含む終日予定があるかチェック
                            has_location_event = False
                            filtered_events = []
                            for event in all_events:
                                event_location = event.get('location', '')
                                event_title = event.get('title', '')
                                is_all_day = event.get('is_all_day', False)
                                # 終日予定のタイトルに場所が含まれている場合のみ
                                if is_all_day and (location in event_location or location in event_title):
                                    has_location_event = True
                                    print(f"[DEBUG] 場所を含む終日予定を発見: {event}")
                                    # 終日マーカーは空き時間計算から除外
                                else:
                                    # 終日マーカー以外の予定は空き時間計算に含める
                                    filtered_events.append(event)
                            
                            # その日に「場所」を含む終日予定がない場合はスキップ
                            if not has_location_event:
                                print(f"[DEBUG] 日付{i+1}には場所を含む終日予定がないためスキップ")
                                continue
                            
                            # 場所を含む終日予定がある場合、終日マーカーを除いた予定を使う
                            events = filtered_events
                            print(f"[DEBUG] 場所フィルタ通過、終日マーカーを除いた予定を使用: {len(events)}件")
                        else:
                            # 場所フィルタがない場合でも、終日マーカーは空き時間計算から除外
                            filtered_events = []
                            for event in all_events:
                                is_all_day = event.get('is_all_day', False)
                                # 終日予定は場所マーカーとして空き時間計算から除外
                                if not is_all_day:
                                    filtered_events.append(event)
                                else:
                                    print(f"[DEBUG] 終日マーカーを除外: {event}")
                            events = filtered_events
                            print(f"[DEBUG] 終日マーカーを除いた予定を使用: {len(events)}件")
                        
                        # 文脈に応じた時間範囲を使用（既に上で調整済み）
                        day_start = start_time
                        day_end = end_time

                        # 日をまたぐ時間範囲の処理（例：22:00〜02:00）
                        # start_time と end_time をdatetimeオブジェクトに変換して比較
                        start_dt_temp = jst.localize(datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M"))
                        end_dt_temp = jst.localize(datetime.strptime(f"{date_str} {end_time}", "%Y-%m-%d %H:%M"))
                        
                        # end_time が start_time より小さい場合は翌日とみなす
                        if end_dt_temp <= start_dt_temp:
                            end_dt_temp = end_dt_temp + timedelta(days=1)
                        
                        day_start_dt = jst.localize(datetime.strptime(f"{date_str} {day_start}", "%Y-%m-%d %H:%M"))
                        day_end_dt = jst.localize(datetime.strptime(f"{date_str} {day_end}", "%Y-%m-%d %H:%M"))
                        
                        # 範囲の重なりを計算
                        slot_start_dt = max(start_dt_temp, day_start_dt)
                        slot_end_dt = min(end_dt_temp, day_end_dt)
                        
                        print(f"[DEBUG] 日付{i+1}のスロット範囲: slot_start_dt={slot_start_dt}, slot_end_dt={slot_end_dt}")
                        
                        # 範囲が有効かチェック（重なりがあるか）
                        if slot_start_dt < slot_end_dt:
                            print(f"[DEBUG] 日付{i+1}の空き時間計算開始")
                            # slot_start_dtとslot_end_dtをそのまま使用（既にdatetimeオブジェクト）
                            free_slots = self.calendar_service.find_free_slots_for_day(slot_start_dt, slot_end_dt, events)
                            print(f"[DEBUG] 日付{i+1}の空き時間結果: {free_slots}")
                            
                            # 移動時間が指定されている場合、前後に移動時間分の余裕が必要な空き時間のみ抽出
                            if travel_time_minutes and travel_time_minutes > 0:
                                print(f"[DEBUG] 移動時間フィルタ適用: {travel_time_minutes}分")
                                filtered_free_slots = []
                                travel_delta = timedelta(minutes=travel_time_minutes)
                                for slot in free_slots:
                                    slot_start_str = slot['start']
                                    slot_end_str = slot['end']
                                    # 開始時刻と終了時刻をdatetimeに変換
                                    slot_start_parsed = jst.localize(datetime.strptime(f"{date_str} {slot_start_str}", "%Y-%m-%d %H:%M"))
                                    slot_end_parsed = jst.localize(datetime.strptime(f"{date_str} {slot_end_str}", "%Y-%m-%d %H:%M"))
                                    # 実際に予定を入れられる時間を計算（移動時間を除く）
                                    available_start = slot_start_parsed + travel_delta
                                    available_end = slot_end_parsed - travel_delta
                                    
                                    # 利用可能時間があるかチェック
                                    if available_start < available_end:
                                        # 利用可能時間を作成
                                        available_slot = {
                                            'start': available_start.strftime('%H:%M'),
                                            'end': available_end.strftime('%H:%M')
                                        }
                                        filtered_free_slots.append(available_slot)
                                        print(f"[DEBUG] 移動時間考慮後の利用可能時間: {available_slot} (元の空き時間: {slot_start_str}〜{slot_end_str})")
                                    else:
                                        print(f"[DEBUG] 移動時間不足で除外: {slot_start_str}〜{slot_end_str}")
                                free_slots = filtered_free_slots
                                print(f"[DEBUG] 移動時間フィルタ後: {len(free_slots)}件")
                        else:
                            print(f"[DEBUG] 日付{i+1}のスロット範囲が無効（範囲が重ならない）: {slot_start_dt} >= {slot_end_dt}, スキップ")
                            # 範囲が重ならない場合は、その日の処理をスキップ
                            continue
                        
                        # スロット範囲の文字列表現を取得
                        slot_start_str = slot_start_dt.strftime('%H:%M')
                        slot_end_str = slot_end_dt.strftime('%H:%M')
                        
                        free_slots_by_frame.append({
                            'date': date_str,
                            'start_time': slot_start_str,
                            'end_time': slot_end_str,
                            'free_slots': free_slots
                        })
                        print(f"[DEBUG] 日付{i+1}のfree_slots_by_frame追加完了")
                    
                    except Exception as e:
                        print(f"[DEBUG] 日付{i+1}処理でエラー: {e}")
                        import traceback
                        traceback.print_exc()
                        # エラーが発生しても他の日付は処理を続行
                        free_slots_by_frame.append({
                            'date': date_str,
                            'start_time': start_time,
                            'end_time': end_time,
                            'free_slots': []
                        })
                else:
                    print(f"[DEBUG] 日付{i+1}の必須項目が不足: date_str={date_str}, start_time={start_time}, end_time={end_time}")
            
            print(f"[DEBUG] 全日付処理完了、free_slots_by_frame: {free_slots_by_frame}")
            
            # 最小連続空き時間が指定されている場合、各日の空き時間スロットから指定時間以上のものだけをフィルタリング
            if min_free_hours is not None:
                print(f"[DEBUG] 最小連続空き時間でスロットフィルタリング開始: {min_free_hours}時間")
                jst = pytz.timezone('Asia/Tokyo')
                min_free_minutes = min_free_hours * 60
                
                for frame in free_slots_by_frame:
                    date_str = frame['date']
                    slots = frame['free_slots']
                    
                    # この日の空き時間スロットの中で、指定時間以上の連続空き時間があるスロットだけをフィルタリング
                    filtered_slots = []
                    for slot in slots:
                        slot_start = slot['start']
                        slot_end = slot['end']
                        
                        # 時間文字列をdatetimeに変換して時間差を計算
                        slot_start_dt = jst.localize(datetime.strptime(f"{date_str} {slot_start}", "%Y-%m-%d %H:%M"))
                        slot_end_dt = jst.localize(datetime.strptime(f"{date_str} {slot_end}", "%Y-%m-%d %H:%M"))
                        slot_duration = (slot_end_dt - slot_start_dt).total_seconds() / 60  # 分単位
                        
                        if slot_duration >= min_free_minutes:
                            filtered_slots.append(slot)
                            print(f"[DEBUG] 日付 {date_str} に {slot_duration}分（{slot_duration/60:.1f}時間）の連続空き時間を保持: {slot_start}〜{slot_end}")
                        else:
                            print(f"[DEBUG] 日付 {date_str} の空き時間スロット {slot_start}〜{slot_end} は {slot_duration}分で条件未満のため除外")
                    
                    # フィルタリング後のスロットで更新（スロットが空でも日付は残す）
                    frame['free_slots'] = filtered_slots
                    print(f"[DEBUG] 日付 {date_str} のフィルタリング後: {len(filtered_slots)}件のスロット")
                
                print(f"[DEBUG] スロットフィルタリング完了")
            
            print(f"[DEBUG] format_free_slots_response_by_frame呼び出し")
            response_text = self.ai_service.format_free_slots_response_by_frame(free_slots_by_frame, min_free_hours=min_free_hours)
            print(f"[DEBUG] レスポンス生成完了: {response_text}")

            # ボットの応答を会話履歴に保存
            self.db_helper.save_conversation(line_user_id, "assistant", response_text)

            # 古い会話履歴を削除（最新50件を保持）
            self.db_helper.clear_old_conversations(line_user_id, keep_recent=50)

            return TextSendMessage(text=response_text)
            
        except Exception as e:
            print(f"[DEBUG] _handle_availability_checkで例外発生: {e}")
            import traceback
            traceback.print_exc()
            return TextSendMessage(text=f"空き時間確認でエラーが発生しました: {str(e)}")
    
    def _handle_event_addition(self, user_message, line_user_id):
        """イベント追加を処理します"""
        try:
            # ユーザーの認証状態をチェック
            if not self._check_user_auth(line_user_id):
                return self._send_auth_guide(line_user_id)
            
            if not self.calendar_service:
                return TextSendMessage(text="Google Calendarサービスが初期化されていません。認証ファイルを確認してください。")
            
            if not self.ai_service:
                return TextSendMessage(text="AIサービスが初期化されていません。")
            
            # AIを使ってイベント情報を抽出
            event_info = self.ai_service.extract_event_info(user_message)
            
            if 'error' in event_info:
                # 日程のみの場合は空き時間確認として処理
                dates_info = self.ai_service.extract_dates_and_times(user_message)
                if 'error' not in dates_info and dates_info.get('dates'):
                    return self._handle_availability_check(dates_info.get('dates', []), line_user_id)
                
                return TextSendMessage(text="・日時を打つと空き時間を返します\n・予定を打つとカレンダーに追加します\n\n例：\n・「明日の空き時間」\n・「7/15 15:00〜16:00の空き時間」\n・「明日の午前9時から会議を追加して」\n・「来週月曜日の14時から打ち合わせ」")
            
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
                event_info.get('description', ''),
                line_user_id=line_user_id,
                force_add=True
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