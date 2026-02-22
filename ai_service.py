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

    def extract_dates_and_times(self, text, conversation_history=None):
        """
        テキストから日時を抽出します（空き時間確認専用）
        Function Callingを使用して精度向上

        Args:
            text: ユーザーの入力テキスト
            conversation_history: 会話履歴（形式: [{"role": "user"/"assistant", "content": "..."}]）
        """
        try:
            # 日時の詳細抽出（Function Calling使用）
            extraction_result = self._extract_dates_with_function_calling(text, conversation_history)
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
                "error": "日時情報を正しく認識できませんでした。\n\n日時を入力すると空き時間を返します。\n\n例：\n『明日の空き時間』\n『来週月曜日 9-18時』\n『12/5-12/10の空き時間』"
            }

    def _extract_dates_with_function_calling(self, text, conversation_history=None):
        """
        Function Callingを使用した日時抽出（空き時間確認専用）
        より構造化された正確な出力を得る

        Args:
            text: ユーザーの入力テキスト
            conversation_history: 会話履歴（形式: [{"role": "user"/"assistant", "content": "..."}]）
        """
        try:
            now_jst = self._get_jst_now_str()

            # Function Callingの定義（空き時間確認専用）
            functions = [
                {
                    "name": "extract_availability_check",
                    "description": "ユーザーのメッセージから空き時間確認のための日程・時間・移動情報を抽出する",
                    "parameters": {
                        "type": "object",
                        "properties": {
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
                                        }
                                    },
                                    "required": ["date"]
                                }
                            },
                            "location": {
                                "type": "string",
                                "description": "目的地の場所（横浜、大阪など、打ち合わせや予定がある場所）"
                            },
                            "current_location": {
                                "type": "string",
                                "description": "現在地（銀座、新宿など、ユーザーが今いる場所）"
                            },
                            "meeting_duration_hours": {
                                "type": "number",
                                "description": "打ち合わせや予定の所要時間（時間単位）。「2時間打ち合わせ」なら2.0"
                            }
                        },
                        "required": ["dates"]
                    }
                }
            ]

            system_prompt = f"""あなたは空き時間確認専用のAIアシスタントです。

【現在の日時（日本時間）】
{now_jst}

【重要な指示】
1. この日時を**絶対的な基準**として使用してください
2. 「今日」「明日」「来週」などの相対的な表現を正確に変換してください
3. 年月日は必ずYYYY-MM-DD形式で出力してください
4. 時刻は必ずHH:MM形式（24時間表記）で出力してください

【月の解釈ルール】
- 月だけが指定された場合（例：「1月」「2月」）、その月が現在の月より過去であれば来年として解釈してください
- 例: 現在が12月の場合、「1月」→ 来年の1月、「11月」→ 来年の11月
- 例: 現在が3月の場合、「2月」→ 来年の2月、「4月」→ 今年の4月

【日付範囲の処理】
- 「12/5-12/28」のような範囲表記は、開始日から終了日まで**全ての日付を個別に展開**してください
- 例: 「12/5-12/10」→ 12/5, 12/6, 12/7, 12/8, 12/9, 12/10 の6件
- 日付範囲で月をまたぐ場合（例：「12/25-1/5」）は適切に年を判断してください

【週の処理】
- 「今週」→ 今週の月曜日から日曜日まで7日間を展開
- 「来週」→ 来週の月曜日から日曜日まで7日間を展開

【時間範囲の処理】
**明示的な時間指定がある場合:**
- 「9-10時」→ time: "09:00", end_time: "10:00"
- 「18時以降」→ time: "18:00", end_time: "22:00"
- 「18時以前」→ time: "08:00", end_time: "18:00"
- 「終日」→ time: "00:00", end_time: "23:59"

**文脈から時間を推測する場合（キーワードや文脈から自然な時間帯を判断）:**
- 「ランチ」「昼食」「お昼」「昼ご飯」などの表現 → time: "11:00", end_time: "14:00"
- 「朝食」「モーニング」「朝ご飯」「朝」などの表現 → time: "07:00", end_time: "10:00"
- 「夕食」「ディナー」「夜ご飯」「晩ご飯」などの表現 → time: "18:00", end_time: "22:00"
- 「会食」→ 文脈から昼食なら11:00-14:00、夕食なら18:00-22:00
- 「午前」→ time: "09:00", end_time: "12:00"
- 「午後」→ time: "13:00", end_time: "18:00"
- 「カフェ」「お茶」「コーヒー」→ 文脈から適切な時間帯（午後なら13:00-18:00）
- 「飲み」「飲み会」「bar」→ time: "18:00", end_time: "22:00"

**時間指定も文脈もない場合:**
- time: "08:00", end_time: "22:00"（デフォルト）

**重要**: ユーザーの自然な表現から意図を理解し、適切な時間帯を推測してください。キーワードを厳密にマッチさせる必要はありません。

【複数時間帯の処理】
- 「15:00-16:00 18:00-19:00」のように複数の時間帯がある場合は、別々のエントリとして抽出
- 改行や箇条書き（・や-）で区切られた日時も全て抽出

【最小連続空き時間】
- 「2時間空いている」「3時間空いてる」という表現の「X時間」は時間範囲ではなく、条件です
- この場合は時間範囲を指定せず、デフォルト（08:00-22:00）を使用してください

【場所による日付フィルタリング】
- 「〇〇で会食できる日は？」「〇〇で予定を入れたい」のような表現の場合:
  - 〇〇 → location（カレンダーで該当の場所マーカーがある日だけを検索）
- 例: 「東京で会食できる日は？」「東京で空いている日は？」
  → location: "東京"（カレンダーに「東京」という終日予定がある日だけを検索）
- 例: 「大阪で打ち合わせできる日は？」
  → location: "大阪"（カレンダーに「大阪」という終日予定がある日だけを検索）
- 例: 「福岡で予定を入れたい」
  → location: "福岡"

【移動と打ち合わせの処理】
- 「今〇〇にいて、△△で×時間打ち合わせ」のような表現を正確に理解してください:
  - 〇〇 → current_location（現在地）
  - △△ → location（目的地）
  - ×時間 → meeting_duration_hours（打ち合わせ時間）
- 例: 「今銀座にいて、横浜で2時間打ち合わせ」
  → current_location: "銀座", location: "横浜", meeting_duration_hours: 2.0
- 例: 「渋谷から品川に行って3時間会議」
  → current_location: "渋谷", location: "品川", meeting_duration_hours: 3.0
- この情報は移動時間の計算に使用されます
- **重要**: current_locationとmeeting_duration_hoursが両方指定されている場合のみ移動時間計算を行います
  - 場所フィルタのみの場合はlocationのみを指定し、current_locationとmeeting_duration_hoursは指定しないでください

【例】
入力: 「明日と明後日の空き時間」
→ dates: [{{date: "2025-XX-XX", time: "08:00", end_time: "22:00"}}, {{date: "2025-XX-XX", time: "08:00", end_time: "22:00"}}]

入力: 「明日ランチできる？」
→ dates: [{{date: "2025-XX-XX", time: "11:00", end_time: "14:00"}}]

入力: 「来週モーニングで会える日は？」
→ dates: [{{date: "2025-XX-XX", time: "07:00", end_time: "10:00"}}, ... (7日間)]

入力: 「今週の夜ご飯空いてる？」
→ dates: [{{date: "2025-XX-XX", time: "18:00", end_time: "22:00"}}, ... (7日間)]

入力: 「7/10 9-10時」
→ dates: [{{date: "2025-07-10", time: "09:00", end_time: "10:00"}}]

入力: 「12/5-12/10の空き時間」
→ dates: [{{date: "2025-12-05", time: "08:00", end_time: "22:00"}}, {{date: "2025-12-06", ...}}, ..., {{date: "2025-12-10", ...}}]

入力: 「来週2時間空いている日」
→ dates: [{{date: "2025-XX-XX", time: "08:00", end_time: "22:00"}}, ... (7日間)]

入力: 「1月の空き時間」（現在が2025年12月の場合）
→ dates: [{{date: "2026-01-01", time: "08:00", end_time: "22:00"}}, ... (1月の全日)]

入力: 「3月18時以降、東京で会食できる日は？」
→ dates: [{{date: "2025-03-01", time: "18:00", end_time: "22:00"}}, ... (3月の全日)], location: "東京"

入力: 「来週大阪で空いている日は？」
→ dates: [{{date: "2025-XX-XX", time: "08:00", end_time: "22:00"}}, ... (7日間)], location: "大阪"
"""

            # メッセージリストを構築
            messages = [{"role": "system", "content": system_prompt}]

            # 会話履歴があれば追加（最新5件まで）
            if conversation_history:
                for msg in conversation_history[-5:]:
                    messages.append({"role": msg["role"], "content": msg["content"]})

            # 現在のユーザー入力を追加
            messages.append({"role": "user", "content": text})

            # Function Callingを使用
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                functions=functions,
                function_call={"name": "extract_availability_check"},
                temperature=0.1
            )

            # Function Callingの結果を取得
            message = response.choices[0].message

            if message.function_call:
                function_args = json.loads(message.function_call.arguments)
                logger.info(f"[DEBUG] Function Calling結果: {function_args}")

                # task_typeを常にavailability_checkに設定
                function_args['task_type'] = 'availability_check'

                return function_args
            else:
                # Function Callが失敗した場合はフォールバック
                logger.warning("[WARN] Function Callingが失敗、フォールバック処理")
                return self._extract_dates_fallback(text)

        except Exception as e:
            logger.error(f"[ERROR] _extract_dates_with_function_calling エラー: {e}")
            import traceback
            traceback.print_exc()
            # エラー時はフォールバック
            return self._extract_dates_fallback(text)

    def _extract_dates_fallback(self, text):
        """
        Function Calling失敗時のフォールバック処理
        従来のGPT-3.5を使用した抽出方法
        """
        try:
            now_jst = self._get_jst_now_str()
            system_prompt = (
                f"あなたは空き時間確認のAIです。\n"
                f"現在の日時（日本時間）は {now_jst} です。  \n"
                "【最重要】ユーザーの入力が箇条書き・改行・スペース・句読点で区切られている場合も、全ての時間帯・枠を必ず個別に抽出してください。\n"
                "この日時は、すべての自然言語の解釈において**常に絶対的な基準**としてください。  \n"
                "\n"
                "あなたは日時抽出の専門家です。ユーザーのテキストを分析して、以下のJSON形式で返してください。\n\n"
                "分析ルール:\n"
                "1. 複数の日時がある場合は全て抽出\n"
                "2. 日本語の日付表現（今日、明日、来週月曜日など）を具体的な日付に変換\n"
                "3. **日付範囲（例：12/5-12/28、1/10-1/20）は必ず開始日から終了日までの全ての日付を個別に抽出してください**\n"
                "4. **「今週」「来週」という表現は必ず1週間分（7日間）の日付として抽出してください**\n"
                "5. 月が指定されていない場合（例：16日、17日）は今月として認識\n"
                "6. **月だけが指定された場合（例：「1月」「2月」）、その月が現在の月より過去であれば来年として解釈してください**\n"
                "7. 時間表現（午前9時、14時30分、9-10時、9時-10時、9:00-10:00など）を24時間形式に変換\n"
                "8. task_typeは常に「availability_check」\n"
                "\n"
                "【出力例】\n"
                "{\"task_type\": \"availability_check\", \"dates\": [{\"date\": \"2025-07-08\", \"time\": \"09:00\", \"end_time\": \"18:00\"}]}\n"
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

            # task_typeを常にavailability_checkに設定
            if parsed and isinstance(parsed, dict):
                parsed['task_type'] = 'availability_check'

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

    def _extract_time_range_from_text(self, text):
        """
        テキストから時間範囲を抽出する
        Returns: (start_time, end_time) のタプル、見つからない場合は (None, None)
        """
        import re

        # 「以降」「以前」パターンを優先的にチェック
        # 18時以降 → 18:00-22:00
        after_match = re.search(r'(\d{1,2})時以降', text)
        if after_match:
            hour = int(after_match.group(1))
            return (f"{hour:02d}:00", "22:00")

        # 18時以前 → 08:00-18:00
        before_match = re.search(r'(\d{1,2})時以前', text)
        if before_match:
            hour = int(before_match.group(1))
            return ("08:00", f"{hour:02d}:00")

        # 様々な時間範囲パターンを試行（優先度順）
        patterns = [
            r'(\d{1,2}):(\d{2})[\s]*[\-〜~][\s]*(\d{1,2}):(\d{2})',  # 12:00-15:00, 12:00〜15:00
            r'(\d{1,2})時(\d{2})分?[\s]*[\-〜~][\s]*(\d{1,2})時(\d{2})分?',  # 12時00分-15時00分
            r'(\d{1,2}):(\d{2})[\s]*[\-〜~][\s]*(\d{1,2})',  # 12:00-15
            r'(\d{1,2})時[\s]*[\-〜~][\s]*(\d{1,2})時',  # 9時〜17時
            r'(\d{1,2})[\s]*[\-〜~][\s]*(\d{1,2})時',  # 12-15時
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                groups = match.groups()
                if len(groups) == 4:
                    start_hour, start_min, end_hour, end_min = groups
                    return (f"{int(start_hour):02d}:{int(start_min):02d}",
                            f"{int(end_hour):02d}:{int(end_min):02d}")
                elif len(groups) == 3:
                    start_hour, start_min, end_hour = groups
                    return (f"{int(start_hour):02d}:{int(start_min):02d}",
                            f"{int(end_hour):02d}:00")
                elif len(groups) == 2:
                    start_hour, end_hour = groups
                    return (f"{int(start_hour):02d}:00",
                            f"{int(end_hour):02d}:00")

        return (None, None)

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

        # dates が空の場合は今日の日付をデフォルトとして追加
        if not parsed.get('dates'):
            print(f"[DEBUG] datesが空のため、今日の日付をデフォルトとして追加")
            today = now.strftime('%Y-%m-%d')
            parsed['dates'] = [{
                'date': today,
                'time': '08:00',
                'end_time': '22:00'
            }]
            print(f"[DEBUG] デフォルト日付追加: {parsed['dates']}")

        # 元のテキストから日付範囲（例：12/5-12/28）を直接検出して展開
        date_range_patterns = [
            (r'(\d{1,2})/(\d{1,2})[/\-〜~](\d{1,2})/(\d{1,2})', True),
            (r'(\d{1,2})月(\d{1,2})日[/\-〜~](\d{1,2})月(\d{1,2})日', False),
        ]

        for pattern, is_slash_format in date_range_patterns:
            match = re.search(pattern, original_text)
            if match:
                print(f"[DEBUG] 日付範囲パターンを検出: {match.group(0)}")
                try:
                    if is_slash_format:
                        start_month = int(match.group(1))
                        start_day = int(match.group(2))
                        end_month = int(match.group(3))
                        end_day = int(match.group(4))
                    else:
                        start_month = int(match.group(1))
                        start_day = int(match.group(2))
                        end_month = int(match.group(3))
                        end_day = int(match.group(4))

                    current_year = now.year
                    start_date = datetime(current_year, start_month, start_day).date()
                    end_date = datetime(current_year, end_month, end_day).date()

                    if start_date < now.date():
                        start_date = datetime(current_year + 1, start_month, start_day).date()
                        end_date = datetime(current_year + 1, end_month, end_day).date()

                    print(f"[DEBUG] 日付範囲を展開: {start_date} から {end_date} まで")
                    expanded_dates = []
                    current_date = start_date
                    while current_date <= end_date:
                        expanded_dates.append({
                            'date': current_date.strftime('%Y-%m-%d'),
                            'time': '08:00',
                            'end_time': '22:00'
                        })
                        current_date += timedelta(days=1)

                    if expanded_dates:
                        print(f"[DEBUG] 日付範囲を {len(expanded_dates)} 件に展開")
                        parsed['dates'] = expanded_dates
                        break
                except Exception as e:
                    print(f"[DEBUG] 日付範囲の展開エラー: {e}")

        allday_dates = set()
        new_dates = []
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
                        date_entry.pop('end_date', None)
                        if not date_entry.get('time'):
                            date_entry['time'] = '08:00'
                        if not date_entry.get('end_time'):
                            date_entry['end_time'] = '22:00'
                        new_dates.append(date_entry)
                        print(f"[DEBUG] 日付範囲から日付を追加: {current_date.strftime('%Y-%m-%d')}")
                        current_date += timedelta(days=1)
                    continue
                except Exception as e:
                    print(f"[DEBUG] 日付範囲の展開エラー: {e}")

            # time, end_timeが両方セットされていればそのまま
            if d.get('time') and d.get('end_time'):
                new_dates.append(d)
                continue

            # time, end_timeが空欄の場合のみ補完
            range_match = re.search(r'(\d{1,2})[\-〜~](\d{1,2})時', phrase)
            if range_match:
                d['time'] = f"{int(range_match.group(1)):02d}:00"
                d['end_time'] = f"{int(range_match.group(2)):02d}:00"

            # 18時以降
            if (not d.get('time') or not d.get('end_time')) and re.search(r'(\d{1,2})時以降', phrase):
                m = re.search(r'(\d{1,2})時以降', phrase)
                if m:
                    d['time'] = f"{int(m.group(1)):02d}:00"
                    d['end_time'] = '22:00'

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
                    d['time'] = '08:00'
                if not d.get('end_time'):
                    d['end_time'] = '22:00'

            # 今日
            if re.search(r'今日', phrase):
                d['date'] = now.strftime('%Y-%m-%d')
                time_match = re.search(r'今日(\d{1,2})時', phrase)
                if time_match:
                    hour = int(time_match.group(1))
                    d['time'] = f"{hour:02d}:00"
                    d['end_time'] = f"{hour+1:02d}:00"
                elif not d.get('time'):
                    d['time'] = '08:00'
                    d['end_time'] = '22:00'

            # 本日
            if re.search(r'本日', phrase):
                d['date'] = now.strftime('%Y-%m-%d')
                time_match = re.search(r'本日(\d{1,2})時', phrase)
                if time_match:
                    hour = int(time_match.group(1))
                    d['time'] = f"{hour:02d}:00"
                    d['end_time'] = f"{hour+1:02d}:00"
                elif not d.get('time'):
                    d['time'] = '08:00'
                    d['end_time'] = '22:00'

            # 今週
            if re.search(r'今週', phrase):
                current_weekday = now.weekday()
                days_until_monday = -current_weekday
                this_monday = now + timedelta(days=days_until_monday)
                this_monday_date = this_monday.date()

                week_dates = []
                for i in range(7):
                    week_date = this_monday_date + timedelta(days=i)
                    week_dates.append(week_date.strftime('%Y-%m-%d'))

                for week_date in week_dates:
                    week_entry = {
                        'date': week_date,
                        'time': d.get('time', '08:00'),
                        'end_time': d.get('end_time', '22:00')
                    }
                    if not any(existing.get('date') == week_date for existing in new_dates):
                        new_dates.append(week_entry)
                        print(f"[DEBUG] 今週の日付を追加: {week_date}, 時間: {week_entry['time']}-{week_entry['end_time']}")
                continue

            # 来週
            if re.search(r'来週', phrase):
                current_weekday = now.weekday()
                if current_weekday == 0:
                    days_until_next_monday = 7
                else:
                    days_until_next_monday = (7 - current_weekday) % 7
                    if days_until_next_monday == 0:
                        days_until_next_monday = 7
                next_monday = now + timedelta(days=days_until_next_monday)

                week_dates = []
                for i in range(7):
                    week_date = next_monday + timedelta(days=i)
                    week_dates.append(week_date.strftime('%Y-%m-%d'))

                for week_date in week_dates:
                    week_entry = {
                        'date': week_date,
                        'time': d.get('time', '08:00'),
                        'end_time': d.get('end_time', '22:00')
                    }
                    if not any(existing.get('date') == week_date for existing in new_dates):
                        new_dates.append(week_entry)
                        print(f"[DEBUG] 来週の日付を追加: {week_date}, 時間: {week_entry['time']}-{week_entry['end_time']}")
                continue

            # end_timeが空
            if d.get('time') and not d.get('end_time'):
                time_obj = datetime.strptime(d.get('time'), "%H:%M")
                end_time_obj = time_obj + timedelta(hours=1)
                d['end_time'] = end_time_obj.strftime('%H:%M')

            new_dates.append(d)

        print(f"[DEBUG] new_dates(AI+補完): {new_dates}")

        # 月だけが指定された場合の処理（例：「1月の空き時間」「2月 12:00〜15:00」）
        month_only_pattern = r'(\d{1,2})月'
        month_only_matches = re.findall(month_only_pattern, original_text)
        if month_only_matches and not re.search(r'(\d{1,2})月(\d{1,2})日', original_text):
            # 「X月Y日」の形式がない場合のみ、月だけの指定として扱う

            # テキストから時間範囲を抽出（例：「2月 12:00〜15:00」）
            extracted_start_time, extracted_end_time = self._extract_time_range_from_text(original_text)
            default_start_time = extracted_start_time if extracted_start_time else '08:00'
            default_end_time = extracted_end_time if extracted_end_time else '22:00'
            print(f"[DEBUG] 月だけ指定時の時間範囲: {default_start_time} - {default_end_time}")

            for month_str in month_only_matches:
                month = int(month_str)
                year = now.year
                start_day = 1

                # 月が現在の月より小さい場合は来年とする
                if month < now.month:
                    year = now.year + 1
                # 月が現在の月と同じ場合は、今年の現在日以降のみ
                elif month == now.month:
                    start_day = now.day

                # その月の全日を展開（既存日付の時間範囲も更新）
                try:
                    import calendar as cal
                    _, last_day = cal.monthrange(year, month)
                    for day in range(start_day, last_day + 1):
                        date_str = f"{year}-{month:02d}-{day:02d}"

                        # 既に存在する日付を探す
                        existing_date = None
                        for d in new_dates:
                            if d.get('date') == date_str:
                                existing_date = d
                                break

                        if existing_date:
                            # 既存の日付の時間範囲を更新
                            existing_date['time'] = default_start_time
                            existing_date['end_time'] = default_end_time
                            print(f"[DEBUG] 月だけ指定で日付の時間範囲を更新: {date_str} {default_start_time}-{default_end_time}")
                        else:
                            # 新規追加
                            new_dates.append({
                                'date': date_str,
                                'time': default_start_time,
                                'end_time': default_end_time
                            })
                            print(f"[DEBUG] 月だけ指定で日付を追加: {date_str} {default_start_time}-{default_end_time}")
                except Exception as e:
                    print(f"[DEBUG] 月だけ指定の展開エラー: {e}")
                break  # 最初の月だけを処理

        # 正規表現で漏れた枠を追加
        pattern1 = r'(\d{1,2})/(\d{1,2})[\s　]*([0-9]{1,2}):?([0-9]{0,2})[\-〜~]([0-9]{1,2}):?([0-9]{0,2})'
        matches1 = re.findall(pattern1, original_text)
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
                new_dates.append({
                    'date': date_str,
                    'time': start_time,
                    'end_time': end_time
                })

        pattern2 = r'[・\-]\s*(\d{1,2})/(\d{1,2})\s*([0-9]{1,2})-([0-9]{1,2})時'
        matches2 = re.findall(pattern2, original_text)
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
                new_dates.append({
                    'date': date_str,
                    'time': start_time,
                    'end_time': end_time
                })

        pattern3 = r'(\d{1,2})/(\d{1,2})\s*([0-9]{1,2})時?-([0-9]{1,2})時?'
        matches3 = re.findall(pattern3, original_text)
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
                new_dates.append({
                    'date': date_str,
                    'time': start_time,
                    'end_time': end_time
                })

        pattern4 = r'(\d{1,2})日\s*([0-9]{1,2}):?([0-9]{0,2})[\-〜~]([0-9]{1,2}):?([0-9]{0,2})'
        matches4 = re.findall(pattern4, original_text)
        for m in matches4:
            day, sh, sm, eh, em = m
            year = now.year
            month = now.month
            try:
                dt = datetime(year, month, int(day))
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
                new_dates.append({
                    'date': date_str,
                    'time': start_time,
                    'end_time': end_time
                })

        pattern5 = r'(\d{1,2})日\s*([0-9]{1,2}):?([0-9]{0,2})[\-〜~]([0-9]{1,2}):?([0-9]{0,2})/([0-9]{1,2}):?([0-9]{0,2})[\-〜~]([0-9]{1,2}):?([0-9]{0,2})'
        matches5 = re.findall(pattern5, original_text)
        for m in matches5:
            day, sh1, sm1, eh1, em1, sh2, sm2, eh2, em2 = m
            year = now.year
            month = now.month
            try:
                dt = datetime(year, month, int(day))
                if dt < now:
                    if month == 12:
                        dt = datetime(year+1, 1, int(day))
                    else:
                        dt = datetime(year, month+1, int(day))
            except Exception:
                continue
            date_str = dt.strftime('%Y-%m-%d')

            start_time1 = f"{int(sh1):02d}:{sm1 if sm1 else '00'}"
            end_time1 = f"{int(eh1):02d}:{em1 if em1 else '00'}"
            if not any(d.get('date') == date_str and d.get('time') == start_time1 and d.get('end_time') == end_time1 for d in new_dates):
                new_dates.append({
                    'date': date_str,
                    'time': start_time1,
                    'end_time': end_time1
                })

            start_time2 = f"{int(sh2):02d}:{sm2 if sm2 else '00'}"
            end_time2 = f"{int(eh2):02d}:{em2 if em2 else '00'}"
            if not any(d.get('date') == date_str and d.get('time') == start_time2 and d.get('end_time') == end_time2 for d in new_dates):
                new_dates.append({
                    'date': date_str,
                    'time': start_time2,
                    'end_time': end_time2
                })

        lines = original_text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue

            day_match = re.search(r'(\d{1,2})日', line)
            if not day_match:
                continue

            day = int(day_match.group(1))
            year = now.year
            month = now.month

            try:
                dt = datetime(year, month, day)
                if dt < now:
                    if month == 12:
                        dt = datetime(year+1, 1, day)
                    else:
                        dt = datetime(year, month+1, day)
            except Exception:
                continue

            date_str = dt.strftime('%Y-%m-%d')

            time_pattern = r'([0-9]{1,2}):?([0-9]{0,2})[\-〜~]([0-9]{1,2}):?([0-9]{0,2})'
            time_matches = re.findall(time_pattern, line)

            for time_match in time_matches:
                sh, sm, eh, em = time_match
                start_time = f"{int(sh):02d}:{sm if sm else '00'}"
                end_time = f"{int(eh):02d}:{em if em else '00'}"

                if not any(d.get('date') == date_str and d.get('time') == start_time and d.get('end_time') == end_time for d in new_dates):
                    new_dates.append({
                        'date': date_str,
                        'time': start_time,
                        'end_time': end_time
                    })

        parsed['dates'] = new_dates
        parsed['task_type'] = 'availability_check'
        return parsed

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

    def check_multiple_dates_availability(self, dates_info):
        """複数の日付の空き時間を確認するための情報を抽出します"""
        try:
            now_jst = self._get_jst_now_str()
            system_prompt = (
                f"あなたは空き時間確認のAIです。\n"
                f"現在の日時（日本時間）は {now_jst} です。  \n"
                "この日時は、すべての自然言語の解釈において**常に絶対的な基準**としてください。  \n"
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

    def determine_intent(self, text, conversation_history=None):
        """
        ユーザーメッセージの意図を判断します

        Args:
            text: ユーザーの入力テキスト
            conversation_history: 会話履歴

        Returns:
            dict: {
                "needs_calendar": bool,  # スケジュール情報が必要かどうか
                "intent_type": str,      # "schedule_query" / "greeting" / "confirmation" / "other"
                "response_hint": str     # AIへのヒント
            }
        """
        try:
            now_jst = self._get_jst_now_str()

            system_prompt = f"""あなたは意図判断AIです。ユーザーのメッセージを分析し、スケジュール情報が必要かどうかを判断してください。

【現在の日時（日本時間）】
{now_jst}

【判断基準】
以下の場合は needs_calendar = true:
- 予定を確認したい（「今日の予定は？」「明日何がある？」）
- 空き時間を探したい（「明日空いてる？」「来週ランチできる？」）
- 特定の時間帯の予定を聞く（「午後の予定は？」「夜の予定ある？」）
- スケジュールに関する質問全般

以下の場合は needs_calendar = false:
- 挨拶（「こんにちは」「おはよう」「ありがとう」）
- 確認・同意（「はい」「わかった」「了解」）
- 雑談・その他（スケジュールと無関係な内容）

【intent_type】
- "schedule_query": スケジュール関連の質問
- "greeting": 挨拶
- "confirmation": 確認・同意
- "other": その他

【response_hint】
AIが応答する際のヒントを簡潔に記載してください。
例: "今日の予定を教える" / "親しみを込めて挨拶に応える" / "了解の返事をする"
"""

            messages = [{"role": "system", "content": system_prompt}]

            # 会話履歴があれば最新3件を追加
            if conversation_history:
                for msg in conversation_history[-3:]:
                    messages.append({"role": msg["role"], "content": msg["content"]})

            # 現在のユーザーメッセージ
            messages.append({"role": "user", "content": text})

            # Function Callingで意図判断
            tools = [{
                "type": "function",
                "function": {
                    "name": "determine_user_intent",
                    "description": "ユーザーの意図を判断する",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "needs_calendar": {
                                "type": "boolean",
                                "description": "スケジュール情報が必要かどうか"
                            },
                            "intent_type": {
                                "type": "string",
                                "enum": ["schedule_query", "greeting", "confirmation", "other"],
                                "description": "意図のタイプ"
                            },
                            "response_hint": {
                                "type": "string",
                                "description": "AIが応答する際のヒント"
                            }
                        },
                        "required": ["needs_calendar", "intent_type", "response_hint"]
                    }
                }
            }]

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice={"type": "function", "function": {"name": "determine_user_intent"}}
            )

            # Function Callingの結果を取得
            tool_call = response.choices[0].message.tool_calls[0]
            result = json.loads(tool_call.function.arguments)

            logger.info(f"[DEBUG] 意図判断結果: {result}")
            return result

        except Exception as e:
            logger.error(f"[ERROR] determine_intent エラー: {e}")
            import traceback
            traceback.print_exc()
            # エラー時はデフォルトでスケジュール取得を試みる
            return {
                "needs_calendar": True,
                "intent_type": "schedule_query",
                "response_hint": "スケジュール情報を提供する"
            }

    def chat_with_calendar_context(self, user_message, conversation_history=None, calendar_events=None):
        """
        カレンダー情報を含む文脈で自然な会話応答を生成します（秘書モード）

        Args:
            user_message: ユーザーの入力メッセージ
            conversation_history: 会話履歴
            calendar_events: カレンダーイベント情報（オプション）

        Returns:
            str: AI秘書の応答メッセージ
        """
        try:
            now_jst = self._get_jst_now_str()
            jst = pytz.timezone('Asia/Tokyo')
            now_dt = datetime.now(jst)

            # システムプロンプト
            system_prompt = f"""あなたは親切で有能な秘書AIアシスタントです。ユーザーのスケジュール管理をサポートします。

【現在の日時（日本時間）】
{now_jst}
{now_dt.strftime('%Y年%m月%d日 %H:%M (%A)')}

【あなたの役割】
- ユーザーのスケジュールを把握し、適切にアドバイスする秘書
- 親しみやすく、自然な日本語で会話する
- 必要に応じて絵文字を使い、温かみのある応答をする
- 予定の確認や空き時間の提案を的確に行う

【応答のスタイル】
- 簡潔で分かりやすい（長すぎない）
- 親しみやすいトーン（敬語は使うが堅苦しくない）
- 具体的で実用的な情報を提供
- ユーザーの状況に配慮した気の利いたコメントを添える

【スケジュール情報の扱い】
- 予定がある場合：時間、タイトル、場所などを分かりやすく伝える
- 忙しい場合：「今日は予定が詰まっていますね」など配慮のコメント
- 余裕がある場合：「比較的ゆとりのある一日ですね」など
- 時間帯を考慮：朝なら「おはようございます」、夜なら「お疲れ様です」など

【注意事項】
- 絵文字は適度に使用（多用しない）
- 予定がない場合は無理に情報を作らない
- 不明な点は正直に伝える
"""

            messages = [{"role": "system", "content": system_prompt}]

            # カレンダー情報があれば追加
            if calendar_events:
                calendar_info = "\n\n【現在のスケジュール情報】\n"
                calendar_info += calendar_events
                messages[0]["content"] += calendar_info

            # 会話履歴を追加（最新10件）
            if conversation_history:
                for msg in conversation_history[-10:]:
                    messages.append({"role": msg["role"], "content": msg["content"]})

            # 現在のユーザーメッセージ
            messages.append({"role": "user", "content": user_message})

            # ChatGPT風の応答生成
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,  # やや創造的な応答
                max_tokens=500
            )

            ai_response = response.choices[0].message.content
            logger.info(f"[DEBUG] 秘書モード応答: {ai_response}")

            return ai_response

        except Exception as e:
            logger.error(f"[ERROR] chat_with_calendar_context エラー: {e}")
            import traceback
            traceback.print_exc()
            return "申し訳ございません。少し調子が悪いようです。もう一度お試しいただけますか？"
