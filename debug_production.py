#!/usr/bin/env python3
"""
本番環境でのデバッグ用スクリプト
AIサービスの動作を詳細にテストし、問題を特定します
"""

import os
import sys
from datetime import datetime
import pytz

# 設定を読み込み
from config import Config
from ai_service import AIService

def test_ai_extraction():
    """AI抽出機能をテスト"""
    print("=== AI抽出機能テスト開始 ===")
    print(f"現在時刻: {datetime.now(pytz.timezone('Asia/Tokyo'))}")
    print(f"OpenAI API Key: {'設定済み' if Config.OPENAI_API_KEY else '未設定'}")
    print(f"API Key 先頭10文字: {Config.OPENAI_API_KEY[:10] if Config.OPENAI_API_KEY else 'N/A'}")
    
    try:
        ai_service = AIService()
        print("✅ AIサービス初期化成功")
    except Exception as e:
        print(f"❌ AIサービス初期化失敗: {e}")
        return
    
    # テストケース
    test_cases = [
        "7/10 9-10時",
        "・7/10 9-10時\n・7/11 9-10時",
        "7/10 9時-10時",
        "7/10 9:00-10:00",
        "明日の空き時間",
        "7/15 15:00〜16:00の空き時間"
    ]
    
    for i, test_input in enumerate(test_cases, 1):
        print(f"\n--- テストケース {i}: {test_input} ---")
        try:
            result = ai_service.extract_dates_and_times(test_input)
            print(f"結果: {result}")
            
            if 'dates' in result:
                print("抽出された日時:")
                for j, date_info in enumerate(result['dates'], 1):
                    print(f"  {j}. 日付: {date_info.get('date')}, 開始: {date_info.get('time')}, 終了: {date_info.get('end_time')}")
            
        except Exception as e:
            print(f"❌ エラー: {e}")

def test_openai_direct():
    """OpenAI APIを直接テスト"""
    print("\n=== OpenAI API直接テスト ===")
    
    try:
        import openai
        client = openai.OpenAI(api_key=Config.OPENAI_API_KEY)
        
        # 簡単なテスト
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "あなたはテスト用のAIです。"},
                {"role": "user", "content": "こんにちは"}
            ],
            temperature=0.1
        )
        
        print(f"✅ OpenAI API接続成功")
        print(f"モデル: {response.model}")
        print(f"レスポンス: {response.choices[0].message.content}")
        
    except Exception as e:
        print(f"❌ OpenAI API接続失敗: {e}")

def test_environment():
    """環境情報を確認"""
    print("\n=== 環境情報 ===")
    print(f"Python バージョン: {sys.version}")
    print(f"作業ディレクトリ: {os.getcwd()}")
    print(f"環境変数 OPENAI_API_KEY: {'設定済み' if os.getenv('OPENAI_API_KEY') else '未設定'}")
    print(f"環境変数 LINE_CHANNEL_ACCESS_TOKEN: {'設定済み' if os.getenv('LINE_CHANNEL_ACCESS_TOKEN') else '未設定'}")
    print(f"環境変数 LINE_CHANNEL_SECRET: {'設定済み' if os.getenv('LINE_CHANNEL_SECRET') else '未設定'}")

if __name__ == "__main__":
    test_environment()
    test_openai_direct()
    test_ai_extraction()
    print("\n=== テスト完了 ===") 