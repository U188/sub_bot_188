# config.py
import os
from dataclasses import dataclass
from typing import List, Dict

@dataclass
class Config:
    # Bot配置
    BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN', '')
    
    # 文件路径
    PROXIES_FILE: str = "all_proxies.txt"
    CONFIG_FILE: str = "bot_config.json"
    UPLOAD_DIR: str = "uploads"
    SOURCE_CONFIG_FILE = 'data/proxy_sources.json'  # 使用 JSON 格式存储，方便 dataclass 序列化
    # 权限配置
    ADMIN_IDS: List[int] = None
    PERMISSION_LEVELS: Dict[str, int] = None
    
    # 扫描配置
    DEFAULT_CHECK_COUNT: int = 2000
    DEFAULT_PASSWORDS: List[str] = None
    REQUEST_TIMEOUT: int = 5
    
    # UI配置
    NODES_PER_PAGE: int = 10
    RATE_LIMIT_SECONDS: int = 5
    
    def __post_init__(self):
        if self.ADMIN_IDS is None:
            self.ADMIN_IDS = [7387265533]
        
        if self.PERMISSION_LEVELS is None:
            self.PERMISSION_LEVELS = {
                'banned': 0,
                'guest': 1,
                'user': 2,
                'admin': 3
            }
        
        if self.DEFAULT_PASSWORDS is None:
            self.DEFAULT_PASSWORDS = ["admin", "123456"]
        
        # 确保上传目录存在
        os.makedirs(self.UPLOAD_DIR, exist_ok=True)

# 全局配置实例
config = Config()

# 常量定义
class States:
    IDLE = 'idle'
    SCAN_XUI = 'scan_xui'
    SCAN_OLLAMA = 'scan_ollama'
    AWAITING_ADD = 'awaiting_add'
    SEARCHING = 'searching'

class Permissions:
    BANNED = 'banned'
    GUEST = 'guest'
    USER = 'user'
    ADMIN = 'admin'