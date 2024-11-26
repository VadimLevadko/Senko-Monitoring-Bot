import re
import json
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import pytz
from project.config import LIMITS

def format_size(size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"

def format_time(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)} сек"
    elif seconds < 3600:
        return f"{int(seconds/60)} мин {int(seconds%60)} сек"
    else:
        hours = int(seconds/3600)
        minutes = int((seconds%3600)/60)
        return f"{hours} ч {minutes} мин"

def validate_phone(phone: str) -> bool:
    pattern = r'^\+?[1-9]\d{10,14}$'
    return bool(re.match(pattern, phone))

def load_json_file(file_path: str) -> Optional[Dict]:
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def save_json_file(data: Any, file_path: str) -> bool:
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def get_moscow_time() -> datetime:
    moscow_tz = pytz.timezone('Europe/Moscow')
    return datetime.now(moscow_tz)

async def run_with_timeout(coro, timeout: float):
    try:
        return await asyncio.wait_for(coro, timeout)
    except asyncio.TimeoutError:
        return None

def check_limits(entities_count: int, limit_type: str) -> bool:
    return entities_count < LIMITS.get(limit_type, float('inf'))

class RateLimiter:
    """Класс для ограничения частоты запросов"""
    
    def __init__(self, calls: int, period: float):
        self.calls = calls
        self.period = period
        self.timestamps = []

    async def acquire(self):
        """Получение разрешения на выполнение запроса"""
        now = datetime.now().timestamp()

        self.timestamps = [ts for ts in self.timestamps if now - ts < self.period]
        
        if len(self.timestamps) >= self.calls:
            sleep_time = self.period - (now - self.timestamps[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
                now = datetime.now().timestamp()
        
        self.timestamps.append(now)