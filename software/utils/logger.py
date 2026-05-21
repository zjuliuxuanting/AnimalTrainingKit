"""
日志工具模块

提供全局日志记录功能，支持控制台和文件输出，按天分割日志文件。
"""

import os
import sys
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
from typing import Optional
import platform


class ColoredFormatter(logging.Formatter):
    """带颜色的日志格式化器（控制台用）"""
    
    COLORS = {
        'DEBUG': '\033[36m',     # 青色
        'INFO': '\033[32m',      # 绿色
        'WARNING': '\033[33m',   # 黄色
        'ERROR': '\033[31m',     # 红色
        'CRITICAL': '\033[35m',  # 紫色
    }
    RESET = '\033[0m'
    
    def __init__(self, fmt: str, datefmt: str = None, use_color: bool = True):
        super().__init__(fmt, datefmt)
        self._use_color = use_color and self._supports_color()
    
    @staticmethod
    def _supports_color() -> bool:
        if platform.system() == "Windows":
            return sys.stdout.isatty()
        return True
    
    def format(self, record: logging.LogRecord) -> str:
        if self._use_color and record.levelname in self.COLORS:
            record.levelname = f"{self.COLORS[record.levelname]}{record.levelname}{self.RESET}"
        return super().format(record)


class LoggerManager:
    """日志管理器"""
    
    _instance: Optional['LoggerManager'] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._logger: Optional[logging.Logger] = None
        self._log_dir: Optional[str] = None
        self._file_handler: Optional[TimedRotatingFileHandler] = None
        self._console_handler: Optional[logging.StreamHandler] = None
    
    def setup(self, log_dir: str, level: int = logging.INFO, 
              console_output: bool = True) -> logging.Logger:
        """
        初始化日志系统
        
        Args:
            log_dir: 日志文件目录
            level: 日志级别
            console_output: 是否输出到控制台
            
        Returns:
            配置好的Logger实例
        """
        self._log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        
        self._logger = logging.getLogger("BehaviorBox")
        self._logger.setLevel(level)
        self._logger.handlers.clear()
        
        log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        date_format = "%Y-%m-%d %H:%M:%S"
        
        log_file = os.path.join(log_dir, "behavior_box.log")
        self._file_handler = TimedRotatingFileHandler(
            log_file,
            when='midnight',
            interval=1,
            backupCount=7,
            encoding='utf-8'
        )
        self._file_handler.setLevel(level)
        self._file_handler.setFormatter(logging.Formatter(log_format, date_format))
        self._logger.addHandler(self._file_handler)
        
        if console_output:
            self._console_handler = logging.StreamHandler(sys.stdout)
            self._console_handler.setLevel(level)
            self._console_handler.setFormatter(ColoredFormatter(log_format, date_format))
            self._logger.addHandler(self._console_handler)
        
        return self._logger
    
    def get_logger(self) -> logging.Logger:
        """获取Logger实例"""
        if self._logger is None:
            self.setup(
                log_dir=os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs"),
                level=logging.INFO
            )
        return self._logger
    
    def set_level(self, level: int):
        """设置日志级别"""
        if self._logger:
            self._logger.setLevel(level)
        if self._file_handler:
            self._file_handler.setLevel(level)
        if self._console_handler:
            self._console_handler.setLevel(level)
    
    def close(self):
        """关闭日志处理器"""
        if self._file_handler:
            self._file_handler.close()
        if self._console_handler:
            self._console_handler.close()
        if self._logger:
            for handler in self._logger.handlers[:]:
                handler.close()
                self._logger.removeHandler(handler)


def setup_logger(log_dir: str = None, level: int = logging.INFO, 
                 console_output: bool = True) -> logging.Logger:
    """
    初始化全局日志系统
    
    Args:
        log_dir: 日志文件目录，默认为项目根目录下的logs文件夹
        level: 日志级别，默认INFO
        console_output: 是否输出到控制台，默认True
        
    Returns:
        配置好的Logger实例
    """
    if log_dir is None:
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    
    manager = LoggerManager()
    return manager.setup(log_dir, level, console_output)


def get_logger() -> logging.Logger:
    """获取全局Logger实例"""
    return LoggerManager().get_logger()


def set_log_level(level: int):
    """设置全局日志级别"""
    LoggerManager().set_level(level)


def close_logger():
    """关闭日志系统"""
    LoggerManager().close()


if __name__ == "__main__":
    logger = setup_logger(level=logging.DEBUG)
    
    logger.debug("调试信息")
    logger.info("普通信息")
    logger.warning("警告信息")
    logger.error("错误信息")
    logger.critical("严重错误")
    
    close_logger()
    print("日志测试完成")
