#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「明日ランチできる？」というクエリのテスト
"""
import sys
import os
from datetime import datetime
import pytz

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai_service import AIService

def test_lunch_query():
    """明日ランチできる？のテスト"""
    ai_service = AIService()

    # 現在時刻（JST）
    jst = pytz.timezone('Asia/Tokyo')
    now = datetime.now(jst)
    print(f"現在時刻: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # テストクエリ
    test_query = "明日ランチできる？"
    print(f"入力: {test_query}")
    print("-" * 50)

    # AIで解析
    result = ai_service.extract_dates_and_times(test_query)

    print(f"AI解析結果:")
    print(f"  task_type: {result.get('task_type')}")
    print(f"  dates: {result.get('dates')}")
    print(f"  location: {result.get('location')}")
    print()

    # キーワード検出のテスト
    lunch_keywords = ['ランチ', 'lunch', '昼食', '昼ご飯', 'お昼', 'ひるごはん']
    is_lunch = any(keyword in test_query for keyword in lunch_keywords)
    print(f"ランチキーワード検出: {is_lunch}")

    # 期待される結果
    tomorrow = (now + timedelta(days=1)).strftime('%Y-%m-%d')
    print()
    print("期待される結果:")
    print(f"  日付: {tomorrow}")
    print(f"  時間: 11:00-14:00")

if __name__ == "__main__":
    from datetime import timedelta
    test_lunch_query()
