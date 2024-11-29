import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import ContextTypes
from project.database.database_manager import DatabaseManager
from project.config import STATES

logger = logging.getLogger(__name__)

class KeywordHandler:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self.logger = logging.getLogger(__name__)
        self.monitor_handler = None
    
    def set_monitor_handler(self, monitor_handler):
        self.monitor_handler = monitor_handler

    async def show_keywords_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            [InlineKeyboardButton("➕ Добавить слово", callback_data='add_keyword')],
            [InlineKeyboardButton("📋 Список слов", callback_data='list_keywords')],
            [InlineKeyboardButton("📊 Статистика", callback_data='keyword_stats')],
            [InlineKeyboardButton("« Назад", callback_data='back_to_monitor')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = (
            "🔍 *Управление ключевыми словами*\n\n"
            "Выберите действие:\n"
            "• Добавить новые слова\n"
            "• Просмотреть список\n"
            "• Посмотреть статистику"
        )

        if update.callback_query:
            await update.callback_query.message.edit_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        
        return STATES['MANAGING_KEYWORDS']

    async def handle_keyword_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        try:
            if query.data == 'add_keyword':
                return await self.start_keyword_addition(update, context)
                
            elif query.data == 'list_keywords':
                return await self.list_keywords(update, context)
                
            elif query.data == 'keyword_stats':
                return await self.show_keyword_stats(update, context)
                
            elif query.data == 'back_to_keywords':
                return await self.show_keywords_menu(update, context)
                
            elif query.data == 'back_to_monitor':
                if hasattr(self, 'monitor_handler') and self.monitor_handler:
                    return await self.monitor_handler.show_monitor_menu(update, context)
                return STATES['MONITORING']
                
            elif query.data.startswith('delete_keyword_'):
                keyword = query.data.replace('delete_keyword_', '')
                keywords = self.db.load_keywords()
                
                if keyword in keywords:
                    keywords.remove(keyword)
                    if self.db.save_keywords(keywords):
                        await query.answer(f"Ключевое слово '{keyword}' удалено")
                        return await self.list_keywords(update, context)
                    else:
                        await query.answer("Ошибка при удалении ключевого слова")
                        return STATES['MANAGING_KEYWORDS']
                else:
                    await query.answer("Ключевое слово не найдено")
                    return STATES['MANAGING_KEYWORDS']

            return STATES['MANAGING_KEYWORDS']

        except Exception as e:
            self.logger.error(f"Ошибка при обработке callback {query.data}: {e}")
            await query.answer("Произошла ошибка")
            return STATES['MANAGING_KEYWORDS']



    async def start_keyword_addition(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса добавления ключевого слова"""
        try:
            message = (
                "*Добавление ключевых слов*\n\n"
                "Отправьте ключевое слово или фразу.\n"
                "Можно отправить несколько слов, каждое с новой строки.\n\n"
                "Правила:\n"
                "• Минимальная длина: 3 символа\n"
                "• Без спецсимволов\n"
                "• Чувствительно к регистру\n\n"
                "❌ Для отмены отправьте /cancel"
            )

            if update.callback_query:
                await update.callback_query.edit_message_text(
                    text=message,
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    text=message,
                    parse_mode='Markdown'
                )

            return STATES['ADDING_KEYWORD']

        except Exception as e:
            self.logger.error(f"Ошибка при начале добавления ключевого слова: {e}")
            if update.callback_query:
                await update.callback_query.message.reply_text(
                    "❌ Произошла ошибка. Попробуйте позже."
                )
            else:
                await update.message.reply_text(
                    "❌ Произошла ошибка. Попробуйте позже."
                )
            return STATES['MANAGING_KEYWORDS']

    async def add_keywords(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        words = update.message.text.strip().split('\n')
        added = []
        skipped = []
        
        existing_keywords = self.db.load_keywords()
        
        for word in words:
            word = word.strip()
            if len(word) < 3:
                skipped.append(f"{word} (слишком короткое)")
                continue
            if any(char in word for char in ['!', '@', '#', '$', '%', '^', '&', '*']):
                skipped.append(f"{word} (содержит спецсимволы)")
                continue
            if word in existing_keywords:
                skipped.append(f"{word} (уже существует)")
                continue
                
            existing_keywords.append(word)
            added.append(word)

        if added:
            self.db.save_keywords(existing_keywords)

        message = []
        if added:
            message.append("✅ *Добавлены слова:*\n" + "\n".join(f"• {word}" for word in added))
        if skipped:
            message.append("❌ *Пропущены слова:*\n" + "\n".join(f"• {word}" for word in skipped))
        
        await update.message.reply_text(
            "\n\n".join(message),
            parse_mode='Markdown'
        )
        
        await update.message.reply_text(
            "Отправьте ещё ключевые слова или /done для завершения"
        )
        return STATES['ADDING_KEYWORD']

    async def finish_keyword_addition(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "✅ Добавление ключевых слов завершено"
        )
        return await self.show_keywords_menu(update, context)

    async def list_keywords(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            keywords = self.db.load_keywords()
            
            if not keywords:
                message = "📋 *Список ключевых слов*\n\nСписок пуст."
                keyboard = [[InlineKeyboardButton("« Назад", callback_data='back_to_keywords')]]
            else:
                message = "📋 *Список ключевых слов* (страница 1/1)\n\n"
                for keyword in keywords:
                    message += f"• {keyword}\n"
                
                keyboard = []
                for keyword in keywords:
                    keyboard.append([InlineKeyboardButton(
                        f"🗑 Удалить {keyword}", 
                        callback_data=f'delete_keyword_{keyword}'
                    )])
                keyboard.append([InlineKeyboardButton("« Назад", callback_data='back_to_keywords')])

            reply_markup = InlineKeyboardMarkup(keyboard)

            if isinstance(update, Update) and update.callback_query:
                await update.callback_query.message.edit_text(
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

            return STATES['MANAGING_KEYWORDS']

        except Exception as e:
            self.logger.error(f"Ошибка при отображении списка ключевых слов: {e}")
            if isinstance(update, Update) and update.callback_query:
                await update.callback_query.answer("Ошибка при загрузке списка")
            return STATES['MANAGING_KEYWORDS']

    async def delete_keyword(self, query: Update, context: ContextTypes.DEFAULT_TYPE, keyword: str):
        try:
            keywords = self.db.load_keywords()
            self.logger.info(f"Удаляем ключевое слово: {keyword}")
            
            if keyword in keywords:
                keywords.remove(keyword)
                if self.db.save_keywords(keywords):
                    await query.edit_message_text(
                        f"✅ Слово '{keyword}' удалено",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("« Назад к списку", callback_data='list_keywords')
                        ]])
                    )
                    await asyncio.sleep(2)
                    return await self.list_keywords(query, context)
                
            await query.answer("❌ Ошибка при удалении слова")
            return STATES['MANAGING_KEYWORDS']
                
        except Exception as e:
            self.logger.error(f"Ошибка при удалении слова {keyword}: {e}")
            await query.answer("❌ Произошла ошибка")
            return STATES['MANAGING_KEYWORDS']

    async def show_keyword_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer()

            stats = await self.db.get_keyword_stats()
            
            message = (
                "📊 *Статистика ключевых слов*\n\n"
                f"📝 Всего слов: {len(stats)}\n\n"
                "*Топ по упоминаниям:*\n"
            )

            sorted_stats = sorted(
                stats.items(), 
                key=lambda x: x[1]['total_mentions'], 
                reverse=True
            )[:10]  # Показываем топ-10

            for keyword, stat in sorted_stats:
                message += (
                    f"• `{keyword}`: {stat['total_mentions']} упоминаний\n"
                    f"  За сегодня: {stat['mentions_today']}\n"
                    f"  За неделю: {stat['mentions_week']}\n"
                )

            keyboard = [
                [InlineKeyboardButton("« Назад", callback_data='back_to_keywords')]
            ]

            await query.edit_message_text(
                text=message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

            return STATES['MANAGING_KEYWORDS']

        except Exception as e:
            self.logger.error(f"Ошибка при обработке callback keyword_stats: {e}")
            await query.edit_message_text(
                "❌ Произошла ошибка при получении статистики",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Назад", callback_data='back_to_keywords')
                ]])
            )
            return STATES['MANAGING_KEYWORDS']

    async def start_keywords_import(self, query: Update, context: ContextTypes.DEFAULT_TYPE):
        await query.edit_message_text(
            "*Импорт ключевых слов*\n\n"
            "Отправьте файл со списком слов.\n"
            "Требования к файлу:\n"
            "• Формат: .txt\n"
            "• Кодировка: UTF-8\n"
            "• Одно слово на строку\n\n"
            "❌ Для отмены отправьте /cancel",
            parse_mode='Markdown'
        )
        return STATES['IMPORTING_KEYWORDS']

    async def import_keywords(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message.document:
            await update.message.reply_text("❌ Пожалуйста, отправьте текстовый файл.")
            return STATES['IMPORTING_KEYWORDS']

        file = await update.message.document.get_file()
        
        try:
            content = await file.read_as_string()
            words = content.strip().split('\n')
            
            added = []
            skipped = []
            existing_keywords = self.db.load_keywords()
            
            for word in words:
                word = word.strip()
                if len(word) < 3 or word in existing_keywords:
                    skipped.append(word)
                    continue
                    
                existing_keywords.append(word)
                added.append(word)

            if added:
                self.db.save_keywords(existing_keywords)

            message = f"✅ Импортировано {len(added)} слов\n❌ Пропущено {len(skipped)} слов"
            await update.message.reply_text(message)
            
            return await self.show_keywords_menu(update, context)
            
        except Exception as e:
            logger.error(f"Ошибка при импорте ключевых слов: {e}")
            await update.message.reply_text("❌ Произошла ошибка при импорте файла.")
            return STATES['IMPORTING_KEYWORDS']

    async def export_keywords(self, query: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отказано"""
        keywords = self.db.load_keywords()
        
        if not keywords:
            await query.edit_message_text(
                "❌ Список ключевых слов пуст. Нечего экспортировать.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Назад", callback_data='back_to_keywords')
                ]])
            )
            return

        content = "\n".join(keywords)
        
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=content.encode(),
            filename="keywords.txt",
            caption="📤 Экспорт ключевых слов"
        )
        
        return await self.show_keywords_menu(query, context)

    def get_handlers(self):
        return [
            self.show_keywords_menu,
            self.handle_keyword_callback,
            self.add_keywords,
            self.finish_keyword_addition,
            self.import_keywords
        ]