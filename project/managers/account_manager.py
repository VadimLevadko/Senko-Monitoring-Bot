import os
import json
import shutil
import logging
import asyncio
from telethon import TelegramClient
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty
from typing import Tuple, Optional, List, Dict
from datetime import datetime
from ..config import BOTS_FOLDER

logger = logging.getLogger(__name__)

class AccountManager:
    def __init__(self, bots_folder: str, proxy_manager=None):
        if not proxy_manager:
            raise ValueError("ProxyManager должен быть предоставлен")
            
        self.bots_folder = bots_folder
        self.proxy_manager = proxy_manager
        self.logger = logging.getLogger(__name__)
        self.locks = {}  # Словарь для блокировок
        self.monitoring_clients = {}  # Словарь для клиентов
        os.makedirs(self.bots_folder, exist_ok=True)

    async def import_account(self, session_path: str, json_path: str) -> Tuple[bool, str]:
        """Импорт нового аккаунта"""
        client = None
        used_proxy = None
        try:
            self.logger.info(f"Начало импорта аккаунта. Session: {session_path}, JSON: {json_path}")
            
            # Проверяем файлы
            if not os.path.exists(session_path):
                self.logger.error(f"Файл session не найден: {session_path}")
                return False, "Session файл не найден"
            if not os.path.exists(json_path):
                self.logger.error(f"Файл JSON не найден: {json_path}")
                return False, "JSON файл не найден"

            # Загружаем конфигурацию
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.logger.info(f"JSON конфигурация загружена: {json.dumps(config, indent=2)}")
            except json.JSONDecodeError as e:
                self.logger.error(f"Ошибка парсинга JSON: {e}")
                return False, "Неверный формат JSON файла"
            except Exception as e:
                self.logger.error(f"Ошибка чтения JSON: {e}")
                return False, "Ошибка чтения JSON файла"

            # Получаем api_id и api_hash
            api_id = config.get('app_id') or config.get('api_id')
            api_hash = config.get('app_hash') or config.get('api_hash')
            
            if not api_id or not api_hash:
                self.logger.error("Отсутствуют обязательные поля в JSON")
                return False, "Отсутствуют api_id/api_hash в JSON файле"

            # Получаем прокси
            proxy = await self.proxy_manager.reserve_proxy()
            if not proxy:
                self.logger.error("Не удалось получить прокси")
                return False, "Нет доступных прокси"
                
            used_proxy = proxy
            self.logger.info(f"Создаем тестовый клиент с прокси: {proxy}")

            # Создаем тестовый клиент
            client = TelegramClient(
                session_path,
                api_id,
                api_hash,
                proxy=proxy,
                device_model=config.get('device', 'Desktop'),
                system_version=config.get('sdk', 'Windows 10'),
                app_version=config.get('app_version', '1.0'),
                lang_code=config.get('lang_code', 'ru')
            )

            # Пробуем подключиться и авторизоваться
            try:
                self.logger.info("Подключаемся к Telegram...")
                await client.connect()
                
                if not await client.is_user_authorized():
                    self.logger.error("Аккаунт не авторизован")
                    return False, "Аккаунт не авторизован"

                me = await client.get_me()
                if not me:
                    self.logger.error("Не удалось получить информацию о пользователе")
                    return False, "Не удалось получить информацию о пользователе"

                self.logger.info(f"Успешная авторизация: {me.phone}")

                # Сохраняем файлы
                phone = str(me.phone)
                account_folder = os.path.join(self.bots_folder, phone)
                os.makedirs(account_folder, exist_ok=True)

                self.logger.info(f"Копируем файлы в {account_folder}")
                
                shutil.copy2(session_path, os.path.join(account_folder, f"{phone}.session"))
                
                config.update({
                    'phone': phone,
                    'username': me.username,
                    'first_name': me.first_name,
                    'last_name': me.last_name,
                    'last_check_time': int(datetime.now().timestamp())
                })
                
                with open(os.path.join(account_folder, f"{phone}.json"), 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=4, ensure_ascii=False)
                    
                with open(os.path.join(account_folder, "proxy.json"), 'w', encoding='utf-8') as f:
                    json.dump(proxy, f, indent=4, ensure_ascii=False)

                # Форматируем строку прокси для удаления
                proxy_string = f"{proxy['addr']}:{proxy['port']}:{proxy['username']}:{proxy['password']}"
                
                # Удаляем использованную прокси из файла прокси
                with open(self.proxy_manager.proxy_file, 'r') as f:
                    proxies = f.readlines()
                
                with open(self.proxy_manager.proxy_file, 'w') as f:
                    for p in proxies:
                        if p.strip() != proxy_string:
                            f.write(p)

                self.logger.info(f"Аккаунт {phone} успешно импортирован, прокси {proxy_string} удалена из списка")
                return True, f"Аккаунт {phone} успешно импортирован"

            except Exception as e:
                self.logger.error(f"Ошибка при проверке аккаунта: {str(e)}")
                return False, f"Ошибка при проверке аккаунта: {str(e)}"

        finally:
            if client:
                try:
                    await client.disconnect()
                except:
                    pass

    async def create_client(self, phone: str) -> Optional[TelegramClient]:
        """Создание клиента Telegram"""
        try:
            account_folder = os.path.join(self.bots_folder, phone)
            self.logger.info(f"Проверка файлов для аккаунта {phone} в папке {account_folder}")

            json_file = os.path.join(account_folder, f"{phone}.json")
            proxy_file = os.path.join(account_folder, "proxy.json")
            session_path = os.path.join(account_folder, f"{phone}.session")

            if not os.path.exists(json_file):
                self.logger.error(f"❌ JSON файл не найден: {json_file}")
                return None
            if not os.path.exists(proxy_file):
                self.logger.error(f"❌ Proxy файл не найден: {proxy_file}")
                return None
            if not os.path.exists(session_path):
                self.logger.error(f"❌ Session файл не найден: {session_path}")
                return None

            # Загружаем и проверяем конфигурацию
            with open(json_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # Выводим конфиг без чувствительных данных
                safe_config = config.copy()
                if 'app_hash' in safe_config:
                    safe_config['app_hash'] = safe_config['app_hash'][:8] + '...'
                self.logger.info(f"📱 Конфигурация аккаунта {phone}: {json.dumps(safe_config, indent=2, ensure_ascii=False)}")

            with open(proxy_file, 'r', encoding='utf-8') as f:
                proxy = json.load(f)
                safe_proxy = proxy.copy()
                if 'password' in safe_proxy:
                    safe_proxy['password'] = '***'
                self.logger.info(f"🔒 Прокси для {phone}: {json.dumps(safe_proxy, indent=2, ensure_ascii=False)}")

            # Проверяем api_id и api_hash
            api_id = config.get('app_id') or config.get('api_id')
            api_hash = config.get('app_hash') or config.get('api_hash')

            if not api_id or not api_hash:
                self.logger.error(f"❌ Отсутствует api_id или api_hash для {phone}")
                return None

            self.logger.info(f"✅ Все необходимые файлы и данные найдены для {phone}")

            # Создаем клиент
            self.logger.info(f"🔄 Создание клиента Telethon для {phone}")
            client = TelegramClient(
                session_path,
                int(api_id),
                api_hash,
                proxy=proxy,
                device_model=config.get('device', 'Desktop'),
                system_version=config.get('sdk', 'Windows 10'),
                app_version=config.get('app_version', '1.0'),
                lang_code=config.get('lang_code', 'ru'),
                connection_retries=3
            )

            try:
                self.logger.info(f"🔄 Подключение клиента {phone}...")
                await client.connect()
                self.logger.info(f"✅ Подключение установлено для {phone}")

                if not await client.is_user_authorized():
                    self.logger.error(f"❌ Клиент {phone} не авторизован. Проблема с сессией.")
                    # Проверяем session файл
                    session_size = os.path.getsize(session_path)
                    self.logger.info(f"📊 Размер session файла: {session_size} байт")
                    await client.disconnect()
                    return None

                me = await client.get_me()
                if not me:
                    self.logger.error(f"❌ Не удалось получить информацию о пользователе {phone}")
                    await client.disconnect()
                    return None

                self.logger.info(f"✅ Успешная авторизация {phone}: username={me.username}, phone={me.phone}")
                return client

            except Exception as e:
                self.logger.error(f"❌ Ошибка при подключении {phone}: {str(e)}")
                if client.is_connected():
                    await client.disconnect()
                return None

        except Exception as e:
            self.logger.error(f"❌ Критическая ошибка при создании клиента {phone}: {str(e)}")
            return None

    async def delete_account(self, phone: str) -> bool:
        """Удаление аккаунта"""
        try:
            account_folder = os.path.join(self.bots_folder, phone)
            if os.path.exists(account_folder):
                # Отключаем клиент если он существует
                if phone in self.monitoring_clients:
                    client = self.monitoring_clients[phone]
                    try:
                        if client.is_connected():
                            await client.disconnect()
                    except:
                        pass
                    self.monitoring_clients.pop(phone)

                # Удаляем папку с файлами
                shutil.rmtree(account_folder)
                self.logger.info(f"Удален аккаунт {phone}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Ошибка при удалении аккаунта {phone}: {e}")
            return False

    async def check_account(self, phone: str) -> Tuple[bool, str]:
        client = None
        try:
            client = await self.create_client(phone)
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
                    return True, f"Онлайн 🟢 - {name.strip()}"
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
            if client:
                try:
                    await client.disconnect()
                except:
                    pass

    def get_accounts(self) -> List[str]:
        """Получение списка аккаунтов"""
        try:
            accounts = []
            for item in os.listdir(self.bots_folder):
                folder_path = os.path.join(self.bots_folder, item)
                if os.path.isdir(folder_path):
                    json_path = os.path.join(folder_path, f"{item}.json")
                    session_path = os.path.join(folder_path, f"{item}.session")
                    # Проверяем наличие необходимых файлов
                    if os.path.exists(json_path) and os.path.exists(session_path):
                        accounts.append(item)
            return accounts
        except Exception as e:
            self.logger.error(f"Ошибка при получении списка аккаунтов: {e}")
            return []
            
    async def disconnect_all(self) -> None:
        try:
            accounts = self.get_accounts()
            for phone in accounts:
                try:
                    client = self.monitoring_clients.get(phone)
                    if client:
                        try:
                            if client.is_connected():
                                await client.disconnect()
                                self.logger.info(f"Отключен клиент {phone}")
                        except Exception as e:
                            self.logger.error(f"Ошибка при отключении клиента {phone}: {e}")
                        finally:
                            self.monitoring_clients.pop(phone, None)
                except Exception as e:
                    self.logger.error(f"Ошибка при обработке отключения аккаунта {phone}: {e}")

        except Exception as e:
            self.logger.error(f"Ошибка при отключении всех аккаунтов: {e}")
        finally:
            self.monitoring_clients.clear()

    def get_account_info(self, phone: str) -> Optional[Dict]:
        try:
            json_path = os.path.join(self.bots_folder, phone, f"{phone}.json")
            if os.path.exists(json_path):
                with open(json_path, 'r', encoding='utf-8') as f:
                    info = json.load(f)
                    if 'app_hash' in info:
                        info['app_hash'] = info['app_hash'][:8] + '...'
                    if 'api_hash' in info:
                        info['api_hash'] = info['api_hash'][:8] + '...'
                    return info
            return None
        except Exception as e:
            self.logger.error(f"Ошибка при получении информации об аккаунте {phone}: {e}")
            return None

    async def update_account_proxy(self, phone: str, new_proxy: Dict) -> bool:
        """Обновление прокси для аккаунта"""
        try:
            proxy_path = os.path.join(self.bots_folder, phone, "proxy.json")
            
            # Сохраняем новую прокси
            with open(proxy_path, 'w', encoding='utf-8') as f:
                json.dump(new_proxy, f, indent=4)

            # Пересоздаем клиент с новой прокси
            if phone in self.monitoring_clients:
                old_client = self.monitoring_clients[phone]
                try:
                    if old_client.is_connected():
                        await old_client.disconnect()
                except:
                    pass
                self.monitoring_clients.pop(phone)

            # Создаем новый клиент
            new_client = await self.create_client(phone)
            if new_client:
                self.monitoring_clients[phone] = new_client
                self.logger.info(f"Обновлена прокси для аккаунта {phone}")
                return True

            return False

        except Exception as e:
            self.logger.error(f"Ошибка при обновлении прокси для аккаунта {phone}: {e}")
            return False

    def get_active_clients_count(self) -> int:
        return len(self.monitoring_clients)

    async def check_all_accounts(self) -> Dict[str, bool]:
        """Проверка всех аккаунтов"""
        results = {}
        try:
            accounts = self.get_accounts()
            for phone in accounts:
                is_working, status = await self.check_account(phone)
                results[phone] = is_working
                self.logger.info(f"Аккаунт {phone}: {'работает' if is_working else 'не работает'} ({status})")
        except Exception as e:
            self.logger.error(f"Ошибка при проверке аккаунтов: {e}")
        return results

    async def get_stats(self) -> Dict:
        """Получение статистики по аккаунтам"""
        try:
            accounts = self.get_accounts()
            active_accounts = 0
            total_accounts = len(accounts)
            
            for phone in accounts:
                if phone in self.monitoring_clients:
                    client = self.monitoring_clients[phone]
                    try:
                        if client.is_connected() and await client.is_user_authorized():
                            active_accounts += 1
                    except:
                        pass

            return {
                'total_accounts': total_accounts,
                'active_accounts': active_accounts,
                'inactive_accounts': total_accounts - active_accounts,
                'active_percentage': round((active_accounts / total_accounts * 100) if total_accounts > 0 else 0, 2)
            }

        except Exception as e:
            self.logger.error(f"Ошибка при получении статистики аккаунтов: {e}")
            return {
                'total_accounts': 0,
                'active_accounts': 0,
                'inactive_accounts': 0,
                'active_percentage': 0
            }

    async def cleanup(self):
        """Очистка ресурсов"""
        try:
            # Отключаем все клиенты
            await self.disconnect_all()

            self.monitoring_clients.clear()
            self.locks.clear()
            self.logger.info("Ресурсы менеджера аккаунтов очищены")
            
        except Exception as e:
            self.logger.error(f"Ошибка при очистке ресурсов: {e}")