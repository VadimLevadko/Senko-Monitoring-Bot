import os
import sys
from typing import Optional
from typing import Dict, List, Optional
from telegram import Update
from telegram.ext import ContextTypes
from .utils.logger import setup_logger, LoggerManager
from .config import (
    Config, STATES, MONITORING_SETTINGS,
    BOT_TOKEN, SUPER_ADMIN_USERNAME, TELETHON_SETTINGS,
    BOTS_FOLDER
)

from .handlers.admin_handler import AdminHandler
from .managers.account_manager import AccountManager
from .managers.proxy_manager import ProxyManager
from .managers.message_monitor import MessageMonitor
from .handlers.account_handler import AccountHandler
from .handlers.proxy_handler import ProxyHandler
from .handlers.keyword_handler import KeywordHandler
from .handlers.monitor_handler import MonitorHandler
from .database.database_manager import DatabaseManager

__version__ = '1.0.0'
__author__ = 'GeFox_dev'


logger = setup_logger('telegram_monitor')

if sys.version_info < (3, 8):
    logger.error("Python 3.8 или выше требуется для работы бота")
    sys.exit(1)

__all__ = [
    'AccountManager',
    'ProxyManager',
    'MessageMonitor',
    'AccountHandler',
    'ProxyHandler',
    'KeywordHandler',
    'MonitorHandler',
    'DatabaseManager',
    'Config',
    'STATES',
    'MONITORING_SETTINGS',
    'setup_logger',
    'LoggerManager',
    'TelegramMonitorBot',
    'create_bot'
]

class TelegramMonitorBot:
    def __init__(self, bot_token: str = BOT_TOKEN):
        self.token = bot_token
        self.logger = LoggerManager.get_logger('bot')
        
        try:
            self.db_manager = DatabaseManager(SUPER_ADMIN_USERNAME)
            self.logger.info("База данных инициализирована")
            
            self.proxy_manager = ProxyManager()
            self.account_manager = AccountManager(
                bots_folder=BOTS_FOLDER,
                proxy_manager=self.proxy_manager
            )
            
            self.message_monitor = MessageMonitor(
                db_manager=self.db_manager,
                account_manager=self.account_manager
            )
            
            self.logger.info("Менеджеры инициализированы")

            self.handlers = {
                'account': AccountHandler(
                    account_manager=self.account_manager,
                    message_monitor=self.message_monitor
                ),
                'proxy': ProxyHandler(self.proxy_manager),
                'keyword': KeywordHandler(self.db_manager),
                'monitor': MonitorHandler(self.message_monitor),
                'admin': AdminHandler(self.db_manager)
            }
            
            self.logger.info("Обработчики инициализированы")
            
            self.telethon_settings = TELETHON_SETTINGS
            
            self.logger.info("Бот успешно инициализирован")
            
        except Exception as e:
            self.logger.error(f"Ошибка при инициализации бота: {e}", exc_info=True)
            raise

    async def start(self):
        try:
            try:
                await self.proxy_manager.check_all_proxies()
                self.logger.info("Прокси проверены")
            except Exception as e:
                self.logger.error(f"Ошибка при проверке прокси: {e}")

            await self.message_monitor.initialize(self)
            self.logger.info("Монитор сообщений инициализирован")
            
            
        except Exception as e:
            self.logger.error(f"Ошибка при запуске бота: {e}")
            raise

    async def stop(self):
        try:
            await self.message_monitor.stop_monitoring()
            self.logger.info("Мониторинг остановлен")
            
            await self.account_manager.disconnect_all()
            self.logger.info("Аккаунты отключены")
            self.logger.info("Бот успешно остановлен")
            
        except Exception as e:
            self.logger.error(f"Ошибка при остановке бота: {e}", exc_info=True)
            raise

    def get_handlers(self) -> Dict:
        return self.handlers

    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = (
            "*Справка по использованию бота*\n\n"
            "Доступные команды:\n"
            "/start - Главное меню\n"
            "/help - Эта справка\n\n"
            "Возможности бота:\n"
            "• Мониторинг каналов\n"
            "• Управление аккаунтами\n"
            "• Настройка прокси\n"
            "• Управление ключевыми словами"
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def show_about(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        about_text = (
            "*О боте*\n\n"
            f"Версия: {__version__}\n"
            "Назначение: Мониторинг Telegram каналов\n\n"
            "Возможности:\n"
            "• Отслеживание ключевых слов\n"
            "• Управление несколькими аккаунтами\n"
            "• Работа через прокси\n"
            "• Гибкая настройка уведомлений\n\n"
            f"Автор: {__author__}\n"
            f"Лицензия: {__license__}"
        )
        await update.message.reply_text(about_text, parse_mode='Markdown')

    def get_stats(self) -> Dict:
        try:
            monitoring_stats = self.message_monitor.get_stats()
            account_stats = self.account_manager.get_stats()
            proxy_stats = self.proxy_manager.get_stats()
            logger_metrics = LoggerManager.get_all_metrics()
            
            return {
                'monitoring': monitoring_stats,
                'accounts': account_stats,
                'proxies': proxy_stats,
                'logging': logger_metrics,
                'version': __version__,
                'uptime': self.message_monitor.get_uptime()
            }
        except Exception as e:
            self.logger.error(f"Ошибка при получении статистики: {e}")
            return {}

    async def check_status(self) -> bool:
        try:

            db_status = False
            try:
                db_status = self.db_manager.is_connected()
            except Exception as e:
                self.logger.error(f"Ошибка при проверке статуса БД: {e}")

            monitor_status = self.message_monitor.is_monitoring

            # Проверяем все активные клиенты
            active_clients = 0
            for client in self.message_monitor.monitoring_clients.values():
                try:
                    if client and client.is_connected() and await client.is_user_authorized():
                        active_clients += 1
                except Exception as e:
                    self.logger.error(f"Ошибка при проверке клиента: {e}")

            # Проверяем наличие аккаунтов
            accounts = self.account_manager.get_accounts()
            has_accounts = len(accounts) > 0

            # Для каждого компонента выводим статус
            if not db_status:
                self.logger.error(f"Компонент database не работает")
                
            # Не считаем отсутствие аккаунтов критической ошибкой
            if not has_accounts:
                self.logger.warning("В системе нет добавленных аккаунтов")
            else:
                # Проверяем остальные компоненты только если есть аккаунты
                if not monitor_status:
                    self.logger.error(f"Компонент monitor не работает")
                if not active_clients:
                    self.logger.error(f"Компонент active_clients не работает")

            # Система считается работоспособной если:
            # 1. База данных работает
            # 2. Если есть аккаунты, то монитор и клиенты должны работать
            # 3. Если аккаунтов нет, то проверяем только БД
            all_ok = db_status and (not has_accounts or (monitor_status and active_clients > 0))

            if not all_ok:
                self.logger.warning("Не все компоненты работают корректно")
            
            return all_ok

        except Exception as e:
            self.logger.error(f"Ошибка при проверке статуса: {e}")
            return False

def create_bot(token: Optional[str] = None, admin_id: Optional[str] = None) -> TelegramMonitorBot:
    try:
        bot_token = token or BOT_TOKEN
        admin_chat_id = admin_id or ADMIN_CHAT_ID
        
        if not bot_token or not admin_chat_id:
            raise ValueError("Не указаны BOT_TOKEN или ADMIN_CHAT_ID")
        
        return TelegramMonitorBot(bot_token, admin_chat_id)
        
    except Exception as e:
        logger.error(f"Ошибка при создании бота: {e}", exc_info=True)
        raise
        
async def cleanup(self):
    if hasattr(self, 'message_monitor'):
        await self.message_monitor.stop_monitoring()