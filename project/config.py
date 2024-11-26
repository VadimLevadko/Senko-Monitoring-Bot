import os
import json
import logging
import logging.config
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
DATA_DIR = os.path.join(BASE_DIR, 'data')
TEMP_DIR = os.path.join(BASE_DIR, 'temp')

for directory in [LOGS_DIR, DATA_DIR, TEMP_DIR]:
    os.makedirs(directory, exist_ok=True)

# Настройки бота
BOT_TOKEN = "7777476078:AAEO6JXwVC3uWQSYy1LNUcDKS9lcGYX5Nh8"
SUPER_ADMIN_USERNAME = "VL7940"  # Только username супер-админа


BOTS_FOLDER = os.path.join(BASE_DIR, 'БОТЫ')
ACCOUNTS_FILE = os.path.join(DATA_DIR, 'accounts.json')
PROXY_FILE = os.path.join(DATA_DIR, 'proxy.txt')
KEYWORDS_FILE = os.path.join(DATA_DIR, 'keywords.json')
SETTINGS_FILE = os.path.join(DATA_DIR, 'settings.json')
DATABASE_FILE = os.path.join(DATA_DIR, 'monitor.db')

# Настройки по умолчанию
DEFAULT_MONITORING_SETTINGS = {
    'check_interval': 1,
    'max_message_length': 4096,
    'max_channels_per_client': 500,
    'max_keywords': 1000,
    'notification_chunk_size': 50,
    'retry_interval': 300,
    'cleanup_interval': 86400,
    'data_retention_days': 30,
    'auto_restart': True,
    'restart_delay': 60,
    'max_errors_before_restart': 5,
    'message_processing_timeout': 30,
    'join_timeout': 30,
    'flood_wait_threshold': 60,
    'join_channel_delay': 5,
}

# Состояния
STATES = {
    'MAIN_MENU': 0,
    'MANAGING_ACCOUNTS': 1,
    'MANAGING_PROXIES': 2,
    'MANAGING_KEYWORDS': 3,
    'MONITORING': 4,
    'SETTINGS': 5,
    'SETTINGS_MENU': 6,
    'EDITING_NOTIFICATIONS': 7,
    'EDITING_PERFORMANCE': 8,
    'EDITING_AUTORESTART': 9,
    'EDITING_STORAGE': 10,
    'ENTERING_VALUE': 11,
    'ADDING_ACCOUNT': 20,
    'ADDING_PROXY': 21,
    'ADDING_KEYWORD': 22,
    'ADDING_CHANNEL': 23,
    'MANAGING_ADMINS': 50,
    'ADDING_ADMIN': 51,
    'REMOVING_ADMIN': 52,
    'IMPORTING_KEYWORDS': 30,
    'EXPORTING_KEYWORDS': 31,
    'CONFIRMING_DELETE': 40,
    'CONFIRMING_CLEAR': 41,
    'MANAGING_CHANNELS': 43,
    'CONFIRMING_SETTINGS': 42,
    'EDITING_TIMEOUTS': 44,
    'EDITING_OTHER': 45,
}

# Настройки прокси
PROXY_SETTINGS = {
    'check_timeout': 10,
    'max_retries': 3,
    'retry_delay': 5,
    'rotation_interval': 3600,
    'min_valid_proxies': 5,
    'check_interval': 300,
    'max_simultaneous_checks': 10,
    'banned_timeout': 3600,
}

# Лимиты
LIMITS = {
    'max_accounts': 100,
    'max_channels': 1000,
    'max_keywords_per_import': 1000,
    'max_file_size': 10 * 1024 * 1024,  # 10 MB
    'max_concurrent_tasks': 10,
    'max_message_rate': 30,
    'max_keyword_length': 100,
    'min_keyword_length': 3,
    'max_notifications_per_minute': 60,
}

# Настройки Telethon
TELETHON_SETTINGS = {
    'connection_retries': 5,
    'retry_delay': 1,
    'auto_reconnect': True,
    'request_retries': 3,
    'flood_sleep_threshold': 60,
    'device_model': 'Desktop',
    'system_version': 'Windows 10',
    'app_version': '1.0.0',
    'lang_code': 'ru',
    'system_lang_code': 'ru'
}

# Шаблоны сообщений
MESSAGE_TEMPLATES = {
    'keyword_found': (
        "🔍 *Найдено совпадение!*\n\n"
        "📱 *Группа:* `{chat_title}`\n"
        "👤 *Отправитель:* `{sender}`\n"
        "🔑 *Ключевые слова:* `{keywords}`\n\n"
        "💬 *Сообщение:*\n"
        "`{message}`\n\n"
        "🔗 [Ссылка на сообщение]({message_link})\n"
        "⏰ Время: `{time}`"
    ),
    'error_notification': (
        "❌ *Ошибка мониторинга*\n\n"
        "Тип: `{error_type}`\n"
        "Описание: `{description}`\n"
        "Время: `{time}`"
    ),
    'proxy_error': (
        "🔴 *Ошибка прокси*\n\n"
        "Прокси: `{proxy}`\n"
        "Ошибка: `{error}`\n"
        "Время: `{time}`"
    ),
    'account_banned': (
        "🚫 *Аккаунт заблокирован*\n\n"
        "Телефон: `{phone}`\n"
        "Причина: `{reason}`\n"
        "Время: `{time}`"
    ),
    'channel_added': (
        "✅ *Канал добавлен*\n\n"
        "Название: `{title}`\n"
        "ID: `{chat_id}`\n"
        "Время: `{time}`"
    ),
    'channel_removed': (
        "❌ *Канал удален*\n\n"
        "Название: `{title}`\n"
        "ID: `{chat_id}`\n"
        "Время: `{time}`"
    ),
    'monitoring_started': (
        "▶️ *Мониторинг запущен*\n\n"
        "Активных клиентов: `{clients_count}`\n"
        "Отслеживаемых каналов: `{channels_count}`\n"
        "Время: `{time}`"
    ),
    'monitoring_stopped': (
        "⏹ *Мониторинг остановлен*\n\n"
        "Длительность: `{duration}`\n"
        "Обработано сообщений: `{messages_count}`\n"
        "Найдено совпадений: `{keywords_found}`\n"
        "Время: `{time}`"
    ),
    'settings_changed': (
        "⚙️ *Настройки изменены*\n\n"
        "Параметр: `{setting_name}`\n"
        "Новое значение: `{new_value}`\n"
        "Старое значение: `{old_value}`\n"
        "Время: `{time}`"
    ),
    'status_update': (
        "📊 *Статус мониторинга*\n\n"
        "Состояние: `{status}`\n"
        "Активных клиентов: `{clients_count}`\n"
        "Отслеживаемых каналов: `{channels_count}`\n"
        "Обработано сообщений: `{messages_count}`\n"
        "Найдено совпадений: `{keywords_found}`\n"
        "Ошибок: `{errors_count}`\n"
        "Время работы: `{uptime}`"
    ),
    'error_report': (
        "⚠️ *Отчет об ошибке*\n\n"
        "Компонент: `{component}`\n"
        "Ошибка: `{error}`\n"
        "Описание: `{description}`\n"
        "Стек вызовов: ```\n{traceback}```\n"
        "Время: `{time}`"
    )
}

# Настройки логирования
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        },
        'detailed': {
            'format': '%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s'
        }
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'formatter': 'standard',
            'class': 'logging.StreamHandler',
        },
        'file': {
            'level': 'DEBUG',
            'formatter': 'detailed',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(LOGS_DIR, 'monitor.log'),
            'maxBytes': 10485760,  # 10MB
            'backupCount': 5,
            'encoding': 'utf8'
        }
    },
    'loggers': {
        '': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': True
        }
    }
}


logging.config.dictConfig(LOGGING_CONFIG)

def load_settings() -> Dict:
    """Загрузка настроек из файла"""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                saved_settings = json.load(f)
                settings = DEFAULT_MONITORING_SETTINGS.copy()
                settings.update(saved_settings)
                return settings
        return DEFAULT_MONITORING_SETTINGS.copy()
    except Exception as e:
        logger.error(f"Ошибка при загрузке настроек: {e}")
        return DEFAULT_MONITORING_SETTINGS.copy()

def save_settings(settings: Dict) -> bool:
    """Сохранение настроек в файл"""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении настроек: {e}")
        return False

# Загружаем актуальные настройки
MONITORING_SETTINGS = load_settings()

class Config:
    @staticmethod
    def get_db_path() -> str:
        return DATABASE_FILE
    
    @staticmethod
    def get_proxy_file() -> str:
        return PROXY_FILE
    
    @staticmethod
    def get_settings() -> Dict:
        return load_settings()
    
    @staticmethod
    def save_settings(settings: Dict) -> bool:
        return save_settings(settings)
    
    @staticmethod
    def get_monitoring_settings() -> Dict:
        return MONITORING_SETTINGS
    
    @staticmethod
    def get_proxy_settings() -> Dict:
        return PROXY_SETTINGS
    
    @staticmethod
    def get_limits() -> Dict:
        return LIMITS
    
    @staticmethod
    def get_telethon_settings() -> Dict:
        return TELETHON_SETTINGS

for directory in [BOTS_FOLDER]:
    os.makedirs(directory, exist_ok=True)

logger.info("Конфигурация загружена")