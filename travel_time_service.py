import os
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

class TravelTimeService:
    """移動時間を計算するサービス（簡易版 + Google Maps API対応）"""

    def __init__(self):
        # 主要都市間の移動時間マップ（分単位）
        # 電車での平均的な移動時間を想定
        self.travel_time_map = {
            # 東京都内
            ('東京', '銀座'): 10,
            ('東京', '新宿'): 15,
            ('東京', '渋谷'): 20,
            ('東京', '品川'): 10,
            ('東京', '池袋'): 15,
            ('東京', '上野'): 10,
            ('東京', '秋葉原'): 5,
            ('銀座', '新宿'): 20,
            ('銀座', '渋谷'): 25,
            ('銀座', '品川'): 15,
            ('銀座', '池袋'): 30,
            ('新宿', '渋谷'): 10,
            ('新宿', '池袋'): 10,

            # 東京 ↔ 神奈川
            ('東京', '横浜'): 30,
            ('銀座', '横浜'): 40,
            ('新宿', '横浜'): 35,
            ('渋谷', '横浜'): 30,
            ('品川', '横浜'): 20,
            ('東京', 'みなとみらい'): 40,
            ('銀座', 'みなとみらい'): 50,
            ('東京', '川崎'): 20,
            ('銀座', '川崎'): 30,

            # 東京 ↔ 埼玉
            ('東京', '大宮'): 30,
            ('新宿', '大宮'): 35,
            ('池袋', '大宮'): 25,
            ('東京', '浦和'): 25,
            ('東京', 'さいたま'): 30,

            # 東京 ↔ 千葉
            ('東京', '千葉'): 40,
            ('東京', '船橋'): 30,
            ('東京', '柏'): 35,
            ('秋葉原', '千葉'): 40,

            # 東京 ↔ 関西
            ('東京', '大阪'): 180,  # 新幹線
            ('東京', '京都'): 165,  # 新幹線
            ('東京', '神戸'): 200,  # 新幹線
            ('新宿', '大阪'): 190,
            ('品川', '大阪'): 175,

            # 東京 ↔ その他主要都市
            ('東京', '名古屋'): 110,  # 新幹線
            ('東京', '仙台'): 95,    # 新幹線
            ('東京', '広島'): 240,   # 新幹線
            ('東京', '福岡'): 300,   # 新幹線

            # 関西圏内
            ('大阪', '京都'): 30,
            ('大阪', '神戸'): 25,
            ('大阪', '奈良'): 40,
            ('京都', '神戸'): 50,

            # 名古屋圏内
            ('名古屋', '岐阜'): 20,
            ('名古屋', '豊田'): 30,
        }

        # Google Maps API キー（環境変数から取得）
        self.google_maps_api_key = os.getenv('GOOGLE_MAPS_API_KEY')

    def get_travel_time(self, origin: str, destination: str) -> Optional[int]:
        """
        2地点間の移動時間を取得（分単位）

        Args:
            origin: 出発地
            destination: 目的地

        Returns:
            移動時間（分）、取得できない場合はNone
        """
        # 同じ場所の場合は0分
        if self._normalize_location(origin) == self._normalize_location(destination):
            return 0

        # まず簡易マップから検索
        travel_time = self._get_from_map(origin, destination)
        if travel_time is not None:
            logger.info(f"[簡易マップ] {origin} → {destination}: {travel_time}分")
            return travel_time

        # Google Maps APIが利用可能な場合は使用
        if self.google_maps_api_key:
            try:
                travel_time = self._get_from_google_maps(origin, destination)
                if travel_time is not None:
                    logger.info(f"[Google Maps API] {origin} → {destination}: {travel_time}分")
                    return travel_time
            except Exception as e:
                logger.warning(f"Google Maps API エラー: {e}")

        # どちらも取得できない場合はデフォルト値を返す
        default_time = self._estimate_default_travel_time(origin, destination)
        logger.info(f"[デフォルト推定] {origin} → {destination}: {default_time}分")
        return default_time

    def _normalize_location(self, location: str) -> str:
        """地名を正規化（表記ゆれ対応）"""
        location = location.strip()

        # 別名マッピング
        aliases = {
            '東京駅': '東京',
            '東京都': '東京',
            '銀座駅': '銀座',
            '新宿駅': '新宿',
            '渋谷駅': '渋谷',
            '横浜駅': '横浜',
            '横浜市': '横浜',
            '大阪駅': '大阪',
            '大阪市': '大阪',
            '梅田': '大阪',
            'なんば': '大阪',
            '難波': '大阪',
            '京都駅': '京都',
            '京都市': '京都',
        }

        return aliases.get(location, location)

    def _get_from_map(self, origin: str, destination: str) -> Optional[int]:
        """簡易マップから移動時間を取得"""
        origin = self._normalize_location(origin)
        destination = self._normalize_location(destination)

        # 直接検索
        key = (origin, destination)
        if key in self.travel_time_map:
            return self.travel_time_map[key]

        # 逆方向も検索（対称性を仮定）
        reverse_key = (destination, origin)
        if reverse_key in self.travel_time_map:
            return self.travel_time_map[reverse_key]

        return None

    def _get_from_google_maps(self, origin: str, destination: str) -> Optional[int]:
        """Google Maps Distance Matrix API から移動時間を取得"""
        try:
            import requests

            url = "https://maps.googleapis.com/maps/api/distancematrix/json"
            params = {
                'origins': origin,
                'destinations': destination,
                'mode': 'transit',  # 公共交通機関を使用
                'language': 'ja',
                'key': self.google_maps_api_key
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if data['status'] == 'OK':
                if data['rows'][0]['elements'][0]['status'] == 'OK':
                    # 秒単位で取得されるので分単位に変換
                    duration_seconds = data['rows'][0]['elements'][0]['duration']['value']
                    duration_minutes = int(duration_seconds / 60)
                    return duration_minutes

            return None

        except Exception as e:
            logger.error(f"Google Maps API エラー: {e}")
            return None

    def _estimate_default_travel_time(self, origin: str, destination: str) -> int:
        """
        デフォルトの移動時間を推定
        都市間の距離や規模から大まかに推定
        """
        origin = self._normalize_location(origin)
        destination = self._normalize_location(destination)

        # 主要都市のリスト
        major_cities = ['東京', '大阪', '名古屋', '福岡', '札幌', '仙台', '広島', '京都', '神戸']

        # 両方が主要都市の場合は長距離と仮定
        if origin in major_cities and destination in major_cities:
            if origin != destination:
                return 180  # 3時間（新幹線想定）

        # 首都圏内の移動と仮定
        tokyo_area = ['東京', '銀座', '新宿', '渋谷', '品川', '池袋', '上野', '秋葉原']
        if origin in tokyo_area or destination in tokyo_area:
            return 45  # 45分（首都圏内の平均的な移動時間）

        # それ以外は中距離と仮定
        return 60  # 1時間

    def calculate_total_required_time(
        self,
        origin: str,
        destination: str,
        meeting_duration_hours: float
    ) -> Tuple[int, dict]:
        """
        必要な合計時間を計算

        Args:
            origin: 出発地
            destination: 目的地
            meeting_duration_hours: 打ち合わせ時間（時間単位）

        Returns:
            (合計時間（分）, 詳細情報)
        """
        # 往路の移動時間
        outbound_time = self.get_travel_time(origin, destination)
        if outbound_time is None:
            outbound_time = 60  # デフォルト1時間

        # 復路の移動時間（往路と同じと仮定）
        return_time = outbound_time

        # 打ち合わせ時間（分に変換）
        meeting_time = int(meeting_duration_hours * 60)

        # 合計時間
        total_time = outbound_time + meeting_time + return_time

        # 詳細情報
        details = {
            'origin': origin,
            'destination': destination,
            'outbound_time_minutes': outbound_time,
            'meeting_time_minutes': meeting_time,
            'return_time_minutes': return_time,
            'total_time_minutes': total_time,
            'total_time_hours': round(total_time / 60, 1)
        }

        logger.info(f"移動時間計算: {origin}→{destination}")
        logger.info(f"  往路: {outbound_time}分")
        logger.info(f"  打ち合わせ: {meeting_time}分")
        logger.info(f"  復路: {return_time}分")
        logger.info(f"  合計: {total_time}分（{details['total_time_hours']}時間）")

        return total_time, details
