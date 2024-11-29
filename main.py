import os
import sys
import asyncio
import logging
import signal
import time
import telegram
import telegram.error
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler, 
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
from project import (
    TelegramMonitorBot, 
    create_bot,
    Config, 
    STATES, 
    BOT_TOKEN, 
    SUPER_ADMIN_USERNAME
)


current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)


# Настройка логирования
logger = logging.getLogger(__name__)
logging.getLogger('apscheduler').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('telethon').setLevel(logging.WARNING)
logging.getLogger('aiohttp').setLevel(logging.WARNING)
logging.getLogger('asyncio').setLevel(logging.WARNING)


logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def setup_application(bot):
    application = (
        Application.builder()
        .token(bot.token)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(30.0)
        .build()
    )

    monitor_handler = bot.handlers['monitor']
    
    # Устанавливаем monitor_handler для всех хендлеров
    bot.handlers['keyword'].set_monitor_handler(monitor_handler)
    bot.handlers['proxy'].set_monitor_handler(monitor_handler)
    bot.handlers['account'].set_monitor_handler(monitor_handler)
    bot.handlers['admin'].set_monitor_handler(monitor_handler)

    await application.bot.set_my_commands([
        ('start', 'Главное меню')
    ])
    
    reply_keyboard = ReplyKeyboardMarkup([
        ['🏠 Главное меню']
    ], resize_keyboard=True)
    
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        try:
            user = update.effective_user
            username = user.username
            chat_id = update.effective_chat.id

            # Проверяем, является ли пользователь супер-админом или обычным админом
            is_super_admin = username == SUPER_ADMIN_USERNAME
            is_admin = await bot.db_manager.is_admin(username)

            if not is_admin and not is_super_admin:
                await update.message.reply_text(
                    "❌ У вас нет доступа к этому боту.\n"
                    "Обратитесь к администратору для получения доступа."
                )
                return ConversationHandler.END

            if is_super_admin:
                await bot.db_manager.save_super_admin_chat_id(chat_id)
                logger.info(f"Обновлен chat_id супер-админа {username}: {chat_id}")
            elif is_admin:
                await bot.db_manager.save_admin_chat_id(username, chat_id)
                logger.info(f"Обновлен chat_id админа {username}: {chat_id}")

            reply_keyboard = ReplyKeyboardMarkup([
                ['🏠 Главное меню']
            ], resize_keyboard=True)

            await update.message.reply_text(
                text="👋 Добро пожаловать в панель управления мониторингом!\n\n"
                     "Используйте кнопки для навигации:",
                reply_markup=reply_keyboard
            )

            return await monitor_handler.show_monitor_menu(update, context)

        except Exception as e:
            logger.error(f"Ошибка при обработке /start: {e}")
            await update.message.reply_text(
                text="Произошла ошибка. Пожалуйста, попробуйте позже."
            )
            return ConversationHandler.END

    async def check_admin_access_and_show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Проверка доступа и показ главного меню"""
        username = update.effective_user.username
        if not await bot.db_manager.is_admin(username):
            await update.message.reply_text(
                "❌ У вас нет доступа к этому боту.\n"
                "Обратитесь к администратору для получения доступа."
            )
            return ConversationHandler.END
        return await monitor_handler.show_monitor_menu(update, context)

    application.add_handler(CommandHandler('start', start))
    
    conversation_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('help', lambda u, c: bot.show_help(u, c)),
            MessageHandler(
                filters.Regex('^🏠 Главное меню$'), 
                check_admin_access_and_show_menu
            ),
            
            CommandHandler('proxies', bot.handlers['proxy'].show_proxy_menu),
            CallbackQueryHandler(bot.handlers['account'].show_accounts_menu, pattern='^manage_accounts$'),
            CallbackQueryHandler(monitor_handler.start_channel_addition, pattern='^add_channel$'),
            CallbackQueryHandler(bot.handlers['proxy'].show_proxy_menu, pattern='^manage_proxies$'),
            CallbackQueryHandler(bot.handlers['keyword'].show_keywords_menu, pattern='^manage_keywords$'),
            CallbackQueryHandler(bot.handlers['admin'].show_admin_menu, pattern='^manage_admins$')
        ],
        states={
            STATES['MANAGING_PROXIES']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                CallbackQueryHandler(
                    bot.handlers['proxy'].handle_proxy_callback,
                    pattern='^(add_proxy|list_proxies|check_proxies|delete_all_proxies|back_to_monitor)$'
                ),
                CommandHandler(
                    'cancel',
                    lambda u, c: bot.handlers['proxy'].show_proxy_menu(u, c)
                )
            ],

            STATES['ADDING_PROXY']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, 
                    bot.handlers['proxy'].add_proxies
                ),
                CommandHandler(
                    'done',
                    bot.handlers['proxy'].finish_proxy_addition
                ),
                CommandHandler(
                    'cancel',
                    lambda u, c: bot.handlers['proxy'].show_proxy_menu(u, c)
                ),
                CallbackQueryHandler(
                    bot.handlers['proxy'].handle_proxy_callback,
                    pattern='^back_to_proxies$'
                )
            ],

            STATES['MANAGING_ACCOUNTS']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                CallbackQueryHandler(
                    bot.handlers['account'].handle_account_callback,
                    pattern='^(list_accounts|start_account_add|remove_invalid|back_to_monitor)$'
                ),
                CommandHandler(
                    'cancel',
                    lambda u, c: monitor_handler.show_monitor_menu(u, c)
                )
            ],

            STATES['ADDING_ACCOUNT']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                MessageHandler(
                    filters.Document.ALL, 
                    bot.handlers['account'].receive_account_file
                ),
                CommandHandler(
                    'done', 
                    bot.handlers['account'].finish_account_addition
                ),
                CommandHandler(
                    'cancel',
                    lambda u, c: bot.handlers['account'].show_accounts_menu(u, c)
                ),
                CallbackQueryHandler(
                    bot.handlers['account'].handle_account_callback,
                    pattern='^.*$'
                )
            ],

            STATES['MANAGING_ADMINS']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                CallbackQueryHandler(
                    bot.handlers['admin'].handle_admin_callback,
                    pattern='^(add_admin|list_admins|remove_admin_.*|back_to_admins|back_to_monitor)$'
                ),
                CommandHandler(
                    'cancel',
                    lambda u, c: bot.handlers['admin'].show_admin_menu(u, c)
                )
            ],

            STATES['ADDING_ADMIN']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    bot.handlers['admin'].add_admin
                ),
                CommandHandler(
                    'cancel',
                    lambda u, c: bot.handlers['admin'].show_admin_menu(u, c)
                ),
                CallbackQueryHandler(
                    bot.handlers['admin'].handle_admin_callback,
                    pattern='^back_to_admins$'
                )
            ],

            STATES['ADDING_CHANNEL']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, 
                    monitor_handler.add_channel
                ),
                CallbackQueryHandler(
                    monitor_handler.handle_monitor_callback,
                    pattern='^back_to_monitor$'
                ),
                CommandHandler(
                    'cancel', 
                    lambda u, c: monitor_handler.show_monitor_menu(u, c)
                )
            ],

            STATES['EDITING_OTHER']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                CallbackQueryHandler(
                    monitor_handler.handle_monitor_callback,
                    pattern='^(change_max_message_length|change_max_keywords|'
                           'change_flood_wait_threshold|change_join_channel_delay|'
                           'change_retry_interval|change_cleanup_interval|'
                           'change_data_retention_days|monitor_settings|back_to_monitor)$'
                ),
                CommandHandler(
                    'cancel',
                    lambda u, c: monitor_handler.show_settings_menu(u, c)
                )
            ],

            STATES['MANAGING_CHANNELS']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                CallbackQueryHandler(
                    monitor_handler.handle_monitor_callback,
                    pattern='^(delete_channel_|confirm_delete_all|delete_channels_menu|list_channels).*$'
                ),
                CommandHandler(
                    'cancel',
                    lambda u, c: monitor_handler.show_monitor_menu(u, c)
                )
            ],

            STATES['MANAGING_KEYWORDS']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                CallbackQueryHandler(
                    bot.handlers['keyword'].handle_keyword_callback,
                    pattern='^(add_keyword|list_keywords|keyword_stats|import_keywords|export_keywords|back_to_keywords|back_to_monitor|delete_keyword_.*)$'
                ),
                CommandHandler(
                    'cancel',
                    lambda u, c: bot.handlers['keyword'].show_keywords_menu(u, c)
                )
            ],

            STATES['ADDING_KEYWORD']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, 
                    bot.handlers['keyword'].add_keywords
                ),
                CommandHandler(
                    'done',
                    bot.handlers['keyword'].finish_keyword_addition
                ),
                CommandHandler(
                    'cancel',
                    lambda u, c: bot.handlers['keyword'].show_keywords_menu(u, c)
                )
            ],

            STATES['MONITORING']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                CallbackQueryHandler(
                    monitor_handler.handle_monitor_callback,
                    pattern='^(toggle_monitoring|add_channel|list_channels|check_channels|monitor_stats|monitor_settings|manage_accounts|manage_proxies|manage_keywords|manage_admins|back_to_monitor|delete_channels_menu)$'
                ),
                CommandHandler('menu', lambda u, c: monitor_handler.show_monitor_menu(u, c))
            ],

            STATES['SETTINGS_MENU']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                CallbackQueryHandler(
                    monitor_handler.handle_monitor_callback,
                    pattern='^(edit_notifications|edit_performance|edit_autorestart|'
                           'edit_timeouts|edit_other|back_to_monitor)$'  # Добавили edit_other
                ),
                CommandHandler(
                    'cancel',
                    lambda u, c: monitor_handler.show_monitor_menu(u, c)
                )
            ],

            STATES['EDITING_NOTIFICATIONS']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                CallbackQueryHandler(
                    monitor_handler.handle_monitor_callback,
                    pattern='^(change_notification_chunk_size|change_message_processing_timeout|monitor_settings|back_to_monitor)$'
                ),
                CommandHandler(
                    'cancel',
                    lambda u, c: monitor_handler.show_settings_menu(u, c)
                )
            ],

            STATES['EDITING_PERFORMANCE']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                CallbackQueryHandler(
                    monitor_handler.handle_monitor_callback,
                    pattern='^(change_check_interval|change_max_channels_per_client|monitor_settings|back_to_monitor)$'
                ),
                CommandHandler(
                    'cancel',
                    lambda u, c: monitor_handler.show_settings_menu(u, c)
                )
            ],

            STATES['EDITING_AUTORESTART']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                CallbackQueryHandler(
                    monitor_handler.handle_monitor_callback,
                    pattern='^(toggle_autorestart|change_restart_delay|change_max_errors|monitor_settings|back_to_monitor)$'
                ),
                CommandHandler(
                    'cancel',
                    lambda u, c: monitor_handler.show_settings_menu(u, c)
                )
            ],

            STATES['SETTINGS_MENU']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                CallbackQueryHandler(
                    monitor_handler.handle_monitor_callback,
                    pattern='^(edit_notifications|edit_performance|edit_autorestart|edit_timeouts|back_to_monitor)$'
                )
            ],
            
            STATES['ENTERING_VALUE']: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    monitor_handler.save_setting_value
                ),
                CommandHandler(
                    'cancel',
                    lambda u, c: monitor_handler.show_settings_menu(u, c)
                )
            ],

            STATES['EDITING_TIMEOUTS']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                CallbackQueryHandler(
                    monitor_handler.handle_monitor_callback,
                    pattern='^(change_join_timeout|change_message_timeout|back_to_monitor|monitor_settings)$'
                ),
                CommandHandler(
                    'cancel',
                    lambda u, c: monitor_handler.show_settings_menu(u, c)
                )
            ],

            STATES['CONFIRMING_DELETE']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                CallbackQueryHandler(
                    monitor_handler.handle_monitor_callback,
                    pattern='^(confirm_delete|cancel_delete|back_to_monitor)$'
                )
            ],
            
            STATES['IMPORTING_KEYWORDS']: [
                MessageHandler(
                    filters.Regex('^🏠 Главное меню$'),
                    check_admin_access_and_show_menu
                ),
                
                MessageHandler(filters.Document.ALL, bot.handlers['keyword'].import_keywords),
                CommandHandler('cancel', lambda u, c: bot.handlers['keyword'].show_keywords_menu(u, c))
            ]
        },
        fallbacks=[
            CommandHandler(
                'start',
                start
            ),
            CommandHandler(
                'help',
                lambda u, c: bot.show_help(u, c)
            ),
            CommandHandler(
                'cancel',
                lambda u, c: monitor_handler.show_monitor_menu(u, c)
            ),
            MessageHandler(
                filters.Regex('^🏠 Главное меню$'),
                check_admin_access_and_show_menu
            ),
            CallbackQueryHandler(
                lambda u, c: monitor_handler.show_monitor_menu(u, c),
                pattern='^back_to_monitor$'
            ),
            CallbackQueryHandler(
                bot.handlers['proxy'].show_proxy_menu,
                pattern='^back_to_proxies$'
            ),
            CallbackQueryHandler(
                monitor_handler.show_settings_menu,
                pattern='^back_to_settings$'
            ),
            CallbackQueryHandler(
                bot.handlers['admin'].show_admin_menu,
                pattern='^back_to_admins$'
            ),
        ],
        name='main_conversation',
        persistent=False,
        allow_reentry=True,
    )


    application.add_handler(conversation_handler)

    application.add_handler(
        MessageHandler(
            filters.COMMAND,
            lambda u, c: u.message.reply_text(
                "❌ Неизвестная команда. Используйте /help для просмотра списка команд."
            )
        )
    )
    
    application.add_error_handler(
        lambda update, context: logger.error(
            f"Ошибка при обработке обновления {update}: {context.error}",
            exc_info=context.error
        )
    )
    
    return application

def create_bot():
    """Создание экземпляра бота"""
    try:
        if not BOT_TOKEN:
            raise ValueError("Не указан BOT_TOKEN")
            
        return TelegramMonitorBot(bot_token=BOT_TOKEN)
        
    except Exception as e:
        logger.error(f"Ошибка при создании бота: {e}", exc_info=True)
        raise

async def main():
    max_retries = 3
    retry_delay = 5
    
    for attempt in range(max_retries):
        bot = None
        application = None
        
        try:
            bot = create_bot()
            application = await setup_application(bot)
            
            async with application:
                await application.initialize()
                await application.start()

                try:
                    # Базовая инициализация
                    await bot.start()
                    await bot.message_monitor.initialize(application)
                    
                    # Проверяем наличие аккаунтов
                    accounts = bot.account_manager.get_accounts()
                    if accounts:
                        await bot.message_monitor.initialize_clients()
                        await asyncio.sleep(3)
                        await bot.message_monitor.start_monitoring()
                    else:
                        logger.info("Бот запущен в режиме без мониторинга (нет аккаунтов)")
                    
                except Exception as e:
                    logger.error(f"Ошибка при запуске компонентов бота: {e}")
                    if "Не удалось инициализировать клиентов" not in str(e):
                        raise

                print("Бот запущен. Нажмите Ctrl+C для остановки.")

                await application.updater.start_polling(
                    timeout=30,
                    read_timeout=30,
                    write_timeout=30,
                    connect_timeout=30,
                    pool_timeout=30,
                    drop_pending_updates=True
                )
                
                try:
                    status_check_interval = 60
                    last_check_time = time.time()
                    
                    while True:
                        await asyncio.sleep(1)

                        current_time = time.time()
                        if current_time - last_check_time >= status_check_interval:
                            current_accounts = bot.account_manager.get_accounts()
                            if current_accounts:  # Проверяем статус только если есть аккаунты
                                if not await bot.check_status():
                                    logger.warning("Обнаружены проблемы с компонентами")
                                    recovery_attempts = 3
                                    for _ in range(recovery_attempts):
                                        await asyncio.sleep(10)
                                        if await bot.check_status():
                                            logger.info("Система восстановилась")
                                            break
                                    else:
                                        logger.error("Система не смогла восстановиться, требуется перезапуск")
                                        raise Exception("Component failure detected")
                            last_check_time = current_time
                            
                except asyncio.CancelledError:
                    logger.info("Получен сигнал остановки")
                except KeyboardInterrupt:
                    logger.info("Получена команда остановки от пользователя")
                finally:
                    logger.info("Начало процесса завершения работы")
                    try:
                        if bot and bot.message_monitor:
                            await bot.message_monitor.stop_monitoring()
                        if bot:
                            await bot.stop()
                        if application and application.updater:
                            await application.updater.stop()
                        if application:
                            await application.stop()
                            await application.shutdown()
                    except Exception as e:
                        logger.error(f"Ошибка при завершении работы: {e}")
                        
            break
            
        except telegram.error.TimedOut:
            if attempt < max_retries - 1:
                logger.warning(f"Таймаут подключения, повторная попытка через {retry_delay} секунд...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error("Превышено максимальное количество попыток подключения")
                raise
                
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}", exc_info=True)
            if attempt < max_retries - 1:
                logger.warning(f"Повторная попытка через {retry_delay} секунд...")
                if bot:
                    try:
                        await bot.stop()
                    except:
                        pass
                if application:
                    try:
                        await application.stop()
                        await application.shutdown()
                    except:
                        pass
                await asyncio.sleep(retry_delay)
            else:
                raise

async def cleanup():
    """Очистка ресурсов"""
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

def run_bot():
    """Запуск бота"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(main())
        except KeyboardInterrupt:
            logger.info("Программа остановлена пользователем")
            loop.run_until_complete(cleanup())
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}", exc_info=True)
            loop.run_until_complete(cleanup())
            
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
        except Exception as e:
            logger.error(f"Ошибка при закрытии event loop: {e}")

if __name__ == "__main__":
    run_bot()