import os
import json
import logging
import asyncio
import aiosqlite
from typing import Dict, List, Optional, Any
from telethon.tl.functions.channels import JoinChannelRequest, GetFullChannelRequest
from ..config import MONITORING_SETTINGS, load_settings

class SmartDistributor:
    def __init__(self, account_manager, db_manager):
        self.account_manager = account_manager
        self.db = db_manager
        self.logger = logging.getLogger(__name__)
        self._distribution = {}

        try:
            settings = load_settings()
            self.max_channels_per_account = settings.get('max_channels_per_client', 500)
            self.join_delay = settings.get('join_channel_delay', 5)
        except Exception as e:
            self.logger.warning(f"Не удалось загрузить настройки, используем значения по умолчанию: {e}")
            self.max_channels_per_account = MONITORING_SETTINGS.get('max_channels_per_client', 500)
            self.join_delay = MONITORING_SETTINGS.get('join_channel_delay', 5)
            
        self.logger.info(f"Настройки дистрибьютора: max_channels={self.max_channels_per_account}, join_delay={self.join_delay}")

    async def initialize(self):
        """Инициализация распределения из базы"""
        try:
            self._distribution = await self.load_distribution()
            self.logger.info(f"Загружено распределение: {len(self._distribution)} аккаунтов")
        except Exception as e:
            self.logger.error(f"Ошибка при инициализации распределения: {e}")
            self._distribution = {}
  
    async def _check_membership(self, account_id: str, chat_id: int) -> bool:
        """Проверка членства аккаунта в канале"""
        try:
            client = self.account_manager.monitoring_clients.get(account_id)
            if not client:
                return False
                
            try:
                channel = await client(GetFullChannelRequest(chat_id))
                return channel.full_chat.can_view_messages
            except:
                return False
        except Exception as e:
            self.logger.error(f"Ошибка при проверке членства {account_id} в {chat_id}: {e}")
            return False

    async def distribute_channels(self, channels: List[int], accounts: List[str]) -> Dict[str, List[int]]:
        """Распределение каналов между аккаунтами"""
        try:
            if not accounts:
                self.logger.error("Нет доступных аккаунтов для распределения")
                return {}

            # Создаем новое распределение
            new_distribution = {account_id: [] for account_id in accounts}
            
            # Получаем текущее распределение
            current_distribution = await self.db.load_distribution()
            
            # Вычисляем оптимальное количество каналов на аккаунт
            channels_per_account = min(
                len(channels) // len(accounts) + (1 if len(channels) % len(accounts) > 0 else 0),
                self.max_channels_per_account
            )

            self.logger.info(f"Всего каналов: {len(channels)}")
            self.logger.info(f"Всего аккаунтов: {len(accounts)}")
            self.logger.info(f"Оптимально каналов на аккаунт: {channels_per_account}")

            # Сначала сохраняем текущие назначения где возможно
            for channel_id in channels:
                current_account = None
                for acc_id, acc_channels in current_distribution.items():
                    if channel_id in acc_channels and acc_id in accounts:
                        current_account = acc_id
                        break

                if current_account:
                    if len(new_distribution[current_account]) < channels_per_account:
                        new_distribution[current_account].append(channel_id)
                        continue

            # Распределяем оставшиеся каналы
            remaining_channels = [ch for ch in channels if not any(ch in dist for dist in new_distribution.values())]
            account_index = 0
            
            for channel_id in remaining_channels:
                # Находим аккаунт с наименьшим количеством каналов
                account_id = min(new_distribution.keys(), 
                               key=lambda x: len(new_distribution[x]))
                
                if len(new_distribution[account_id]) < channels_per_account:
                    new_distribution[account_id].append(channel_id)
                else:
                    # Если все аккаунты заполнены, добавляем к наименее загруженному
                    min_account = min(new_distribution.keys(), 
                                    key=lambda x: len(new_distribution[x]))
                    new_distribution[min_account].append(channel_id)

            # Логируем результаты распределения
            for account_id, account_channels in new_distribution.items():
                self.logger.info(
                    f"Аккаунт {account_id}: {len(account_channels)} каналов "
                    f"(лимит: {channels_per_account})"
                )

            return new_distribution

        except Exception as e:
            self.logger.error(f"Ошибка при распределении каналов: {e}")
            return {}
  
    @property
    def distribution(self):
        return self._distribution

    @distribution.setter 
    def distribution(self, value):
        self._distribution = value

    async def load_distribution(self) -> Dict[str, List[int]]:
        distribution = {}
        try:
            async with aiosqlite.connect(self.db.db_path) as db:
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

    async def apply_distribution(self, new_distribution: Dict[str, List[int]]) -> None:
        try:
            async with aiosqlite.connect(self.db.db_path) as db:
                # Очищаем старое распределение
                await db.execute('DELETE FROM channel_distribution')
                
                # Добавляем новое распределение
                for account_id, channels in new_distribution.items():
                    for chat_id in channels:
                        await db.execute('''
                            INSERT INTO channel_distribution (chat_id, account_id)
                            VALUES (?, ?)
                        ''', (chat_id, account_id))
                
                await db.commit()
                self._distribution = new_distribution
                self.logger.info("Новое распределение успешно применено")

        except aiosqlite.Error as e:
            self.logger.error(f"Ошибка SQLite при применении распределения: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Ошибка при применении распределения: {e}")
            raise

    async def get_account_for_channel(self, chat_id: int) -> Optional[str]:
        # Сначала проверяем кэш
        for account_id, channels in self.distribution.items():
            if chat_id in channels:
                return account_id
                
        # Если нет в кэше, проверяем базу
        return await self.db.get_channel_account(chat_id)
        
    async def distribute_channels(self, channels_list: List[int], accounts_list: List[str]) -> Dict[str, List[int]]:
        try:
            if not accounts_list:
                raise ValueError("Нет доступных аккаунтов")

            # Создаем новое распределение
            new_distribution = {account_id: [] for account_id in accounts_list}
            
            # Считаем оптимальное количество каналов на аккаунт
            channels_per_account = min(
                len(channels_list) // len(accounts_list) + (1 if len(channels_list) % len(accounts_list) > 0 else 0),
                self.max_channels_per_account
            )

            # Текущее распределение из базы
            current_distribution = await self.db.load_distribution()
            
            # Сначала оставляем каналы на прежних аккаунтах где возможно
            channels_to_distribute = []
            for channel_id in channels_list:
                current_account = None
                for acc_id, acc_channels in current_distribution.items():
                    if channel_id in acc_channels:
                        current_account = acc_id
                        break
                        
                if current_account and current_account in accounts_list:
                    # Оставляем канал на текущем аккаунте если не превышает лимит
                    if len(new_distribution[current_account]) < channels_per_account:
                        new_distribution[current_account].append(channel_id)
                        continue
                
                channels_to_distribute.append(channel_id)

            accounts_sorted = sorted(
                accounts_list,
                key=lambda x: len(new_distribution[x])
            )

            for channel_id in channels_to_distribute:
                # Ищем аккаунт с минимальной нагрузкой
                for account_id in accounts_sorted:
                    if len(new_distribution[account_id]) < channels_per_account:
                        new_distribution[account_id].append(channel_id)
                        break
                else:
                    # Если все аккаунты загружены, добавляем к наименее загруженному
                    new_distribution[accounts_sorted[0]].append(channel_id)

            # Сохраняем новое распределение
            await self.db.save_distribution(new_distribution)

            for account_id, channels in new_distribution.items():
                self.logger.info(
                    f"Аккаунт {account_id}: {len(channels)} каналов "
                    f"(лимит: {channels_per_account})"
                )

            return new_distribution

        except Exception as e:
            self.logger.error(f"Ошибка при распределении каналов: {e}")
            raise

    async def check_account(self, client) -> bool:
        try:
            return await client.is_user_authorized()
        except Exception as e:
            self.logger.error(f"Ошибка при проверке аккаунта: {e}")
            return False

    async def add_new_account(self, account_id: str) -> bool:
        try:
            # Проверяем новый аккаунт
            client = await self.account_manager.get_client(account_id)
            if not client or not await self.check_account(client):
                return False

            # Если есть нераспределенные каналы
            if self.unassigned_channels:
                channels_to_assign = self.unassigned_channels[:self.max_channels_per_account]
                self.distribution[account_id] = channels_to_assign
                self.unassigned_channels = self.unassigned_channels[self.max_channels_per_account:]
                
                # Вступаем в назначенные каналы
                await self.join_channels(client, channels_to_assign)
                
                self.logger.info(f"Аккаунту {account_id} назначено {len(channels_to_assign)} каналов")
                return True

            return False

        except Exception as e:
            self.logger.error(f"Ошибка при добавлении нового аккаунта: {e}")
            return False

    async def handle_account_failure(self, failed_account_id: str) -> bool:
        try:
            # Получаем каналы неработающего аккаунта
            failed_channels = self.distribution.pop(failed_account_id, [])
            if not failed_channels:
                return True

            # Добавляем их к нераспределенным
            self.unassigned_channels.extend(failed_channels)

            # Пытаемся распределить между оставшимися аккаунтами
            working_accounts = [acc for acc in self.distribution.keys()]
            if working_accounts:
                channels_per_account = min(
                    self.max_channels_per_account,
                    len(self.unassigned_channels) // len(working_accounts)
                )

                for account_id in working_accounts:
                    # Проверяем количество текущих каналов
                    current_channels = len(self.distribution[account_id])
                    if current_channels < self.max_channels_per_account:
                        # Сколько можем добавить
                        can_add = min(
                            self.max_channels_per_account - current_channels,
                            channels_per_account
                        )
                        if can_add > 0:
                            new_channels = self.unassigned_channels[:can_add]
                            self.unassigned_channels = self.unassigned_channels[can_add:]
                            
                            # Вступаем в новые каналы
                            client = await self.account_manager.get_client(account_id)
                            if client:
                                await self.join_channels(client, new_channels)
                                self.distribution[account_id].extend(new_channels)

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при обработке выхода аккаунта из строя: {e}")
            return False

    async def join_channels(self, client, channels: List[int]) -> None:
        """Вступление в каналы с задержкой"""
        for channel_id in channels:
            try:
                if await self.safe_join_channel(client, channel_id):
                    await asyncio.sleep(self.join_delay)
            except Exception as e:
                self.logger.error(f"Ошибка при вступлении в канал {channel_id}: {e}")

    async def safe_join_channel(self, client, channel_id: int) -> bool:
        """Безопасное вступление в канал с проверками и повторными попытками"""
        max_retries = 3
        base_delay = self.join_delay
        
        for attempt in range(max_retries):
            try:
                try:
                    channel = await client(GetFullChannelRequest(channel_id))
                    if channel.full_chat.can_view_messages:
                        return True
                except Exception as e:
                    if "CHANNEL_PRIVATE" in str(e):
                        self.logger.error(f"Канал {channel_id} недоступен")
                        return False

                # Вступаем в канал
                await client(JoinChannelRequest(channel_id))
                
                # Увеличенная задержка между попытками
                await asyncio.sleep(base_delay * (attempt + 1))
                
                # Проверяем успешность вступления
                check = await client(GetFullChannelRequest(channel_id))
                if check.full_chat.can_view_messages:
                    self.logger.info(f"Успешное вступление в канал {channel_id}")
                    return True
                    
            except Exception as e:
                error_msg = str(e)
                if "FLOOD_WAIT" in error_msg:
                    wait_time = int(''.join(filter(str.isdigit, error_msg)))
                    self.logger.warning(f"Флуд-контроль для {channel_id}, ожидание {wait_time} сек")
                    await asyncio.sleep(wait_time)
                    continue
                    
                self.logger.error(f"Ошибка при вступлении в канал {channel_id}: {e}")
                await asyncio.sleep(base_delay * (attempt + 1))
        
        return False

    async def redistribute_with_new_account(self, account_id: str) -> bool:
        """Перераспределение каналов при добавлении нового аккаунта"""
        try:
            if account_id not in self.account_manager.monitoring_clients:
                return False

            # Получаем текущее распределение
            current_distribution = self.distribution.copy()
            total_channels = sum(len(channels) for channels in current_distribution.values())
            account_count = len(current_distribution) + 1
            
            # Считаем оптимальное количество каналов на аккаунт
            optimal_channels = min(
                total_channels // account_count,
                self.max_channels_per_account
            )

            # Собираем каналы для перераспределения
            channels_to_move = []
            for acc_id, channels in current_distribution.items():
                if len(channels) > optimal_channels:
                    excess = len(channels) - optimal_channels
                    channels_to_move.extend(channels[-excess:])
                    current_distribution[acc_id] = channels[:-excess]

            # Назначаем каналы новому аккаунту
            if channels_to_move:
                client = self.account_manager.monitoring_clients[account_id]
                new_channels = []
                
                # Пробуем вступить в каналы
                for channel_id in channels_to_move:
                    if await self.safe_join_channel(client, channel_id):
                        new_channels.append(channel_id)
                        await asyncio.sleep(self.join_delay * 2)
                    else:
                        for acc_id, channels in current_distribution.items():
                            if channel_id in channels:
                                current_distribution[acc_id].append(channel_id)
                                break

                if new_channels:
                    current_distribution[account_id] = new_channels
                    await self.apply_distribution(current_distribution)
                    return True

            return False

        except Exception as e:
            self.logger.error(f"Ошибка при перераспределении с новым аккаунтом: {e}")
            return False