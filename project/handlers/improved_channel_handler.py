import logging
import asyncio
from telethon import events
from typing import List, Dict, Tuple, Any
from telethon.tl.types import Channel, PeerChannel, Chat, InputPeerChannel
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

class ImprovedChannelHandler:
    def __init__(self, message_monitor, db_manager):
        self.monitor = message_monitor
        self.db = db_manager
        self.logger = logging.getLogger(__name__)
        
    async def process_channel_addition(self, channel_links: List[str], progress_callback) -> Tuple[int, List[str]]:
        added = 0
        errors = []
        total = len(channel_links)
        new_channels = []

        try:
            if not self.monitor.monitoring_clients:
                return 0, ["❌ Нет доступных клиентов для добавления каналов"]

            # Получаем текущее распределение    
            distribution_before = await self.monitor.distributor.load_distribution()
            stats_before = self._get_distribution_stats(distribution_before)
            
            # Проверяем валидность каналов через один клиент
            check_client = next(iter(self.monitor.monitoring_clients.values()))

            for i, link in enumerate(channel_links, 1):
                try:
                    status = f"🔄 *Проверка канала {i}/{total}*\n\n"
                    await progress_callback(status)

                    chat_link = self._process_channel_link(link)
                    entity = await check_client.get_entity(chat_link)

                    if not isinstance(entity, (Channel, PeerChannel)):
                        errors.append(f"{link}: Это не канал или группа")
                        continue

                    if await self._is_channel_exists(entity.id):
                        errors.append(f"{link}: Канал уже добавлен")
                        continue

                    # Сохраняем канал в базу
                    await self.db.add_channel(
                        chat_id=entity.id,
                        title=entity.title,
                        username=entity.username
                    )
                    
                    new_channels.append({
                        'id': entity.id,
                        'title': entity.title,
                        'entity': entity
                    })
                    added += 1

                except Exception as e:
                    errors.append(f"{link}: {str(e)}")
                    continue

            if added > 0:
                await progress_callback(
                    "⚡️ *Распределение каналов*\n\n"
                    "🔄 Расчет оптимального распределения..."
                )

                # Получаем все каналы и выполняем распределение
                all_channels = await self.db.load_channels()
                channel_ids = [int(channel['chat_id']) for channel in all_channels]
                
                new_distribution = await self.monitor.distributor.distribute_channels(
                    channel_ids,
                    list(self.monitor.monitoring_clients.keys())
                )

                if new_distribution:
                    await self.monitor.distributor.apply_distribution(new_distribution)

                    # Теперь вступаем в каналы
                    for account_id, channels in new_distribution.items():
                        client = self.monitor.monitoring_clients.get(account_id)
                        if client:
                            for new_channel in new_channels:
                                if new_channel['id'] in channels:
                                    await progress_callback(
                                        f"🔄 Вступаем в канал {new_channel['title']} через аккаунт {account_id}..."
                                    )
                                    
                                    # Добавляем задержку перед вступлением
                                    for sec in range(30, 0, -1):
                                        if sec % 5 == 0:
                                            await progress_callback(
                                                f"⏳ Ожидание перед вступлением: {sec} сек"
                                            )
                                        await asyncio.sleep(1)
                                    
                                    try:
                                        await self.safe_join_channel(client, new_channel['id'])
                                        await asyncio.sleep(5)
                                    except Exception as e:
                                        self.logger.error(f"Ошибка при вступлении в канал {new_channel['id']}: {e}")

                            # Обновляем обработчики
                            for handler in client.list_event_handlers():
                                client.remove_event_handler(handler[0])

                            client.add_event_handler(
                                self.monitor.message_handler,
                                events.NewMessage(chats=channels)
                            )

                    stats_after = self._get_distribution_stats(new_distribution)
                    
                    result = (
                        "📊 *Результаты добавления каналов*\n\n"
                        f"✅ Успешно добавлено: `{added}`\n"
                        f"❌ Ошибок: `{len(errors)}`\n"
                        f"📋 Всего обработано: `{total}`\n\n"
                        "*Распределение до:*\n" +
                        self._format_distribution_stats(stats_before) +
                        "\n*Распределение после:*\n" +
                        self._format_distribution_stats(stats_after)
                    )

                    if errors:
                        result += "\n\n❌ *Ошибки при добавлении:*\n"
                        result += "\n".join(f"• {error}" for error in errors)

                    await progress_callback(result)

            return added, errors

        except Exception as e:
            self.logger.error(f"Ошибка при добавлении каналов: {e}")
            return 0, [f"Критическая ошибка: {str(e)}"]

    def _process_channel_link(self, link: str) -> str:
        if link.startswith('https://t.me/'):
            if '+' in link:
                return link
            username = link.split('/')[-1]
            return f"@{username}"
        elif not link.startswith('@'):
            return f"@{link}"
        return link

    async def _is_channel_exists(self, chat_id: int) -> bool:
        channels = await self.db.load_channels()
        return any(int(channel['chat_id']) == chat_id for channel in channels)

    async def safe_join_channel(self, client, chat_id: int) -> bool:
        """Безопасное вступление в канал или группу"""
        try:
            try:
                # Сначала пробуем получить сущность через username
                entity = None
                channels = await self.db.load_channels()
                for channel in channels:
                    if int(channel['chat_id']) == chat_id and channel.get('username'):
                        try:
                            entity = await client.get_entity(f"@{channel['username']}")
                            break
                        except:
                            pass

                # Если не получилось через username, пробуем напрямую через ID
                if not entity:
                    entity = await client.get_entity(chat_id)

                # Пытаемся вступить
                if isinstance(entity, (Channel, Chat)):
                    try:
                        await client(JoinChannelRequest(entity))
                        self.logger.info(f"Успешно присоединились к чату: {entity.title}")
                        await asyncio.sleep(2)
                        return True
                    except Exception as e:
                        self.logger.error(f"Ошибка при вступлении в чат {entity.title}: {e}")
                        return False
                else:
                    self.logger.error(f"Неподдерживаемый тип чата: {type(entity)}")
                    return False

            except ValueError as e:
                # Если не удалось получить сущность, пробуем через диалоги
                try:
                    dialogs = await client.get_dialogs()
                    for dialog in dialogs:
                        if dialog.entity.id == chat_id:
                            entity = dialog.entity
                            await client(JoinChannelRequest(entity))
                            self.logger.info(f"Успешно присоединились к чату через диалоги: {entity.title}")
                            await asyncio.sleep(2)
                            return True
                    self.logger.error(f"Не удалось найти чат {chat_id} в диалогах")
                    return False
                except Exception as e:
                    self.logger.error(f"Ошибка при поиске в диалогах: {e}")
                    return False

        except Exception as e:
            self.logger.error(f"Ошибка при получении информации о чате {chat_id}: {e}")
            return False

    def _get_distribution_stats(self, distribution: Dict[str, List[int]]) -> Dict[str, Any]:
        stats = {
            'total_channels': sum(len(channels) for channels in distribution.values()),
            'accounts': len(distribution),
            'per_account': {
                account: len(channels) 
                for account, channels in distribution.items()
            }
        }
        if stats['accounts'] > 0:
            stats['avg_channels'] = stats['total_channels'] / stats['accounts']
        else:
            stats['avg_channels'] = 0
        return stats

    def _format_distribution_stats(self, stats: Dict[str, Any]) -> str:
        result = [
            f"📱 Всего аккаунтов: `{stats['accounts']}`",
            f"📢 Всего каналов: `{stats['total_channels']}`",
            f"📊 В среднем на аккаунт: `{stats['avg_channels']:.1f}`\n"
        ]
        
        for account, count in stats['per_account'].items():
            result.append(f"👤 `{account}`: {count} каналов")
            
        return "\n".join(result)