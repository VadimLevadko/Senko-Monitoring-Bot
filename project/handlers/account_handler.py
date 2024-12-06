import os
import json
import logging
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, error as telegram_error
from telegram.ext import ContextTypes
from typing import Dict, List, Tuple, Optional
from ..managers.account_manager import AccountManager
from ..config import STATES

logger = logging.getLogger(__name__)

class AccountHandler:
    def __init__(self, account_manager: AccountManager, message_monitor):
        self.account_manager = account_manager
        self.message_monitor = message_monitor
        self.logger = logger
        self.monitor_handler = None

    def set_monitor_handler(self, monitor_handler):
        self.monitor_handler = monitor_handler

    async def show_accounts_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            keyboard = [
                [InlineKeyboardButton("➕ Добавить аккаунт", callback_data='start_account_add')],
                [InlineKeyboardButton("📋 Список аккаунтов", callback_data='list_accounts')],
                [InlineKeyboardButton("« Назад", callback_data='back_to_monitor')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = (
                "👤 *Управление аккаунтами*\n\n"
                "Название .session и .json аккаунта должно быть одинаковым\n"
            )

            if update.callback_query:
                await update.callback_query.edit_message_text(
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
                
            return STATES['MANAGING_ACCOUNTS']
                
        except Exception as e:
            self.logger.error(f"Ошибка при отображении меню аккаунтов: {e}")
            return STATES['MONITORING']

    async def list_accounts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
       """Показать список аккаунтов"""
       try:
           self.logger.info("Получение списка аккаунтов")
           accounts = self.account_manager.get_accounts()
           
           self.logger.info(f"Найдено {len(accounts)} аккаунтов")
           
           has_invalid_accounts = False
           has_invalid_proxies = False
           
           if not accounts:
               message = (
                   "📋 *Список аккаунтов*\n\n"
                   "Список пуст. Нажмите кнопку 'Добавить аккаунт'"
               )
           else:
               message = "📋 *Список аккаунтов:*\n\n"
               for phone in accounts:
                   try:
                       json_path = os.path.join(self.account_manager.bots_folder, phone, f"{phone}.json")
                       proxy_path = os.path.join(self.account_manager.bots_folder, phone, "proxy.json")
                       
                       # Загружаем конфиг аккаунта
                       with open(json_path, 'r', encoding='utf-8') as f:
                           config = json.load(f)

                       # Проверяем прокси
                       proxy_valid = False
                       try:
                           with open(proxy_path, 'r', encoding='utf-8') as f:
                               proxy_config = json.load(f)
                               proxy_valid = await self.account_manager.proxy_manager.check_proxy(proxy_config)
                       except:
                           proxy_valid = False
                           
                       if not proxy_valid:
                           has_invalid_proxies = True

                       # Проверяем аккаунт
                       is_valid = False
                       if phone in self.message_monitor.monitoring_clients:
                           client = self.message_monitor.monitoring_clients[phone]
                           if client and client.is_connected():
                               try:
                                   is_valid = await client.is_user_authorized()
                               except:
                                   is_valid = False
                       
                       if not is_valid:
                           has_invalid_accounts = True
                       
                       # Формируем строку статуса
                       status = "🟢 Онлайн" if is_valid else "🔴 Оффлайн"
                       proxy_status = "✅" if proxy_valid else "❌"
                       
                       # Получаем имя и информацию
                       name = (f"{config.get('first_name', '')} "
                              f"{config.get('last_name', '')}").strip()
                       username = config.get('username', '')
                       
                       message += (f"{status} {proxy_status} {phone}"
                                 f"{f' (@{username})' if username else ''}"
                                 f"{f': {name}' if name else ''}\n")

                   except Exception as e:
                       message += f"❌ {phone}: Ошибка чтения\n"
                       self.logger.error(f"Ошибка при обработке аккаунта {phone}: {e}")
                       has_invalid_accounts = True

               message += "\n*Обозначения:*\n"
               message += "🟢 - аккаунт работает\n"
               message += "🔴 - аккаунт не работает\n"
               message += "✅ - прокси работает\n"
               message += "❌ - прокси не работает\n"

           keyboard = [
               [InlineKeyboardButton("🔄 Обновить", callback_data='list_accounts')]
           ]
           
           if has_invalid_accounts:
               keyboard.append([
                   InlineKeyboardButton(
                       "🗑 Удалить невалидные аккаунты", 
                       callback_data='remove_invalid'
                   )
               ])
           
           if has_invalid_proxies:
               keyboard.append([
                   InlineKeyboardButton(
                       "🔄 Обновить прокси", 
                       callback_data='update_invalid_proxies'
                   )
               ])
               
           keyboard.append([
               InlineKeyboardButton("« Назад", callback_data='back_to_monitor')
           ])
           
           reply_markup = InlineKeyboardMarkup(keyboard)

           try:
               if update.callback_query:
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
           except telegram.error.BadRequest as e:
               if "Message is not modified" in str(e):
                   await update.callback_query.answer("Список обновлен")
               else:
                   raise

           return STATES['MANAGING_ACCOUNTS']

       except Exception as e:
           self.logger.error(f"Ошибка при отображении списка аккаунтов: {e}")
           error_text = (
               "❌ Произошла ошибка при получении списка аккаунтов\n"
               "Попробуйте еще раз или вернитесь в главное меню"
           )
           error_keyboard = InlineKeyboardMarkup([[
               InlineKeyboardButton("« Назад", callback_data='back_to_monitor')
           ]])
           
           try:
               if update.callback_query:
                   await update.callback_query.message.edit_text(
                       text=error_text,
                       reply_markup=error_keyboard,
                       parse_mode='Markdown'
                   )
               else:
                   await update.message.reply_text(
                       text=error_text,
                       reply_markup=error_keyboard,
                       parse_mode='Markdown'
                   )
           except telegram.error.BadRequest as e:
               if "Message is not modified" not in str(e):
                   raise
                   
           return STATES['MANAGING_ACCOUNTS']

    async def check_account(self, phone: str) -> Tuple[bool, str]:
        """Проверка статуса аккаунта"""
        try:
            # Сначала проверяем, есть ли активный клиент в мониторинге
            active_client = self.message_monitor.monitoring_clients.get(phone)
            if active_client and active_client.is_connected():
                try:
                    # Проверяем авторизацию
                    if await active_client.is_user_authorized():
                        name = f"{active_client.me.first_name} {active_client.me.last_name if active_client.me.last_name else ''}"
                        return True, f"🟢 Онлайн - {name.strip()}"
                except:
                    pass

            # Если нет активного клиента или он не работает, пробуем создать новый
            client = await self.account_manager.create_client(phone)
            if not client:
                return False, "Не удалось создать клиент ⚠️"

            try:
                me = await client.get_me()
                if not me:
                    return False, "Не удалось получить информацию о пользователе ⚠️"

                name = f"{me.first_name} {me.last_name if me.last_name else ''}"

                try:
                    await client(GetDialogsRequest(
                        offset_date=None,
                        offset_id=0,
                        offset_peer=InputPeerEmpty(),
                        limit=1,
                        hash=0
                    ))
                    return True, f"🟢 Онлайн - {name.strip()}"
                except Exception as e:
                    error_msg = str(e)
                    if "USER_DEACTIVATED" in error_msg:
                        return False, f"Бан 🔴 - {name.strip()}"
                    if "FLOOD_WAIT" in error_msg:
                        return False, f"Флуд 🟡 - {name.strip()}"
                    return False, f"Ошибка: {error_msg} ⚠️"

            except Exception as e:
                return False, f"Ошибка проверки: {str(e)} ⚠️"

            finally:
                if client and client != active_client:
                    try:
                        await client.disconnect()
                    except:
                        pass

        except Exception as e:
            return False, f"Ошибка: {str(e)} ⚠️"

    async def delete_invalid_accounts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Удаление невалидных аккаунтов"""
        try:
            status_message = await update.callback_query.message.edit_text(
                "🔄 Проверка и удаление невалидных аккаунтов...",
                parse_mode='Markdown'
            )

            accounts = self.account_manager.get_accounts()
            removed = 0
            errors = []

            for phone in accounts[:]:
                try:
                    # Проверяем состояние клиента
                    client = self.account_manager.monitoring_clients.get(phone)
                    is_valid = False

                    if client:
                        try:
                            is_valid = await client.is_user_authorized()
                        except:
                            is_valid = False

                        # Отключаем клиента если он существует
                        try:
                            await client.disconnect()
                        except:
                            pass

                    if not is_valid:
                        # Удаляем из словаря клиентов
                        self.account_manager.monitoring_clients.pop(phone, None)
                        
                        # Удаляем файлы аккаунта
                        account_folder = os.path.join(self.account_manager.bots_folder, phone)
                        if os.path.exists(account_folder):
                            import shutil
                            shutil.rmtree(account_folder)
                            removed += 1
                            self.logger.info(f"Удален невалидный аккаунт: {phone}")

                except Exception as e:
                    self.logger.error(f"Ошибка при удалении аккаунта {phone}: {e}")
                    errors.append(phone)

            message = f"✅ *Удаление невалидных аккаунтов завершено*\n\n"
            message += f"📊 *Результаты:*\n"
            message += f"• Удалено аккаунтов: {removed}\n"
            message += f"• Осталось аккаунтов: {len(accounts) - removed}\n"
            
            if errors:
                message += f"\n⚠️ *Не удалось обработать:*\n"
                message += "\n".join([f"• {phone}" for phone in errors])

            await status_message.edit_text(
                message,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Назад к списку", callback_data='list_accounts')
                ]]),
                parse_mode='Markdown'
            )

            return STATES['MANAGING_ACCOUNTS']

        except Exception as e:
            self.logger.error(f"Ошибка при удалении невалидных аккаунтов: {e}")
            if update.callback_query and update.callback_query.message:
                await update.callback_query.message.edit_text(
                    "❌ Произошла ошибка при удалении невалидных аккаунтов",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("« Назад", callback_data='list_accounts')
                    ]]),
                    parse_mode='Markdown'
                )
            return STATES['MANAGING_ACCOUNTS']

    async def update_invalid_proxies(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обновление невалидных прокси"""
        try:
            status_message = await update.callback_query.message.edit_text(
                "🔄 Проверка и обновление прокси...",
                parse_mode='Markdown'
            )

            accounts = self.account_manager.get_accounts()
            updated = 0
            errors = []
            
            # Получаем список свободных прокси
            available_proxies = await self.account_manager.proxy_manager.get_available_proxies()
            
            if not available_proxies:
                await status_message.edit_text(
                    "❌ Нет доступных прокси для обновления!\n"
                    "Добавьте новые прокси в список.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("« Назад", callback_data='list_accounts')
                    ]]),
                    parse_mode='Markdown'
                )
                return STATES['MANAGING_ACCOUNTS']

            for phone in accounts:
                try:
                    # Проверяем текущую прокси
                    proxy_path = os.path.join(self.account_manager.bots_folder, phone, "proxy.json")
                    
                    with open(proxy_path, 'r', encoding='utf-8') as f:
                        current_proxy = json.load(f)
                    
                    is_valid = await self.account_manager.proxy_manager.check_proxy(current_proxy)
                    
                    if not is_valid:
                        # Получаем новую прокси
                        new_proxy = await self.account_manager.proxy_manager.reserve_proxy()
                        
                        if new_proxy:
                            # Форматируем строку прокси для удаления
                            proxy_str = f"{new_proxy['addr']}:{new_proxy['port']}:{new_proxy['username']}:{new_proxy['password']}"
                            
                            # Читаем текущий список прокси
                            with open(self.account_manager.proxy_manager.proxy_file, 'r') as f:
                                proxies = f.readlines()
                            
                            # Удаляем использованную прокси из списка
                            with open(self.account_manager.proxy_manager.proxy_file, 'w') as f:
                                for proxy in proxies:
                                    if proxy.strip() != proxy_str:
                                        f.write(proxy)
                                        
                            # Сохраняем новую прокси для аккаунта
                            with open(proxy_path, 'w', encoding='utf-8') as f:
                                json.dump(new_proxy, f, indent=4)
                                
                            # Отключаем старый клиент
                            if phone in self.account_manager.monitoring_clients:
                                client = self.account_manager.monitoring_clients[phone]
                                try:
                                    await client.disconnect()
                                except:
                                    pass
                                self.account_manager.monitoring_clients.pop(phone)
                            
                            # Пробуем создать новый клиент
                            try:
                                new_client = await self.account_manager.create_client(phone)
                                if new_client:
                                    # Добавляем в список клиентов
                                    self.account_manager.monitoring_clients[phone] = new_client
                                    self.message_monitor.monitoring_clients[phone] = new_client
                                    
                                    # Инициализируем мониторинг для нового клиента
                                    try:
                                        # Получаем распределенные каналы для этого аккаунта
                                        channels = self.message_monitor.distributor.distribution.get(phone, [])
                                        
                                        # Добавляем обработчик сообщений для каналов
                                        if channels:
                                            new_client.add_event_handler(
                                                self.message_monitor.message_handler,
                                                events.NewMessage(chats=channels)
                                            )
                                        
                                        # Обновляем статистику активных клиентов
                                        self.message_monitor.stats['active_clients'] = len(
                                            [c for c in self.message_monitor.monitoring_clients.values() 
                                             if c and c.is_connected()]
                                        )
                                        
                                    except Exception as e:
                                        self.logger.error(f"Ошибка при инициализации мониторинга для {phone}: {e}")
                                    
                                    self.logger.info(f"Обновлена прокси для {phone}")
                                    updated += 1
                                    
                            except Exception as e:
                                self.logger.error(f"Не удалось создать клиент с новой прокси для {phone}: {e}")
                
                except Exception as e:
                    self.logger.error(f"Ошибка при обновлении прокси для {phone}: {e}")
                    errors.append(phone)

            message = f"✅ *Обновление прокси завершено*\n\n"
            message += f"📊 *Результаты:*\n"
            message += f"• Обновлено прокси: {updated}\n"
            message += f"• Всего аккаунтов: {len(accounts)}\n"
            
            if errors:
                message += f"\n⚠️ *Не удалось обработать:*\n"
                message += "\n".join([f"• {phone}" for phone in errors])
            
            await status_message.edit_text(
                message,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Назад к списку", callback_data='list_accounts')
                ]]),
                parse_mode='Markdown'
            )
            
            return STATES['MANAGING_ACCOUNTS']

        except Exception as e:
            self.logger.error(f"Ошибка при обновлении прокси: {e}")
            await update.callback_query.message.edit_text(
                "❌ Произошла ошибка при обновлении прокси",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Назад", callback_data='list_accounts')
                ]]),
                parse_mode='Markdown'
            )
            return STATES['MANAGING_ACCOUNTS']

            
    async def handle_account_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик callback-ов"""
        query = update.callback_query
        self.logger.info(f"Получен callback: {query.data}")
        await query.answer()

        try:
            if query.data == 'start_account_add':
                return await self.start_account_addition(update, context)
                    
            elif query.data == 'list_accounts':
                return await self.list_accounts(update, context)
                    
            elif query.data == 'remove_invalid':
                return await self.delete_invalid_accounts(update, context)
                    
            elif query.data == 'back_to_monitor':
                if self.monitor_handler:
                    return await self.monitor_handler.show_monitor_menu(update, context)
                return STATES['MONITORING']
                    
            elif query.data == 'back_to_accounts':
                return await self.show_accounts_menu(update, context)
                    
            elif query.data == 'update_invalid_proxies':
                return await self.update_invalid_proxies(update, context)
                
            self.logger.warning(f"Неизвестный callback: {query.data}")
            return STATES['MANAGING_ACCOUNTS']
                    
        except Exception as e:
            self.logger.error(f"Ошибка при обработке callback {query.data}: {e}")
            await update.callback_query.message.edit_text(
                "❌ Произошла ошибка. Попробуйте еще раз.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Назад", callback_data='back_to_accounts')
                ]]),
                parse_mode='Markdown'
            )
            return STATES['MANAGING_ACCOUNTS']

    async def start_account_addition(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса добавления аккаунта"""
        try:
            message = (
                "📱 *Добавление аккаунта Telegram*\n\n"
                "Отправьте следующие файлы:\n"
                "1. .session файл\n"
                "2. .json файл с конфигурацией\n\n"
                "❌ Для отмены отправьте /cancel"
            )

            if update.callback_query:
                await update.callback_query.edit_message_text(
                    message,
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    message,
                    parse_mode='Markdown'
                )

            context.user_data['state'] = STATES['ADDING_ACCOUNT']
            context.user_data['pending_files'] = {}
            
            return STATES['ADDING_ACCOUNT']
            
        except Exception as e:
            self.logger.error(f"Ошибка при начале добавления аккаунта: {e}")
            return STATES['MANAGING_ACCOUNTS']

    async def receive_account_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if 'pending_files' not in context.user_data:
                context.user_data['pending_files'] = {}
                
            if not update.message.document:
                await update.message.reply_text("❌ Пожалуйста, отправьте файл.")
                return STATES['ADDING_ACCOUNT']

            file = await update.message.document.get_file()
            file_name = update.message.document.file_name
            
            if not file_name.endswith(('.session', '.json')):
                await update.message.reply_text(
                    "❌ Неверный формат файла.\n"
                    "Принимаются только .session и .json файлы."
                )
                return STATES['ADDING_ACCOUNT']
            os.makedirs('temp', exist_ok=True)
            file_path = os.path.join('temp', file_name)
            await file.download_to_drive(file_path)

            base_name = file_name.split('.')[0]
            if base_name not in context.user_data['pending_files']:
                context.user_data['pending_files'][base_name] = {}
            
            file_type = 'session' if file_name.endswith('.session') else 'json'
            context.user_data['pending_files'][base_name][file_type] = file_path

            ready_accounts = []
            waiting_files = []
            
            for acc_name, files in context.user_data['pending_files'].items():
                if len(files) == 2:  # Есть оба файла
                    ready_accounts.append(acc_name)
                else:
                    missing = 'session' if 'json' in files else 'json'
                    waiting_files.append(f"{acc_name}.{missing}")

            status = (
                f"✅ Файл {file_name} получен.\n\n"
                "*Статус загрузки:*\n"
            )
            
            if ready_accounts:
                status += "\n*Готовы к добавлению:*\n"
                for acc in ready_accounts:
                    status += f"✅ {acc}\n"
                    
            if waiting_files:
                status += "\n*Ожидают файлов:*\n"
                for file in waiting_files:
                    status += f"⏳ {file}\n"

            status += "\nОтправьте /done для добавления аккаунтов"

            await update.message.reply_text(status, parse_mode='Markdown')

            return STATES['ADDING_ACCOUNT']
            
        except Exception as e:
            logger.error(f"Ошибка при получении файла: {e}")
            await update.message.reply_text("❌ Произошла ошибка при получении файла")
            return STATES['ADDING_ACCOUNT']

    async def finish_account_addition(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Завершение добавления аккаунтов"""
        try:
            if not context.user_data.get('pending_files'):
                await update.message.reply_text("❌ Нет файлов для обработки.")
                return STATES['ADDING_ACCOUNT']

            status_message = await update.message.reply_text(
                "🔄 Начинаем добавление аккаунтов...",
                parse_mode='Markdown'
            )

            results = []
            for base_name, files in context.user_data['pending_files'].items():
                if 'session' in files and 'json' in files:
                    try:
                        await status_message.edit_text(
                            f"🔄 Добавление аккаунта {base_name}...",
                            parse_mode='Markdown'
                        )
                        
                        success = await self.account_manager.import_account(
                            files['session'],
                            files['json']
                        )
                        results.append(f"{'✅' if success else '❌'} Аккаунт {base_name}")
                    except Exception as e:
                        results.append(f"❌ Аккаунт {base_name}: {str(e)}")
                else:
                    results.append(f"❌ Аккаунт {base_name}: не хватает файлов")

            # Очистка временных файлов
            for files in context.user_data['pending_files'].values():
                for file_path in files.values():
                    if os.path.exists(file_path):
                        os.remove(file_path)

            context.user_data.pop('pending_files', None)
            
            # итоговый отчет
            report = "*Результаты добавления аккаунтов:*\n\n"
            report += "\n".join(results)
            
            await status_message.edit_text(
                report,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Назад к меню", callback_data="back_to_accounts")
                ]])
            )
            
            return STATES['MANAGING_ACCOUNTS']
            
        except Exception as e:
            self.logger.error(f"Ошибка при добавлении аккаунтов: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка при добавлении аккаунтов",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Назад", callback_data="back_to_accounts")
                ]]),
                parse_mode='Markdown'
            )
            return STATES['MANAGING_ACCOUNTS']

    def get_handlers(self):
        return [
            self.show_accounts_menu,
            self.handle_account_callback,
            self.add_proxies,
            self.finish_proxy_addition,
            self.list_accounts,
            self.check_proxies,
            self.clear_invalid_proxies,
            self.update_invalid_proxies,  # Добавляем в список обработчиков
            self.delete_invalid_accounts
        ]