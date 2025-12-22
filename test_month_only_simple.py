#!/usr/bin/env python3
"""
月だけ指定された場合のテスト（シンプル版）
"""

from datetime import datetime
import pytz

# 現在の日時を2025年12月23日に固定してテスト
def test_month_logic():
    """月だけが指定された場合のロジックテスト"""
    print("=== 月だけ指定のロジックテスト ===")

    jst = pytz.timezone('Asia/Tokyo')
    now = datetime(2025, 12, 23, 10, 0, 0, tzinfo=jst)  # 2025年12月23日

    # テストケース1: 1月（現在の月より小さい）→ 2026年1月
    month = 1
    year = now.year
    start_day = 1

    if month < now.month:
        year = now.year + 1
    elif month == now.month:
        start_day = now.day

    print(f"テストケース1: 現在が{now.strftime('%Y年%m月%d日')}で「1月」と指定")
    print(f"  → {year}年{month}月{start_day}日から")
    assert year == 2026, f"エラー: 年が{year}年になりました（期待値: 2026年）"
    assert start_day == 1, f"エラー: 開始日が{start_day}日になりました（期待値: 1日）"
    print("  ✅ 正しく2026年1月と解釈されました")

    # テストケース2: 12月（現在の月と同じ）→ 2025年12月23日から
    month = 12
    year = now.year
    start_day = 1

    if month < now.month:
        year = now.year + 1
    elif month == now.month:
        start_day = now.day

    print(f"\nテストケース2: 現在が{now.strftime('%Y年%m月%d日')}で「12月」と指定")
    print(f"  → {year}年{month}月{start_day}日から")
    assert year == 2025, f"エラー: 年が{year}年になりました（期待値: 2025年）"
    assert start_day == 23, f"エラー: 開始日が{start_day}日になりました（期待値: 23日）"
    print("  ✅ 正しく2025年12月23日からと解釈されました")

    # テストケース3: 11月（現在の月より小さい）→ 2026年11月
    month = 11
    year = now.year
    start_day = 1

    if month < now.month:
        year = now.year + 1
    elif month == now.month:
        start_day = now.day

    print(f"\nテストケース3: 現在が{now.strftime('%Y年%m月%d日')}で「11月」と指定")
    print(f"  → {year}年{month}月{start_day}日から")
    assert year == 2026, f"エラー: 年が{year}年になりました（期待値: 2026年）"
    assert start_day == 1, f"エラー: 開始日が{start_day}日になりました（期待値: 1日）"
    print("  ✅ 正しく2026年11月と解釈されました")

    # テストケース4: 3月の場合（現在が12月）→ 2026年3月
    now = datetime(2025, 3, 15, 10, 0, 0, tzinfo=jst)  # 2025年3月15日
    month = 2
    year = now.year
    start_day = 1

    if month < now.month:
        year = now.year + 1
    elif month == now.month:
        start_day = now.day

    print(f"\nテストケース4: 現在が{now.strftime('%Y年%m月%d日')}で「2月」と指定")
    print(f"  → {year}年{month}月{start_day}日から")
    assert year == 2026, f"エラー: 年が{year}年になりました（期待値: 2026年）"
    assert start_day == 1, f"エラー: 開始日が{start_day}日になりました（期待値: 1日）"
    print("  ✅ 正しく2026年2月と解釈されました")

    print("\n" + "=" * 50)
    print("全テストケース成功！")

if __name__ == "__main__":
    test_month_logic()
