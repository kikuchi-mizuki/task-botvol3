#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2月 12:00〜15:00 打合せ のパターンをテスト
"""

from ai_service import AIService
import json

def test_february_with_time():
    ai_service = AIService()

    test_cases = [
        "2月 12:00〜15:00 打合せ",
        "2月 12:00-15:00",
        "2月12:00〜15:00の空き時間",
    ]

    for text in test_cases:
        print(f"\n{'='*60}")
        print(f"テスト入力: {text}")
        print(f"{'='*60}")

        result = ai_service.extract_dates_and_times(text)

        print("\n抽出結果:")
        print(json.dumps(result, ensure_ascii=False, indent=2))

        if 'dates' in result:
            print(f"\n抽出された日数: {len(result['dates'])}件")

            # 最初の3件だけ表示
            for i, date_info in enumerate(result['dates'][:3]):
                print(f"\n{i+1}件目:")
                print(f"  日付: {date_info.get('date')}")
                print(f"  時間: {date_info.get('time')} - {date_info.get('end_time')}")

            if len(result['dates']) > 3:
                print(f"\n... (残り {len(result['dates']) - 3}件)")

        print("\n")

if __name__ == "__main__":
    test_february_with_time()
