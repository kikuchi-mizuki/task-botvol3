import openai
from datetime import datetime, timedelta
from dateutil import parser
import re
import json
from config import Config
import calendar
import pytz

class AIService:
    def __init__(self):
        self.client = openai.OpenAI(api_key=Config.OPENAI_API_KEY)
    
    def _get_jst_now_str(self):
        now = datetime.now(pytz.timezone('Asia/Tokyo'))
        return now.strftime('%Y-%m-%dT%H:%M:%S%z')
    
    def extract_dates_and_times(self, text):
        """テキストから日時を抽出し、タスクの種類を判定します"""
        try:
            now_jst = self._get_jst_now_str()
            system_prompt = (
                f"あなたは予定とタスクを管理するAIです。\n"
                f"現在の日時（日本時間）は {now_jst} です。  \n"
                "【最重要】ユーザーの入力が箇条書き・改行・スペース・句読点で区切られている場合も、全ての時間帯・枠を必ず個別に抽出してください。\n"
                "この日時は、すべての自然言語の解釈において**常に絶対的な基準**としてください。  \n"
                "会話の流れや前回の入力に引きずられることなく、**毎回この現在日時を最優先にしてください。**\n"
                "\n"
                "あなたは日時抽出とタスク管理の専門家です。ユーザーのテキストを分析して、以下のJSON形式で返してください。\n\n"
                "分析ルール:\n"
                "1. 複数の日時がある場合は全て抽出\n"
                "2. 日本語の日付表現（今日、明日、来週月曜日など）を具体的な日付に変換\n"
                "3. 時間表現（午前9時、14時30分、9-10時、9時-10時、9:00-10:00など）を24時間形式に変換\n"
                "4. **タスクの種類を判定（重要）**:\n   - 日時のみ（タイトルや内容がない）場合は必ず「availability_check」（空き時間確認）\n   - 日時+タイトル/予定内容がある場合は「add_event」（予定追加）\n   - 例：「7/8 18時以降」→ availability_check（日時のみ）\n   - 例：「7/10 18:00〜20:00」→ availability_check（日時のみ）\n   - 例：「・7/10 9-10時\n・7/11 9-10時」→ availability_check（日時のみ複数）\n   - 例：「7/10 9-10時」→ availability_check（9:00〜10:00として抽出）\n   - 例：「7/10 9時-10時」→ availability_check（9:00〜10:00として抽出）\n   - 例：「7/10 9:00-10:00」→ availability_check（9:00〜10:00として抽出）\n   - 例：「明日の午前9時から会議を追加して」→ add_event（日時+予定内容）\n   - 例：「来週月曜日の14時から打ち合わせ」→ add_event（日時+予定内容）\n"
                "5. 自然言語の時間表現は必ず具体的な時刻範囲・日付範囲に変換してください。\n"
                "   例：'18時以降'→'18:00〜23:59'、'終日'→'00:00〜23:59'、'今日'→'現在時刻〜23:59'、'今日から1週間'→'今日〜7日後の23:59'。\n"
                "6. 箇条書き（・や-）、改行、スペース、句読点で区切られている場合も、すべての日時・時間帯を抽出してください。\n"
                "   例：'・7/10 9-10時\n・7/11 9-10時' → 2件の予定として抽出\n"
                "   例：'7/11 15:00〜16:00 18:00〜19:00' → 2件の予定として抽出\n"
                "   例：'7/12 終日' → 1件の終日予定として抽出\n"
                "7. 同じ日付の終日予定は1件だけ抽出してください。\n"
                "8. 予定タイトル（description）も必ず抽出してください。\n"
                "9. \"終日\"や\"00:00〜23:59\"の終日枠は、ユーザーが明示的に\"終日\"と書いた場合のみ抽出してください。\n"
                "10. 1つの日付に複数の時間帯（枠）が指定されている場合は、必ずその枠ごとに抽出してください。\n"
                "11. 同じ日に部分枠（例: 15:00〜16:00, 18:00〜19:00）がある場合は、その日付の終日枠（00:00〜23:59）は抽出しないでください。\n"
                "12. 複数の日時・時間帯が入力される場合、全ての時間帯をリストにし、それぞれに対して開始時刻・終了時刻をISO形式（例: 2025-07-11T15:00:00+09:00）で出力してください。\n"
                "13. 予定タイトル（会議名や打合せ名など）と、説明（議題や詳細、目的など）があれば両方抽出してください。\n"
                "14. 説明はタイトル以降の文や\"の件\"\"について\"などを優先して抽出してください。\n"
                "\n"
                "【出力例】\n"
                "空き時間確認の場合:\n"
                "{\n  \"task_type\": \"availability_check\",\n  \"dates\": [\n    {\n      \"date\": \"2025-07-08\",\n      \"time\": \"18:00\",\n      \"end_time\": \"23:59\"\n    }\n  ]\n}\n"
                "\n"
                "予定追加の場合:\n"
                "{\n  \"task_type\": \"add_event\",\n  \"dates\": [\n    {\n      \"date\": \"2025-07-14\",\n      \"time\": \"20:00\",\n      \"end_time\": \"20:30\",\n      \"title\": \"田中さんMTG\",\n      \"description\": \"新作アプリの件\"\n    }\n  ]\n}\n"
            )
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                temperature=0.1
            )
            
            result = response.choices[0].message.content
            parsed = self._parse_ai_response(result)
            return self._supplement_times(parsed, text)
            
        except Exception as e:
            return {"error": "イベント情報を正しく認識できませんでした。\n\n・日時を打つと空き時間を返します\n・予定を打つとカレンダーに追加します\n\n例：\n『明日の午前9時から会議を追加して』\n『来週月曜日の14時から打ち合わせ』"}
    
    def _parse_ai_response(self, response):
        """AIの応答をパースします"""
        try:
            # JSON部分を抽出
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            else:
                return {"error": "AI応答のパースに失敗しました"}
        except Exception as e:
            return {"error": f"JSONパースエラー: {str(e)}"}
    
    def _supplement_times(self, parsed, original_text):
        """AIの出力でtimeやend_timeが空の場合に自然言語表現や状況に応じて自動補完する。titleが空の場合はdescriptionや日付・時刻から補完する。さらに正規表現で漏れた枠も補完する。"""
        from datetime import datetime, timedelta
        import re
        jst = pytz.timezone('Asia/Tokyo')
        now = datetime.now(jst)
        print(f"[DEBUG] _supplement_times開始: parsed={parsed}")
        print(f"[DEBUG] 元テキスト: {original_text}")
        if not parsed or 'dates' not in parsed:
            print(f"[DEBUG] datesが存在しない: {parsed}")
            return parsed
        # --- 既存AI抽出の補完処理 ---
        allday_dates = set()
        new_dates = []
        for d in parsed['dates']:
            print(f"[DEBUG] datesループ: {d}")
            phrase = d.get('description', '') or original_text
            # 終日
            if (not d.get('time') and not d.get('end_time')) or re.search(r'終日', phrase):
                d['time'] = '00:00'
                d['end_time'] = '23:59'
                if d.get('date') in allday_dates:
                    print(f"[DEBUG] 同じ日付の終日予定はスキップ: {d.get('date')}")
                    continue  # 同じ日付の終日予定は1件だけ
                allday_dates.add(d.get('date'))
            # 18時以降
            elif re.search(r'(\d{1,2})時以降', phrase):
                m = re.search(r'(\d{1,2})時以降', phrase)
                if m:
                    d['time'] = f"{int(m.group(1)):02d}:00"
                    d['end_time'] = '23:59'
            # 明日
            elif re.search(r'明日', phrase):
                d['date'] = (now + timedelta(days=1)).strftime('%Y-%m-%d')
                if not d.get('time'):
                    d['time'] = '08:00'
                if not d.get('end_time'):
                    d['end_time'] = '22:00'
            # 今日
            elif re.search(r'今日', phrase):
                d['date'] = now.strftime('%Y-%m-%d')
                if not d.get('time'):
                    d['time'] = now.strftime('%H:%M')
                if not d.get('end_time'):
                    d['end_time'] = '23:59'
            # 今日から1週間
            elif re.search(r'今日から1週間', phrase):
                d['date'] = now.strftime('%Y-%m-%d')
                d['end_date'] = (now + timedelta(days=6)).strftime('%Y-%m-%d')
                d['time'] = '00:00'
                d['end_time'] = '23:59'
            # end_timeが空
            elif d.get('time') and not d.get('end_time'):
                d['end_time'] = '23:59'
            # title補完（空き時間確認の場合はタイトルを生成しない）
            if not d.get('title') or d['title'] == '':
                if d.get('description'):
                    d['title'] = d['description']
                elif parsed.get('task_type') == 'add_event':
                    # 予定追加の場合のみタイトルを生成
                    t = d.get('time', '')
                    e = d.get('end_time', '')
                    d['title'] = f"予定（{d.get('date', '')} {t}〜{e}）"
            new_dates.append(d)
        print(f"[DEBUG] new_dates(補完後): {new_dates}")
        # --- ここから全日枠の除外 ---
        if len(new_dates) > 1:
            filtered = []
            for d in new_dates:
                if d.get('time') == '00:00' and d.get('end_time') == '23:59':
                    if any((d2.get('date') == d.get('date') and (d2.get('time') != '00:00' or d2.get('end_time') != '23:59')) for d2 in new_dates):
                        print(f"[DEBUG] 全日枠を除外: {d}")
                        continue
                filtered.append(d)
            new_dates = filtered
        print(f"[DEBUG] new_dates(全日枠除外後): {new_dates}")
        # --- 正規表現で漏れた枠を補完 ---
        pattern1 = r'(\d{1,2})/(\d{1,2})[\s　]*([0-9]{1,2}):?([0-9]{0,2})[\-〜~]([0-9]{1,2}):?([0-9]{0,2})'
        matches1 = re.findall(pattern1, original_text)
        print(f"[DEBUG] pattern1マッチ: {matches1}")
        for m in matches1:
            month, day, sh, sm, eh, em = m
            year = now.year
            try:
                dt = datetime(year, int(month), int(day))
                if dt < now:
                    dt = datetime(year+1, int(month), int(day))
            except Exception:
                continue
            date_str = dt.strftime('%Y-%m-%d')
            start_time = f"{int(sh):02d}:{sm if sm else '00'}"
            end_time = f"{int(eh):02d}:{em if em else '00'}"
            if not any(d.get('date') == date_str and d.get('time') == start_time and d.get('end_time') == end_time for d in new_dates):
                new_date_entry = {
                    'date': date_str,
                    'time': start_time,
                    'end_time': end_time,
                    'description': ''
                }
                if parsed.get('task_type') == 'add_event':
                    new_date_entry['title'] = f"予定（{date_str} {start_time}〜{end_time}）"
                new_dates.append(new_date_entry)
                print(f"[DEBUG] pattern1で補完: {new_date_entry}")
        pattern2 = r'[・\-]\s*(\d{1,2})/(\d{1,2})\s*([0-9]{1,2})-([0-9]{1,2})時'
        matches2 = re.findall(pattern2, original_text)
        print(f"[DEBUG] pattern2マッチ: {matches2}")
        for m in matches2:
            month, day, sh, eh = m
            year = now.year
            try:
                dt = datetime(year, int(month), int(day))
                if dt < now:
                    dt = datetime(year+1, int(month), int(day))
            except Exception:
                continue
            date_str = dt.strftime('%Y-%m-%d')
            start_time = f"{int(sh):02d}:00"
            end_time = f"{int(eh):02d}:00"
            if not any(d.get('date') == date_str and d.get('time') == start_time and d.get('end_time') == end_time for d in new_dates):
                new_date_entry = {
                    'date': date_str,
                    'time': start_time,
                    'end_time': end_time,
                    'description': ''
                }
                if parsed.get('task_type') == 'add_event':
                    new_date_entry['title'] = f"予定（{date_str} {start_time}〜{end_time}）"
                new_dates.append(new_date_entry)
                print(f"[DEBUG] pattern2で補完: {new_date_entry}")
        pattern3 = r'(\d{1,2})/(\d{1,2})\s*([0-9]{1,2})時?-([0-9]{1,2})時?'
        matches3 = re.findall(pattern3, original_text)
        print(f"[DEBUG] pattern3マッチ: {matches3}")
        for m in matches3:
            month, day, sh, eh = m
            year = now.year
            try:
                dt = datetime(year, int(month), int(day))
                if dt < now:
                    dt = datetime(year+1, int(month), int(day))
            except Exception:
                continue
            date_str = dt.strftime('%Y-%m-%d')
            start_time = f"{int(sh):02d}:00"
            end_time = f"{int(eh):02d}:00"
            if not any(d.get('date') == date_str and d.get('time') == start_time and d.get('end_time') == end_time for d in new_dates):
                new_date_entry = {
                    'date': date_str,
                    'time': start_time,
                    'end_time': end_time,
                    'description': ''
                }
                if parsed.get('task_type') == 'add_event':
                    new_date_entry['title'] = f"予定（{date_str} {start_time}〜{end_time}）"
                new_dates.append(new_date_entry)
                print(f"[DEBUG] pattern3で補完: {new_date_entry}")
        print(f"[DEBUG] new_dates(正規表現補完後): {new_dates}")
        parsed['dates'] = new_dates
        return parsed
    
    def extract_event_info(self, text):
        """イベント追加用の情報を抽出します"""
        try:
            now_jst = self._get_jst_now_str()
            system_prompt = (
                f"あなたは予定とタスクを管理するAIです。\n"
                f"現在の日時（日本時間）は {now_jst} です。  \n"
                "この日時は、すべての自然言語の解釈において**常に絶対的な基準**としてください。  \n"
                "会話の流れや前回の入力に引きずられることなく、**毎回この現在日時を最優先にしてください。**\n"
                "\n"
                "あなたはイベント情報抽出の専門家です。ユーザーのテキストからイベントのタイトルと日時を抽出し、以下のJSON形式で返してください。\n\n"
                "抽出ルール:\n"
                "1. イベントのタイトルは、直前の人名や主語、会議名なども含めて、できるだけ長く・具体的に抽出してください。\n"
                "   例:『田中さんとMTG 新作アプリの件』→タイトル:『田中さんとMTG』、説明:『新作アプリの件』\n"
                "2. 開始日時と終了日時を抽出（終了時間が明示されていない場合は1時間後をデフォルトとする）\n"
                "3. 日本語の日付表現を具体的な日付に変換\n"
                "4. 時間表現を24時間形式に変換\n"
                "5. タイムゾーンは日本時間（JST）を想定\n\n"
                "出力形式:\n"
                "{\n  \"title\": \"イベントタイトル\",\n  \"start_datetime\": \"2024-01-15T09:00:00\",\n  \"end_datetime\": \"2024-01-15T10:00:00\",\n  \"description\": \"説明（オプション）\"\n}\n"
            )
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                temperature=0.1
            )
            result = response.choices[0].message.content
            parsed = self._parse_ai_response(result)
            # --- タイトルが短すぎる場合は人名や主語＋MTGなどを含めて補完 ---
            if parsed and isinstance(parsed, dict) and 'title' in parsed:
                title = parsed['title']
                # 例: "MTG"や"会議"など短い場合は元テキストから人名＋MTGを抽出
                if title and len(title) <= 4:
                    import re
                    # 例: "田中さんとMTG" "佐藤さん会議" "山田さんMTG" など
                    m = re.search(r'([\w一-龠ぁ-んァ-ン]+さん[と]?\s*MTG|[\w一-龠ぁ-んァ-ン]+さん[と]?\s*会議)', text)
                    if m:
                        parsed['title'] = m.group(1)
            return parsed
        except Exception as e:
            return {"error": f"AI処理エラー: {str(e)}"}
    
    def format_calendar_response(self, events_info):
        """カレンダー情報を読みやすい形式にフォーマットします"""
        if not events_info:
            return "📅 指定された日付に予定はありません。"
        
        response = "📅 カレンダー情報\n\n"
        
        for day_info in events_info:
            if 'error' in day_info:
                response += f"❌ {day_info['date']}: {day_info['error']}\n\n"
                continue
            
            date = day_info['date']
            events = day_info['events']
            
            if not events:
                response += f"📅 {date}: 予定なし（空いています）\n\n"
            else:
                response += f"📅 {date}:\n"
                for event in events:
                    start_time = self._format_datetime(event['start'])
                    end_time = self._format_datetime(event['end'])
                    response += f"  • {event['title']} ({start_time} - {end_time})\n"
                response += "\n"
        
        return response
    
    def _format_datetime(self, datetime_str):
        """日時文字列を読みやすい形式にフォーマットします"""
        try:
            dt = parser.parse(datetime_str)
            return dt.strftime('%m/%d %H:%M')
        except:
            return datetime_str
    
    def format_event_confirmation(self, success, message, event_info):
        """
        イベント追加結果をフォーマットします
        予定が入っている場合：
        ❌予定が入っています！\n\n• タイトル (MM/DD HH:MM - HH:MM)
        予定を追加した場合：
        ✅予定を追加しました！\n\n📅タイトル\nM/D（曜）HH:MM〜HH:MM
        """
        if success:
            response = "✅予定を追加しました！\n\n"
            if event_info:
                title = event_info.get('title', '')
                start = event_info.get('start')
                end = event_info.get('end')
                if start and end:
                    from datetime import datetime
                    import pytz
                    jst = pytz.timezone('Asia/Tokyo')
                    start_dt = datetime.fromisoformat(start).astimezone(jst)
                    end_dt = datetime.fromisoformat(end).astimezone(jst)
                    weekday = "月火水木金土日"[start_dt.weekday()]
                    date_str = f"{start_dt.month}/{start_dt.day}（{weekday}）"
                    time_str = f"{start_dt.strftime('%H:%M')}〜{end_dt.strftime('%H:%M')}"
                    response += f"📅{title}\n{date_str}{time_str}"
        else:
            response = "❌予定が入っています！\n\n"
            if event_info and isinstance(event_info, list):
                for event in event_info:
                    title = event.get('title', '')
                    start = event.get('start')
                    end = event.get('end')
                    if start and end:
                        from datetime import datetime
                        import pytz
                        jst = pytz.timezone('Asia/Tokyo')
                        start_dt = datetime.fromisoformat(start).astimezone(jst)
                        end_dt = datetime.fromisoformat(end).astimezone(jst)
                        date_str = f"{start_dt.month:02d}/{start_dt.day:02d}"
                        time_str = f"{start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}"
                        response += f"• {title} ({date_str} {time_str})\n"
        return response
    
    def check_multiple_dates_availability(self, dates_info):
        """複数の日付の空き時間を確認するための情報を抽出します"""
        try:
            now_jst = self._get_jst_now_str()
            system_prompt = (
                f"あなたは予定とタスクを管理するAIです。\n"
                f"現在の日時（日本時間）は {now_jst} です。  \n"
                "この日時は、すべての自然言語の解釈において**常に絶対的な基準**としてください。  \n"
                "会話の流れや前回の入力に引きずられることなく、**毎回この現在日時を最優先にしてください。**\n"
                "\n"
                "複数の日付の空き時間確認リクエストを処理してください。以下のJSON形式で返してください。\n\n"
                "出力形式:\n"
                "{\n  \"dates\": [\n    {\n      \"date\": \"2024-01-15\",\n      \"time_range\": \"09:00-18:00\"\n    }\n  ]\n}\n"
            )
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": dates_info
                    }
                ],
                temperature=0.1
            )
            
            result = response.choices[0].message.content
            return self._parse_ai_response(result)
            
        except Exception as e:
            return {"error": f"AI処理エラー: {str(e)}"}
    
    def format_free_slots_response(self, free_slots_by_date):
        """
        free_slots_by_date: { 'YYYY-MM-DD': [{'start': '10:00', 'end': '11:00'}, ...], ... }
        指定フォーマットで空き時間を返す
        """
        jst = pytz.timezone('Asia/Tokyo')
        if not free_slots_by_date:
            return "✅空き時間はありませんでした。"
        response = "✅以下が空き時間です！\n\n"
        for date, slots in free_slots_by_date.items():
            dt = jst.localize(datetime.strptime(date, "%Y-%m-%d"))
            weekday = "月火水木金土日"[dt.weekday()]
            response += f"{dt.month}/{dt.day}（{weekday}）\n"
            if not slots:
                response += "・空き時間なし\n"
            else:
                for slot in slots:
                    response += f"・{slot['start']}〜{slot['end']}\n"
        return response
    
    def format_free_slots_response_by_frame(self, free_slots_by_frame):
        """
        free_slots_by_frame: [
            {'date': 'YYYY-MM-DD', 'start_time': 'HH:MM', 'end_time': 'HH:MM', 'free_slots': [{'start': 'HH:MM', 'end': 'HH:MM'}, ...]},
            ...
        ]
        日付ごとに空き時間をまとめて返す（重複枠・重複時間帯は除外）
        """
        print(f"[DEBUG] format_free_slots_response_by_frame開始")
        print(f"[DEBUG] 入力データ: {free_slots_by_frame}")
        
        jst = pytz.timezone('Asia/Tokyo')
        if not free_slots_by_frame:
            print(f"[DEBUG] free_slots_by_frameが空")
            return "✅空き時間はありませんでした。"
            
        # 日付ごとに空き時間をまとめる
        date_slots = {}
        for i, frame in enumerate(free_slots_by_frame):
            print(f"[DEBUG] フレーム{i+1}処理: {frame}")
            date = frame['date']
            slots = frame['free_slots']
            print(f"[DEBUG] フレーム{i+1}の空き時間: {slots}")
            
            if date not in date_slots:
                date_slots[date] = set()
            for slot in slots:
                date_slots[date].add((slot['start'], slot['end']))
                print(f"[DEBUG] 日付{date}に空き時間追加: {slot['start']}〜{slot['end']}")
                
        print(f"[DEBUG] 日付ごとの空き時間: {date_slots}")
        
        response = "✅以下が空き時間です！\n\n"
        for date in sorted(date_slots.keys()):
            dt = jst.localize(datetime.strptime(date, "%Y-%m-%d"))
            weekday = "月火水木金土日"[dt.weekday()]
            response += f"{dt.month}/{dt.day}（{weekday}）\n"
            
            slots = sorted(list(date_slots[date]))
            print(f"[DEBUG] 日付{date}の最終空き時間: {slots}")
            
            if not slots:
                response += "・空き時間なし\n"
            else:
                for start, end in slots:
                    response += f"・{start}〜{end}\n"
                    
        print(f"[DEBUG] 最終レスポンス: {response}")
        return response 