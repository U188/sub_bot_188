# utils/ui_helpers.py (修复)
from typing import List, Dict, Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import config, Permissions

class UIHelper:
    """UI辅助工具类 - 遵循DRY原则"""
    
    @staticmethod
    def create_main_menu(user_permission: str) -> InlineKeyboardMarkup:
        """创建主菜单 - 优化为2列布局"""
        keyboard = []

        if user_permission in [Permissions.USER, Permissions.ADMIN]:
            keyboard.extend([
                [
                    InlineKeyboardButton("🚀 节点管理", callback_data='node_management'),
                    InlineKeyboardButton("📊 查看节点", callback_data='view_nodes')
                ],
                [
                    InlineKeyboardButton("🤖 AI对话", callback_data='ai_chat:menu'),
                    InlineKeyboardButton("🔍 扫描XUI", callback_data='scan_xui')
                ],
                [
                    InlineKeyboardButton("🍺 扫描Ollama", callback_data='scan_ollama')
                ]
            ])

        if user_permission == Permissions.ADMIN:
            keyboard.append([
                InlineKeyboardButton("👥 管理员面板", callback_data='user_management')
            ])
        else:
            # 访客只能查看节点
            keyboard.extend([
                [InlineKeyboardButton("📊 查看节点", callback_data='view_nodes_guest')],
                [InlineKeyboardButton("🤖 AI对话", callback_data='ai_chat:menu')]
            ])

        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_node_management_menu() -> InlineKeyboardMarkup:
        """创建节点管理菜单 - 优化为紧凑布局"""
        keyboard = [
            [
                InlineKeyboardButton("➕ 增加", callback_data='add_node'),
                InlineKeyboardButton("📋 查看", callback_data='view_nodes'),
                InlineKeyboardButton("🔍 搜索", callback_data='search_nodes')
            ],
            [
                InlineKeyboardButton("✅ 多选管理", callback_data='select_nodes'),
                InlineKeyboardButton("📄 下载文件", callback_data='download_file')
            ],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data='back_to_start')]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_pagination_keyboard(current_page: int, total_pages: int,
                                 callback_prefix: str, return_callback: str) -> InlineKeyboardMarkup:
        """创建分页键盘 - 优化导航布局"""
        keyboard = []

        # 分页导航按钮
        nav_buttons = []

        # 首页按钮（仅当不在第一页时显示）
        if current_page > 2:
            nav_buttons.append(InlineKeyboardButton("⏮️ 首页",
                                                  callback_data=f'{callback_prefix}_1'))

        # 上一页按钮
        if current_page > 1:
            nav_buttons.append(InlineKeyboardButton("◀️ 上页",
                                                  callback_data=f'{callback_prefix}_{current_page - 1}'))

        # 页码显示
        nav_buttons.append(InlineKeyboardButton(f"· {current_page}/{total_pages} ·",
                                              callback_data='noop'))

        # 下一页按钮
        if current_page < total_pages:
            nav_buttons.append(InlineKeyboardButton("下页 ▶️",
                                                  callback_data=f'{callback_prefix}_{current_page + 1}'))

        # 末页按钮（仅当不在最后一页时显示）
        if current_page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("末页 ⏭️",
                                                  callback_data=f'{callback_prefix}_{total_pages}'))

        if nav_buttons:
            keyboard.append(nav_buttons)

        # 返回按钮单独一行
        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data=return_callback)])

        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def format_proxy_display(proxy: Dict[str, Any], index: int) -> str:
        """格式化代理显示"""
        name = proxy.get('name', '未知')[:30]
        if len(proxy.get('name', '')) > 30:
            name += "..."
        
        proxy_type = proxy.get('type', '未知').upper()
        server = proxy.get('server', '未知')
        port = proxy.get('port', '未知')
        
        return f"{index}. **{name}**\n   类型: `{proxy_type}` | 服务器: `{server}:{port}`\n"
    
    @staticmethod
    def format_scan_progress(current: int, total: int, success_count: int, 
                           current_url: str, elapsed_time: float) -> str:
        """格式化扫描进度"""
        progress = (current / total) * 100
        
        eta_text = "计算中..."
        if current > 0:
            avg_time = elapsed_time / current
            remaining_time = avg_time * (total - current)
            eta_text = f"预计剩余：{int(remaining_time)}秒"
        
        return f"""📊 扫描进度：
• 目标数量：{total} 个
• 当前进度：{current}/{total} ({progress:.1f}%)
• 成功数量：{success_count} 个
• 当前目标：{current_url[:30]}...
• 已用时间：{int(elapsed_time)}秒
• {eta_text}"""