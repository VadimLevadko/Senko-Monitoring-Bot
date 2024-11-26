import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from ..config import STATES
import asyncio

logger = logging.getLogger(__name__)

class AdminHandler:
    def __init__(self, db_manager):
        self.db = db_manager
        self.logger = logging.getLogger(__name__)
        self.monitor_handler = None

    def set_monitor_handler(self, monitor_handler):
        self.monitor_handler = monitor_handler

    async def show_admin_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            keyboard = [
                [InlineKeyboardButton("➕ Добавить админа", callback_data='add_admin')],
                [InlineKeyboardButton("📋 Список админов", callback_data='list_admins')],
                [InlineKeyboardButton("« Назад", callback_data='back_to_monitor')]
            ]
            
            message = (
                "👥 *Управление администраторами*\n\n"
                "Выберите действие:\n"
                "• Добавить нового администратора\n"
                "• Просмотреть список администраторов"
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
                
            return STATES['MANAGING_ADMINS']
            
        except Exception as e:
            self.logger.error(f"Ошибка при показе меню админов: {e}")
            return STATES['MONITORING']

    async def handle_admin_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка callback-ов от кнопок меню администраторов"""
        query = update.callback_query
        try:
            self.logger.info(f"Получен callback: {query.data}")
            await query.answer()
            
            if query.data == 'add_admin':
                return await self.start_admin_addition(update, context)
            
            elif query.data == 'list_admins':
                return await self.list_admins(update, context)
            
            elif query.data.startswith('remove_admin_'):
                username = query.data.replace('remove_admin_', '')
                return await self.remove_admin(update, context, username)
                
            elif query.data == 'back_to_admins':
                return await self.show_admin_menu(update, context)
                
            elif query.data == 'back_to_monitor':
                if self.monitor_handler:
                    return await self.monitor_handler.show_monitor_menu(update, context)
                return STATES['MONITORING']
                
            return STATES['MANAGING_ADMINS']
            
        except Exception as e:
            self.logger.error(f"Ошибка при обработке callback {query.data}: {e}")
            await query.edit_message_text(
                "❌ Произошла ошибка. Попробуйте еще раз.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Назад", callback_data='back_to_monitor')
                ]])
            )
            return STATES['MANAGING_ADMINS']

    async def start_admin_addition(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса добавления администратора"""
        try:
            message = (
                "👤 *Добавление нового администратора*\n\n"
                "Отправьте в любом формате:\n"
                "• @username\n"
                "• https://t.me/username\n"
                "• username\n\n"
                "❌ Для отмены отправьте /cancel"
            )
            
            keyboard = [[InlineKeyboardButton("« Отмена", callback_data='back_to_admins')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            return STATES['ADDING_ADMIN']
            
        except Exception as e:
            self.logger.error(f"Ошибка при начале добавления админа: {e}")
            return STATES['MANAGING_ADMINS']

    async def list_admins(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать список администраторов"""
        try:
            admins = await self.db.get_admins()
            self.logger.info(f"Получен список админов: {admins}")

            if not admins:
                message = "📋 *Список администраторов пуст*"
                keyboard = [[InlineKeyboardButton("« Назад", callback_data='back_to_admins')]]
            else:
                message = "📋 *Список администраторов*\n\n"
                
                for admin in admins:
                    safe_username = admin['username'].replace('_', '\\_')
                    safe_added_by = admin['added_by'].replace('_', '\\_')
                    
                    if isinstance(admin['added_at'], str):
                        added_date = admin['added_at'].split('.')[0]
                    else:
                        added_date = admin['added_at'].strftime("%Y-%m-%d %H:%M:%S")
                    
                    # Определяем тип админа
                    admin_type = "👑 Супер админ" if admin['is_super_admin'] else "👤 Админ"
                    
                    message += (
                        f"{admin_type}\n"
                        f"Имя: @{safe_username}\n"
                        f"Добавил: @{safe_added_by}\n"
                        f"Дата: `{added_date}`\n"
                        "➖➖➖➖➖➖➖➖\n"
                    )
                
                keyboard = []
                for admin in admins:
                    if not admin['is_super_admin']:
                        keyboard.append([
                            InlineKeyboardButton(
                                f"🗑 Удалить @{admin['username']}", 
                                callback_data=f"remove_admin_{admin['username']}"
                            )
                        ])
                
                keyboard.append([InlineKeyboardButton("« Назад", callback_data='back_to_admins')])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if isinstance(update, Update):
                if update.callback_query:
                    await update.callback_query.edit_message_text(
                        text=message,
                        reply_markup=reply_markup,
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )
                else:
                    await update.message.reply_text(
                        text=message,
                        reply_markup=reply_markup,
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )
            
            return STATES['MANAGING_ADMINS']
            
        except Exception as e:
            self.logger.error(f"Ошибка при отображении списка админов: {e}")
            error_message = "❌ Произошла ошибка при получении списка администраторов"
            if isinstance(update, Update):
                if update.callback_query:
                    await update.callback_query.edit_message_text(
                        error_message,
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("« Назад", callback_data='back_to_monitor')
                        ]]),
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text(
                        error_message,
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("« Назад", callback_data='back_to_monitor')
                        ]]),
                        parse_mode='Markdown'
                    )
            return STATES['MANAGING_ADMINS']

    async def add_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка добавления администратора"""
        try:
            input_text = update.message.text.strip()
            username = None
            
            if input_text.startswith('@'):
                username = input_text[1:]  # Убираем @
            elif 't.me/' in input_text:
                username = input_text.split('t.me/')[-1].split('?')[0]  # Извлекаем username из ссылки
            else:
                username = input_text.strip('/')
            
            if not username:
                await update.message.reply_text(
                    "❌ Не удалось получить username.\n"
                    "Отправьте username в одном из форматов:\n"
                    "• @username\n"
                    "• https://t.me/username\n"
                    "• username\n\n"
                    "Или отправьте /cancel для отмены"
                )
                return STATES['ADDING_ADMIN']

            # Проверяем, не существует ли уже такой админ
            if await self.db.is_admin(username):
                await update.message.reply_text(
                    f"❌ Пользователь @{username} уже является администратором"
                )
                return STATES['MANAGING_ADMINS']

            # Получаем username текущего админа
            current_admin = update.effective_user.username

            # Добавляем нового админа
            success = await self.db.add_admin(
                username=username,
                added_by=current_admin
            )

            if success:
                await update.message.reply_text(
                    f"✅ Администратор @{username} успешно добавлен\n\n"
                    "ℹ️ Передайте администратору следующую информацию:\n"
                    f"1. Перейдите в бота @{context.bot.username}\n"
                    "2. Отправьте команду /start\n"
                    "3. После этого вам будут доступны все функции бота"
                )
            else:
                await update.message.reply_text(
                    "❌ Произошла ошибка при добавлении администратора"
                )

            return await self.show_admin_menu(update, context)

        except Exception as e:
            self.logger.error(f"Ошибка при добавлении админа: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка при добавлении администратора"
            )
            return STATES['MANAGING_ADMINS']

    async def remove_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE, username: str):
        """Удаление администратора"""
        try:
            query = update.callback_query
            current_admin = query.from_user.username
            
            # Проверяем, существует ли админ
            if not await self.db.is_admin(username):
                await query.answer("❌ Администратор не найден")
                return await self.list_admins(update, context)
                
            # Удаляем админа
            success = await self.db.remove_admin(username, current_admin)
            
            if success:
                await query.answer(f"✅ Администратор @{username} успешно удален")
            else:
                await query.answer("❌ Не удалось удалить администратора (возможно, это супер-админ)")
            
            # Обновляем список админов
            return await self.list_admins(update, context)
            
        except Exception as e:
            self.logger.error(f"Ошибка при удалении админа {username}: {e}")
            await query.answer("❌ Произошла ошибка при удалении администратора")
            return STATES['MANAGING_ADMINS']

    def get_handlers(self):
        """Получить все обработчики для регистрации"""
        return [
            self.show_admin_menu,
            self.handle_admin_callback,
            self.add_admin,
            self.list_admins,
            self.remove_admin
        ]