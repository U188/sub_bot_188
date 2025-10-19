# handlers/common.py (修复类型注解)
import asyncio
import time
from typing import Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import config, States, Permissions
from data_manager import data_manager
from utils.ui_helpers import UIHelper

class CommonHandler:
    """通用处理器"""
    
    def __init__(self):
        self.user_states = {}
        self.rate_limits = {}
        self.selected_nodes = {}
    
    def check_rate_limit(self, user_id: int) -> Tuple[bool, float]:
        """检查速率限制"""
        current_time = time.time()
        last_request = self.rate_limits.get(user_id, 0)
        
        if current_time - last_request < config.RATE_LIMIT_SECONDS:
            return False, config.RATE_LIMIT_SECONDS - (current_time - last_request)
        
        self.rate_limits[user_id] = current_time
        return True, 0
    
    def check_permission(self, user_id: int, required_level: str) -> bool:
        """检查用户权限"""
        user_permission = data_manager.get_user_permission(user_id)
        user_level = config.PERMISSION_LEVELS.get(user_permission, 0)
        required = config.PERMISSION_LEVELS.get(required_level, 3)
        return user_level >= required
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理/start命令"""
        user_id = update.effective_user.id
        user_permission = data_manager.get_user_permission(user_id)
        
        if user_permission == Permissions.BANNED:
            await update.message.reply_text("❌ 您已被禁止使用此机器人")
            return
        
        proxy_count = len(data_manager.load_proxies())
        
        welcome_text = f"""🎯 欢迎使用代理管理Bot！

👤 用户信息：
• 权限等级：{user_permission.upper()}
• 用户ID：{user_id}
• 节点总数：{proxy_count} 个

💡 点击下方按钮开始使用"""
        
        reply_markup = UIHelper.create_main_menu(user_permission)
        self.user_states[update.effective_chat.id] = States.IDLE
        
        if update.message:
            await update.message.reply_text(welcome_text, reply_markup=reply_markup)
        elif update.callback_query:
            await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup)
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """取消当前操作 - 立即响应"""
        chat_id = update.effective_chat.id
        
        # 清除用户状态
        self.user_states[chat_id] = States.IDLE
        context.user_data.clear()
        
        # 立即响应用户
        await update.message.reply_text("✅ 当前操作已取消")
        
        # 返回主菜单
        await self.start_command(update, context)