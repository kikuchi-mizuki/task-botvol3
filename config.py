import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # LINE Bot設定
    LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
    LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
    
    # OpenAI設定
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    
    # Google Calendar設定
    GOOGLE_CALENDAR_ID = 'primary'
    GOOGLE_CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
    
    # Flask設定
    FLASK_SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')
    
    # アプリケーション設定
    TIMEZONE = os.getenv('TIMEZONE', 'Asia/Tokyo')
    DEFAULT_EVENT_DURATION = int(os.getenv('DEFAULT_EVENT_DURATION', '60'))  # 分
    
    @classmethod
    def validate_config(cls):
        """設定の妥当性をチェックします"""
        required_vars = [
            'LINE_CHANNEL_ACCESS_TOKEN',
            'LINE_CHANNEL_SECRET',
            'OPENAI_API_KEY'
        ]
        
        missing_vars = []
        for var in required_vars:
            if not getattr(cls, var):
                missing_vars.append(var)
        
        if missing_vars:
            raise ValueError(f"必要な環境変数が設定されていません: {', '.join(missing_vars)}")
        
        # Google認証ファイルの存在確認（実際のファイルパスでチェック）
        # Railway環境では write_credentials() で credentials.json を生成するため、常に 'credentials.json' をチェック
        credentials_file = 'credentials.json'
        if not os.path.exists(credentials_file):
            print(f"警告: Google認証ファイル '{credentials_file}' が見つかりません。")
            print("Google Calendar APIを使用するには、credentials.jsonファイルが必要です。")
            # Railway環境でのデバッグ情報
            if os.getenv('RAILWAY_ENVIRONMENT'):
                print(f"現在の作業ディレクトリ: {os.getcwd()}")
                print(f"ディレクトリ内容: {os.listdir('.')}")
                if 'GOOGLE_CREDENTIALS_FILE' in os.environ:
                    print("GOOGLE_CREDENTIALS_FILE環境変数は設定されています")
                else:
                    print("GOOGLE_CREDENTIALS_FILE環境変数が設定されていません") 