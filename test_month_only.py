#!/usr/bin/env python3
"""
月だけ指定された場合のテスト
"""

from dotenv import load_dotenv
from ai_service import AIService
import json

# 環境変数を読み込み
load_dotenv()

def test_month_only():
    """月だけが指定された場合のテスト"""
    print("=== 月だけ指定のテスト ===")

    ai_service = AIService()

    test_messages = [
        "1月の空き時間",
        "2月の空き時間を教えて",
        "12月の空いている日"
    ]

    for message in test_messages:
        print(f"\nテストメッセージ: {message}")
        result = ai_service.extract_dates_and_times(message)
        print(f"結果: {json.dumps(result, ensure_ascii=False, indent=2)}")

        # 日付の範囲を確認
        if 'dates' in result:
            dates = result['dates']
            if dates:
                print(f"日付の範囲: {dates[0]['date']} から {dates[-1]['date']} まで ({len(dates)}件)")
        print("-" * 50)

if __name__ == "__main__":
    test_month_only()
