import re
import json
import aiohttp
import logging
import os
import asyncio
from aiohttp_socks import ProxyConnector
from typing import Optional, List, Dict, Tuple
from ..config import PROXY_FILE, PROXY_SETTINGS

logger = logging.getLogger(__name__)

class ProxyManager:
    def __init__(self):
        self.proxy_file = PROXY_FILE
        self.test_url = "http://httpbin.org/ip"
        self.test_timeout = PROXY_SETTINGS['check_timeout']
        self.max_concurrent_checks = PROXY_SETTINGS['max_simultaneous_checks']
        self._cached_proxies = []
        self.logger = logger
        self._semaphore = asyncio.Semaphore(self.max_concurrent_checks)
        
        proxy_dir = os.path.dirname(self.proxy_file)
        os.makedirs(proxy_dir, exist_ok=True)
        if not os.path.exists(self.proxy_file):
            with open(self.proxy_file, 'w', encoding='utf-8') as f:
                pass

    def add_proxy(self, proxy_string: str) -> bool:
        try:
            with open(self.proxy_file, 'a', encoding='utf-8') as f:
                f.write(f"{proxy_string}\n")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка при добавлении прокси: {e}")
            return False

    def parse_proxy(self, proxy_string: str) -> Optional[Dict]:
        """Парсинг строки прокси"""
        try:
            proxy_string = proxy_string.strip().split()[0]

            # Формат IP/DOMAIN:PORT:LOGIN:PASSWORD
            match = re.match(r'^([a-zA-Z0-9.-]+):(\d+):([^:]+):(.+)$', proxy_string)
            if match:
                return {
                    'proxy_type': 'socks5',
                    'addr': match.group(1),
                    'port': int(match.group(2)),
                    'username': match.group(3),
                    'password': match.group(4),
                    'rdns': True
                }

            # Формат LOGIN:PASSWORD@IP/DOMAIN:PORT
            match = re.match(r'^([^:]+):([^@]+)@([a-zA-Z0-9.-]+):(\d+)$', proxy_string)
            if match:
                return {
                    'proxy_type': 'socks5',
                    'addr': match.group(3),
                    'port': int(match.group(4)),
                    'username': match.group(1),
                    'password': match.group(2),
                    'rdns': True
                }

            return None
        except Exception as e:
            self.logger.error(f"Ошибка при парсинге прокси {proxy_string}: {e}")
            return None

    async def reserve_proxy(self) -> Optional[Dict]:
        """Получить и зарезервировать прокси"""
        try:
            available_proxies = await self.get_available_proxies()
            if not available_proxies:
                self.logger.warning("Нет доступных прокси")
                return None

            # Берем первую рабочую прокси
            return available_proxies[0]
            
        except Exception as e:
            self.logger.error(f"Ошибка при резервировании прокси: {e}")
            return None

    async def return_proxy(self, proxy: Dict) -> None:
        """Вернуть прокси в пул"""
        try:
            if await self.check_proxy(proxy):
                self.add_proxy(
                    f"{proxy['addr']}:{proxy['port']}:{proxy['username']}:{proxy['password']}"
                )
        except Exception as e:
            self.logger.error(f"Ошибка при возврате прокси: {e}")

    async def check_proxy(self, proxy_config: Dict) -> bool:
        """Асинхронная проверка работоспособности прокси"""
        async with self._semaphore:  # Ограничиваем одновременных проверок
            try:
                proxy_url = f"socks5://{proxy_config['username']}:{proxy_config['password']}@{proxy_config['addr']}:{proxy_config['port']}"
                
                connector = ProxyConnector.from_url(proxy_url)
                timeout = aiohttp.ClientTimeout(total=self.test_timeout)
                
                async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                    async with session.get(self.test_url) as response:
                        if response.status == 200:
                            data = await response.json()
                            return 'origin' in data
                return False
            except Exception as e:
                self.logger.error(f"Ошибка при проверке прокси {proxy_config['addr']}:{proxy_config['port']}: {e}")
                return False

    async def get_available_proxies(self) -> List[Dict]:
        try:
            proxies = []
            with open(self.proxy_file, 'r', encoding='utf-8') as f:
                proxy_strings = [line.strip() for line in f if line.strip()]

            # Создаем список задач для проверки прокси
            tasks = []
            for proxy_string in proxy_strings:
                proxy_config = self.parse_proxy(proxy_string)
                if proxy_config:
                    tasks.append(self.check_proxy(proxy_config))

            # Запускаем проверки параллельно
            if tasks:
                results = await asyncio.gather(*tasks)
                proxies = [
                    config for config, is_valid in zip(
                        [self.parse_proxy(p) for p in proxy_strings],
                        results
                    ) if is_valid
                ]

            self.logger.info(f"Найдено {len(proxies)} рабочих прокси")
            return proxies
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении списка доступных прокси: {e}")
            return []

    async def add_proxies(self, proxy_strings: List[str]) -> Tuple[int, int]:
        added = 0
        failed = 0
        
        try:
            # Парсим все прокси
            proxy_configs = []
            for proxy_string in proxy_strings:
                config = self.parse_proxy(proxy_string)
                if config:
                    proxy_configs.append((proxy_string, config))
                else:
                    failed += 1

            # Проверяем все прокси параллельно
            tasks = [self.check_proxy(config) for _, config in proxy_configs]
            if tasks:
                results = await asyncio.gather(*tasks)

                # Добавляем рабочие прокси в файл
                with open(self.proxy_file, 'a', encoding='utf-8') as f:
                    for (proxy_string, _), is_working in zip(proxy_configs, results):
                        if is_working:
                            f.write(f"{proxy_string}\n")
                            added += 1
                        else:
                            failed += 1

            return added, failed

        except Exception as e:
            self.logger.error(f"Ошибка при массовом добавлении прокси: {e}")
            return added, failed

    async def check_all_proxies(self) -> List[Tuple[Dict, bool]]:
        results = []
        try:
            with open(self.proxy_file, 'r') as f:
                proxy_strings = [line.strip() for line in f if line.strip()]

            proxy_configs = [self.parse_proxy(p) for p in proxy_strings]
            proxy_configs = [p for p in proxy_configs if p]

            # Запускаем проверки параллельно
            tasks = [self.check_proxy(config) for config in proxy_configs]
            if tasks:
                check_results = await asyncio.gather(*tasks)
                results = list(zip(proxy_configs, check_results))

                for config, is_working in results:
                    status = "работает" if is_working else "не работает"
                    self.logger.info(
                        f"Проверка прокси {config['addr']}:{config['port']} - {status}"
                    )

        except Exception as e:
            self.logger.error(f"Ошибка при проверке прокси: {e}")
        
        return results

    async def get_proxy_status(self) -> Dict:
        """Получение статистики прокси"""
        try:
            with open(self.proxy_file, 'r') as f:
                lines = f.readlines()
            
            total = len(lines)
            if not total:
                return {
                    "total": 0,
                    "working": 0,
                    "not_working": 0,
                    "error_rate": 0
                }

            results = await self.check_all_proxies()
            working = sum(1 for _, is_working in results if is_working)
            
            stats = {
                "total": total,
                "working": working,
                "not_working": total - working,
                "error_rate": round((total - working) / total * 100, 2) if total > 0 else 0
            }
            
            self.logger.info(f"Статистика прокси: {stats}")
            return stats
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении статистики прокси: {e}")
            return {
                "total": 0,
                "working": 0,
                "not_working": 0,
                "error_rate": 0
            }

    async def remove_invalid_proxies(self) -> int:
        try:
            results = await self.check_all_proxies()
            valid_proxies = []
            removed = 0

            with open(self.proxy_file, 'r') as f:
                proxy_strings = [line.strip() for line in f if line.strip()]

            # Собираем рабочие прокси
            for proxy_string, (config, is_working) in zip(proxy_strings, results):
                if is_working:
                    valid_proxies.append(proxy_string)
                else:
                    removed += 1

            # Перезаписываем файл только рабочими прокси
            with open(self.proxy_file, 'w') as f:
                for proxy in valid_proxies:
                    f.write(f"{proxy}\n")

            return removed

        except Exception as e:
            self.logger.error(f"Ошибка при удалении невалидных прокси: {e}")
            return 0