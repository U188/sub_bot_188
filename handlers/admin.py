# handlers/admin.py (修复设置数量功能)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import config, Permissions
from data_manager import data_manager
from handlers.common import CommonHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes


class AdminHandler(CommonHandler):
    """管理员功能处理器"""

    def __init__(self):
        super().__init__()
        self.scanner_handler = None  # 将在main.py中注入
        self.user_states = {}

    async def user_management_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """用户管理菜单"""
        query = update.callback_query
        await query.answer()

        if not self.check_permission(update.effective_user.id, Permissions.ADMIN):
            await query.edit_message_text("❌ 权限不足")
            return

        admin_count = len(data_manager.admin_ids)
        user_count = len(data_manager.user_permissions)

        menu_text = f"""👥 用户管理

📊 当前状态：
• 管理员数量：{admin_count} 个
• 用户权限记录：{user_count} 个

🛠️ 管理功能："""

        keyboard = [
            [
                InlineKeyboardButton("👥 查看用户", callback_data="view_users"),
                InlineKeyboardButton("🔑 权限管理", callback_data="set_permission")
            ],
            [
                InlineKeyboardButton("📊 使用统计", callback_data="usage_stats"),
                InlineKeyboardButton("🎛️ 扫描设置", callback_data="set_count")
            ],
            [
                InlineKeyboardButton("🔄 代理同步", callback_data="proxy_sync")
            ],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "👑 **管理员面板**\\n\n选择管理功能：",
            reply_markup=reply_markup
        )

    def check_admin_permission(self, user_id: int) -> bool:
        """检查管理员权限"""
        from config import config
        return user_id in config.ADMIN_IDS

    async def view_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """查看用户列表"""
        query = update.callback_query
        await query.answer()

        if not self.check_permission(update.effective_user.id, Permissions.ADMIN):
            await query.edit_message_text("❌ 权限不足")
            return

        users_text = "👥 用户权限列表\n\n"
        users_text += f"🔑 管理员 ({len(data_manager.admin_ids)} 人):\n"
        for admin_id in data_manager.admin_ids:
            users_text += f"• {admin_id}\n"

        users_text += f"\n👤 其他用户 ({len(data_manager.user_permissions)} 人):\n"
        permission_emojis = {
            "user": "✅",
            "guest": "👀",
            "banned": "🚫"
        }

        for user_id, permission in data_manager.user_permissions.items():
            emoji = permission_emojis.get(permission, "❓")
            users_text += f"• {user_id}: {emoji} {permission.upper()}\n"

        keyboard = [
            [InlineKeyboardButton("🔄 刷新", callback_data='view_users')],
            [InlineKeyboardButton("🔙 返回", callback_data='user_management')]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(users_text, reply_markup=reply_markup)

    async def set_permission_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """设置用户权限提示"""
        query = update.callback_query
        await query.answer()

        if not self.check_permission(update.effective_user.id, Permissions.ADMIN):
            await query.edit_message_text("❌ 权限不足")
            return

        prompt_text = """🔧 设置用户权限

📝 请发送格式：用户ID 权限类型

🔑 权限类型：
• `user` - 普通用户（可使用所有功能）
• `guest` - 访客（仅查看功能）  
• `banned` - 封禁用户

💡 示例：
`123456789 user`
`987654321 banned`

发送设置命令..."""

        keyboard = [[InlineKeyboardButton("❌ 取消", callback_data='user_management')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        context.user_data['setting_permission'] = True
        await query.edit_message_text(prompt_text, reply_markup=reply_markup)

    async def handle_set_permission(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理设置权限"""
        try:
            parts = update.message.text.strip().split()
            if len(parts) != 2:
                await update.message.reply_text("❌ 格式错误，请使用：用户ID 权限类型")
                return

            target_user_id, permission = parts
            target_user_id = int(target_user_id)

            valid_permissions = ['user', 'guest', 'banned']
            if permission not in valid_permissions:
                await update.message.reply_text(f"❌ 权限类型必须是：{', '.join(valid_permissions)}")
                return

            data_manager.set_user_permission(target_user_id, permission)
            context.user_data.pop('setting_permission', None)

            keyboard = [[InlineKeyboardButton("🔙 返回管理", callback_data='user_management')]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                f"✅ 已设置用户 {target_user_id} 权限为：{permission.upper()}",
                reply_markup=reply_markup
            )

        except ValueError:
            await update.message.reply_text("❌ 用户ID必须是数字")
        except Exception as e:
            await update.message.reply_text(f"❌ 设置失败: {str(e)}")

    async def usage_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """使用统计"""
        query = update.callback_query
        await query.answer()

        if not self.check_permission(update.effective_user.id, Permissions.ADMIN):
            await query.edit_message_text("❌ 权限不足")
            return

        # 统计各权限级别用户数
        permission_stats = {}
        for permission in data_manager.user_permissions.values():
            permission_stats[permission] = permission_stats.get(permission, 0) + 1

        proxy_count = len(data_manager.load_proxies())

        current_scan_limit = self.scanner_handler.check_count if self.scanner_handler else config.DEFAULT_CHECK_COUNT

        stats_text = f"""📊 使用统计

🗂️ 数据统计：
• 节点总数：{proxy_count} 个
• 用户总数：{len(data_manager.user_permissions) + len(data_manager.admin_ids)} 个
• 管理员数：{len(data_manager.admin_ids)} 个
• 普通用户：{permission_stats.get('user', 0)} 个
• 访客用户：{permission_stats.get('guest', 0)} 个
• 封禁用户：{permission_stats.get('banned', 0)} 个

⚙️ 系统设置：
• 当前扫描限制：{current_scan_limit} 个
• 速率限制：{config.RATE_LIMIT_SECONDS} 秒
• 每页节点：{config.NODES_PER_PAGE} 个

📁 文件状态：
• 配置文件：{'✅' if os.path.exists(config.CONFIG_FILE) else '❌'}
• 代理文件：{'✅' if os.path.exists(config.PROXIES_FILE) else '❌'}"""

        keyboard = [
            [InlineKeyboardButton("🔄 刷新", callback_data='usage_stats')],
            [InlineKeyboardButton("🔙 返回", callback_data='user_management')]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(stats_text, reply_markup=reply_markup)

    async def set_settings_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """设置系统参数提示"""
        query = update.callback_query
        await query.answer()

        if not self.check_permission(update.effective_user.id, Permissions.ADMIN):
            await query.edit_message_text("❌ 权限不足")
            return

        current_scan_limit = self.scanner_handler.check_count if self.scanner_handler else config.DEFAULT_CHECK_COUNT

        prompt_text = f"""⚙️ 设置系统参数

📝 当前设置：
• 扫描限制：{current_scan_limit} 个

请发送新的扫描数量限制：

💡 建议范围：10-1000
    """

        keyboard = [[InlineKeyboardButton("❌ 取消", callback_data='user_management')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        context.user_data['setting_count'] = True
        await query.edit_message_text(prompt_text, reply_markup=reply_markup)

    async def handle_set_count(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理设置检查数量"""
        try:
            new_count = int(update.message.text.strip())
            if new_count <= 0:
                await update.message.reply_text("❌ 请输入大于0的数字")
                return

            config.DEFAULT_CHECK_COUNT = new_count
            if self.scanner_handler:
                self.scanner_handler.set_check_count(new_count)

            context.user_data.pop('setting_count', None)

            keyboard = [[InlineKeyboardButton("🔙 返回管理", callback_data='user_management')]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                f"✅ 扫描数量限制已设置为：{new_count}",
                reply_markup=reply_markup
            )

        except ValueError:
            await update.message.reply_text("❌ 请输入有效的数字")
        except Exception as e:
            await update.message.reply_text(f"❌ 设置失败: {str(e)}")


import os