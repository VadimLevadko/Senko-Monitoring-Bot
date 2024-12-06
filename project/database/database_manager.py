import os
import json
import sqlite3
import logging
from typing import List, Dict, Optional, Tuple, Any
from telegram import Update
from telegram.ext import ContextTypes
from datetime import datetime, timedelta
import aiosqlite
from ..config import SUPER_ADMIN_USERNAME
from project.config import (
    ACCOUNTS_FILE,
    PROXY_FILE,
    KEYWORDS_FILE,
    BOTS_FOLDER,
    BASE_DIR
)

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, super_admin_username: str = None):
        """Инициализация менеджера базы данных"""
        self.db_path = os.path.join(BASE_DIR, 'monitor.db')
        self.accounts_file = ACCOUNTS_FILE
        self.proxy_file = PROXY_FILE
        self.keywords_file = KEYWORDS_FILE
        self.bots_folder = BOTS_FOLDER
        self._connection = None
        self.logger = logging.getLogger(__name__)
        self.super_admin_username = super_admin_username or SUPER_ADMIN_USERNAME

        os.makedirs(BASE_DIR, exist_ok=True)
        os.makedirs(self.bots_folder, exist_ok=True)

        self.init_db()

    def is_connected(self) -> bool:
        """Проверка подключения к базе данных"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT 1')
                result = cursor.fetchone()
                return result is not None
        except Exception as e:
            self.logger.error(f"Ошибка при проверке подключения к БД: {e}")
            return False

    def init_db(self) -> None:
        """Инициализация базы данных SQLite"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()

                # Таблица администраторов
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS administrators (
                        username TEXT PRIMARY KEY,
                        added_by TEXT NOT NULL,
                        added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        is_super_admin INTEGER DEFAULT 0,
                        is_active INTEGER DEFAULT 1,
                        chat_id INTEGER
                    )
                ''')

                # Таблица для хранения найденных сообщений
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL,
                        chat_title TEXT NOT NULL,
                        message_id INTEGER NOT NULL,
                        sender_id INTEGER,
                        sender_name TEXT,
                        text TEXT NOT NULL,
                        found_keywords TEXT NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Таблица для статистики ключевых слов
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS keyword_stats (
                        keyword TEXT PRIMARY KEY,
                        total_mentions INTEGER DEFAULT 0,
                        mentions_today INTEGER DEFAULT 0,
                        mentions_week INTEGER DEFAULT 0,
                        mentions_month INTEGER DEFAULT 0,
                        first_mention_date DATETIME,
                        last_mention_date DATETIME,
                        last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Таблица для отслеживаемых каналов
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS channels (
                        chat_id INTEGER PRIMARY KEY,
                        title TEXT NOT NULL,
                        username TEXT,
                        join_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                        last_check DATETIME,
                        is_active INTEGER DEFAULT 1
                    )
                ''')

                # Таблица для логов мониторинга
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS monitoring_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_type TEXT NOT NULL,
                        description TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Таблица для отслеживания членства
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS channel_memberships (
                        chat_id INTEGER,
                        account_id TEXT,
                        is_member BOOLEAN,
                        join_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (chat_id, account_id)
                    )
                ''')

                # Таблица для детальной статистики по каналам
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS keyword_channel_stats (
                        keyword TEXT NOT NULL,
                        channel_id INTEGER NOT NULL,
                        channel_title TEXT NOT NULL,
                        mentions INTEGER DEFAULT 0,
                        first_mention DATETIME,
                        last_mention DATETIME,
                        PRIMARY KEY (keyword, channel_id)
                    )
                ''')

                # Таблица для хранения распределения каналов
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS channel_distribution (
                        chat_id INTEGER NOT NULL,
                        account_id TEXT NOT NULL,
                        assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (chat_id)
                    )
                ''')

                # Добавляем супер-админа если его нет
                cur.execute('''
                    INSERT OR IGNORE INTO administrators 
                    (username, added_by, is_super_admin, is_active)
                    VALUES (?, 'system', 1, 1)
                ''', (self.super_admin_username,))

                conn.commit()
                self.logger.info("База данных успешно инициализирована")

        except Exception as e:
            self.logger.error(f"Ошибка при инициализации базы данных: {e}")
            raise

    async def save_super_admin_chat_id(self, chat_id: int) -> bool:
        """Сохранение chat_id супер-админа"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute('''
                    UPDATE administrators 
                    SET chat_id = ? 
                    WHERE username = ? AND is_super_admin = 1
                ''', (chat_id, SUPER_ADMIN_USERNAME))
                conn.commit()
                self.logger.info(f"Chat ID супер-админа обновлен: {chat_id}")
                return True
        except Exception as e:
            self.logger.error(f"Ошибка при сохранении chat_id супер-админа: {e}")
            return False

    async def get_admin_chat_id(self, username: str) -> Optional[int]:
        """Получение chat_id администратора"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute('''
                    SELECT chat_id 
                    FROM administrators 
                    WHERE username = ? AND is_active = 1
                ''', (username,))
                result = cur.fetchone()
                return result[0] if result and result[0] is not None else None
        except Exception as e:
            self.logger.error(f"Ошибка при получении chat_id админа: {e}")
            return None

    async def is_admin(self, username: str) -> bool:
        """Проверка является ли пользователь администратором"""
        if not username:
            return False
            
        try:
            # Если это супер-админ из конфига
            if username == SUPER_ADMIN_USERNAME:
                return True

            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute('''
                    SELECT 1 FROM administrators 
                    WHERE username = ? AND is_active = 1
                ''', (username,))
                return bool(cur.fetchone())
        except Exception as e:
            self.logger.error(f"Ошибка при проверке админа: {e}")
            return False

    async def add_admin(self, username: str, added_by: str, is_super: bool = False) -> bool:
        """Добавление нового администратора"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute('''
                    INSERT OR REPLACE INTO administrators 
                    (username, added_by, is_super_admin, is_active, chat_id)
                    VALUES (?, ?, ?, 1, NULL)
                ''', (username, added_by, 1 if is_super else 0))
                conn.commit()
                return True
        except Exception as e:
            self.logger.error(f"Ошибка при добавлении админа: {e}")
            return False

    async def save_admin_chat_id(self, username: str, chat_id: int) -> bool:
        """Сохранение chat_id администратора"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute('''
                    UPDATE administrators 
                    SET chat_id = ? 
                    WHERE username = ? AND is_active = 1
                ''', (chat_id, username))
                conn.commit()
                return True
        except Exception as e:
            self.logger.error(f"Ошибка при сохранении chat_id админа: {e}")
            return False

    async def remove_admin(self, username: str, removed_by: str) -> bool:
        """Удаление администратора"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                
                # Проверяем, не является ли удаляемый админ супер-админом
                cur.execute('SELECT is_super_admin FROM administrators WHERE username = ?', (username,))
                result = cur.fetchone()
                
                if result and result[0]:
                    return False  # Нельзя удалить супер-админа
                
                cur.execute('''
                    UPDATE administrators 
                    SET is_active = 0 
                    WHERE username = ? AND is_super_admin = 0
                ''', (username,))
                conn.commit()
                return cur.rowcount > 0
        except Exception as e:
            self.logger.error(f"Ошибка при удалении админа: {e}")
            return False

    async def get_admins(self) -> List[Dict]:
        """Получение списка администраторов"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute('''
                    SELECT username, added_by, added_at, is_super_admin 
                    FROM administrators 
                    WHERE is_active = 1
                    ORDER BY is_super_admin DESC, added_at ASC
                ''')
                
                admins = []
                for row in cur.fetchall():
                    admins.append({
                        'username': row[0],
                        'added_by': row[1],
                        'added_at': row[2],
                        'is_super_admin': bool(row[3])
                    })
                return admins
        except Exception as e:
            self.logger.error(f"Ошибка при получении списка админов: {e}")
            return []

    async def update_keyword_stats(self, keyword: str, channel_id: int, channel_title: str) -> None:
        """Обновление статистики для ключевого слова"""
        try:
            current_time = datetime.now()
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                
                # Обновляем общую статистику
                cur.execute('''
                    INSERT INTO keyword_stats (
                        keyword, total_mentions, first_mention_date, last_mention_date,
                        mentions_today, mentions_week, mentions_month
                    )
                    VALUES (?, 1, ?, ?, 1, 1, 1)
                    ON CONFLICT(keyword) DO UPDATE SET
                        total_mentions = total_mentions + 1,
                        last_mention_date = ?,
                        mentions_today = mentions_today + 1,
                        mentions_week = mentions_week + 1,
                        mentions_month = mentions_month + 1,
                        last_updated = ?
                ''', (keyword, current_time, current_time, current_time, current_time))

                # Обновляем статистику по каналам
                cur.execute('''
                    INSERT INTO keyword_channel_stats (
                        keyword, channel_id, channel_title, mentions,
                        first_mention, last_mention
                    )
                    VALUES (?, ?, ?, 1, ?, ?)
                    ON CONFLICT(keyword, channel_id) DO UPDATE SET
                        mentions = mentions + 1,
                        last_mention = ?
                ''', (keyword, channel_id, channel_title, current_time, current_time, current_time))

                conn.commit()
        except Exception as e:
            self.logger.error(f"Ошибка при обновлении статистики ключевого слова: {e}")

    async def get_keyword_stats(self, keyword: Optional[str] = None) -> Dict:
        """Получение статистики ключевых слов"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                
                if keyword:
                    # Статистика для конкретного слова
                    cur.execute('''
                        SELECT 
                            k.total_mentions,
                            k.total_channels,
                            k.mentions_today,
                            k.mentions_week,
                            k.mentions_month,
                            k.first_mention_date,
                            k.last_mention_date,
                            COUNT(DISTINCT kc.channel_id) as unique_channels,
                            GROUP_CONCAT(DISTINCT kc.channel_title) as channels
                        FROM keyword_stats k
                        LEFT JOIN keyword_channel_stats kc ON k.keyword = kc.keyword
                        WHERE k.keyword = ?
                        GROUP BY k.keyword
                    ''', (keyword,))
                    row = cur.fetchone()
                    
                    if not row:
                        return {}
                        
                    return {
                        'total_mentions': row[0],
                        'total_channels': row[1],
                        'mentions_today': row[2],
                        'mentions_week': row[3],
                        'mentions_month': row[4],
                        'first_mention': row[5],
                        'last_mention': row[6],
                        'unique_channels': row[7],
                        'channels': row[8].split(',') if row[8] else []
                    }
                else:
                    cur.execute('''
                        SELECT 
                            keyword,
                            total_mentions,
                            mentions_today,
                            mentions_week,
                            mentions_month
                        FROM keyword_stats
                        ORDER BY total_mentions DESC
                    ''')
                    
                    stats = {}
                    for row in cur.fetchall():
                        stats[row[0]] = {
                            'total_mentions': row[1],
                            'mentions_today': row[2],
                            'mentions_week': row[3],
                            'mentions_month': row[4]
                        }
                    return stats
                    
        except Exception as e:
            self.logger.error(f"Ошибка при получении статистики ключевых слов: {e}")
            return {}

    async def cleanup_keyword_stats(self) -> None:
        """Очистка устаревшей статистики"""
        try:
            current_time = datetime.now()
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()

                cur.execute('''
                    UPDATE keyword_stats
                    SET mentions_today = 0
                    WHERE date(last_updated) < date(?)
                ''', (current_time,))
                
                # Сбрасываем еженедельную статистику
                cur.execute('''
                    UPDATE keyword_stats
                    SET mentions_week = 0
                    WHERE date(last_updated) < date(?, '-7 days')
                ''', (current_time,))
                
                # Сбрасываем ежемесячную статистику
                cur.execute('''
                    UPDATE keyword_stats
                    SET mentions_month = 0
                    WHERE date(last_updated) < date(?, '-30 days')
                ''', (current_time,))
                
                conn.commit()
        except Exception as e:
            self.logger.error(f"Ошибка при очистке статистики: {e}")

    async def get_top_keywords(self, limit: int = 10, period: str = 'total') -> List[Dict]:
        """Получение топ ключевых слов"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                
                period_field = {
                    'total': 'total_mentions',
                    'today': 'mentions_today',
                    'week': 'mentions_week',
                    'month': 'mentions_month'
                }.get(period, 'total_mentions')

                cur.execute(f'''
                    SELECT 
                        keyword,
                        {period_field} as mentions,
                        total_channels,
                        first_mention_date,
                        last_mention_date
                    FROM keyword_stats
                    WHERE {period_field} > 0
                    ORDER BY {period_field} DESC
                    LIMIT ?
                ''', (limit,))
                
                return [{
                    'keyword': row[0],
                    'mentions': row[1],
                    'channels': row[2],
                    'first_mention': row[3],
                    'last_mention': row[4]
                } for row in cur.fetchall()]
                
        except Exception as e:
            self.logger.error(f"Ошибка при получении топ ключевых слов: {e}")
            return []

    async def save_distribution(self, distribution: Dict[str, List[int]]) -> bool:
        """Сохранение распределения каналов по аккаунтам"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Очищаем старое распределение
                await db.execute('DELETE FROM channel_distribution')
                
                # Сохраняем новое распределение
                for account_id, channel_ids in distribution.items():
                    for chat_id in channel_ids:
                        await db.execute('''
                            INSERT INTO channel_distribution (chat_id, account_id)
                            VALUES (?, ?)
                        ''', (chat_id, account_id))
                
                await db.commit()
                return True
                
        except Exception as e:
            self.logger.error(f"Ошибка при сохранении распределения: {e}")
            return False

    async def load_distribution(self) -> Dict[str, List[int]]:
        """Загрузка распределения каналов по аккаунтам"""
        try:
            distribution = {}
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute('''
                    SELECT account_id, chat_id 
                    FROM channel_distribution 
                    ORDER BY assigned_at
                ''') as cursor:
                    async for row in cursor:
                        account_id, chat_id = row
                        if account_id not in distribution:
                            distribution[account_id] = []
                        distribution[account_id].append(chat_id)
                        
            return distribution
            
        except Exception as e:
            self.logger.error(f"Ошибка при загрузке распределения: {e}")
            return {}

    async def get_channel_account(self, chat_id: int) -> Optional[str]:
        """Получение ID аккаунта, отвечающего за канал"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute('''
                    SELECT account_id 
                    FROM channel_distribution 
                    WHERE chat_id = ?
                ''', (chat_id,)) as cursor:
                    row = await cursor.fetchone()
                    return row[0] if row else None
                    
        except Exception as e:
            self.logger.error(f"Ошибка при получении аккаунта для канала: {e}")
            return None

    async def update_channel_account(self, chat_id: int, account_id: str) -> bool:
        """Обновление привязки канала к аккаунту"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute('''
                    INSERT OR REPLACE INTO channel_distribution (chat_id, account_id)
                    VALUES (?, ?)
                ''', (chat_id, account_id))
                await db.commit()
                return True
                
        except Exception as e:
            self.logger.error(f"Ошибка при обновлении привязки канала: {e}")
            return False

    def load_keywords(self) -> List[str]:
        try:
            if os.path.exists(self.keywords_file):
                with open(self.keywords_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return []
        except Exception as e:
            logger.error(f"Ошибка при загрузке ключевых слов: {e}")
            return []

    def save_keywords(self, keywords: List[str]) -> bool:
        try:
            with open(self.keywords_file, 'w', encoding='utf-8') as f:
                json.dump(keywords, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Ошибка при сохранении ключевых слов: {e}")
            return False

    async def add_found_message(self, chat_id: int, chat_title: str, message_id: int,
                              sender_id: Optional[int], sender_name: str, text: str,
                              found_keywords: List[str]) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute('''
                    INSERT INTO messages (
                        chat_id, chat_title, message_id, sender_id,
                        sender_name, text, found_keywords
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    chat_id, chat_title, message_id, sender_id,
                    sender_name, text, json.dumps(found_keywords)
                ))
                await db.commit()

                for keyword in found_keywords:
                    await db.execute('''
                        INSERT INTO keyword_stats (
                            keyword, total_mentions, first_mention_date, last_mention_date,
                            mentions_today, mentions_week, mentions_month
                        )
                        VALUES (?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, 1, 1)
                        ON CONFLICT(keyword) DO UPDATE SET
                            total_mentions = total_mentions + 1,
                            last_mention_date = CURRENT_TIMESTAMP,
                            mentions_today = mentions_today + 1,
                            mentions_week = mentions_week + 1,
                            mentions_month = mentions_month + 1,
                            last_updated = CURRENT_TIMESTAMP
                    ''', (keyword,))
                await db.commit()
                
            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении сообщения: {e}")
            return False

    async def add_multiple_channels(self, channel_links: List[str]) -> Tuple[int, List[str]]:
        """
        Массовое добавление каналов с распределением по аккаунтам
        
        Args:
            channel_links: Список ссылок на каналы
            
        Returns:
            Tuple[int, List[str]]: (количество добавленных каналов, список ошибок)
        """
        added = 0
        errors = []
        new_channels = []
        
        # Проверяем наличие клиентов
        if not self.monitoring_clients:
            return 0, ["Нет доступных клиентов для добавления каналов"]
            
        client = next(iter(self.monitoring_clients.values()))
        
        # Обрабатываем каждую ссылку
        for link in channel_links:
            try:
                # Обработка ссылки
                if link.startswith('https://t.me/'):
                    if '+' in link:
                        # Приватная ссылка остается как есть
                        chat_link = link
                    else:
                        username = link.split('/')[-1]
                        chat_link = f"@{username}"
                elif not link.startswith('@'):
                    chat_link = f"@{link}"
                else:
                    chat_link = link
                    
                self.logger.info(f"Пытаемся добавить чат: {chat_link}")
                
                # Получаем информацию о канале
                try:
                    entity = await client.get_entity(chat_link)
                    self.logger.info(f"Получена информация о чате: {entity.title}")
                    
                    if not isinstance(entity, (Channel, PeerChannel)):
                        errors.append(f"{chat_link}: Это не канал или группа")
                        continue
                        
                    # Проверяем, не добавлен ли уже канал
                    channels = await self.db.load_channels()
                    if any(int(channel['chat_id']) == entity.id for channel in channels):
                        errors.append(f"{chat_link}: Канал уже добавлен")
                        continue
                        
                    new_channels.append({
                        'id': entity.id,
                        'title': entity.title,
                        'username': entity.username,
                        'link': chat_link
                    })
                    added += 1
                    
                except Exception as e:
                    errors.append(f"{chat_link}: Не удалось получить информацию о канале: {str(e)}")
                    continue
                    
            except Exception as e:
                errors.append(f"{chat_link}: {str(e)}")
                continue
                
        if added > 0:
            try:
                # Сохраняем новые каналы в базу
                for channel in new_channels:
                    success = await self.db.add_channel(
                        chat_id=channel['id'],
                        title=channel['title'],
                        username=channel['username']
                    )
                    if not success:
                        self.logger.error(f"Не удалось сохранить канал {channel['title']} в базу")
                
                # Получаем все каналы для распределения
                all_channels = await self.db.load_channels()
                available_accounts = list(self.monitoring_clients.keys())
                
                # Запускаем перераспределение
                new_distribution = await self.distributor.distribute_channels(
                    [int(channel['chat_id']) for channel in all_channels],
                    available_accounts
                )
                
                # Применяем новое распределение
                if new_distribution:
                    await self.distributor.apply_distribution(new_distribution)
                    
                    # Для каждого аккаунта обрабатываем его новые каналы
                    for account_id, channels in new_distribution.items():
                        client = self.monitoring_clients.get(account_id)
                        if client:
                            # Вступаем в новые каналы
                            for chat_id in channels:
                                try:
                                    await self.distributor.safe_join_channel(client, chat_id)
                                    await asyncio.sleep(self.distributor.join_delay)
                                except Exception as e:
                                    errors.append(f"Ошибка при вступлении в канал {chat_id} с аккаунта {account_id}: {str(e)}")
                                    
                            # Обновляем обработчики для клиента
                            handlers_to_remove = []
                            for handler in client.list_event_handlers():
                                if handler[0] == self.message_handler:
                                    handlers_to_remove.append(handler)
                            
                            for handler in handlers_to_remove:
                                client.remove_event_handler(handler[0])
                                
                            client.add_event_handler(
                                self.message_handler,
                                events.NewMessage(chats=channels)
                            )
                            
                            self.logger.info(f"Обновлены каналы для аккаунта {account_id}: {len(channels)} каналов")
            
            except Exception as e:
                errors.append(f"Ошибка при распределении каналов: {str(e)}")
                
        return added, errors
        
    async def add_channel(self, chat_id: int, title: str, username: str = None) -> bool:
        """Добавление канала в базу данных"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute('''
                    INSERT OR IGNORE INTO channels 
                    (chat_id, title, username, is_active) 
                    VALUES (?, ?, ?, 1)
                ''', (chat_id, title, username))
                await db.commit()
                return True
        except Exception as e:
            self.logger.error(f"Ошибка при добавлении канала: {e}")
            return False

    async def load_channels(self) -> List[Dict]:
        """Асинхронная загрузка списка каналов"""
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                cursor = await conn.execute('''
                    SELECT chat_id, username, title 
                    FROM channels 
                    WHERE is_active = 1
                ''')
                
                rows = await cursor.fetchall()
                channels = []
                
                for row in rows:
                    chat_id, username, title = row
                    channel = {
                        'chat_id': int(chat_id),
                        'username': username,
                        'title': title
                    }
                    channels.append(channel)
                    self.logger.info(f"Загружен канал: {title} (ID={chat_id})")
                    
                await cursor.close()
                return channels
                
        except Exception as e:
            self.logger.error(f"Ошибка при загрузке каналов: {e}")
            return []

    async def remove_channel(self, chat_id: int) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    'UPDATE channels SET is_active = 0 WHERE chat_id = ?',
                    (chat_id,)
                )
                await db.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка при удалении канала: {e}")
            return False


    async def log_event(self, event_type: str, description: str) -> None:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    'INSERT INTO monitoring_logs (event_type, description) VALUES (?, ?)',
                    (event_type, description)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Ошибка при логировании события: {e}")

    def get_monitoring_stats(self) -> Dict:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute('''
                    SELECT 
                        COUNT(*) as total_messages,
                        COUNT(DISTINCT chat_id) as unique_chats,
                        COUNT(DISTINCT DATE(timestamp)) as active_days,
                        MAX(timestamp) as last_message
                    FROM messages
                ''')
                msg_stats = cur.fetchone()

                # Статистика по ошибкам
                cur.execute('''
                    SELECT COUNT(*) 
                    FROM monitoring_logs 
                    WHERE event_type = 'error'
                    AND timestamp > datetime('now', '-1 day')
                ''')
                error_count = cur.fetchone()[0]

                return {
                    'total_messages': msg_stats[0],
                    'unique_chats': msg_stats[1],
                    'active_days': msg_stats[2],
                    'last_message': msg_stats[3],
                    'errors_24h': error_count
                }
        except Exception as e:
            logger.error(f"Ошибка при получении статистики мониторинга: {e}")
            return {
                'total_messages': 0,
                'unique_chats': 0,
                'active_days': 0,
                'last_message': None,
                'errors_24h': 0
            }

    def cleanup_old_data(self, days: int = 30) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute(
                    'DELETE FROM messages WHERE timestamp < datetime("now", ?)',
                    (f'-{days} days',)
                )
                cur.execute(
                    'DELETE FROM monitoring_logs WHERE timestamp < datetime("now", ?)',
                    (f'-{days} days',)
                )
                conn.commit()
                logger.info(f"Очищены данные старше {days} дней")
        except Exception as e:
            logger.error(f"Ошибка при очистке старых данных: {e}")

    def save_state(self) -> None:
        """Сохранение текущего состояния базы данных"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.commit()
            logger.info("Состояние базы данных сохранено")
        except Exception as e:
            logger.error(f"Ошибка при сохранении состояния базы данных: {e}")