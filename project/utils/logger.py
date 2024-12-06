import os
import sys
import logging
import logging.handlers
from datetime import datetime
from typing import Optional
from pathlib import Path
import traceback
import json
from functools import wraps
import time
from ..config import LOGS_DIR, LOGGING_CONFIG

class ColoredFormatter(logging.Formatter):
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    blue = "\x1b[34;20m"
    green = "\x1b[32;20m"
    reset = "\x1b[0m"

    COLORS = {
        logging.DEBUG: grey,
        logging.INFO: green,
        logging.WARNING: yellow,
        logging.ERROR: red,
        logging.CRITICAL: bold_red,
    }

    def __init__(self, fmt: str):
        super().__init__()
        self.fmt = fmt

    def format(self, record: logging.LogRecord) -> str:
        if not record.exc_info:
            level_color = self.COLORS.get(record.levelno)
            record.levelname = f"{level_color}{record.levelname}{self.reset}"
            record.msg = f"{level_color}{record.msg}{self.reset}"
        return logging.Formatter(self.fmt).format(record)

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            'timestamp': self.formatTime(record),
            'level': record.levelname,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        if record.exc_info:
            exc_type = record.exc_info[0]
            if exc_type:
                log_data['exception'] = {
                    'type': exc_type.__name__,
                    'message': str(record.exc_info[1]),
                    'traceback': traceback.format_exception(*record.exc_info)
                }
                
        if hasattr(record, 'extra_data'):
            log_data['extra'] = record.extra_data
            
        return json.dumps(log_data, ensure_ascii=False)

class AsyncLogger(logging.Logger):
    def __init__(self, name: str, level: int = logging.NOTSET):
        super().__init__(name, level)
        self.metrics = {
            'errors': 0,
            'warnings': 0,
            'start_time': time.time()
        }

    def log_with_extra(self, level: int, msg: str, extra_data: dict = None, *args, **kwargs):
        if extra_data:
            extra = {'extra_data': extra_data}
            kwargs['extra'] = extra
        self.log(level, msg, *args, **kwargs)

    def get_metrics(self) -> dict:
        uptime = time.time() - self.metrics['start_time']
        return {
            'errors': self.metrics['errors'],
            'warnings': self.metrics['warnings'],
            'uptime': uptime,
            'errors_per_hour': (self.metrics['errors'] / uptime) * 3600 if uptime > 0 else 0
        }

def setup_logger(name: Optional[str] = None) -> AsyncLogger:
    # Регистрируем новый класс логгера
    logging.setLoggerClass(AsyncLogger)
    
    # Создаем логгер
    logger = logging.getLogger(name or __name__)
    logger.setLevel(logging.DEBUG)

    # Очищаем существующие обработчики
    logger.handlers.clear()

    # Создаем директорию для логов если её нет
    os.makedirs(LOGS_DIR, exist_ok=True)

    # Консольный обработчик с цветной подсветкой
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = "%(asctime)s - %(levelname)s - %(message)s"
    console_handler.setFormatter(ColoredFormatter(console_format))
    logger.addHandler(console_handler)

    # Файловый обработчик для всех логов
    file_handler = logging.handlers.RotatingFileHandler(
        filename=os.path.join(LOGS_DIR, 'monitor.log'),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JsonFormatter())
    logger.addHandler(file_handler)

    # Файловый обработчик только для ошибок
    error_handler = logging.handlers.RotatingFileHandler(
        filename=os.path.join(LOGS_DIR, 'error.log'),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(JsonFormatter())
    logger.addHandler(error_handler)

    return logger

def log_async_errors(logger: logging.Logger):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.error(
                    f"Error in {func.__name__}: {str(e)}",
                    exc_info=True,
                    extra={
                        'function': func.__name__,
                        'args': str(args),
                        'kwargs': str(kwargs)
                    }
                )
                raise
        return wrapper
    return decorator

class LoggerManager:
    """Менеджер логгеров для централизованного управления"""
    
    _loggers = {}

    @classmethod
    def get_logger(cls, name: str) -> AsyncLogger:
        if name not in cls._loggers:
            cls._loggers[name] = setup_logger(name)
        return cls._loggers[name]

    @classmethod
    def get_all_metrics(cls) -> dict:
        return {name: logger.get_metrics() for name, logger in cls._loggers.items()}

def cleanup_old_logs(days: int = 30):
    try:
        current_time = time.time()
        for filename in os.listdir(LOGS_DIR):
            filepath = os.path.join(LOGS_DIR, filename)
            if os.path.isfile(filepath):
                file_time = os.path.getmtime(filepath)
                if (current_time - file_time) > (days * 86400):
                    os.remove(filepath)
    except Exception as e:
        logger = setup_logger('cleanup')
        logger.error(f"Error cleaning old logs: {e}")