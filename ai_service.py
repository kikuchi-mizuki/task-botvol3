import openai
from datetime import datetime, timedelta
from dateutil import parser
import re
import json
from config import Config
import calendar
import pytz
import logging

logger = logging.getLogger("ai_service")
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

class AIService:
    def __init__(self):
        self.client = openai.OpenAI(api_key=Config.OPENAI_API_KEY)
        # GPT-4を使用（より高精度）
        self.model = "gpt-4-turbo-preview"
        # フォールバック用にGPT-3.5も用意
        self.fallback_model = "gpt-3.5-turbo"

    def _get_jst_now_str(self):
        now = datetime.now(pytz.timezone('Asia/Tokyo'))
        return now.strftime('%Y-%m-%dT%H:%M:%S%z')

    def extract_dates_and_times(self, text):
        """
        テキストから日時を抽出し、タスクの種類を判定します
        二段階処理とFunction Callingを使用して精度向上
        """
        try:
            # 第1段階：ユーザーの意図を理解
            intent = self._understand_intent(text)
            logger.info(f"[DEBUG] 意図理解結果: {intent}")

            # 第2段階：日時の詳細抽出（Function Calling使用）
            extraction_result = self._extract_dates_with_function_calling(text, intent)
            logger.info(f"[DEBUG] 日時抽出結果: {extraction_result}")

            if 'error' in extraction_result:
                return extraction_result

            # 抽出結果を補完
            supplemented = self._supplement_times(extraction_result, text)
            logger.info(f"[DEBUG] 補完後の結果: {supplemented}")

            return supplemented

        except Exception as e:
            logger.error(f"[ERROR] extract_dates_and_times エラー: {e}")
            import traceback
            traceback.print_exc()
            return {
                "error": "イベント情報を正しく認識できませんでした。\n\n・日時を打つと空き時間を返します\n・予定を打つとカレンダーに追加します\n\n例：\n『明日の午前9時から会議を追加して』\n『来週月曜日の14時から打ち合わせ』"
            }

    def _understand_intent(self, text):
        """
        第1段階：ユーザーの意図を理解
        - availability_check（空き時間確認）
        - add_event（予定追加）
        - unknown（不明）
        """
        try:
            now_jst = self._get_jst_now_str()

            system_prompt = f"""あなたは予定管理アシスタントです。
現在の日時（日本時間）: {now_jst}

ユーザーのメッセージから意図を判定してください。

【判定ルール】
1. **空き時間確認（availability_check）**:
   - 日時のみで予定内容がない
   - 「空き時間」「空いてる」「予定ある？」などの表現
   - 例: 「明日の空き時間」「来週月曜日は空いてる？」「7/10 9-10時」

2. **予定追加（add_event）**:
   - 日時＋予定内容（会議名、タイトル等）がある
   - 「追加して」「入れて」「予定」などの表現
   - 例: 「明日9時から会議」「7/10 10時 田中さんとMTG」

3. **不明（unknown）**:
   - 日時が含まれていない
   - 判定できない曖昧な表現

【出力形式】
以下のJSON形式で返してください：
{{
  "intent": "availability_check" または "add_event" または "unknown",
  "confidence": 0.0～1.0の数値,
  "reason": "判定理由の簡潔な説明"
}}

【重要】
- 日時のみで予定内容がない場合は必ず「availability_check」
- 予定内容が明示されている場合のみ「add_event」
- 迷った場合は「availability_check」を選択
"""

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ],
                temperature=0.1,
                max_tokens=200
            )

            result = response.choices[0].message.content
            logger.info(f"[DEBUG] 意図理解AI応答: {result}")

            # JSONをパース
            intent_data = self._parse_ai_response(result)

            if not intent_data or 'intent' not in intent_data:
                # パース失敗時はavailability_checkをデフォルトに
                return {
                    "intent": "availability_check",
                    "confidence": 0.5,
                    "reason": "パース失敗のためデフォルト"
                }

            return intent_data

        except Exception as e:
            logger.error(f"[ERROR] _understand_intent エラー: {e}")
            # エラー時はavailability_checkをデフォルトに
            return {
                "intent": "availability_check",
                "confidence": 0.5,
                "reason": f"エラー発生: {str(e)}"
            }

    def _extract_dates_with_function_calling(self, text, intent):
        """
        第2段階：Function Callingを使用した日時抽出
        より構造化された正確な出力を得る
        """
        try:
            now_jst = self._get_jst_now_str()
            task_type = intent.get('intent', 'availability_check')

            # Function Callingの定義
            functions = [
                {
                    "name": "extract_schedule_info",
                    "description": "ユーザーのメッセージから日程・時間・予定情報を抽出する",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task_type": {
                                "type": "string",
                                "enum": ["availability_check", "add_event"],
                                "description": "タスクの種類（空き時間確認 or 予定追加）"
                            },
                            "dates": {
                                "type": "array",
                                "description": "抽出された日時情報のリスト",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "date": {
                                            "type": "string",
                                            "description": "日付（YYYY-MM-DD形式）"
                                        },
                                        "time": {
                                            "type": "string",
                                            "description": "開始時刻（HH:MM形式、24時間表記）"
                                        },
                                        "end_time": {
                                            "type": "string",
                                            "description": "終了時刻（HH:MM形式、24時間表記）"
                                        },
                                        "title": {
                                            "type": "string",
                                            "description": "予定のタイトル（add_eventの場合のみ）"
                                        },
                                        "description": {
                                            "type": "string",
                                            "description": "予定の詳細説明（任意）"
                                        }
                                    },
                                    "required": ["date"]
                                }
                            },
                            "location": {
                                "type": "string",
                                "description": "場所（東京、大阪など、指定されている場合のみ）"
                            },
                            "travel_time_minutes": {
                                "type": "integer",
                                "description": "移動時間（分単位、指定されている場合のみ）"
                            }
                        },
                        "required": ["task_type", "dates"]
                    }
                }
            ]

            system_prompt = f"""あなたは予定とタスクを管理するAIアシスタントです。

【現在の日時（日本時間）】
{now_jst}

【重要な指示】
1. この日時を**絶対的な基準**として使用してください
2. 「今日」「明日」「来週」などの相対的な表現を正確に変換してください
3. 年月日は必ずYYYY-MM-DD形式で出力してください
4. 時刻は必ずHH:MM形式（24時間表記）で出力してください

【日付範囲の処理】
- 「12/5-12/28」のような範囲表記は、開始日から終了日まで**全ての日付を個別に展開**してください
- 例: 「12/5-12/10」→ 12/5, 12/6, 12/7, 12/8, 12/9, 12/10 の6件

【週の処理】
- 「今週」→ 今週の月曜日から日曜日まで7日間を展開
- 「来週」→ 来週の月曜日から日曜日まで7日間を展開

【時間範囲の処理】
- 「9-10時」→ time: "09:00", end_time: "10:00"
- 「18時以降」→ time: "18:00", end_time: "23:59"
- 「終日」→ time: "00:00", end_time: "23:59"
- 終了時刻が未指定の場合は開始時刻の1時間後に設定

【複数時間帯の処理】
- 「15:00-16:00 18:00-19:00」のように複数の時間帯がある場合は、別々のエントリとして抽出
- 改行や箇条書き（・や-）で区切られた日時も全て抽出

【最小連続空き時間】
- 「2時間空いている」「3時間空いてる」という表現の「X時間」は時間範囲ではなく、条件です
- この場合は時間範囲を指定せず、デフォルト（09:00-18:00）を使用してください

【タスクタイプの判定】
現在のタスクタイプ: {task_type}
- availability_check: 日時のみ、予定内容なし
- add_event: 日時＋予定内容あり

【例】
入力: 「明日と明後日の空き時間」
→ task_type: "availability_check", dates: [{{date: "2025-XX-XX", time: "09:00", end_time: "18:00"}}, {{date: "2025-XX-XX", time: "09:00", end_time: "18:00"}}]

入力: 「7/10 9-10時」
→ task_type: "availability_check", dates: [{{date: "2025-07-10", time: "09:00", end_time: "10:00"}}]

入力: 「明日10時から会議」
→ task_type: "add_event", dates: [{{date: "2025-XX-XX", time: "10:00", end_time: "11:00", title: "会議"}}]

入力: 「12/5-12/10の空き時間」
→ task_type: "availability_check", dates: [{{date: "2025-12-05", ...}}, {{date: "2025-12-06", ...}}, ..., {{date: "2025-12-10", ...}}]
"""

            # Function Callingを使用
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ],
                functions=functions,
                function_call={"name": "extract_schedule_info"},
                temperature=0.1
            )

            # Function Callingの結果を取得
            message = response.choices[0].message

            if message.function_call:
                function_args = json.loads(message.function_call.arguments)
                logger.info(f"[DEBUG] Function Calling結果: {function_args}")

                # task_typeを意図理解の結果で上書き（より正確）
                function_args['task_type'] = task_type

                return function_args
            else:
                # Function Callが失敗した場合はフォールバック
                logger.warning("[WARN] Function Callingが失敗、フォールバック処理")
                return self._extract_dates_fallback(text, task_type)

        except Exception as e:
            logger.error(f"[ERROR] _extract_dates_with_function_calling エラー: {e}")
            import traceback
            traceback.print_exc()
            # エラー時はフォールバック
            return self._extract_dates_fallback(text, intent.get('intent', 'availability_check'))

    def _extract_dates_fallback(self, text, task_type):
        """
        Function Calling失敗時のフォールバック処理
        従来のGPT-3.5を使用した抽出方法
        """
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
                "3. **日付範囲（例：12/5-12/28、1/10-1/20）は必ず開始日から終了日までの全ての日付を個別に抽出してください**\n"
                "   - 例：「12/5-12/28」→ 12/5, 12/6, 12/7, ..., 12/28 の全ての日付を個別に抽出\n"
                "   - 例：「1/10-1/20」→ 1/10, 1/11, 1/12, ..., 1/20 の全ての日付を個別に抽出\n"
                "   - 日付範囲は必ず全ての日付を展開し、1日ずつ個別のエントリとして抽出してください\n"
                "4. **「今週」「来週」という表現は必ず1週間分（7日間）の日付として抽出してください**\n"
                "   - 例：「今週」→ 今週月曜日から日曜日までの7日間\n"
                "   - 例：「来週」→ 来週月曜日から日曜日までの7日間\n"
                "   - 例：「今週の空き時間」→ 今週月曜日〜日曜日の7日間の空き時間\n"
                "   - 例：「来週の空き時間」→ 来週月曜日〜日曜日の7日間の空き時間\n"
                "5. 月が指定されていない場合（例：16日、17日）は今月として認識\n"
                "6. 時間表現（午前9時、14時30分、9-10時、9時-10時、9:00-10:00など）を24時間形式に変換\n"
                "7. **タスクの種類を判定（最重要）**:\n   - 日時のみ（タイトルや内容がない）場合は必ず「availability_check」（空き時間確認）\n   - 日時+タイトル/予定内容がある場合は「add_event」（予定追加）\n"
                f"8. 現在のタスクタイプ: {task_type}\n"
                "\n"
                "【出力例】\n"
                "空き時間確認の場合:\n"
                "{\"task_type\": \"availability_check\", \"dates\": [{\"date\": \"2025-07-08\", \"time\": \"18:00\", \"end_time\": \"23:59\"}]}\n"
            )

            response = self.client.chat.completions.create(
                model=self.fallback_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ],
                temperature=0.1
            )

            result = response.choices[0].message.content
            logger.info(f"[DEBUG] フォールバックAI応答: {result}")
            parsed = self._parse_ai_response(result)

            # task_typeを上書き
            if parsed and isinstance(parsed, dict):
                parsed['task_type'] = task_type

            return parsed if parsed else {"error": "パース失敗"}

        except Exception as e:
            logger.error(f"[ERROR] _extract_dates_fallback エラー: {e}")
            return {"error": str(e)}

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
        from datetime import datetime, timedelta
        import re
        from dateutil import parser as date_parser
        jst = pytz.timezone('Asia/Tokyo')
        now = datetime.now(jst)
        logger = logging.getLogger("ai_service")
        print(f"[DEBUG] _supplement_times開始: parsed={parsed}")
        print(f"[DEBUG] 元テキスト: {original_text}")
        if not parsed or 'dates' not in parsed:
            print(f"[DEBUG] datesが存在しない: {parsed}")
            return parsed

        # 元のテキストから日付範囲（例：12/5-12/28）を直接検出して展開
        # パターン: M/D-M/D または M月D日-M月D日
        date_range_patterns = [
            (r'(\d{1,2})/(\d{1,2})[/\-〜~](\d{1,2})/(\d{1,2})', True),  # 12/5-12/28
            (r'(\d{1,2})月(\d{1,2})日[/\-〜~](\d{1,2})月(\d{1,2})日', False),  # 12月5日-12月28日
        ]

        for pattern, is_slash_format in date_range_patterns:
            match = re.search(pattern, original_text)
            if match:
                print(f"[DEBUG] 日付範囲パターンを検出: {match.group(0)}")
                try:
                    if is_slash_format:
                        # 12/5-12/28 形式
                        start_month = int(match.group(1))
                        start_day = int(match.group(2))
                        end_month = int(match.group(3))
                        end_day = int(match.group(4))
                    else:
                        # 12月5日-12月28日 形式
                        start_month = int(match.group(1))
                        start_day = int(match.group(2))
                        end_month = int(match.group(3))
                        end_day = int(match.group(4))

                    # 年を決定（現在の年、または来年）
                    current_year = now.year
                    start_date = datetime(current_year, start_month, start_day).date()
                    end_date = datetime(current_year, end_month, end_day).date()

                    # 開始日が過去の場合は来年
                    if start_date < now.date():
                        start_date = datetime(current_year + 1, start_month, start_day).date()
                        end_date = datetime(current_year + 1, end_month, end_day).date()

                    # 日付範囲を展開
                    print(f"[DEBUG] 日付範囲を展開: {start_date} から {end_date} まで")
                    expanded_dates = []
                    current_date = start_date
                    while current_date <= end_date:
                        expanded_dates.append({
                            'date': current_date.strftime('%Y-%m-%d'),
                            'time': '09:00',
                            'end_time': '18:00'
                        })
                        current_date += timedelta(days=1)

                    # parsed['dates']を展開された日付で置き換え
                    if expanded_dates:
                        print(f"[DEBUG] 日付範囲を {len(expanded_dates)} 件に展開")
                        parsed['dates'] = expanded_dates
                        break
                except Exception as e:
                    print(f"[DEBUG] 日付範囲の展開エラー: {e}")

        allday_dates = set()
        new_dates = []
        # 1. AI抽出を最優先。time, end_timeが空欄のものだけ補完
        # ただし、「今週」「来週」が含まれる場合は、AIが抽出した時間範囲を無視して09:00-18:00に上書き
        has_this_week = '今週' in original_text
        has_next_week = '来週' in original_text
        for d in parsed['dates']:
            print(f"[DEBUG] datesループ: {d}")
            phrase = d.get('description', '') or original_text

            # 日付範囲（end_date）がある場合は展開
            if d.get('end_date'):
                start_date_str = d.get('date')
                end_date_str = d.get('end_date')
                print(f"[DEBUG] 日付範囲を検出: {start_date_str} から {end_date_str} まで展開")
                try:
                    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                    current_date = start_date
                    while current_date <= end_date:
                        date_entry = d.copy()
                        date_entry['date'] = current_date.strftime('%Y-%m-%d')
                        date_entry.pop('end_date', None)  # end_dateフィールドを削除
                        # 時間範囲が設定されていない場合は09:00-18:00を設定
                        if not date_entry.get('time'):
                            date_entry['time'] = '09:00'
                        if not date_entry.get('end_time'):
                            date_entry['end_time'] = '18:00'
                        new_dates.append(date_entry)
                        print(f"[DEBUG] 日付範囲から日付を追加: {current_date.strftime('%Y-%m-%d')}")
                        current_date += timedelta(days=1)
                    continue  # 元のエントリはスキップ（展開済み）
                except Exception as e:
                    print(f"[DEBUG] 日付範囲の展開エラー: {e}")
                    # エラーが発生した場合は元のエントリをそのまま使用

            # 「今週」「来週」が含まれる場合は、時間範囲を無視して処理を続行（後で上書きされる）
            if (has_this_week or has_next_week) and d.get('time') and d.get('end_time'):
                print(f"[DEBUG] 今週/来週が含まれるため、AIが抽出した時間範囲 {d.get('time')}-{d.get('end_time')} を無視")
                # 時間範囲をクリアして、後で09:00-18:00に設定されるようにする
                d['time'] = None
                d['end_time'] = None
            # time, end_timeが両方セットされていれば何もしない
            if d.get('time') and d.get('end_time'):
                new_dates.append(d)
                continue
            # time, end_timeが空欄の場合のみ補完
            # 範囲表現
            range_match = re.search(r'(\d{1,2})[\-〜~](\d{1,2})時', phrase)
            if range_match:
                d['time'] = f"{int(range_match.group(1)):02d}:00"
                d['end_time'] = f"{int(range_match.group(2)):02d}:00"
            # 18時以降
            if (not d.get('time') or not d.get('end_time')) and re.search(r'(\d{1,2})時以降', phrase):
                m = re.search(r'(\d{1,2})時以降', phrase)
                if m:
                    d['time'] = f"{int(m.group(1)):02d}:00"
                    d['end_time'] = '23:59'
            # 終日
            if (not d.get('time') and not d.get('end_time')) or re.search(r'終日', phrase):
                d['time'] = '00:00'
                d['end_time'] = '23:59'
                if d.get('date') in allday_dates:
                    print(f"[DEBUG] 同じ日付の終日予定はスキップ: {d.get('date')}")
                    continue
                allday_dates.add(d.get('date'))
            # 明日
            if re.search(r'明日', phrase):
                d['date'] = (now + timedelta(days=1)).strftime('%Y-%m-%d')
                if not d.get('time'):
                    d['time'] = '09:00'
                if not d.get('end_time'):
                    d['end_time'] = '18:00'
            # 今日
            if re.search(r'今日', phrase):
                d['date'] = now.strftime('%Y-%m-%d')
                # 今日X時の形式を処理
                time_match = re.search(r'今日(\d{1,2})時', phrase)
                if time_match:
                    hour = int(time_match.group(1))
                    d['time'] = f"{hour:02d}:00"
                    d['end_time'] = f"{hour+1:02d}:00"
                elif not d.get('time'):
                    d['time'] = now.strftime('%H:%M')
                # 今日の場合は終了時間を1時間後に強制設定（AIの設定を上書き）
                if d.get('time'):
                    from datetime import datetime, timedelta
                    time_obj = datetime.strptime(d.get('time'), "%H:%M")
                    end_time_obj = time_obj + timedelta(hours=1)
                    d['end_time'] = end_time_obj.strftime('%H:%M')
                    print(f"[DEBUG] 今日の終了時間を1時間後に強制設定: {d.get('time')} -> {d['end_time']}")
            # 本日
            if re.search(r'本日', phrase):
                d['date'] = now.strftime('%Y-%m-%d')
                # 本日X時の形式を処理
                time_match = re.search(r'本日(\d{1,2})時', phrase)
                if time_match:
                    hour = int(time_match.group(1))
                    d['time'] = f"{hour:02d}:00"
                    d['end_time'] = f"{hour+1:02d}:00"
                    print(f"[DEBUG] 本日X時の処理: {hour}時 -> {hour+1}時")
                elif not d.get('time'):
                    d['time'] = now.strftime('%H:%M')
                # 本日の場合は終了時間を1時間後に強制設定（AIの設定を上書き）
                if d.get('time'):
                    from datetime import datetime, timedelta
                    time_obj = datetime.strptime(d.get('time'), "%H:%M")
                    end_time_obj = time_obj + timedelta(hours=1)
                    d['end_time'] = end_time_obj.strftime('%H:%M')
                    print(f"[DEBUG] 本日の終了時間を1時間後に強制設定: {d.get('time')} -> {d['end_time']}")
            # 今週
            if re.search(r'今週', phrase):
                # 今週の月曜日を計算
                current_weekday = now.weekday()
                # 現在の曜日から今週の月曜日までの日数を計算（マイナス値になる）
                days_until_monday = -current_weekday
                this_monday = now + timedelta(days=days_until_monday)
                # 日付のみを取得（時刻は0:00に、タイムゾーンは維持）
                this_monday_date = this_monday.date()

                # 今週の7日間を生成
                week_dates = []
                for i in range(7):
                    week_date = this_monday_date + timedelta(days=i)
                    week_dates.append(week_date.strftime('%Y-%m-%d'))

                # 今週の各日付に対して空き時間確認のエントリを作成
                # 「X時間空いている」という表現がある場合でも、時間範囲は09:00-18:00に設定
                for week_date in week_dates:
                    week_entry = {
                        'date': week_date,
                        'time': '09:00',
                        'end_time': '18:00'
                    }
                    if not any(existing.get('date') == week_date for existing in new_dates):
                        new_dates.append(week_entry)
                        print(f"[DEBUG] 今週の日付を追加: {week_date} (時間範囲: 09:00-18:00)")

                # 元のエントリは削除（今週の処理で置き換え）
                continue
            # 来週
            if re.search(r'来週', phrase):
                # 来週の月曜日を計算
                # 月曜日(0)の場合: 来週の月曜日は7日後
                # 火曜日(1)の場合: 来週の月曜日は6日後
                # 水曜日(2)の場合: 来週の月曜日は5日後
                # 木曜日(3)の場合: 来週の月曜日は4日後
                # 金曜日(4)の場合: 来週の月曜日は3日後
                # 土曜日(5)の場合: 来週の月曜日は2日後
                # 日曜日(6)の場合: 来週の月曜日は1日後
                current_weekday = now.weekday()
                if current_weekday == 0:  # 月曜日の場合
                    days_until_next_monday = 7
                else:
                    days_until_next_monday = (7 - current_weekday) % 7
                    if days_until_next_monday == 0:
                        days_until_next_monday = 7
                next_monday = now + timedelta(days=days_until_next_monday)

                # 来週の7日間を生成
                week_dates = []
                for i in range(7):
                    week_date = next_monday + timedelta(days=i)
                    week_dates.append(week_date.strftime('%Y-%m-%d'))

                # 来週の各日付に対して空き時間確認のエントリを作成
                # 「X時間空いている」という表現がある場合でも、時間範囲は09:00-18:00に設定
                for week_date in week_dates:
                    week_entry = {
                        'date': week_date,
                        'time': '09:00',
                        'end_time': '18:00'
                    }
                    if not any(existing.get('date') == week_date for existing in new_dates):
                        new_dates.append(week_entry)
                        print(f"[DEBUG] 来週の日付を追加: {week_date} (時間範囲: 09:00-18:00)")

                # 元のエントリは削除（来週の処理で置き換え）
                continue
            # 今日から1週間
            if re.search(r'今日から1週間', phrase):
                d['date'] = now.strftime('%Y-%m-%d')
                d['end_date'] = (now + timedelta(days=6)).strftime('%Y-%m-%d')
                d['time'] = '00:00'
                d['end_time'] = '23:59'
            # end_timeが空
            if d.get('time') and not d.get('end_time'):
                # 終了時間が設定されていない場合は1時間後に設定
                from datetime import datetime, timedelta
                time_obj = datetime.strptime(d.get('time'), "%H:%M")
                end_time_obj = time_obj + timedelta(hours=1)
                d['end_time'] = end_time_obj.strftime('%H:%M')
            # title補完
            if not d.get('title') or d['title'] == '':
                if d.get('description'):
                    d['title'] = d['description']
                elif parsed.get('task_type') == 'add_event':
                    t = d.get('time', '')
                    e = d.get('end_time', '')
                    d['title'] = f"予定（{d.get('date', '')} {t}〜{e}）"
            new_dates.append(d)
        print(f"[DEBUG] new_dates(AI+補完): {new_dates}")
        # 2. 正規表現で漏れた枠を「追加」する（AI抽出に無い場合のみ）
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
                print(f"[DEBUG] pattern1で追加: {new_date_entry}")
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
                print(f"[DEBUG] pattern2で追加: {new_date_entry}")
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
                print(f"[DEBUG] pattern3で追加: {new_date_entry}")

        # 月が指定されていない場合（例：16日11:30-14:00）の処理
        pattern4 = r'(\d{1,2})日\s*([0-9]{1,2}):?([0-9]{0,2})[\-〜~]([0-9]{1,2}):?([0-9]{0,2})'
        matches4 = re.findall(pattern4, original_text)
        print(f"[DEBUG] pattern4マッチ（日のみ）: {matches4}")
        for m in matches4:
            day, sh, sm, eh, em = m
            year = now.year
            month = now.month
            try:
                dt = datetime(year, month, int(day))
                # 過去の日付の場合は来月として扱う
                if dt < now:
                    if month == 12:
                        dt = datetime(year+1, 1, int(day))
                    else:
                        dt = datetime(year, month+1, int(day))
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
                print(f"[DEBUG] pattern4で追加（日のみ）: {new_date_entry}")

        # 複数の時間帯が同じ日に指定されている場合（例：16日11:30-14:00/15:00-17:00）
        pattern5 = r'(\d{1,2})日\s*([0-9]{1,2}):?([0-9]{0,2})[\-〜~]([0-9]{1,2}):?([0-9]{0,2})/([0-9]{1,2}):?([0-9]{0,2})[\-〜~]([0-9]{1,2}):?([0-9]{0,2})'
        matches5 = re.findall(pattern5, original_text)
        print(f"[DEBUG] pattern5マッチ（日のみ複数時間帯）: {matches5}")
        for m in matches5:
            day, sh1, sm1, eh1, em1, sh2, sm2, eh2, em2 = m
            year = now.year
            month = now.month
            try:
                dt = datetime(year, month, int(day))
                # 過去の日付の場合は来月として扱う
                if dt < now:
                    if month == 12:
                        dt = datetime(year+1, 1, int(day))
                    else:
                        dt = datetime(year, month+1, int(day))
            except Exception:
                continue
            date_str = dt.strftime('%Y-%m-%d')

            # 1つ目の時間帯
            start_time1 = f"{int(sh1):02d}:{sm1 if sm1 else '00'}"
            end_time1 = f"{int(eh1):02d}:{em1 if em1 else '00'}"
            if not any(d.get('date') == date_str and d.get('time') == start_time1 and d.get('end_time') == end_time1 for d in new_dates):
                new_date_entry1 = {
                    'date': date_str,
                    'time': start_time1,
                    'end_time': end_time1,
                    'description': ''
                }
                if parsed.get('task_type') == 'add_event':
                    new_date_entry1['title'] = f"予定（{date_str} {start_time1}〜{end_time1}）"
                new_dates.append(new_date_entry1)
                print(f"[DEBUG] pattern5で追加（1つ目）: {new_date_entry1}")

            # 2つ目の時間帯
            start_time2 = f"{int(sh2):02d}:{sm2 if sm2 else '00'}"
            end_time2 = f"{int(eh2):02d}:{em2 if em2 else '00'}"
            if not any(d.get('date') == date_str and d.get('time') == start_time2 and d.get('end_time') == end_time2 for d in new_dates):
                new_date_entry2 = {
                    'date': date_str,
                    'time': start_time2,
                    'end_time': end_time2,
                    'description': ''
                }
                if parsed.get('task_type') == 'add_event':
                    new_date_entry2['title'] = f"予定（{date_str} {start_time2}〜{end_time2}）"
                new_dates.append(new_date_entry2)
                print(f"[DEBUG] pattern5で追加（2つ目）: {new_date_entry2}")

        # より柔軟な日付解析：改行やスペースで区切られた複数の日付に対応
        # 例：「16日11:30-14:00/15:00-17:00\n17日18:00-19:00\n18日9:00-10:00/16:00-16:30/17:30-18:00」
        lines = original_text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 各行から日付を抽出
            day_match = re.search(r'(\d{1,2})日', line)
            if not day_match:
                continue

            day = int(day_match.group(1))
            year = now.year
            month = now.month

            try:
                dt = datetime(year, month, day)
                # 過去の日付の場合は来月として扱う
                if dt < now:
                    if month == 12:
                        dt = datetime(year+1, 1, day)
                    else:
                        dt = datetime(year, month+1, day)
            except Exception:
                continue

            date_str = dt.strftime('%Y-%m-%d')

            # 時間帯を抽出（複数の時間帯に対応）
            time_pattern = r'([0-9]{1,2}):?([0-9]{0,2})[\-〜~]([0-9]{1,2}):?([0-9]{0,2})'
            time_matches = re.findall(time_pattern, line)

            for time_match in time_matches:
                sh, sm, eh, em = time_match
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
                    print(f"[DEBUG] 柔軟な日付解析で追加: {new_date_entry}")

        # 本日/今日の処理を追加（AIが既に予定を作成していない場合のみ）
        if ('本日' in original_text or '今日' in original_text) and not new_dates:
            date_str = now.strftime('%Y-%m-%d')

            # 時間の抽出
            time_pattern = r'(本日|今日)(\d{1,2})時'
            time_match = re.search(time_pattern, original_text)

            if time_match:
                hour = int(time_match.group(2))
                start_time = f"{hour:02d}:00"
                end_time = f"{hour+1:02d}:00"

                # タイトルを抽出
                title_parts = original_text.split()
                title = ""
                for part in title_parts:
                    if part in ['移動', '移動あり', '移動時間', '移動必要']:
                        break
                    if not re.match(r'^\d{1,2}時$', part) and part not in ['本日', '今日']:
                        if title:
                            title += " "
                        title += part

                if not title:
                    title = "予定"

                print(f"[DEBUG] 抽出されたタイトル: '{title}'")

                # メイン予定を作成
                main_event = {
                    'date': date_str,
                    'time': start_time,
                    'end_time': end_time,
                    'title': title,
                    'description': ''
                }

                new_dates.append(main_event)
                print(f"[DEBUG] 本日/今日の予定を追加: {main_event}")

        print(f"[DEBUG] new_dates(正規表現追加後): {new_dates}")

        # 移動時間の自動追加処理（予定追加の場合のみ）
        if parsed.get('task_type') == 'add_event':
            new_dates = self._add_travel_time(new_dates, original_text)
        else:
            print(f"[DEBUG] 空き時間確認のため、移動時間の自動追加をスキップ")

        parsed['dates'] = new_dates
        return parsed

    def _add_travel_time(self, dates, original_text):
        """移動時間を自動追加する処理"""
        from datetime import datetime, timedelta
        import pytz

        # 移動キーワードをチェック
        travel_keywords = ['移動', '移動あり', '移動時間', '移動必要']
        has_travel = any(keyword in original_text for keyword in travel_keywords)

        print(f"[DEBUG] 移動時間チェック: original_text='{original_text}', has_travel={has_travel}")
        print(f"[DEBUG] 移動キーワード: {travel_keywords}")

        if not has_travel:
            print(f"[DEBUG] 移動キーワードが見つからないため、移動時間を追加しません")
            return dates

        print(f"[DEBUG] 移動時間の自動追加を開始")

        jst = pytz.timezone('Asia/Tokyo')
        new_dates = []

        for date_info in dates:
            # 元の予定を追加
            new_dates.append(date_info)

            # 移動時間を追加するかチェック
            if self._should_add_travel_time(date_info, original_text):
                travel_events = self._create_travel_events(date_info, jst)

                # 移動時間の重複チェック
                for travel_event in travel_events:
                    is_duplicate = False
                    for existing_date in new_dates:
                        if (existing_date.get('date') == travel_event.get('date') and
                            existing_date.get('time') == travel_event.get('time') and
                            existing_date.get('end_time') == travel_event.get('end_time')):
                            is_duplicate = True
                            print(f"[DEBUG] 重複する移動時間をスキップ: {travel_event}")
                            break

                    if not is_duplicate:
                        new_dates.append(travel_event)
                        print(f"[DEBUG] 移動時間を追加: {travel_event}")

        return new_dates

    def _should_add_travel_time(self, date_info, original_text):
        """移動時間を追加すべきかチェック"""
        # 移動キーワードが含まれている場合のみ追加
        travel_keywords = ['移動', '移動あり', '移動時間', '移動必要']
        result = any(keyword in original_text for keyword in travel_keywords)
        print(f"[DEBUG] _should_add_travel_time: original_text='{original_text}', result={result}")
        return result

    def _create_travel_events(self, main_event, jst):
        """移動時間の予定を作成"""
        from datetime import datetime, timedelta

        print(f"[DEBUG] _create_travel_events開始: main_event={main_event}")
        travel_events = []
        date_str = main_event['date']
        start_time = main_event['time']
        end_time = main_event['end_time']

        # 開始時間と終了時間をdatetimeオブジェクトに変換
        start_dt = jst.localize(datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M"))
        end_dt = jst.localize(datetime.strptime(f"{date_str} {end_time}", "%Y-%m-%d %H:%M"))

        # 移動前の予定（1時間前）
        travel_before_dt = start_dt - timedelta(hours=1)
        travel_before_end_dt = start_dt

        travel_before_event = {
            'date': date_str,
            'time': travel_before_dt.strftime('%H:%M'),
            'end_time': travel_before_end_dt.strftime('%H:%M'),
            'title': '移動時間（往路）',
            'description': '移動のための時間'
        }
        travel_events.append(travel_before_event)

        # 移動後の予定（1時間後）
        travel_after_dt = end_dt
        travel_after_end_dt = end_dt + timedelta(hours=1)

        travel_after_event = {
            'date': date_str,
            'time': travel_after_dt.strftime('%H:%M'),
            'end_time': travel_after_end_dt.strftime('%H:%M'),
            'title': '移動時間（復路）',
            'description': '移動のための時間'
        }
        travel_events.append(travel_after_event)

        print(f"[DEBUG] 作成された移動時間イベント: {travel_events}")
        return travel_events

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
                model=self.model,
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
                model=self.model,
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

    def format_free_slots_response_by_frame(self, free_slots_by_frame, min_free_hours=None):
        """
        free_slots_by_frame: [
            {'date': 'YYYY-MM-DD', 'start_time': 'HH:MM', 'end_time': 'HH:MM', 'free_slots': [{'start': 'HH:MM', 'end': 'HH:MM'}, ...]},
            ...
        ]
        日付ごとに空き時間をまとめて返す（重複枠・重複時間帯は除外）
        """
        print(f"[DEBUG] format_free_slots_response_by_frame開始")
        print(f"[DEBUG] 入力データ: {free_slots_by_frame}")
        print(f"[DEBUG] min_free_hours: {min_free_hours}")

        jst = pytz.timezone('Asia/Tokyo')
        if not free_slots_by_frame:
            print(f"[DEBUG] free_slots_by_frameが空")
            if min_free_hours:
                return f"✅{min_free_hours}時間以上連続して空いている時間はありませんでした。"
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

        if min_free_hours:
            response = f"✅{min_free_hours}時間以上連続して空いている時間です！\n\n"
        else:
            response = "✅以下が空き時間です！\n\n"
        for date in sorted(date_slots.keys()):
            slots = sorted(list(date_slots[date]))
            print(f"[DEBUG] 日付{date}の最終空き時間: {slots}")

            # 空き時間がない日付は表示しない
            if not slots:
                continue

            # 空き時間がある日付のみ表示
            dt = jst.localize(datetime.strptime(date, "%Y-%m-%d"))
            weekday = "月火水木金土日"[dt.weekday()]
            response += f"{dt.month}/{dt.day}（{weekday}）\n"

            for start, end in slots:
                response += f"・{start}〜{end}\n"

        # 全ての日付で空き時間がない場合
        if min_free_hours:
            expected_response_start = f"✅{min_free_hours}時間以上連続して空いている時間です！\n\n"
        else:
            expected_response_start = "✅以下が空き時間です！\n\n"

        if response == expected_response_start:
            if min_free_hours:
                return f"✅{min_free_hours}時間以上連続して空いている時間はありませんでした。"
            return "✅空き時間はありませんでした。"

        print(f"[DEBUG] 最終レスポンス: {response}")
        return response
