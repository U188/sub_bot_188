# main.py (完整集成代理同步功能)
import logging
import os
import traceback
import html
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ApplicationBuilder
from telegram.constants import ParseMode
from config import config, States
from data_manager import data_manager
from handlers.common import CommonHandler
from handlers.node_management import NodeHandler
from handlers.scanner import ScannerHandler
from handlers.admin import AdminHandler
from handlers.proxy_sync import register_proxy_sync_handlers
from handlers.ai_chat import AIChatHandler

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 禁用httpx日志噪音
logging.getLogger("httpx").setLevel(logging.WARNING)


class TelegramBot:
    """主Bot类 - 统一处理器调度"""

    def __init__(self):
        self.common_handler = CommonHandler()
        self.node_handler = NodeHandler()
        self.scanner_handler = ScannerHandler()
        self.admin_handler = AdminHandler()
        self.proxy_sync_handler = None  # 初始化为 None，将在 main() 中注入
        self.ai_chat_handler = AIChatHandler()

        shared_states = self.common_handler.user_states
        shared_selected = self.common_handler.selected_nodes

        self.node_handler.user_states = shared_states
        self.node_handler.selected_nodes = shared_selected
        self.scanner_handler.user_states = shared_states
        self.admin_handler.user_states = shared_states
        # AI chat handler 有自己的状态管理

        self.admin_handler.scanner_handler = self.scanner_handler

    # main.py 中的 handle_callback_query 方法修改
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        处理所有未被其他特定 CallbackQueryHandler 捕获的回调查询。
        它将作为所有 CallbackQueryHandler 中优先级最低的"兜底"处理器 (group=1)。
        """
        query = update.callback_query
        data = query.data

        # 添加 proxy_sync 相关的回调到路由表（作为 fallback）
        routes = {
            'back_to_start': self.common_handler.start_command,
            'node_management': self.node_handler.show_management_menu,
            'add_node': self.node_handler.add_node_prompt,
            'view_nodes': lambda u, c: self.node_handler.view_nodes(u, c, 1),
            'view_nodes_guest': lambda u, c: self.node_handler.view_nodes(u, c, 1),
            'search_nodes': self.node_handler.search_nodes_prompt,
            'download_file': self.node_handler.download_file,
            'select_nodes': lambda u, c: self.node_handler.select_nodes_menu(u, c, 1),
            'delete_selected': self.node_handler.delete_selected_nodes,
            'confirm_delete_selected': self.node_handler.confirm_delete_selected,
            'export_selected': self._handle_export_selected,
            'clear_selection': self._handle_clear_selection,

            'scan_xui': self.scanner_handler.scan_xui_prompt,
            'scan_ollama': self.scanner_handler.scan_ollama_prompt,

            'user_management': self.admin_handler.user_management_menu,
            'view_users': self.admin_handler.view_users,
            'set_permission': self.admin_handler.set_permission_prompt,
            'usage_stats': self.admin_handler.usage_stats,
            'set_settings': self.admin_handler.set_settings_prompt,
            'set_count': self.admin_handler.set_settings_prompt,

            # 添加 proxy_sync 相关的 fallback 路由
            'proxy_sync': self.proxy_sync_handler.show_sync_menu if self.proxy_sync_handler else None,
            'source_management': self.proxy_sync_handler.source_management if self.proxy_sync_handler else None,
            'manual_sync': self.proxy_sync_handler.manual_sync if self.proxy_sync_handler else None,

            # AI chat 相关回调
            'ai_chat:menu': self.ai_chat_handler.show_ai_menu,
            'ai_chat:start': self.ai_chat_handler.start_chat,
            'ai_chat:model': self.ai_chat_handler.select_model,
            'ai_chat:preset': self.ai_chat_handler.select_preset,
            'ai_chat:custom_prompt': self.ai_chat_handler.prompt_custom_prompt,
            'ai_chat:reset': self.ai_chat_handler.reset_chat,
            'ai_chat:status': self.ai_chat_handler.show_status,
        }

        # 处理特殊路由（带参数）
        if data.startswith('view_page_'):
            page = int(data.split('_')[2])
            await self.node_handler.view_nodes(update, context, page)
        elif data.startswith('select_page_'):
            page = int(data.split('_')[2])
            await self.node_handler.select_nodes_menu(update, context, page)
        elif data.startswith('toggle_select_'):
            await self.node_handler.toggle_node_selection(update, context)
        elif data.startswith('select_all_'):
            await self._handle_select_all(update, context)
        elif data.startswith('cancel_scan_'):
            await self.scanner_handler.cancel_scan_callback(update, context)
        elif data.startswith('ai_model:'):
            await self.ai_chat_handler.handle_model_selection(update, context)
        elif data.startswith('ai_preset:'):
            await self.ai_chat_handler.handle_preset_selection(update, context)
        elif data == 'noop':
            await query.answer()
        elif data in routes and routes[data] is not None:
            await routes[data](update, context)
        else:
            # 如果仍然未处理，记录详细信息用于调试
            await query.answer("🚫 未知操作或功能已更新，请尝试返回主菜单。")
            logger.warning(f"未处理的回调数据: {data} - 用户: {update.effective_user.id}")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """统一消息处理器 - 集成代理同步状态处理"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        state = self.common_handler.user_states.get(chat_id, States.IDLE)

        if not self.common_handler.check_permission(user_id, 'guest'):
            await update.message.reply_text("🚫 您已被禁止使用此功能")
            return

        # 优先检查 AI chat 模块是否需要处理此消息
        if chat_id in self.ai_chat_handler.user_states or user_id in self.ai_chat_handler.sessions:
            await self.ai_chat_handler.handle_message(update, context)
            return

        # 检查 proxy_sync 模块是否需要处理此消息
        if self.proxy_sync_handler and chat_id in self.proxy_sync_handler.user_states:
            await self.proxy_sync_handler.handle_message(update, context)
            return

        # 其余消息处理逻辑
        if context.user_data.get('searching_nodes'):
            keyword = update.message.text.strip()
            if keyword:
                await self.node_handler.handle_search(update, context, keyword)
            else:
                await update.message.reply_text("⚠️ 请输入有效的搜索关键词")
        elif context.user_data.get('setting_permission'):
            await self.admin_handler.handle_set_permission(update, context)
        elif context.user_data.get('setting_count'):
            await self.admin_handler.handle_set_count(update, context)
        elif state == States.AWAITING_ADD:
            await self.node_handler.handle_add_nodes(update, context)
        elif state in [States.SCAN_XUI, States.SCAN_OLLAMA]:
            text = update.message.text.strip()
            urls = [line.strip() for line in text.split('\n') if line.strip()]
            scan_type = "xui" if state == States.SCAN_XUI else "ollama"
            await self.scanner_handler.handle_scan_urls(update, context, urls, scan_type)
        else:
            await self.common_handler.start_command(update, context)

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理文档上传"""
        await self.scanner_handler.handle_document_upload(update, context)

    async def _handle_export_selected(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        selected = self.node_handler.selected_nodes.get(update.effective_user.id, set())
        if not selected:
            await query.answer("⚠️ 未选择任何节点", show_alert=True)
            return
        try:
            import uuid
            import yaml
            selected_proxies = [p for p in data_manager.load_proxies() if p.get('name') in selected]
            if not selected_proxies:
                await query.edit_message_text("⚠️ 未找到选中的节点")
                return
            filename = f"selected_nodes_{uuid.uuid4().hex[:8]}.txt"
            with open(filename, "w", encoding='utf-8') as f:
                yaml.dump(selected_proxies, f, allow_unicode=True)
            with open(filename, "rb") as f:
                await context.bot.send_document(chat_id=query.message.chat_id, document=f, filename=filename, caption=f"📦 导出的节点文件 ({len(selected_proxies)} 个节点)")
            os.remove(filename)
            await self.node_handler.select_nodes_menu(update, context, 1)
        except Exception as e:
            await query.edit_message_text(f"❌ 导出失败: {str(e)}")

    async def _handle_clear_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer("🧹 已清空选择")
        self.node_handler.selected_nodes[update.effective_user.id] = set()
        await self.node_handler.select_nodes_menu(update, context, 1)

    async def _handle_select_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        if user_id not in self.node_handler.selected_nodes:
            self.node_handler.selected_nodes[user_id] = set()
        try:
            page = int(query.data.split('_')[-1])
            page_data = data_manager.get_proxies_page(page)
            for proxy in page_data['proxies']:
                self.node_handler.selected_nodes[user_id].add(proxy.get('name'))
            await self.node_handler.select_nodes_menu(update, context, page)
        except ValueError:
            await query.answer("❌ 操作失败", show_alert=True)


def main() -> None:
    """启动Bot - 增加调试信息"""
    application = Application.builder().token(config.BOT_TOKEN).build()

    bot = TelegramBot()

    # 1. 注册 CommandHandlers
    application.add_handler(CommandHandler("start", bot.common_handler.start_command))
    application.add_handler(CommandHandler(["cancel", "c", "stop"], bot.scanner_handler.cancel_scan))

    # 2. 注册 ProxySyncHandler 的所有特定处理器
    proxy_sync_instance = register_proxy_sync_handlers(application)
    bot.proxy_sync_handler = proxy_sync_instance
    print(f"🔄 代理同步处理器已注册，包含 {len(proxy_sync_instance.source_manager.sources)} 个源")

    # 3. 注册通用 CallbackQueryHandler（group=1，作为 fallback）
    application.add_handler(CallbackQueryHandler(bot.handle_callback_query), group=1)

    # 4. 注册其他处理器
    application.add_handler(MessageHandler(filters.Document.ALL, bot.handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))

    # 启动信息（增加调试输出）
    print("🚀 Bot启动中...")
    print(f"👑 管理员ID: {config.ADMIN_IDS}")
    print(f"⚙️ 检查数量限制: {bot.scanner_handler.check_count}")
    print(f"⏱️ 速率限制: {config.RATE_LIMIT_SECONDS}秒")
    print(f"📄 每页节点数: {config.NODES_PER_PAGE}")
    print(f"🔄 代理同步功能: 已启用")
    print(f"📂 代理源配置保存路径: {config.SOURCE_CONFIG_FILE}")

    # 输出已注册的处理器信息（调试用）
    handlers_count = len(application.handlers[0]) if 0 in application.handlers else 0
    fallback_handlers_count = len(application.handlers[1]) if 1 in application.handlers else 0
    print(f"📋 Group 0 处理器数量: {handlers_count}")
    print(f"📋 Group 1 处理器数量: {fallback_handlers_count}")

    # 运行Bot
    application.run_polling()


if __name__ == '__main__':
    main()