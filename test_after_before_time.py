#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「以降」「以前」パターンのテスト
"""

import sys
import os
import re

def extract_time_range_from_text(text):
    """
    テキストから時間範囲を抽出する（テスト用）
    """
    # 「以降」「以前」パターンを優先的にチェック
    # 18時以降 → 18:00-22:00
    after_match = re.search(r'(\d{1,2})時以降', text)
    if after_match:
        hour = int(after_match.group(1))
        return (f"{hour:02d}:00", "22:00")

    # 18時以前 → 09:00-18:00
    before_match = re.search(r'(\d{1,2})時以前', text)
    if before_match:
        hour = int(before_match.group(1))
        return ("09:00", f"{hour:02d}:00")

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

def test_extract_time_range():
    """時間範囲抽出機能のテスト"""

    test_cases = [
        ("3月18時以降、東京で会食できる日は？", ("18:00", "22:00")),
        ("2月 12時以降", ("12:00", "22:00")),
        ("3月 15時以前", ("09:00", "15:00")),
        ("4月 20時以降", ("20:00", "22:00")),
        ("5月 12:00-15:00", ("12:00", "15:00")),  # 既存パターンも確認
        ("6月", (None, None)),  # 時間範囲なし
    ]

    print("=" * 60)
    print("時間範囲抽出テスト")
    print("=" * 60)

    all_passed = True
    for text, expected in test_cases:
        result = extract_time_range_from_text(text)
        passed = result == expected
        all_passed = all_passed and passed

        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"\n{status}")
        print(f"  入力: {text}")
        print(f"  期待: {expected}")
        print(f"  結果: {result}")

    print("\n" + "=" * 60)
    if all_passed:
        print("✓ すべてのテストが成功しました")
    else:
        print("✗ 一部のテストが失敗しました")
    print("=" * 60)

    return all_passed

if __name__ == "__main__":
    success = test_extract_time_range()
    sys.exit(0 if success else 1)
