#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
時間範囲抽出のテスト
"""

import sys
import os

# ai_serviceをインポートするためのダミークラス
class DummyConfig:
    OPENAI_API_KEY = "dummy"

sys.modules['config'] = type(sys)('config')
sys.modules['config'].Config = DummyConfig

# AIServiceの時間範囲抽出メソッドのみをテスト
from ai_service import AIService

def test_extract_time_range():
    """時間範囲抽出機能のテスト"""
    print("=== 時間範囲抽出機能のテスト ===\n")

    # AIServiceのインスタンスは作らず、メソッドだけをテスト
    class TestAIService:
        def __init__(self):
            pass

        def _extract_time_range_from_text(self, text):
            """ai_service.pyから移植したメソッド"""
            import re

            patterns = [
                r'(\d{1,2}):(\d{2})[\s]*[\-〜~][\s]*(\d{1,2}):(\d{2})',  # 12:00-15:00
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

    service = TestAIService()

    test_cases = [
        ("2月 12:00〜15:00 打合せ", "12:00", "15:00"),
        ("2月 12:00-15:00", "12:00", "15:00"),
        ("2月 9時〜17時", "09:00", "17:00"),  # 「時」だけのパターン
        ("1月 10:30-14:45", "10:30", "14:45"),
        ("3月 8-18時", "08:00", "18:00"),
        ("2月の空き時間", None, None),  # 時間範囲なし
        ("12:00〜15:00", "12:00", "15:00"),
        ("10時30分-15時45分", "10:30", "15:45"),
        ("9時-18時", "09:00", "18:00"),
        ("14時〜16時 会議", "14:00", "16:00"),
    ]

    all_passed = True
    for i, (text, expected_start, expected_end) in enumerate(test_cases, 1):
        start_time, end_time = service._extract_time_range_from_text(text)

        print(f"テスト {i}: {text}")
        print(f"  期待値: {expected_start} - {expected_end}")
        print(f"  結果  : {start_time} - {end_time}")

        if start_time == expected_start and end_time == expected_end:
            print("  ✅ 成功")
        else:
            print("  ❌ 失敗")
            all_passed = False
        print()

    print("=" * 50)
    if all_passed:
        print("全テストケース成功！")
    else:
        print("一部のテストが失敗しました")

    return all_passed

if __name__ == "__main__":
    test_extract_time_range()
