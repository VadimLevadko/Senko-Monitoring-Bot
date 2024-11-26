import logging
import asyncio
from typing import List, Dict, Tuple, Any
from telethon.tl.types import Channel, PeerChannel
from telethon.tl.functions.channels import JoinChannelRequest

class ImprovedChannelHandler:
    def __init__(self, message_monitor, db_manager):
        self.monitor = message_monitor
        self.db = db_manager
        self.logger = logging.getLogger(__name__)

    async def process_channel_addition(self, channel_links: List[str], progress_callback) -> Tuple[int, List[str]]:
        added = 0
        errors = []
        total = len(channel_links)
        
        try:
            # Проверка наличия клиентов
            if not self.monitor.monitoring_clients:
                return 0, ["❌ Нет доступных клиентов для добавления каналов"]

            # Информация о распределении до
            distribution_before = await self.monitor.distributor.load_distribution()
            stats_before = self._get_distribution_stats(distribution_before)
            
            await progress_callback(
                "📊 *Текущее распределение:*\n\n" + 
                self._format_distribution_stats(stats_before)
            )

            # Получаем клиент для проверки
            client = next(iter(self.monitor.monitoring_clients.values()))

            # Обработка каждого канала
            for i, link in enumerate(channel_links, 1):
                try:

                    status = (
                        f"🔄 *Обработка канала {i}/{total}*\n\n"
                        f"🔗 Канал: `{link}`\n"
                        f"✅ Добавлено: `{added}`\n"
                        f"❌ Ошибок: `{len(errors)}`"
                    )
                    await progress_callback(status)

                    chat_link = self._process_channel_link(link)
                    
                    try:
                        entity = await client.get_entity(chat_link)
                        
                        await progress_callback(
                            f"{status}\n\n"
                            f"📢 Название: `{entity.title}`\n"
                            "✅ Информация получена"
                        )

                        if not isinstance(entity, (Channel, PeerChannel)):
                            errors.append(f"{link}: Это не канал или группа")
                            continue

                        # Проверка на дубликат
                        if await self._is_channel_exists(entity.id):
                            errors.append(f"{link}: Канал уже добавлен")
                            continue

                        # Добавляем задержку перед вступлением
                        for sec in range(30, 0, -1):
                            if sec % 5 == 0:  # Обновляем статус каждые 5 секунд
                                await progress_callback(
                                    f"{status}\n\n"
                                    f"📢 Название: `{entity.title}`\n"
                                    f"⏳ Ожидание: `{sec}` сек"
                                )
                            await asyncio.sleep(1)

                        # Вступаем в канал
                        await progress_callback(
                            f"{status}\n\n"
                            f"📢 Название: `{entity.title}`\n"
                            "🔄 Вступаем в канал..."
                        )

                        await self._join_channel(client, entity)
                        
                        # Сохраняем канал
                        await self.db.add_channel(
                            chat_id=entity.id,
                            title=entity.title,
                            username=entity.username
                        )
                        
                        added += 1
                        await progress_callback(
                            f"{status}\n\n"
                            f"📢 Название: `{entity.title}`\n"
                            "✅ Канал успешно добавлен"
                        )
                        
                        await asyncio.sleep(2)

                    except Exception as e:
                        error_text = str(e).lower()
                        if "wait" in error_text:
                            wait_time = int(''.join(filter(str.isdigit, error_text)))
                            for remaining in range(wait_time, 0, -1):
                                if remaining % 5 == 0:
                                    await progress_callback(
                                        f"{status}\n\n"
                                        f"⚠️ Требуется ожидание: `{remaining}` сек"
                                    )
                                await asyncio.sleep(1)
                            continue
                        else:
                            errors.append(f"{link}: {str(e)}")
                            continue

                except Exception as e:
                    errors.append(f"{link}: {str(e)}")
                    continue

            if added > 0:
                await progress_callback(
                    "⚡️ *Перераспределение каналов*\n\n"
                    "🔄 Расчет оптимального распределения..."
                )

                new_distribution = await self.monitor.redistribute_channels()
                
                if new_distribution:
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

    async def _join_channel(self, client, entity) -> None:
        try:
            await client(JoinChannelRequest(entity))
            await asyncio.sleep(2)
        except Exception as e:
            raise Exception(f"Ошибка при вступлении: {str(e)}")

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