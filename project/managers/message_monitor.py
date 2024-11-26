import asyncio
import logging
from telethon import types
from typing import Dict, Set, List, Optional, Any
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.types import Message, PeerChannel, Channel
from telethon.tl.functions.channels import JoinChannelRequest
from .account_manager import AccountManager
from .proxy_manager import ProxyManager
from ..database.database_manager import DatabaseManager
from ..config import MESSAGE_TEMPLATES, MONITORING_SETTINGS, BOTS_FOLDER, load_settings
from .smart_distributor import SmartDistributor

logger = logging.getLogger(__name__)

REDISTRIBUTION_THRESHOLD = 1.5

class MessageMonitor:
    def __init__(self, db_manager: DatabaseManager, account_manager: AccountManager):
        self.db = db_manager
        self.account_manager = account_manager
        self.monitoring_clients = {}
        self.bot = None
        self.is_monitoring = False
        self.distributor = None
        self.stats = {
            'messages_processed': 0,
            'keywords_found': 0,
            'errors': 0,
            'start_time': None,
            'status': 'Остановлен',
            'active_clients': 0,
            'watched_channels': 0
        }
        self.logger = logging.getLogger(__name__)
        self.processed_messages = set()

    async def initialize(self, app) -> None:
        try:
            self.bot = app
            self.is_monitoring = False
            
            # Первичная инициализация клиентов
            await self.initialize_clients()
            if not self.monitoring_clients:
                self.logger.error("Нет доступных клиентов")
                return

            # Инициализация распределителя
            self.distributor = SmartDistributor(self.account_manager, self.db)
            await self.distributor.initialize()

            # Загрузка и распределение каналов
            channels = await self.db.load_channels()
            self.logger.info(f"Загружено каналов: {len(channels)}")
            channel_ids = [int(channel['chat_id']) for channel in channels]
            
            if not self.distributor.distribution:
                distribution = await self.distributor.distribute_channels(
                    channel_ids,
                    list(self.monitoring_clients.keys())
                )
                if distribution:
                    await self.distributor.apply_distribution(distribution)

            # Настройка обработчиков для каждого клиента
            for account_id, client in self.monitoring_clients.items():
                client_channels = self.distributor.distribution.get(account_id, [])
                if client_channels:
                    client.add_event_handler(
                        self.message_handler,
                        events.NewMessage(chats=client_channels)
                    )
                    self.logger.info(f"Добавлен обработчик для {account_id} ({len(client_channels)} каналов)")

            # Активация мониторинга
            self.is_monitoring = True
            self.stats['status'] = 'Активен'
            self.stats['start_time'] = datetime.now()
            self.stats['watched_channels'] = len(channels)
            
            self.logger.info(f"Мониторинг активирован, отслеживается {len(channels)} каналов")

        except Exception as e:
            self.logger.error(f"Ошибка при инициализации монитора: {e}")
            raise

    async def update_handlers(self):
        """Обновление обработчиков сообщений для всех клиентов"""
        try:
            distribution = self.distributor.distribution
            
            for account_id, channel_ids in distribution.items():
                client = self.monitoring_clients.get(account_id)
                if client:
                    # Удаляем все существующие обработчики для этого клиента
                    handlers_to_remove = []
                    for handler in client.list_event_handlers():
                        if handler[0] == self.message_handler:
                            handlers_to_remove.append(handler)
                    
                    for handler in handlers_to_remove:
                        client.remove_event_handler(handler[0])

                    if channel_ids:  # Проверяем, что есть каналы для мониторинга
                        client.add_event_handler(
                            self.message_handler,
                            events.NewMessage(chats=channel_ids)
                        )
                        self.logger.info(
                            f"Аккаунту {account_id} назначено {len(channel_ids)} каналов"
                        )
                    
        except Exception as e:
            self.logger.error(f"Ошибка при обновлении обработчиков: {e}")
            
    def load_channels(self) -> List[Dict]:
        try:
            channels = []
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute('''
                    SELECT chat_id, username, title 
                    FROM channels 
                    WHERE is_active = 1
                ''')
                rows = cur.fetchall()
                for row in rows:
                    chat_id, username, title = row
                    channel = {
                        'chat_id': chat_id,
                        'username': username,
                        'title': title
                    }
                    channels.append(channel)
                    self.logger.info(f"Загружен канал: ID={chat_id}, username={username}, title={title}")
            return channels
        except Exception as e:
            self.logger.error(f"Ошибка при загрузке каналов: {e}")
            return []
            
    async def initialize_clients(self) -> None:
        try:
            self.logger.info("Начало инициализации клиентов")
            accounts = self.account_manager.get_accounts()
            self.logger.info(f"Найдено {len(accounts)} аккаунтов")

            # Загружаем список разрешенных каналов
            allowed_channels = await self.db.load_channels()
            allowed_chat_ids = [channel['chat_id'] for channel in allowed_channels]

            for account in accounts:
                if account not in self.monitoring_clients:
                    try:
                        await asyncio.sleep(1)
                        client = await self.account_manager.create_client(account)
                        if client:
                            self.logger.info(f"Клиент {account} создан успешно")
                            # Добавляем обработчик только для разрешенных каналов
                            client.add_event_handler(
                                self.message_handler,
                                events.NewMessage(chats=allowed_chat_ids)  # Фильтруем по списку разрешенных каналов
                            )
                            self.monitoring_clients[account] = client
                    except Exception as e:
                        self.logger.error(f"Ошибка при инициализации клиента {account}: {e}")

            self.logger.info(f"Инициализировано {len(self.monitoring_clients)} клиентов")

        except Exception as e:
            self.logger.error(f"Ошибка при инициализации клиентов: {e}")

    async def handle_account_failure(self, account_id: str, error: Exception) -> None:
        """Обработка выхода аккаунта из строя"""
        try:
            self.logger.error(f"Аккаунт {account_id} вышел из строя: {error}")
            
            # Отключаем проблемный клиент
            client = self.monitoring_clients.pop(account_id, None)
            if client:
                try:
                    await client.disconnect()
                except:
                    pass

            # Пробуем переподключить аккаунт
            MAX_RETRY_ATTEMPTS = 3
            for attempt in range(MAX_RETRY_ATTEMPTS):
                try:
                    self.logger.info(f"Попытка переподключения аккаунта {account_id} ({attempt + 1}/{MAX_RETRY_ATTEMPTS})")
                    await asyncio.sleep(5 * (attempt + 1))  # Увеличивающаяся задержка
                    
                    new_client = await self.account_manager.create_client(account_id)
                    if new_client:
                        self.monitoring_clients[account_id] = new_client
                        self.logger.info(f"Аккаунт {account_id} успешно переподключен")
                        
                        # Восстанавливаем обработчики
                        channels = self.distributor.distribution.get(account_id, [])
                        if channels:
                            new_client.add_event_handler(
                                self.message_handler,
                                events.NewMessage(chats=channels)
                            )
                        return
                except Exception as e:
                    self.logger.error(f"Попытка {attempt + 1} переподключения аккаунта {account_id} не удалась: {e}")

            # Если все попытки неудачны, перераспределяем каналы
            self.logger.warning(f"Не удалось восстановить аккаунт {account_id}, выполняем перераспределение")
            await self.distributor.handle_account_failure(account_id)

        except Exception as e:
            self.logger.error(f"Ошибка при обработке выхода аккаунта из строя: {e}")

    async def message_handler(self, event) -> None:
        """Обработчик новых сообщений"""
        try:
            if not self.is_monitoring or not event.message:
                return
                
            chat = await event.get_chat()
            if hasattr(chat, 'type') and chat.type == 'private':
                return
                    
            message_unique_id = f"{event.chat_id}_{event.message.id}"
            
            if message_unique_id in self.processed_messages:
                return
                    
            self.processed_messages.add(message_unique_id)
            
            if len(self.processed_messages) > 1000:
                self.processed_messages = set(list(self.processed_messages)[-1000:])

            self.stats['messages_processed'] += 1
            
            if not event.message.text:
                return
                    
            # Загружаем ключевые слова
            keywords = self.db.load_keywords()
            if not keywords:
                return
                    
            # Ищем совпадения
            found_keywords = []
            message_text = event.message.text.lower()
            for word in keywords:
                if word.lower() in message_text:
                    found_keywords.append(word)

            if not found_keywords:
                return

            # Обновляем статистику найденных ключевых слов - исправлено
            self.stats['keywords_found'] = self.stats.get('keywords_found', 0) + len(found_keywords)
                    
            self.logger.info(f"Найдены ключевые слова: {found_keywords}")

            # Получаем информацию об отправителе
            sender = await event.get_sender()
            sender_info = ""
            if sender:
                if getattr(sender, 'username', None):
                    first_name = sender.first_name or ''
                    last_name = sender.last_name or ''
                    full_name = f"{first_name} {last_name}".strip()
                    
                    if full_name:
                        sender_info = f"[{full_name}](https://t.me/{sender.username})"
                    else:
                        sender_info = f"[@{sender.username}](https://t.me/{sender.username})"
                else:
                    # Если нет username, просто показываем имя
                    sender_info = f"{sender.first_name or ''} {sender.last_name or ''}"

                if not sender_info.strip():
                    sender_info = "Unknown User"
            else:
                sender_info = "Unknown User"

            if hasattr(chat, 'username') and chat.username:
                message_link = f"https://t.me/{chat.username}/{event.message.id}"
            else:
                try:
                    chat_id_str = str(chat.id)
                    if chat_id_str.startswith('-100'):
                        chat_id_str = chat_id_str[4:]
                    message_link = f"https://t.me/c/{chat_id_str}/{event.message.id}"
                except:
                    message_link = "Ссылка недоступна"

            escaped_chat_title = chat.title.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`').replace('[', '\\[')
            escaped_text = event.message.text[:4000].replace('_', '\\_').replace('*', '\\*').replace('`', '\\`').replace('[', '\\[')
            escaped_keywords = ', '.join(k.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`').replace('[', '\\[') for k in found_keywords)

            # Получаем список всех админов
            admins = await self.db.get_admins()

            # Формируем уведомление с кликабельным отправителем
            notification = (
                "🔍 *Найдено совпадение\\!*\n\n"
                f"📱 *Группа:* `{escaped_chat_title}`\n"
                f"👤 *Отправитель:* {sender_info}\n"
                f"🔑 *Ключевые слова:* `{escaped_keywords}`\n\n"
                f"💬 *Сообщение:*\n"
                f"`{escaped_text}`\n\n"
                f"🔗 [Ссылка на сообщение]({message_link})\n"
                f"⏰ Время: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
            )

            # На случай, если форматирование не сработает, запасной вариант без разметки
            simple_notification = (
                "🔍 Найдено совпадение!\n\n"
                f"📱 Группа: {chat.title}\n"
                f"👤 Отправитель: {sender_info}\n"
                f"🔑 Ключевые слова: {', '.join(found_keywords)}\n\n"
                f"💬 Сообщение:\n"
                f"{event.message.text[:4000]}\n\n"
                f"🔗 {message_link}\n"
                f"⏰ Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            # Отправляем уведомление всем админам
            for admin in admins:
                try:
                    chat_id = await self.db.get_admin_chat_id(admin['username'])
                    if not chat_id:
                        self.logger.warning(
                            f"Chat ID не найден для админа @{admin['username']}. "
                            "Возможно, админ ещё не запустил бота"
                        )
                        continue

                    try:
                        # Пробуем отправить форматированное сообщение
                        await self.bot.bot.send_message(
                            chat_id=chat_id,
                            text=notification,
                            parse_mode='MarkdownV2',
                            disable_web_page_preview=True
                        )
                    except Exception as format_error:
                        # Если не получилось, отправляем простое сообщение
                        self.logger.error(f"Ошибка форматирования: {format_error}")
                        await self.bot.bot.send_message(
                            chat_id=chat_id,
                            text=simple_notification,
                            disable_web_page_preview=True
                        )

                except Exception as e:
                    self.logger.error(f"Ошибка при отправке уведомления админу {admin['username']}: {str(e)}")

            # Сохраняем в базу данных
            try:
                await self.db.add_found_message(
                    chat_id=chat.id,
                    chat_title=chat.title,
                    message_id=event.message.id,
                    sender_id=sender.id if sender else None,
                    sender_name=sender_info,
                    text=event.message.text,
                    found_keywords=found_keywords
                )
            except Exception as db_error:
                self.logger.error(f"Ошибка при сохранении сообщения в базу данных: {str(db_error)}")

        except Exception as e:
            self.logger.error(f"Ошибка при обработке сообщения: {str(e)}")
            self.stats['errors'] += 1
            
            
    async def send_error_notification(self, error_description: str) -> None:
        try:
            notification = MESSAGE_TEMPLATES['error_notification'].format(
                error_type="Ошибка обработки сообщения",
                description=error_description,
                time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            
            await self.bot.send_message(
                chat_id=self.admin_chat_id,
                text=notification,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления об ошибке: {e}")

    async def start_monitoring(self) -> None:
        """Запуск мониторинга"""
        try:
            if not self.is_monitoring:
                self.logger.info("Запуск мониторинга...")
                
                if not self.monitoring_clients:
                    self.logger.error("Нет активных клиентов для мониторинга")
                    return

                self.is_monitoring = True
                self.stats['status'] = 'Активен'
                self.stats['start_time'] = datetime.now()
                
                # Запускаем задачу проверки состояния
                self.health_check_task = asyncio.create_task(self.periodic_health_check())
                
                self.logger.info(f"Мониторинг запущен с {len(self.monitoring_clients)} клиентами")
                
        except Exception as e:
            self.logger.error(f"Ошибка при запуске мониторинга: {e}")

    async def stop_monitoring(self) -> None:
        """Остановка мониторинга"""
        try:
            self.is_monitoring = False
            self.stats['status'] = 'Остановлен'
            self.stats['start_time'] = None
            
            # Останавливаем задачу проверки состояния
            if hasattr(self, 'health_check_task'):
                self.health_check_task.cancel()
                
            # Корректно закрываем все клиенты
            for phone, client in self.monitoring_clients.items():
                try:
                    if client and client.is_connected():
                        await client.disconnect()
                        self.logger.info(f"Клиент {phone} отключен")
                except Exception as e:
                    self.logger.error(f"Ошибка при отключении клиента {phone}: {e}")
                
            self.monitoring_clients.clear()
            self.logger.info("Мониторинг остановлен")
                
        except Exception as e:
            self.logger.error(f"Ошибка при остановке мониторинга: {e}")

    async def periodic_health_check(self):
        """Периодическая проверка состояния системы"""
        try:
            while self.is_monitoring:
                await asyncio.sleep(300)  # Проверка каждые 5 минут
                
                if not self.is_monitoring:
                    break
                    
                self.logger.info("Выполняется проверка состояния системы...")
                
                # Проверяем каждый аккаунт
                for account_id, client in list(self.monitoring_clients.items()):
                    try:
                        if not client.is_connected():
                            await self.handle_account_error(
                                account_id,
                                Exception("Клиент отключен")
                            )
                            continue
                            
                        # Проверяем авторизацию
                        if not await client.is_user_authorized():
                            await self.handle_account_error(
                                account_id,
                                Exception("Аккаунт не авторизован")
                            )
                            continue

                        try:
                            await client.get_me()
                        except Exception as e:
                            if "FLOOD_WAIT" in str(e):
                                await self.handle_account_error(account_id, e)
                                continue
                                
                    except Exception as e:
                        self.logger.error(f"Ошибка при проверке аккаунта {account_id}: {e}")
                        
                # Проверяем необходимость перераспределения
                if self.distributor:
                    channels_count = len(set().union(*[
                        channels for channels in self.distributor.distribution.values()
                    ]))
                    
                    if channels_count < self.stats['watched_channels']:
                        self.logger.warning("Обнаружены неотслеживаемые каналы, выполняем перераспределение")
                        await self.redistribute_channels()
                        
        except asyncio.CancelledError:
            self.logger.info("Задача проверки состояния остановлена")
        except Exception as e:
            self.logger.error(f"Ошибка в задаче проверки состояния: {e}")

    async def redistribute_channels(self) -> Dict[str, List[int]]:
        try:
            if not self.distributor:
                return {}
                        
            # Получаем все каналы
            channels = await self.db.load_channels()
            if not channels:
                return {}
                        
            # Получаем рабочие аккаунты
            working_accounts = []
            for account_id, client in self.monitoring_clients.items():
                if client and client.is_connected():
                    is_authorized = await client.is_user_authorized()
                    if is_authorized:
                        working_accounts.append(account_id)
                    
            if not working_accounts:
                self.logger.error("Нет рабочих аккаунтов для перераспределения")
                return {}
                        
            # Выполняем новое распределение
            new_distribution = await self.distributor.distribute_channels(
                [int(channel['chat_id']) for channel in channels],
                working_accounts
            )
                    
            if new_distribution:
                # Применяем новое распределение
                await self.distributor.apply_distribution(new_distribution)
                
                # Для каждого аккаунта обновляем обработчики и членство в каналах
                for account_id, channel_ids in new_distribution.items():
                    client = self.monitoring_clients.get(account_id)
                    if client:
                        # Обновляем обработчики для клиента
                        handlers_to_remove = []
                        for handler in client.list_event_handlers():
                            if handler[0] == self.message_handler:
                                handlers_to_remove.append(handler)
                        
                        for handler in handlers_to_remove:
                            client.remove_event_handler(handler[0])
                            
                        client.add_event_handler(
                            self.message_handler,
                            events.NewMessage(chats=channel_ids)
                        )
                        
                        self.logger.info(f"Обновлены каналы для аккаунта {account_id}: {len(channel_ids)} каналов")

                return new_distribution
                
            return {}

        except Exception as e:
            self.logger.error(f"Ошибка при перераспределении каналов: {e}")
            return {}

    async def add_channel(self, link: str, progress_callback = None) -> bool:
        try:
            if not self.monitoring_clients:
                raise ValueError("Нет доступных клиентов")

            if progress_callback:
                await progress_callback(f"🔍 Получение информации о канале: {link}")

            client = next(iter(self.monitoring_clients.values()))
            self.logger.info(f"Используем клиент для добавления чата")

            if link.startswith('https://t.me/'):
                if '+' in link:
                    chat_link = link
                else:
                    username = link.split('/')[-1]
                    chat_link = f"@{username}"
            elif not link.startswith('@'):
                chat_link = f"@{link}"
            else:
                chat_link = link

            self.logger.info(f"Пытаемся добавить чат: {chat_link}")
            
            if progress_callback:
                await progress_callback(f"🔄 Получение информации о канале...")

            # Получаем информацию о канале
            entity = await client.get_entity(chat_link)
            self.logger.info(f"Получена информацию о чате: {entity.title}")

            if not isinstance(entity, (Channel, PeerChannel)):
                raise ValueError("Это не канал или группа")

            # Проверяем, не добавлен ли уже канал
            existing_channels = await self.db.load_channels()
            if any(int(channel['chat_id']) == entity.id for channel in existing_channels):
                if progress_callback:
                    await progress_callback(f"ℹ️ Канал {entity.title} уже добавлен")
                return True

            # Задержка 30 секунд перед присоединением
            for i in range(30, 0, -1):
                if progress_callback:
                    await progress_callback(
                        f"⏳ Ожидание перед присоединением: {i} сек\n"
                        f"👥 Канал: {entity.title}"
                    )
                await asyncio.sleep(1)

            try:
                if progress_callback:
                    await progress_callback(f"🔄 Вступаем в канал {entity.title}...")
                
                await client(JoinChannelRequest(entity))
                self.logger.info(f"Успешно присоединились к чату: {entity.title}")

                if progress_callback:
                    await progress_callback(f"✅ Успешно вступили в канал {entity.title}")

            except Exception as e:
                if "wait" in str(e).lower():
                    wait_time = int(''.join(filter(str.isdigit, str(e))))
                    if progress_callback:
                        await progress_callback(
                            f"⏳ Требуется ожидание {wait_time} секунд для канала {entity.title}"
                        )
                    await asyncio.sleep(wait_time)
                    
                    if progress_callback:
                        await progress_callback(f"🔄 Повторная попытка вступления в канал {entity.title}")
                    await client(JoinChannelRequest(entity))
                else:
                    raise

            # Сохраняем в базу
            success = await self.db.add_channel(
                chat_id=entity.id,
                title=entity.title,
                username=entity.username
            )

            if not success:
                raise Exception("Не удалось сохранить канал в базу")

            # После успешного сохранения обновляем обработчики
            channels = await self.db.load_channels()
            allowed_chat_ids = [int(channel['chat_id']) for channel in channels]

            for account_id, client in self.monitoring_clients.items():
                try:
                    # Удаляем старые обработчики
                    handlers_to_remove = []
                    for handler in client.list_event_handlers():
                        if handler[0] == self.message_handler:
                            handlers_to_remove.append(handler)
                    
                    for handler in handlers_to_remove:
                        client.remove_event_handler(handler[0])
                    
                    # Добавляем новый обработчик с обновленным списком каналов
                    client.add_event_handler(
                        self.message_handler,
                        events.NewMessage(chats=allowed_chat_ids)
                    )
                    
                    self.logger.info(
                        f"Обновлены обработчики для аккаунта {account_id}: "
                        f"{len(allowed_chat_ids)} каналов"
                    )
                except Exception as e:
                    self.logger.error(
                        f"Ошибка при обновлении обработчиков для аккаунта {account_id}: {e}"
                    )

            # Обновляем статистику
            self.stats['watched_channels'] = len(channels)

            if progress_callback:
                await progress_callback(f"✅ Канал {entity.title} успешно добавлен")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при добавлении чата {link}: {e}")
            if progress_callback:
                await progress_callback(f"❌ Ошибка при добавлении канала {link}: {str(e)}")
            raise
            
            
    async def remove_channel(self, chat_id: int) -> bool:
        try:
            # Удаляем из базы данных
            success = await self.db.remove_channel(chat_id)
            if not success:
                return False

            # Получаем текущее распределение
            if self.distributor:
                distribution = self.distributor.distribution
                
                # Находим аккаунт, которому назначен канал
                for account_id, channels in distribution.items():
                    if chat_id in channels:
                        # Удаляем канал из списка
                        channels.remove(chat_id)
                        
                        # Обновляем обработчики для этого аккаунта
                        client = self.monitoring_clients.get(account_id)
                        if client:
                            # Удаляем старые обработчики
                            handlers_to_remove = []
                            for handler in client.list_event_handlers():
                                if handler[0] == self.message_handler:
                                    handlers_to_remove.append(handler)
                            
                            for handler in handlers_to_remove:
                                client.remove_event_handler(handler[0])
                            
                            # Добавляем новый обработчик с обновленным списком каналов
                            if channels:
                                client.add_event_handler(
                                    self.message_handler,
                                    events.NewMessage(chats=channels)
                                )
                        break

                # Сохраняем обновленное распределение
                await self.distributor.apply_distribution(distribution)

            # Обновляем статистику
            self.stats['watched_channels'] = len(await self.db.load_channels())
            
            self.logger.info(f"Канал {chat_id} успешно удален")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка при удалении канала {chat_id}: {e}")
            return False

    def get_stats(self) -> Dict:
        if self.stats['start_time'] and self.is_monitoring:
            uptime = datetime.now() - self.stats['start_time']
            self.stats['uptime'] = str(uptime).split('.')[0]
        else:
            self.stats['uptime'] = '0:00:00'

        self.stats['active_clients'] = len([client for client in self.monitoring_clients.values() if client.is_connected()])
        
        distribution = self.distributor.distribution if self.distributor else {}
        total_channels = len(set().union(*[channels for channels in distribution.values()])) if distribution else 0
        self.stats['watched_channels'] = total_channels

        return self.stats

    async def check_channels(self) -> Dict[str, bool]:
        results = {}
        for channel in self.watched_channels:
            available = False
            for client in self.monitoring_clients.values():
                try:
                    entity = await client.get_entity(channel)
                    if entity:
                        available = True
                        break
                except Exception:
                    continue
            results[channel] = available
        return results
        
    async def calculate_optimal_channels(self) -> int:
        try:
            from project.config import load_settings
            settings = load_settings()
            max_channels_per_client = settings.get('max_channels_per_client', 500)

            all_channels = self.db.load_channels()
            total_channels = len(all_channels)
            active_accounts = len(self.monitoring_clients)

            if active_accounts == 0:
                return 0

            optimal = total_channels // active_accounts

            if optimal > max_channels_per_client:
                optimal = max_channels_per_client

            MIN_CHANNELS = 10
            if optimal < MIN_CHANNELS and total_channels >= MIN_CHANNELS:
                optimal = MIN_CHANNELS

            self.logger.info(
                f"Расчет оптимальной нагрузки:\n"
                f"Всего каналов: {total_channels}\n"
                f"Активных аккаунтов: {active_accounts}\n"
                f"Оптимально на аккаунт: {optimal}\n"
                f"Максимально разрешено: {max_channels_per_client}"
            )

            return optimal

        except Exception as e:
            self.logger.error(f"Ошибка при расчете оптимальной нагрузки: {e}")
            return settings.get('max_channels_per_client', 500)

    async def handle_new_account(self, account_id: str) -> bool:
        try:
            client = await self.account_manager.create_client(account_id)
            if not client:
                self.logger.error(f"Не удалось создать клиент для аккаунта {account_id}")
                return False

            self.monitoring_clients[account_id] = client

            optimal_channels_per_account = await self.calculate_optimal_channels()
            channels_to_move = []

            for existing_account, existing_client in self.monitoring_clients.items():
                if existing_account == account_id:
                    continue

                current_channels = self.distributor.distribution.get(existing_account, [])
                if len(current_channels) > (optimal_channels_per_account * REDISTRIBUTION_THRESHOLD):
                    excess_channels = len(current_channels) - optimal_channels_per_account
                    channels_to_transfer = min(
                        excess_channels,
                        len(current_channels) - optimal_channels_per_account
                    )

                    channels_to_move.extend(current_channels[-channels_to_transfer:])
                    self.distributor.distribution[existing_account] = current_channels[:-channels_to_transfer]

                    handlers_to_remove = []
                    for handler in existing_client.list_event_handlers():
                        if handler[0] == self.message_handler:
                            handlers_to_remove.append(handler)

                    for handler in handlers_to_remove:
                        existing_client.remove_event_handler(handler[0])

                    existing_client.add_event_handler(
                        self.message_handler,
                        events.NewMessage(chats=self.distributor.distribution[existing_account])
                    )

                    self.logger.info(
                        f"Перемещаем {channels_to_transfer} каналов с аккаунта {existing_account}"
                    )

            if channels_to_move:
                self.distributor.distribution[account_id] = channels_to_move

                for channel_id in channels_to_move:
                    try:
                        await self.distributor.safe_join_channel(client, channel_id)
                        await asyncio.sleep(5)
                    except Exception as e:
                        self.logger.error(f"Ошибка при присоединении к каналу {channel_id}: {e}")

                client.add_event_handler(
                    self.message_handler,
                    events.NewMessage(chats=channels_to_move)
                )

                self.logger.info(
                    f"Аккаунту {account_id} передано {len(channels_to_move)} каналов"
                )

                # Уведомление админу
                notification = (
                    f"✅ Новый аккаунт {account_id} добавлен\n"
                    f"📊 Перераспределено {len(channels_to_move)} каналов\n"
                    f"📈 Текущая нагрузка:\n"
                )

                for acc, channels in self.distributor.distribution.items():
                    notification += f"• Аккаунт {acc}: {len(channels)} каналов\n"

                if hasattr(self.bot, 'bot'):
                    await self.bot.bot.send_message(
                        chat_id=self.admin_chat_id,
                        text=notification,
                        parse_mode='Markdown'
                    )
                elif hasattr(self.bot, 'send_message'):
                    await self.bot.send_message(
                        chat_id=self.admin_chat_id,
                        text=notification,
                        parse_mode='Markdown'
                    )

            else:
                self.logger.info(
                    f"Аккаунт {account_id} добавлен без перераспределения. "
                    f"Будет использован для новых каналов."
                )

                # Уведомление админу о добавлении без перераспределения
                notification = (
                    f"✅ Новый аккаунт {account_id} добавлен\n"
                    "ℹ️ Перераспределение не требуется\n"
                    "📝 Аккаунт будет использован для новых каналов"
                )

                if hasattr(self.bot, 'bot'):
                    await self.bot.bot.send_message(
                        chat_id=self.admin_chat_id,
                        text=notification,
                        parse_mode='Markdown'
                    )
                elif hasattr(self.bot, 'send_message'):
                    await self.bot.send_message(
                        chat_id=self.admin_chat_id,
                        text=notification,
                        parse_mode='Markdown'
                    )

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при обработке нового аккаунта {account_id}: {e}")
            return False

    async def handle_account_error(self, account_id: str, error: Exception) -> None:
        try:
            self.logger.error(f"Ошибка аккаунта {account_id}: {str(error)}")
            
            # Отключаем проблемный клиент
            client = self.monitoring_clients.pop(account_id, None)
            if client:
                try:
                    await client.disconnect()
                except:
                    pass

            # Если есть дистрибьютор
            if self.distributor:
                # Перераспределяем каналы
                success = await self.distributor.handle_account_failure(account_id)
                if success:
                    # Обновляем обработчики для всех аккаунтов
                    for acc_id, channels in self.distributor.distribution.items():
                        client = self.monitoring_clients.get(acc_id)
                        if client:
                            # Удаляем старые обработчики
                            handlers_to_remove = []
                            for handler in client.list_event_handlers():
                                if handler[0] == self.message_handler:
                                    handlers_to_remove.append(handler)
                            
                            for handler in handlers_to_remove:
                                client.remove_event_handler(handler[0])
                            
                            # Добавляем новый обработчик
                            client.add_event_handler(
                                self.message_handler,
                                events.NewMessage(chats=channels)
                            )
                            
                            self.logger.info(
                                f"Обновлены каналы для аккаунта {acc_id}: {len(channels)} каналов"
                            )

            notification = (
                f"❌ *Ошибка аккаунта*\n\n"
                f"Аккаунт: `{account_id}`\n"
                f"Ошибка: `{str(error)}`\n"
                f"Время: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
                "Каналы перераспределены между оставшимися аккаунтами."
            )
            
            try:
                if hasattr(self.bot, 'bot'):
                    await self.bot.bot.send_message(
                        chat_id=self.admin_chat_id,
                        text=notification,
                        parse_mode='Markdown'
                    )
                elif hasattr(self.bot, 'send_message'):
                    await self.bot.send_message(
                        chat_id=self.admin_chat_id,
                        text=notification,
                        parse_mode='Markdown'
                    )
            except Exception as e:
                self.logger.error(f"Ошибка при отправке уведомления: {e}")

        except Exception as e:
            self.logger.error(f"Ошибка при обработке ошибки аккаунта {account_id}: {e}")