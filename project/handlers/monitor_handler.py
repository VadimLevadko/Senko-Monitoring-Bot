import logging
import asyncio
from project.config import STATES, load_settings, MESSAGE_TEMPLATES, MONITORING_SETTINGS
from typing import List, Dict, Optional, Tuple, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, error as telegram_error
from telegram.ext import ContextTypes
from telegram import ReplyKeyboardMarkup, KeyboardButton
from datetime import datetime
from project.managers.message_monitor import MessageMonitor
from telegram import error as telegram_error
from .improved_channel_handler import ImprovedChannelHandler

logger = logging.getLogger(__name__)

class MonitorHandler:
    def __init__(self, message_monitor: MessageMonitor):
        self.monitor = message_monitor
        self.logger = logging.getLogger(__name__)
        self.handlers = None
        self.start_time = None
        self.channel_handler = ImprovedChannelHandler(message_monitor, message_monitor.db)

    def set_handlers(self, handlers):
        self.handlers = handlers
   
    async def start_channel_addition(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()
            
            message = (
                "*Добавление канала или группы*\n\n"
                "Отправьте ссылку в одном из форматов:\n"
                "• `https://t.me/group_name`\n"
                "• `@group_name`\n"
                "• `https://t.me/+abcdef...` (для приватных чатов)\n\n"
                "❌ Для отмены отправьте /cancel"
            )
            
            keyboard = [[InlineKeyboardButton("« Назад", callback_data='back_to_monitor')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            return STATES['ADDING_CHANNEL']
                
        except Exception as e:
            self.logger.error(f"Ошибка при начале добавления чата: {e}")
            if update.callback_query:
                await update.callback_query.answer("Произошла ошибка")
            return STATES['MONITORING']


    async def show_monitor_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            stats = self.monitor.get_stats()
            status_emoji = "🟢" if stats['status'] == 'Активен' else "🔴"
            
            message = (
                f"*Панель мониторинга*\n\n"
                f"Статус: {status_emoji} {stats['status']}\n"
                f"Время работы: {stats.get('uptime', '0:00:00')}\n"
                f"Обработано сообщений: {stats['messages_processed']}\n"
                f"Найдено ключевых слов: {stats['keywords_found']}\n"
                f"Ошибок: {stats['errors']}\n"
                f"Активных клиентов: {stats['active_clients']}\n"
                f"Отслеживаемых каналов: {stats['watched_channels']}\n"
            )

            keyboard = [
                [
                    InlineKeyboardButton(
                        "⏹️ Остановить" if stats['status'] == 'Активен' else "▶️ Запустить",
                        callback_data='toggle_monitoring'
                    )
                ],
                [
                    InlineKeyboardButton("➕ Добавить канал", callback_data='add_channel'),
                    InlineKeyboardButton("📋 Список каналов", callback_data='list_channels')
                ],
                [
                    InlineKeyboardButton("👤 Управление аккаунтами", callback_data='manage_accounts'),
                ],
                [
                    InlineKeyboardButton("🔑 Управление прокси", callback_data='manage_proxies'),
                ],
                [
                    InlineKeyboardButton("🔍 Ключевые слова", callback_data='manage_keywords'),
                ],
                [
                    InlineKeyboardButton("👥 Управление админами", callback_data='manage_admins'),  # Новая кнопка
                ],
                [
                    InlineKeyboardButton("⚙️ Настройки", callback_data='monitor_settings')
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)

            if isinstance(update, Update):
                if update.callback_query:
                    await update.callback_query.edit_message_text(
                        text=message,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                elif update.message:
                    await update.message.reply_text(
                        text=message,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                return STATES['MONITORING']
            return STATES['MONITORING']

        except Exception as e:
            self.logger.error(f"Ошибка при отображении меню мониторинга: {e}")
            return STATES['MONITORING']

    async def handle_monitor_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик callback-ов от кнопок меню мониторинга"""
        query = update.callback_query
        try:
            self.logger.info(f"Получен callback: {query.data}")
            await query.answer()

            # Обработка кнопок навигации
            if query.data == 'back_to_monitor':
                return await self.show_monitor_menu(update, context)
                
            elif query.data == 'monitor_settings':
                return await self.show_settings_menu(query, context)
                
            elif query.data == 'back_to_settings':
                return await self.show_settings_menu(query, context)

            # Обработка основных действий мониторинга
            if query.data == 'toggle_monitoring':
                return await self.toggle_monitoring(query, context)
            
            # Обработка каналов
            elif query.data == 'add_channel':
                return await self.start_channel_addition(update, context)
            elif query.data == 'list_channels':
                return await self.list_channels(update, context)
            elif query.data == 'check_channels':
                return await self.check_channels(query, context)
            elif query.data == 'confirm_delete':
                return await self.delete_all_channels(update, context)
            elif query.data == 'cancel_delete':
                return await self.list_channels(update, context)
                   
            # Настройки и их редактирование
            elif query.data == 'edit_notifications':
                return await self.edit_notifications(query, context)
            elif query.data == 'edit_performance':
                return await self.edit_performance(query, context)
            elif query.data == 'edit_autorestart':
                return await self.edit_autorestart(query, context)
            elif query.data == 'edit_timeouts':
                return await self.edit_timeouts(query, context)
            elif query.data == 'edit_other':
                return await self.edit_other_settings(query, context)
                       
            # Обработка изменения значений настроек
            elif query.data.startswith('change_'):
                setting = query.data.replace('change_', '')
                context.user_data['editing_setting'] = setting
                ranges = {
                    # Настройки производительности
                    'check_interval': (1, 60),                    # Интервал проверки (секунды)
                    'max_channels_per_client': (100, 1000),       # Максимум каналов на один аккаунт
                    
                    # Настройки уведомлений
                    'notification_chunk_size': (10, 100),         # Размер пакета уведомлений
                    'message_processing_timeout': (10, 120),      # Таймаут обработки сообщений
                    
                    # Тайм-ауты и задержки
                    'join_timeout': (10, 300),                    # Таймаут при вступлении в канал
                    'join_channel_delay': (1, 30),                # Задержка между вступлениями
                    'retry_interval': (60, 600),                  # Интервал повторных попыток
                    'restart_delay': (30, 300),                   # Задержка перед перезапуском
                    
                    # Лимиты и пороги
                    'max_message_length': (1000, 10000),          # Максимальная длина сообщения
                    'max_keywords': (100, 10000),                 # Максимум ключевых слов
                    'max_errors_before_restart': (1, 20),         # Максимум ошибок до перезапуска
                    'flood_wait_threshold': (30, 300),            # Порог срабатывания защиты от флуда
                    
                    # Интервалы обслуживания
                    'cleanup_interval': (3600, 86400),            # Интервал очистки (1 час - 1 день)
                    'data_retention_days': (1, 90),               # Срок хранения данных (дни)
                }
                range_info = ranges.get(setting, (0, 100))
                
                # Получаем текущие настройки для отображения
                settings = load_settings()
                current_value = settings.get(setting, "Не задано")
                
                message = (
                    f"⚙️ *Изменение настройки*\n\n"
                    f"Текущее значение: `{current_value}`\n"
                    f"Допустимый диапазон: `{range_info[0]}-{range_info[1]}`\n\n"
                    "Введите новое значение или отправьте /cancel для отмены"
                )
                
                # Определяем кнопку "Назад" в зависимости от типа настройки
                back_button = 'monitor_settings'
                if setting in ['notification_chunk_size', 'message_processing_timeout']:
                    back_button = 'edit_notifications'
                elif setting in ['check_interval', 'max_channels_per_client']:
                    back_button = 'edit_performance'
                elif setting in ['restart_delay', 'max_errors_before_restart']:
                    back_button = 'edit_autorestart'
                elif setting in ['join_timeout', 'message_timeout']:
                    back_button = 'edit_timeouts'
                elif setting in ['max_message_length', 'max_keywords', 'flood_wait_threshold',
                               'join_channel_delay', 'retry_interval', 'cleanup_interval',
                               'data_retention_days']:
                    back_button = 'edit_other'
                
                await query.edit_message_text(
                    text=message,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("« Назад", callback_data=back_button)
                    ]]),
                    parse_mode='Markdown'
                )
                return STATES['ENTERING_VALUE']
                       
            # Обработка каналов
            elif query.data == 'delete_channels_menu':
                return await self.show_delete_channels_menu(update, context)
            elif query.data.startswith('delete_channel_'):
                chat_id = int(query.data.replace('delete_channel_', ''))
                return await self.delete_single_channel(update, context, chat_id)
            elif query.data == 'confirm_delete_all':
                return await self.confirm_delete_all_channels(update, context)
            elif query.data == 'execute_delete_all':
                return await self.delete_all_channels(update, context)
                       
            # Обработка аккаунтов
            elif query.data == 'manage_accounts':
                return await self.handlers['account'].show_accounts_menu(update, context)
                       
            # Обработка прокси
            elif query.data == 'manage_proxies':
                return await self.handlers['proxy'].show_proxy_menu(update, context)
                       
            # Обработка ключевых слов
            elif query.data == 'manage_keywords':
                return await self.handlers['keyword'].show_keywords_menu(update, context)

            # Обработка админов
            elif query.data == 'manage_admins':
                return await self.handlers['admin'].show_admin_menu(update, context)

            # Если команда неизвестна
            self.logger.warning(f"Неизвестный callback: {query.data}")
            return await self.show_monitor_menu(update, context)

        except Exception as e:
            self.logger.error(f"Ошибка при обработке callback {query.data}: {e}")
            return await self.show_error(update, "обработке команды")
   
    async def show_error(self, update: Update, error_context: str) -> int:
        try:
            if hasattr(update, 'callback_query'):
                await update.callback_query.edit_message_text(
                    text=f"❌ Произошла ошибка при {error_context}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("« Назад", callback_data='back_to_monitor')
                    ]]),
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    text=f"❌ Произошла ошибка при {error_context}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("« Назад", callback_data='back_to_monitor')
                    ]]),
                    parse_mode='Markdown'
                )
        except Exception as e:
            self.logger.error(f"Ошибка при показе ошибки: {e}")
            
        return STATES['MONITORING']
   
    async def confirm_delete_all_channels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Подтверждение удаления всех каналов"""
        try:
            query = update.callback_query
            await query.answer()

            await query.edit_message_text(
                "⚠️ *Внимание!*\n\n"
                "Вы действительно хотите удалить *ВСЕ* каналы?\n"
                "Это действие нельзя будет отменить!",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Да, удалить все", callback_data="execute_delete_all"),
                        InlineKeyboardButton("❌ Отмена", callback_data="delete_channels_menu")
                    ]
                ]),
                parse_mode='Markdown'
            )
            
            return STATES['CONFIRMING_DELETE']
            
        except Exception as e:
            self.logger.error(f"Ошибка при подтверждении удаления: {e}")
            return await self.show_error(update, "подтверждении удаления")

    async def delete_single_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        """Удаление отдельного канала"""
        try:
            query = update.callback_query
            
            channels = await self.monitor.db.load_channels()
            channel_info = next((ch for ch in channels if ch['chat_id'] == chat_id), None)
            
            if not channel_info:
                await query.answer("Канал не найден")
                return await self.show_delete_channels_menu(update, context)
                
            # Удаляем канал
            success = await self.monitor.remove_channel(chat_id)
            
            if success:
                # Отправляем сообщение об успешном удалении
                await query.edit_message_text(
                    f"✅ Канал *{channel_info['title']}* успешно удален!\n\n"
                    "Возвращаемся к списку каналов...",
                    parse_mode='Markdown'
                )
                await asyncio.sleep(2)
                return await self.show_delete_channels_menu(update, context)
            else:
                await query.answer("❌ Ошибка при удалении канала")
                return await self.show_delete_channels_menu(update, context)
                
        except Exception as e:
            self.logger.error(f"Ошибка при удалении канала {chat_id}: {e}")
            return await self.show_error(update, "удалении канала")

    async def show_delete_channels_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            self.logger.info("===== Открытие меню удаления каналов =====")
            query = update.callback_query

            channels = await self.monitor.db.load_channels()
            self.logger.info(f"Загружено каналов: {len(channels)}")
            
            if not channels:
                await query.edit_message_text(
                    "❌ *Список каналов пуст*",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("« Назад", callback_data="list_channels")
                    ]]),
                    parse_mode='Markdown'
                )
                return STATES['MANAGING_CHANNELS']

            message_text = (
                "🗑 *Меню удаления каналов*\n\n"
                f"Доступно каналов: {len(channels)}\n"
                "Выберите канал для удаления:\n\n"
            )

            keyboard = []
            
            for channel in channels:
                title = channel.get('title', 'Без названия')
                chat_id = channel.get('chat_id')
                button_text = f"❌ {title[:30]}..." if len(title) > 30 else f"❌ {title}"
                keyboard.append([
                    InlineKeyboardButton(button_text, callback_data=f"delete_channel_{chat_id}")
                ])

            keyboard.extend([
                [InlineKeyboardButton("🗑 Удалить все", callback_data="confirm_delete_all")],
                [InlineKeyboardButton("« Назад к списку", callback_data="list_channels")]
            ])

            await query.edit_message_text(
                text=message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

            return STATES['MANAGING_CHANNELS']

        except Exception as e:
            self.logger.error(f"Ошибка при показе меню удаления: {e}")
            return await self.show_error(update, "показе меню удаления")
            
    async def delete_all_channels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Удаление всех каналов"""
        try:
            query = update.callback_query
            await query.answer()
            
            channels = await self.monitor.db.load_channels()
            total = len(channels)
            deleted = 0

            await query.edit_message_text(
                "🔄 *Удаление всех каналов*\n\n"
                "Пожалуйста, подождите...",
                parse_mode='Markdown'
            )

            for channel in channels:
                try:
                    if await self.monitor.remove_channel(channel['chat_id']):
                        deleted += 1
                except Exception as e:
                    self.logger.error(f"Ошибка при удалении канала {channel['chat_id']}: {e}")

            result_message = (
                "✅ *Операция завершена*\n\n"
                f"Успешно удалено каналов: {deleted}/{total}\n\n"
            )

            await query.edit_message_text(
                result_message,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Вернуться к списку", callback_data="list_channels")
                ]]),
                parse_mode='Markdown'
            )

            return STATES['MONITORING']

        except Exception as e:
            self.logger.error(f"Ошибка при удалении всех каналов: {e}")
            return await self.show_error(update, "удалении каналов")

    async def _update_stats(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обновление статистики в сообщении"""
        try:
            job = context.job
            stats = self.monitor.get_stats()
            status_emoji = "🟢" if stats['status'] == 'Активен' else "🔴"

            message = (
                f"*Панель мониторинга*\n\n"
                f"Статус: {status_emoji} {stats['status']}\n"
                f"Время работы: {stats.get('uptime', '0:00:00')}\n"
                f"Обработано сообщений: {stats['messages_processed']}\n"
                f"Найдено ключевых слов: {stats['keywords_found']}\n"
                f"Ошибок: {stats['errors']}\n"
                f"Активных клиентов: {stats['active_clients']}\n"
                f"Отслеживаемых каналов: {stats['watched_channels']}\n"
            )

            reply_markup = InlineKeyboardMarkup(job.data['keyboard'])

            try:
                await context.bot.edit_message_text(
                    chat_id=job.data['chat_id'],
                    message_id=job.data['message_id'],
                    text=message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            except telegram_error.BadRequest as e:
                if 'Message is not modified' not in str(e):
                    self.logger.error(f"Ошибка при обновлении статистики: {e}")
            except telegram_error.TelegramError as e:
                self.logger.error(f"Telegram ошибка при обновлении статистики: {e}")

        except Exception as e:
            self.logger.error(f"Ошибка при обновлении статистики: {e}")

    async def edit_performance(self, query: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            settings = load_settings()
            
            keyboard = [
                [InlineKeyboardButton(
                    f"Интервал проверки: {settings['check_interval']} сек",
                    callback_data='change_check_interval'
                )],
                [InlineKeyboardButton(
                    f"Каналов на аккаунт: {settings['max_channels_per_client']}",
                    callback_data='change_max_channels_per_client'
                )],
                [InlineKeyboardButton("« Назад", callback_data='monitor_settings')]
            ]
            
            await query.edit_message_text(
                "⚡️ *Настройки производительности*\n\n"
                "Выберите параметр для изменения:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
            return STATES['EDITING_PERFORMANCE']
            
        except Exception as e:
            self.logger.error(f"Ошибка при редактировании производительности: {e}")
            return await self.show_monitor_menu(query, context)

    async def show_settings_menu(self, query: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            settings = load_settings()
            
            message = (
                "⚙️ *Настройки мониторинга*\n\n"
                f"🔄 Интервал проверки: `{settings['check_interval']}` сек\n"
                f"📝 Макс. длина сообщения: `{settings['max_message_length']}`\n"
                f"📊 Каналов на аккаунт: `{settings['max_channels_per_client']}`\n"
                f"⏳ Тайм-аут вступления: `{settings.get('join_timeout', 30)}` сек\n"
                f"🔍 Макс. ключевых слов: `{settings['max_keywords']}`\n"
                f"🕒 Хранение данных: `{settings['data_retention_days']}` дней\n\n"
                "*Уведомления:*\n"
                f"• Размер чанка: `{settings['notification_chunk_size']}`\n"
                f"• Таймаут: `{settings['message_processing_timeout']}` сек\n\n"
                "*Автоматизация:*\n"
                f"• Авторестарт: `{'Включен' if settings['auto_restart'] else 'Выключен'}`\n"
                f"• Задержка рестарта: `{settings['restart_delay']}` сек\n"
                f"• Макс. ошибок: `{settings['max_errors_before_restart']}`"
            )

            keyboard = [
                [
                    InlineKeyboardButton("📱 Уведомления", callback_data='edit_notifications'),
                    InlineKeyboardButton("⚡️ Производительность", callback_data='edit_performance')
                ],
                [
                    InlineKeyboardButton("🔄 Авторестарт", callback_data='edit_autorestart'),
                    InlineKeyboardButton("⏱️ Тайм-ауты", callback_data='edit_timeouts')
                ],
                [
                    InlineKeyboardButton("⚙️ Другие настройки", callback_data='edit_other')
                ],
                [InlineKeyboardButton("« Назад", callback_data='back_to_monitor')]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            return STATES['SETTINGS_MENU']
                
        except Exception as e:
            self.logger.error(f"Ошибка при отображении настроек: {e}")
            if isinstance(query, Update):
                return await self.show_error(query, "загрузке настроек")
            else:
                return STATES['MONITORING']

    async def edit_other_settings(self, query: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            settings = load_settings()
            
            message = (
                "⚙️ *Дополнительные настройки*\n\n"
                "*Параметры сообщений:*\n"
                f"• Макс. длина сообщения: `{settings['max_message_length']}`\n"
                f"• Макс. ключевых слов: `{settings['max_keywords']}`\n\n"
                "*Задержки и тайм-ауты:*\n"
                f"• Порог флуда: `{settings['flood_wait_threshold']}` сек\n"
                f"• Задержка вступления: `{settings['join_channel_delay']}` сек\n"
                f"• Интервал повтора: `{settings['retry_interval']}` сек\n\n"
                "*Хранение данных:*\n"
                f"• Интервал очистки: `{settings['cleanup_interval']}` сек\n"
                f"• Срок хранения: `{settings['data_retention_days']}` дней\n\n"
                "_Выберите параметр для изменения:_"
            )

            keyboard = [
                [InlineKeyboardButton(
                    f"📝 Макс. длина сообщения: {settings['max_message_length']}",
                    callback_data='change_max_message_length'
                )],
                [InlineKeyboardButton(
                    f"🔍 Макс. ключевых слов: {settings['max_keywords']}",
                    callback_data='change_max_keywords'
                )],
                [InlineKeyboardButton(
                    f"⚡️ Порог флуда: {settings['flood_wait_threshold']} сек",
                    callback_data='change_flood_wait_threshold'
                )],
                [InlineKeyboardButton(
                    f"⏰ Задержка вступления: {settings['join_channel_delay']} сек",
                    callback_data='change_join_channel_delay'
                )],
                [InlineKeyboardButton(
                    f"🔄 Интервал повтора: {settings['retry_interval']} сек",
                    callback_data='change_retry_interval'
                )],
                [InlineKeyboardButton(
                    f"🧹 Интервал очистки: {settings['cleanup_interval']} сек",
                    callback_data='change_cleanup_interval'
                )],
                [InlineKeyboardButton(
                    f"📅 Срок хранения: {settings['data_retention_days']} дней",
                    callback_data='change_data_retention_days'
                )],
                [InlineKeyboardButton("« Назад", callback_data='monitor_settings')]
            ]

            await query.edit_message_text(
                text=message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
            return STATES['EDITING_OTHER']

        except Exception as e:
            self.logger.error(f"Ошибка при редактировании прочих настроек: {e}")
            await query.edit_message_text(
                "❌ Произошла ошибка при загрузке настроек",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Назад", callback_data='monitor_settings')
                ]]),
                parse_mode='Markdown'
            )
            return STATES['SETTINGS_MENU']

    async def edit_timeouts(self, query: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            settings = load_settings()
            
            keyboard = [
                [InlineKeyboardButton(
                    f"⏳ Тайм-аут вступления: {settings.get('join_timeout', 30)} сек",
                    callback_data='change_join_timeout'
                )],
                [InlineKeyboardButton(
                    f"⌛️ Тайм-аут сообщений: {settings['message_processing_timeout']} сек",
                    callback_data='change_message_timeout'
                )],
                [InlineKeyboardButton("« Назад к настройкам", callback_data='monitor_settings')]
            ]
            
            await query.edit_message_text(
                "⚙️ *Настройки тайм-аутов*\n\n"
                "Выберите параметр для изменения:\n\n"
                "• *Тайм-аут вступления* - задержка перед вступлением в канал\n"
                "• *Тайм-аут сообщений* - максимальное время обработки сообщения",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
            return STATES['EDITING_TIMEOUTS']
            
        except Exception as e:
            self.logger.error(f"Ошибка при редактировании тайм-аутов: {e}")
            return await self.show_monitor_menu(query, context)

    async def edit_notifications(self, query: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            from ..config import load_settings
            settings = load_settings()
            
            keyboard = [
                [InlineKeyboardButton(
                    f"Размер чанка: {settings['notification_chunk_size']}",
                    callback_data='change_notification_chunk_size'
                )],
                [InlineKeyboardButton(
                    f"Таймаут: {settings['message_processing_timeout']} сек",
                    callback_data='change_message_processing_timeout'
                )],
                [InlineKeyboardButton("« Назад", callback_data='monitor_settings')]
            ]
            
            await query.edit_message_text(
                "📱 *Настройки уведомлений*\n\n"
                "Выберите параметр для изменения:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
            return STATES['EDITING_NOTIFICATIONS']
            
        except Exception as e:
            self.logger.error(f"Ошибка при редактировании уведомлений: {e}")
            return await self.show_monitor_menu(query, context)

    async def save_setting_value(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            setting_type = context.user_data.get('editing_setting')
            if not setting_type:
                return await self.show_settings_menu(update, context)
                    
            value = update.message.text.strip()

            try:
                value = int(value)
            except ValueError:
                await update.message.reply_text(
                    "❌ Значение должно быть числом!\n"
                    "Попробуйте еще раз или отправьте /cancel для отмены",
                    parse_mode='Markdown'
                )
                return STATES['ENTERING_VALUE']
                    
            # Проверка диапазонов
            ranges = {
                # Настройки производительности
                'check_interval': (1, 60),                    # Интервал проверки (секунды)
                'max_channels_per_client': (100, 1000),       # Максимум каналов на один аккаунт
                
                # Настройки уведомлений
                'notification_chunk_size': (10, 100),         # Размер пакета уведомлений
                'message_processing_timeout': (10, 120),      # Таймаут обработки сообщений (секунды)
                
                # Тайм-ауты и задержки
                'join_timeout': (10, 300),                    # Таймаут при вступлении в канал (секунды)
                'join_channel_delay': (1, 30),                # Задержка между вступлениями (секунды)
                'retry_interval': (60, 600),                  # Интервал повторных попыток (секунды)
                'restart_delay': (30, 300),                   # Задержка перед перезапуском (секунды)
                
                # Лимиты и пороги
                'max_message_length': (1000, 10000),          # Максимальная длина сообщения
                'max_keywords': (100, 10000),                 # Максимум ключевых слов
                'max_errors_before_restart': (1, 20),         # Максимум ошибок до перезапуска
                'flood_wait_threshold': (30, 300),            # Порог срабатывания защиты от флуда (секунды)
                
                # Интервалы обслуживания
                'cleanup_interval': (3600, 86400),            # Интервал очистки (секунды, от 1 часа до 1 дня)
                'data_retention_days': (1, 90),               # Срок хранения данных (дни)
            }
            
            valid_range = ranges.get(setting_type)
            if valid_range and not (valid_range[0] <= value <= valid_range[1]):
                await update.message.reply_text(
                    f"❌ Значение должно быть в диапазоне от {valid_range[0]} до {valid_range[1]}!\n"
                    "Попробуйте еще раз или отправьте /cancel для отмены",
                    parse_mode='Markdown'
                )
                return STATES['ENTERING_VALUE']
                    
            # Загружаем текущие настройки
            settings = load_settings()
            
            # Сохраняем новое значение
            old_value = settings.get(setting_type)
            settings[setting_type] = value
            
            if save_settings(settings):
                success_message = (
                    f"✅ Настройка успешно изменена!\n\n"
                    f"Параметр: `{setting_type}`\n"
                    f"Старое значение: `{old_value}`\n"
                    f"Новое значение: `{value}`\n\n"
                    "Возвращаемся в меню настроек..."
                )
                
                await update.message.reply_text(success_message, parse_mode='Markdown')
                await asyncio.sleep(2)
                
                class FakeCallback:
                    def __init__(self, message):
                        self.message = message
                    async def edit_message_text(self, *args, **kwargs):
                        return await self.message.reply_text(*args, **kwargs)

                fake_query = FakeCallback(update.message)
                return await self.show_settings_menu(fake_query, context)
            else:
                await update.message.reply_text(
                    "❌ Ошибка при сохранении настройки. Попробуйте позже.",
                    parse_mode='Markdown'
                )
                    
            return STATES['SETTINGS_MENU']
                
        except Exception as e:
            self.logger.error(f"Ошибка при сохранении значения: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка при сохранении значения. Попробуйте позже.",
                parse_mode='Markdown'
            )
            class FakeCallback:
                def __init__(self, message):
                    self.message = message
                async def edit_message_text(self, *args, **kwargs):
                    return await self.message.reply_text(*args, **kwargs)

            fake_query = FakeCallback(update.message)
            return await self.show_settings_menu(fake_query, context)

    async def start_value_input(self, query: Update, context: ContextTypes.DEFAULT_TYPE, setting_type: str):
        try:
            context.user_data['editing_setting'] = setting_type
            
            setting_info = {
                'check_interval': {
                    'name': 'интервал проверки',
                    'description': 'в секундах',
                    'range': '1-60'
                },
                'max_channels_per_client': {
                    'name': 'каналов на аккаунт',
                    'description': 'максимальное количество',
                    'range': '100-1000'
                },
                'notification_chunk_size': {
                    'name': 'размер чанка уведомлений',
                    'description': 'количество сообщений',
                    'range': '10-100'
                },
                'message_processing_timeout': {
                    'name': 'таймаут обработки',
                    'description': 'в секундах',
                    'range': '10-120'
                }
            }

            info = setting_info.get(setting_type, {
                'name': setting_type,
                'description': '',
                'range': 'число'
            })

            await query.edit_message_text(
                f"⚙️ *Изменение настройки:* {info['name']}\n\n"
                f"Введите новое значение ({info['description']})\n"
                f"Допустимый диапазон: {info['range']}\n\n"
                "Отправьте /cancel для отмены",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Отмена", callback_data='monitor_settings')
                ]])
            )
            
            return STATES['ENTERING_VALUE']
            
        except Exception as e:
            self.logger.error(f"Ошибка при запросе значения настройки: {e}")
            return await self.show_settings_menu(query, context)


    async def toggle_monitoring(self, query: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            is_active = self.monitor.is_monitoring
            
            if is_active:
                await self.monitor.stop_monitoring()
                self.start_time = None
            else:
                await self.monitor.initialize_clients()
                await self.monitor.start_monitoring()
                self.start_time = datetime.now()

            stats = self.monitor.get_stats()
            status_emoji = "🟢" if stats['status'] == 'Активен' else "🔴"
            
            # Рассчитываем время работы
            uptime = '0:00:00'
            if self.start_time and stats['status'] == 'Активен':
                uptime = str(datetime.now() - self.start_time).split('.')[0]

            keyboard = [
                [InlineKeyboardButton(
                    "⏹️ Остановить" if stats['status'] == 'Активен' else "▶️ Запустить",
                    callback_data='toggle_monitoring'
                )],
                [
                    InlineKeyboardButton("➕ Добавить канал", callback_data='add_channel'),
                    InlineKeyboardButton("📋 Список каналов", callback_data='list_channels')
                ],
                [
                    InlineKeyboardButton("👤 Управление аккаунтами", callback_data='manage_accounts'),
                ],
                [
                    InlineKeyboardButton("🔑 Управление прокси", callback_data='manage_proxies'),
                ],
                [
                    InlineKeyboardButton("🔍 Ключевые слова", callback_data='manage_keywords'),
                ],
                [
                    InlineKeyboardButton("⚙️ Настройки", callback_data='monitor_settings')
                ]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)
            message = (
                f"*Панель мониторинга*\n\n"
                f"Статус: {status_emoji} {stats['status']}\n"
                f"Время работы: {uptime}\n"
                f"Обработано сообщений: {stats['messages_processed']}\n"
                f"Найдено ключевых слов: {stats['keywords_found']}\n"
                f"Ошибок: {stats['errors']}\n"
                f"Активных клиентов: {stats['active_clients']}\n"
                f"Отслеживаемых каналов: {stats['watched_channels']}\n"
            )

            # Обновляем сообщение
            await query.edit_message_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
                
            return STATES['MONITORING']
                
        except Exception as e:
            self.logger.error(f"Ошибка при переключении мониторинга: {e}")
            await query.edit_message_text(
                "❌ Произошла ошибка при переключении мониторинга",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Назад", callback_data='back_to_monitor')
                ]])
            )
            return STATES['MONITORING']

    async def edit_autorestart(self, query: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            settings = load_settings()
            
            keyboard = [
                [InlineKeyboardButton(
                    f"Автоперезапуск: {'Включен' if settings['auto_restart'] else 'Выключен'}", 
                    callback_data='toggle_autorestart'
                )],
                [InlineKeyboardButton(
                    f"Задержка: {settings['restart_delay']} сек",
                    callback_data='change_restart_delay'
                )],
                [InlineKeyboardButton(
                    f"Макс. ошибок: {settings['max_errors_before_restart']}",
                    callback_data='change_max_errors'
                )],
                [InlineKeyboardButton("« Назад", callback_data='monitor_settings')]
            ]
            
            await query.edit_message_text(
                "🔄 *Настройки автоперезапуска*\n\n"
                "Выберите параметр для изменения:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
            return STATES['EDITING_AUTORESTART']
            
        except Exception as e:
            self.logger.error(f"Ошибка при редактировании автоперезапуска: {e}")
            return await self.show_monitor_menu(query, context)

    async def start_channel_addition(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса добавления канала"""
        try:
            if not update.callback_query:
                return STATES['MONITORING']
            
            query = update.callback_query
            await query.answer()
            
            message = (
                "*Добавление нового канала*\n\n"
                "Отправьте ссылку на канал в одном из форматов:\n"
                "• `https://t.me/channel_name`\n"
                "• `@channel_name`\n"
                "• `https://t.me/+abcdef...` (для приватных каналов)\n\n"
                "❌ Для отмены отправьте /cancel"
            )
            
            keyboard = [[InlineKeyboardButton("« Назад", callback_data='back_to_monitor')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            context.user_data['state'] = STATES['ADDING_CHANNEL']
            return STATES['ADDING_CHANNEL']
            
        except Exception as e:
            self.logger.error(f"Ошибка при начале добавления канала: {e}")
            if update.callback_query:
                await update.callback_query.answer("Произошла ошибка")
                try:
                    await update.callback_query.edit_message_text(
                        text="❌ Произошла ошибка. Попробуйте еще раз или используйте /cancel",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("« Назад", callback_data='back_to_monitor')
                        ]]),
                        parse_mode='Markdown'
                    )
                except Exception:
                    pass
            return STATES['MONITORING']

    async def add_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):

            try:
                message_text = update.message.text
                channel_links = [link.strip() for link in message_text.split('\n') if link.strip()]

                status_message = await update.message.reply_text(
                    "🔄 *Подготовка к добавлению каналов*\n\n"
                    f"📋 Каналов в очереди: `{len(channel_links)}`\n"
                    "⏳ Начинаем обработку...\n\n"
                    "_💡 Вы можете продолжать работу с ботом_",
                    parse_mode='Markdown'
                )

                await self.show_monitor_menu(update, context)
                asyncio.create_task(
                    self._process_channels_background(
                        channel_links,
                        status_message,
                        update.message.chat_id
                    )
                )

                return STATES['MONITORING']

            except Exception as e:
                self.logger.error(f"Ошибка при добавлении каналов: {e}")
                await update.message.reply_text(
                    "❌ *Произошла ошибка при добавлении каналов*",
                    parse_mode='Markdown'
                )
                return STATES['MONITORING']

    async def _process_channels_background(self, channel_links: List[str], status_message, chat_id: int):
        """Фоновый процесс добавления каналов"""
        try:
            async def update_status(text: str):
                try:
                    await status_message.edit_text(
                        text + "\n\n" +
                        "_💡 Вы можете продолжать работу с ботом, "
                        "добавление каналов происходит в фоновом режиме_",
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    self.logger.error(f"Ошибка при обновлении статуса: {e}")

            added, errors = await self.channel_handler.process_channel_addition(
                channel_links,
                update_status
            )

            # После завершения отправляем финальное уведомление
            final_message = (
                "✅ *Добавление каналов завершено*\n\n"
                f"📊 Добавлено: `{added}`\n"
                f"❌ Ошибок: `{len(errors)}`\n"
            )

            if errors:
                final_message += "\n*Ошибки при добавлении:*\n"
                final_message += "\n".join(f"• {error}" for error in errors)

            keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_monitor")]]
            
            if hasattr(self.monitor, 'bot') and hasattr(self.monitor.bot, 'bot'):
                bot = self.monitor.bot.bot
            else:
                bot = self.monitor.bot

            await bot.send_message(
                chat_id=chat_id,
                text=final_message,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        except Exception as e:
            self.logger.error(f"Ошибка в фоновом процессе: {e}")
            if hasattr(self.monitor, 'bot') and hasattr(self.monitor.bot, 'bot'):
                bot = self.monitor.bot.bot
            else:
                bot = self.monitor.bot

            await bot.send_message(
                chat_id=chat_id,
                text="❌ *Произошла ошибка при добавлении каналов*\n\n"
                     "Попробуйте добавить каналы позже или меньшими группами",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_monitor")
                ]])
            )
            
    async def list_channels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            channels = await self.monitor.db.load_channels()
            query = update if not hasattr(update, 'callback_query') else update.callback_query
            
            if hasattr(update, 'callback_query'):
                await query.answer()

            if not channels:
                message_text = "📋 Список каналов пуст\n\nДобавьте каналы с помощью кнопки 'Добавить канал'"
                keyboard = [[InlineKeyboardButton("« Назад", callback_data="back_to_monitor")]]
            else:
                message_text = f"📋 Список отслеживаемых каналов\n📈 Всего каналов: {len(channels)}\n\n"

                for i, channel in enumerate(channels, 1):
                    title = channel.get('title', 'Без названия')
                    username = channel.get('username', '')
                    message_text += f"{i}. {title}\n"
                    if username:
                        message_text += f"    @{username}\n"
                    message_text += "\n"

                keyboard = [
                    [InlineKeyboardButton("➕ Добавить канал", callback_data="add_channel")],
                    [InlineKeyboardButton("🗑 Удаление групп", callback_data="delete_channels_menu")],
                    [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_monitor")]
                ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            if hasattr(update, 'callback_query'):
                await query.edit_message_text(
                    text=message_text,
                    reply_markup=reply_markup
                )
            else:
                await update.message.reply_text(
                    text=message_text,
                    reply_markup=reply_markup
                )

            return STATES['MONITORING']

        except Exception as e:
            self.logger.error(f"Ошибка при отображении списка каналов: {e}")
            return await self.show_error(update, "получении списка каналов")


    async def manage_channels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню управления каналами"""
        try:
            query = update.callback_query
            await query.answer()

            channels = await self.monitor.db.load_channels()
            
            manage_page = context.user_data.get('manage_channels_page', 0)
            items_per_page = 5  # Меньше каналов на странице для удобства
            total_pages = (len(channels) - 1) // items_per_page + 1
            
            start_idx = manage_page * items_per_page
            end_idx = start_idx + items_per_page
            current_channels = channels[start_idx:end_idx]

            message_text = (
                "🗑 *Управление каналами*\n"
                f"📊 Страница {manage_page + 1} из {total_pages}\n"
                "Выберите канал для удаления:\n\n"
            )

            keyboard = []
            
            for channel in current_channels:
                title = channel.get('title', 'Без названия')
                chat_id = channel.get('chat_id')
                keyboard.append([
                    InlineKeyboardButton(
                        f"🗑 {title[:30]}{'...' if len(title) > 30 else ''}", 
                        callback_data=f"delete_channel_{chat_id}"
                    )
                ])

            nav_buttons = []
            if total_pages > 1:
                if manage_page > 0:
                    nav_buttons.append(InlineKeyboardButton("⬅️", callback_data="prev_manage_page"))
                nav_buttons.append(InlineKeyboardButton(f"{manage_page + 1}/{total_pages}", callback_data="current_manage_page"))
                if manage_page < total_pages - 1:
                    nav_buttons.append(InlineKeyboardButton("➡️", callback_data="next_manage_page"))
                keyboard.append(nav_buttons)

            # Кнопки управления
            keyboard.append([InlineKeyboardButton("🗑 Удалить все", callback_data="confirm_delete_all")])
            keyboard.append([InlineKeyboardButton("« Назад к списку", callback_data="list_channels")])
            
            await query.edit_message_text(
                text=message_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

            return STATES['MANAGING_CHANNELS']

        except Exception as e:
            self.logger.error(f"Ошибка при открытии меню управления каналами: {e}")
            return await self.show_error(update, "открытии меню управления")

    async def handle_channels_navigation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка навигации по страницам"""
        try:
            query = update.callback_query
            await query.answer()

            action = query.data
            
            if 'manage' in action:
                current_page = context.user_data.get('manage_channels_page', 0)
                if action == 'prev_manage_page':
                    context.user_data['manage_channels_page'] = max(0, current_page - 1)
                elif action == 'next_manage_page':
                    context.user_data['manage_channels_page'] = current_page + 1
                return await self.manage_channels(update, context)
            else:
                current_page = context.user_data.get('channels_page', 0)
                if action == 'prev_channels_page':
                    context.user_data['channels_page'] = max(0, current_page - 1)
                elif action == 'next_channels_page':
                    context.user_data['channels_page'] = current_page + 1
                return await self.list_channels(update, context)

        except Exception as e:
            self.logger.error(f"Ошибка при навигации: {e}")
            return await self.show_error(update, "навигации")

    async def delete_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Удаление канала"""
        try:
            query = update.callback_query
            await query.answer()
            
            channel_id = int(query.data.replace('delete_channel_', ''))
            success = await self.monitor.remove_channel(channel_id)
            
            if success:
                await query.answer("✅ Канал успешно удален")
            else:
                await query.answer("❌ Ошибка при удалении канала")

            return await self.manage_channels(update, context)

        except Exception as e:
            self.logger.error(f"Ошибка при удалении канала: {e}")
            return await self.show_error(update, "удалении канала")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений"""
        try:
            if not context.user_data.get('state'):
                return STATES['MONITORING']

            current_state = context.user_data['state']
            
            if current_state == STATES['ADDING_CHANNEL']:
                return await self.add_channel(update, context)

            return STATES['MONITORING']
            
        except Exception as e:
            self.logger.error(f"Ошибка при обработке сообщения: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка при обработке сообщения.\n"
                "Попробуйте еще раз или вернитесь в главное меню с помощью /cancel"
            )
            return STATES['MONITORING']

    async def check_channels(self, query: Update, context: ContextTypes.DEFAULT_TYPE):
        """Проверка доступности всех каналов"""
        try:
            await query.edit_message_text("🔄 Проверка каналов...")
            results = await self.monitor.check_channels()
            
            message = "📊 *Результаты проверки каналов:*\n\n"
            for channel, is_available in results.items():
                status = "🟢" if is_available else "🔴"
                message += f"{status} {channel}\n"

            keyboard = [
                [InlineKeyboardButton("🔄 Проверить снова", callback_data='check_channels')],
                [InlineKeyboardButton("« Назад", callback_data='back_to_monitor')]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return STATES['MONITORING']
            
        except Exception as e:
            logger.error(f"Ошибка при проверке каналов: {e}")
            await query.edit_message_text("❌ Произошла ошибка при проверке каналов")
            return STATES['MONITORING']

    async def show_detailed_stats(self, query: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать подробную статистику мониторинга"""
        try:
            stats = self.monitor.get_stats()
            
            # Вычисляем проценты
            if stats['messages_processed'] > 0:
                finds_percent = (stats['keywords_found'] / stats['messages_processed']) * 100
                errors_percent = (stats['errors'] / stats['messages_processed']) * 100
            else:
                finds_percent = 0
                errors_percent = 0
            
            message = (
                "📊 *Подробная статистика*\n\n"
                f"🕒 Время работы: {stats.get('uptime', '0:00:00')}\n"
                f"📥 Обработано сообщений: {stats['messages_processed']}\n"
                f"🔍 Найдено ключевых слов: {stats['keywords_found']}\n"
                f"❌ Количество ошибок: {stats['errors']}\n"
                f"👥 Активные клиенты: {stats['active_clients']}\n"
                f"📢 Отслеживаемые каналы: {stats['watched_channels']}\n\n"
                f"📈 *Эффективность:*\n"
                f"• Среднее количество находок: {finds_percent:.2f}%\n"
                f"• Ошибок на 100 сообщений: {errors_percent:.2f}"
            )

            keyboard = [
                [InlineKeyboardButton("🔄 Обновить", callback_data='monitor_stats')],
                [InlineKeyboardButton("« Назад", callback_data='back_to_monitor')]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return STATES['MONITORING']
            
        except Exception as e:
            logger.error(f"Ошибка при отображении статистики: {e}")
            await query.edit_message_text("❌ Произошла ошибка при загрузке статистики")
            return STATES['MONITORING']

    async def show_settings(self, query: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать настройки мониторинга"""
        try:
            message = (
                "⚙️ *Настройки мониторинга*\n\n"
                "🔔 Уведомления: Включены\n"
                "🕒 Задержка проверки: 1 сек\n"
                "📝 Формат уведомлений: Стандартный\n"
                "🔄 Автоперезапуск: Включен\n\n"
                "_Настройка параметров будет доступна в следующем обновлении_"
            )

            keyboard = [[InlineKeyboardButton("« Назад", callback_data='back_to_monitor')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return STATES['MONITORING']
            
        except Exception as e:
            logger.error(f"Ошибка при отображении настроек: {e}")
            await query.edit_message_text("❌ Произошла ошибка при загрузке настроек")
            return STATES['MONITORING']

    async def remove_channel(self, query: Update, context: ContextTypes.DEFAULT_TYPE, channel: str):
        """Удаление канала из мониторинга"""
        try:
            success = await self.monitor.remove_channel(channel)
            
            if success:
                message = f"✅ Канал {channel} успешно удален из мониторинга"
            else:
                message = f"❌ Не удалось удалить канал {channel}"

            await query.edit_message_text(message)
            await asyncio.sleep(2)
            return await self.list_channels(query, context)
            
        except Exception as e:
            logger.error(f"Ошибка при удалении канала: {e}")
            await query.edit_message_text("❌ Произошла ошибка при удалении канала")
            return STATES['MONITORING']

    def get_handlers(self):
        """
        Получить все обработчики для регистрации
        """
        return [
            self.show_monitor_menu,          # Показ главного меню мониторинга
            self.handle_monitor_callback,     # Обработка callback-ов
            self.start_channel_addition,      # Начало добавления канала
            self.add_channel,                 # Добавление канала
            self.list_channels,               # Список каналов
            self.check_channels,              # Проверка каналов
            self.show_detailed_stats,         # Подробная статистика
            self.show_settings,               # Настройки
            self.remove_channel,              # Удаление канала
            self.toggle_monitoring,           # Включение/выключение мониторинга
            self.show_delete_channels_menu,   # Меню удаления каналов
            self.delete_single_channel,       # Удаление отдельного канала
            self.delete_all_channels,         # Удаление всех каналов
            self.confirm_delete_all_channels  # Подтверждение удаления всех
        ]
        
class AccountHandler:
    async def show_accounts_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать главное меню управления аккаунтами"""
        try:
            keyboard = [
                [InlineKeyboardButton("➕ Добавить аккаунт", callback_data='add_account')],
                [InlineKeyboardButton("📋 Список аккаунтов", callback_data='list_accounts')],
                [InlineKeyboardButton("🗑 Удалить невалидные", callback_data='remove_invalid')],
                [InlineKeyboardButton("« Назад", callback_data='back_to_monitor')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = (
                "👤 *Управление аккаунтами*\n\n"

            )
            
            if update.callback_query:
                try:
                    await update.callback_query.edit_message_text(
                        message,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                except telegram.error.BadRequest as e:
                    if "Message is not modified" not in str(e):
                        raise e
            else:
                await update.message.reply_text(
                    message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
            return STATES['MANAGING_ACCOUNTS']
                
        except Exception as e:
            self.logger.error(f"Ошибка при отображении меню аккаунтов: {e}")
            return STATES['MANAGING_ACCOUNTS']