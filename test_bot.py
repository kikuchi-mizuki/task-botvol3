#!/usr/bin/env python3
"""
LINE Calendar Bot テストスクリプト
システムの動作確認とデバッグ用
"""

import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 環境変数を読み込み
load_dotenv()

def test_config():
    """設定のテスト"""
    print("=== 設定テスト ===")
    
    required_vars = [
        'LINE_CHANNEL_ACCESS_TOKEN',
        'LINE_CHANNEL_SECRET', 
        'OPENAI_API_KEY'
    ]
    
    for var in required_vars:
        value = os.getenv(var)
        if value:
            print(f"✅ {var}: 設定済み")
        else:
            print(f"❌ {var}: 未設定")
    
    # Google認証ファイルの確認
    creds_file = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
    if os.path.exists(creds_file):
        print(f"✅ Google認証ファイル: {creds_file} 存在")
    else:
        print(f"❌ Google認証ファイル: {creds_file} 不存在")
    
    print()

def test_ai_service():
    """AIサービスのテスト"""
    print("=== AIサービステスト ===")
    
    try:
        from ai_service import AIService
        
        ai_service = AIService()
        
        # 日時抽出テスト
        test_messages = [
            "明日と明後日の空き時間を教えて",
            "明日の午前9時から会議を追加して",
            "来週月曜日の14時から打ち合わせ"
        ]
        
        for message in test_messages:
            print(f"テストメッセージ: {message}")
            result = ai_service.extract_dates_and_times(message)
            print(f"結果: {result}")
            print()
            
    except Exception as e:
        print(f"❌ AIサービステストエラー: {e}")
        print()

def test_calendar_service():
    """カレンダーサービスのテスト"""
    print("=== カレンダーサービステスト ===")
    
    try:
        from calendar_service import GoogleCalendarService
        
        calendar_service = GoogleCalendarService()
        print("✅ Google Calendarサービス初期化成功")
        
        # 今日の日付を取得
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        
        # イベント取得テスト
        events_info = calendar_service.get_events_for_dates([today, tomorrow])
        print(f"今日と明日のイベント: {events_info}")
        print()
        
    except Exception as e:
        print(f"❌ カレンダーサービステストエラー: {e}")
        print()

def test_line_bot_handler():
    """LINE Botハンドラーのテスト"""
    print("=== LINE Botハンドラーテスト ===")
    
    try:
        from line_bot_handler import LineBotHandler
        
        handler = LineBotHandler()
        print("✅ LINE Botハンドラー初期化成功")
        print()
        
    except Exception as e:
        print(f"❌ LINE Botハンドラーテストエラー: {e}")
        print()

def test_flask_app():
    """Flaskアプリケーションのテスト"""
    print("=== Flaskアプリケーションテスト ===")
    
    try:
        from app import app
        
        with app.test_client() as client:
            # ヘルスチェック
            response = client.get('/health')
            print(f"ヘルスチェック: {response.status_code} - {response.json}")
            
            # テストエンドポイント
            response = client.get('/test')
            print(f"テストエンドポイント: {response.status_code} - {response.json}")
            
        print("✅ Flaskアプリケーションテスト成功")
        print()
        
    except Exception as e:
        print(f"❌ Flaskアプリケーションテストエラー: {e}")
        print()

def test_integration():
    """統合テスト"""
    print("=== 統合テスト ===")
    
    try:
        from ai_service import AIService
        from calendar_service import GoogleCalendarService
        
        ai_service = AIService()
        calendar_service = GoogleCalendarService()
        
        # テストメッセージ
        test_message = "明日の午前9時から会議を追加して"
        
        # AIでイベント情報を抽出
        event_info = ai_service.extract_event_info(test_message)
        print(f"イベント情報抽出: {event_info}")
        
        if 'error' not in event_info:
            # カレンダーに追加テスト（実際には追加しない）
            print("✅ 統合テスト成功")
        else:
            print("❌ イベント情報抽出に失敗")
        
        print()
        
    except Exception as e:
        print(f"❌ 統合テストエラー: {e}")
        print()

def main():
    """メイン関数"""
    print("LINE Calendar Bot テスト開始")
    print("=" * 50)
    
    # 各テストを実行
    test_config()
    test_ai_service()
    test_calendar_service()
    test_line_bot_handler()
    test_flask_app()
    test_integration()
    
    print("=" * 50)
    print("テスト完了")
    
    # 起動方法の案内
    print("\n=== 起動方法 ===")
    print("1. 環境変数を設定してください")
    print("2. Google認証ファイルを配置してください")
    print("3. 以下のコマンドで起動してください:")
    print("   python app.py")
    print("\n4. ブラウザで http://localhost:5000/test にアクセスして設定を確認してください")

if __name__ == "__main__":
    main() 