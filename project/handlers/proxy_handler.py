import logging
import os
import shutil
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from project.managers.proxy_manager import ProxyManager
from project.config import STATES

logger = logging.getLogger(__name__)

class ProxyHandler:
    def __init__(self, proxy_manager: ProxyManager):
        self.proxy_manager = proxy_manager
        self.logger = logging.getLogger(__name__)
        self.monitor_handler = None
        
    def set_monitor_handler(self, monitor_handler):
        self.monitor_handler = monitor_handler

    async def show_proxy_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            stats = await self.proxy_manager.get_proxy_status()
            
            keyboard = [
                [InlineKeyboardButton("➕ Добавить прокси", callback_data='add_proxy')],
                [InlineKeyboardButton("📋 Список прокси", callback_data='list_proxies')],
                [InlineKeyboardButton("🔄 Проверить прокси", callback_data='check_proxies')],
                [InlineKeyboardButton("🗑 Удалить все прокси", callback_data='delete_all_proxies')],
                [InlineKeyboardButton("« Назад", callback_data='back_to_monitor')]
            ]
            
            message = (
                "🔑 *Управление прокси*\n\n"
                f"📝 Всего прокси: {stats['total']}\n"
                f"✅ Рабочих: {stats['working']}\n"
                f"❌ Нерабочих: {stats['not_working']}\n"
                f"📈 Процент ошибок: {stats['error_rate']}%\n\n"
                "Выберите действие:"
            )
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    text=message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    text=message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            return STATES['MANAGING_PROXIES']
        
        except Exception as e:
            self.logger.error(f"Ошибка при отображении меню прокси: {e}")
            error_text = "❌ Произошла ошибка при загрузке меню прокси"
            if update.callback_query:
                await update.callback_query.edit_message_text(text=error_text)
            else:
                await update.message.reply_text(text=error_text)
            return STATES['MONITORING']

    def set_monitor_handler(self, monitor_handler):
        self.monitor_handler = monitor_handler

    async def handle_proxy_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        self.logger.info(f"Получен callback: {query.data}")
        await query.answer()
        
        try:
            if query.data == 'add_proxy':
                return await self.start_proxy_addition(update, context)
                
            elif query.data == 'list_proxies':
                return await self.list_proxies(update, context)
                
            elif query.data == 'check_proxies':
                return await self.check_proxies(update, context)
                
            elif query.data == 'delete_all_proxies':
                return await self.delete_all_proxies(update, context)
                
            elif query.data == 'back_to_monitor':
                self.logger.info("Возврат в главное меню")
                if self.monitor_handler:
                    return await self.monitor_handler.show_monitor_menu(update, context)
                else:
                    self.logger.error("monitor_handler не установлен")
                    return STATES['MONITORING']
                    
            return STATES['MONITORING']
            
        except Exception as e:
            self.logger.error(f"Ошибка при обработке callback {query.data}: {e}")
            await query.message.edit_text(
                "❌ Произошла ошибка. Попробуйте еще раз.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Назад", callback_data='back_to_monitor')
                ]]),
                parse_mode='Markdown'
            )
            return STATES['MONITORING']  
            
    async def show_delete_confirmation(self, query: Update, context: ContextTypes.DEFAULT_TYPE):
        await query.edit_message_text(
            "⚠️ *Вы уверены, что хотите удалить все прокси?*\n"
            "Это действие нельзя отменить.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Да", callback_data='confirm_delete'),
                    InlineKeyboardButton("❌ Нет", callback_data='cancel_delete')
                ],
                [InlineKeyboardButton("« Назад", callback_data='back_to_proxies')]
            ]),
            parse_mode='Markdown'
        )
        return STATES['CONFIRMING_DELETE']

    async def delete_all_proxies(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Удаление всех прокси"""
        try:
            self.proxy_manager.clear_proxies()
            await update.callback_query.message.edit_text(
                "✅ Все прокси успешно удалены",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Назад", callback_data='back_to_proxies')
                ]]),
                parse_mode='Markdown'
            )
            return STATES['MANAGING_PROXIES']
        except Exception as e:
            self.logger.error(f"Ошибка при удалении прокси: {e}")
            await update.callback_query.message.edit_text(
                "❌ Произошла ошибка при удалении прокси",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Назад", callback_data='back_to_proxies')
                ]]),
                parse_mode='Markdown'
            )
            return STATES['MANAGING_PROXIES']
            
    async def start_proxy_addition(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса добавления прокси"""
        try:
            await update.callback_query.message.edit_text(
                "📤 *Добавление прокси*\n\n"
                "Отправьте прокси в одном из форматов:\n"
                "• `IP:PORT:LOGIN:PASSWORD`\n"
                "• `LOGIN:PASSWORD@IP:PORT`\n\n"
                "Можно отправить несколько прокси, каждый с новой строки.\n"
                "✅ Для завершения отправьте /done\n"
                "❌ Для отмены отправьте /cancel",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Назад", callback_data='back_to_proxies')
                ]]),
                parse_mode='Markdown'
            )
            return STATES['ADDING_PROXY']
        except Exception as e:
            self.logger.error(f"Ошибка при начале добавления прокси: {e}")
            return STATES['MONITORING']

    async def add_proxies(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка добавляемых прокси"""
        try:
            proxy_lines = update.message.text.strip().split('\n')
            status_message = await update.message.reply_text("🔄 Проверка прокси...")

            added = 0
            invalid = 0
            total = len(proxy_lines)
            
            for i, line in enumerate(proxy_lines, 1):
                line = line.strip()
                if not line:
                    continue
                    
                proxy_config = self.proxy_manager.parse_proxy(line)
                if not proxy_config:
                    invalid += 1
                    continue

                is_working = await self.proxy_manager.check_proxy(proxy_config)
                if is_working:
                    self.proxy_manager.add_proxy(line)
                    added += 1
                else:
                    invalid += 1

                if i % 5 == 0:
                    await status_message.edit_text(
                        f"🔄 Проверка прокси... {i}/{total}\n"
                        f"✅ Рабочих: {added}\n"
                        f"❌ Нерабочих: {invalid}"
                    )

            final_message = (
                "📊 *Результаты добавления:*\n\n"
                f"✅ Добавлено рабочих: {added}\n"
                f"❌ Отклонено нерабочих: {invalid}\n"
                f"📝 Всего проверено: {total}\n\n"
                "Отправьте еще прокси или /done для завершения"
            )

            await status_message.edit_text(final_message, parse_mode='Markdown')
            return STATES['ADDING_PROXY']
            
        except Exception as e:
            self.logger.error(f"Ошибка при добавлении прокси: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка при добавлении прокси.\n"
                "Проверьте формат и попробуйте снова."
            )
            return STATES['ADDING_PROXY']

    async def finish_proxy_addition(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Завершение процесса добавления прокси"""
        try:
            await update.message.reply_text(
                "✅ Добавление прокси завершено\n"
                "Возвращаюсь в меню управления прокси..."
            )
            return await self.show_proxy_menu(update, context)
        except Exception as e:
            self.logger.error(f"Ошибка при завершении добавления прокси: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка. Возвращаюсь в меню..."
            )
            return await self.show_proxy_menu(update, context)

    async def list_proxies(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать список прокси"""
        try:
            results = await self.proxy_manager.check_all_proxies()
            has_invalid = any(not is_working for _, is_working in results)
            
            if not results:
                message = "📋 *Список прокси пуст*\n\nДобавьте прокси с помощью кнопки 'Добавить прокси'"
            else:
                message = "📋 *Список прокси:*\n\n"
                for proxy_config, is_working in results:
                    status = "✅" if is_working else "❌"
                    proxy_str = f"{proxy_config['addr']}:{proxy_config['port']}"
                    message += f"{status} `{proxy_str}`\n"

            keyboard = [
                [InlineKeyboardButton("🔄 Обновить", callback_data='list_proxies')]
            ]
            
            # Добавляем кнопку удаления невалидных, только если они есть
            if has_invalid:
                keyboard.append([
                    InlineKeyboardButton("🗑 Удалить невалидные", callback_data='clear_invalid_proxies')
                ])
                
            keyboard.append([InlineKeyboardButton("« Назад", callback_data='back_to_proxies')])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            self.logger.error(f"Ошибка при отображении списка прокси: {e}")
            await update.callback_query.edit_message_text(
                "❌ Произошла ошибка при получении списка прокси",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Назад", callback_data='back_to_proxies')
                ]]),
                parse_mode='Markdown'
            )

    async def check_proxies(self, query: Update, context: ContextTypes.DEFAULT_TYPE):
        """Проверка всех прокси"""
        try:
            message = await query.edit_message_text("🔄 Проверка прокси...")
            results = await self.proxy_manager.check_all_proxies()
            
            working = sum(1 for _, is_working in results if is_working)
            total = len(results)
            
            status = (
                "📊 *Результаты проверки:*\n\n"
                f"📝 Всего проверено: {total}\n"
                f"✅ Рабочих: {working}\n"
                f"❌ Нерабочих: {total - working}\n"
                f"📈 Процент рабочих: {round(working/total*100 if total else 0, 2)}%"
            )

            keyboard = [
                [InlineKeyboardButton("🔄 Проверить снова", callback_data='check_proxies')],
                [InlineKeyboardButton("« Назад", callback_data='back_to_proxies')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await message.edit_text(
                text=status,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            self.logger.error(f"Ошибка при проверке прокси: {e}")
            await query.edit_message_text(
                "❌ Произошла ошибка при проверке прокси",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Назад", callback_data='back_to_proxies')
                ]])
            )

    async def clear_invalid_proxies(self, query: Update, context: ContextTypes.DEFAULT_TYPE):
       """Удаление невалидных прокси"""
       try:
           await query.edit_message_text("🔄 Проверка и удаление невалидных прокси...")
           
           # Проверяем и удаляем невалидные прокси
           removed_count = await self.proxy_manager.remove_invalid_proxies()

           message = (
               "🗑 *Результаты очистки:*\n\n"
               f"🔍 Удалено невалидных прокси: {removed_count}"
           )
           
           keyboard = [[InlineKeyboardButton("« Назад", callback_data='back_to_monitor')]]
           reply_markup = InlineKeyboardMarkup(keyboard)
           
           await query.edit_message_text(
               text=message,
               reply_markup=reply_markup,
               parse_mode='Markdown'
           )
           
       except Exception as e:
           self.logger.error(f"Ошибка при удалении невалидных прокси: {e}")
           await query.edit_message_text(
               "❌ Произошла ошибка при удалении невалидных прокси",
               reply_markup=InlineKeyboardMarkup([[
                   InlineKeyboardButton("« Назад", callback_data='back_to_monitor')
               ]]),
               parse_mode='Markdown'
           )


    def get_handlers(self):
        """Получить все обработчики для регистрации"""
        return [
            self.show_proxy_menu,
            self.handle_proxy_callback,
            self.add_proxies,
            self.finish_proxy_addition,  # Забыл блять
            self.list_proxies,
            self.check_proxies,
            self.clear_invalid_proxies
        ]