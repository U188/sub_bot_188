# handlers/node_management.py (完整修复版)
import os
import time
import yaml
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import config, States, Permissions
from data_manager import data_manager
from utils.ui_helpers import UIHelper
from handlers.common import CommonHandler

logger = logging.getLogger(__name__)

class NodeHandler(CommonHandler):
    """节点管理处理器 - 增强版错误处理"""
    
    async def show_management_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """显示节点管理菜单"""
        query = update.callback_query
        await query.answer()
        
        if not self.check_permission(update.effective_user.id, Permissions.USER):
            await query.edit_message_text("❌ 权限不足")
            return
        
        proxy_count = len(data_manager.load_proxies())
        
        menu_text = f"""🎭 节点管理

🎭 当前状态：
• 节点总数：{proxy_count} 个

🎭 操作选项："""
        
        reply_markup = UIHelper.create_node_management_menu()
        await query.edit_message_text(menu_text, reply_markup=reply_markup)
    
    async def add_node_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """添加节点提示"""
        query = update.callback_query
        await query.answer()
        
        prompt_text = """➕ 添加节点

✨️ 支持的格式：
• YAML格式代理配置
• 代理链接 (ss://, vmess://, vless://, trojan://, hysteria://, hy2://)

✨️ 支持批量添加，每行一个
⚠️ name字段必须唯一，重复名称将被更新

🎯 VLESS示例：
vless://uuid@server:port/?type=tcp&security=reality&pbk=key&sid=id#name

发送配置信息或代理链接："""
        
        keyboard = [[InlineKeyboardButton("❌ 取消", callback_data='node_management')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        self.user_states[update.effective_chat.id] = States.AWAITING_ADD
        await query.edit_message_text(prompt_text, reply_markup=reply_markup)
    
    async def handle_add_nodes(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        【修复版】处理添加节点 - 增强错误处理和用户反馈
        """
        node_text = update.message.text.strip()
        if not node_text:
            await update.message.reply_text("❌ 请发送有效的节点配置")
            return
        
        # 显示处理进度
        progress_message = await update.message.reply_text("🔥🔥 正在解析节点配置...")
        
        try:
            # 记录用户输入用于调试
            user_id = update.effective_user.id
            logger.info(f"用户 {user_id} 尝试添加节点，行数: {len(node_text.split())}")
            
            # 预检查输入格式
            lines = node_text.strip().split('\n')
            vless_lines = [line for line in lines if line.strip().startswith('vless://')]
            other_lines = [line for line in lines if line.strip() and not line.strip().startswith('vless://')]
            
            if vless_lines:
                await progress_message.edit_text(f"🔥🔥 检测到 {len(vless_lines)} 个VLESS链接，正在解析...")
                logger.info(f"检测到VLESS链接: {len(vless_lines)}个")
            
            # 调用数据管理器处理
            success, message = data_manager.add_proxies(node_text)
            
            # 【修复】详细的结果处理
            if success:
                result_text = f"✅ {message}"
                
                # 添加成功提示
                if vless_lines:
                    result_text += f"\n🌟🌟 VLESS解析状态："
                    result_text += f"\n• 检测数量: {len(vless_lines)}个"
                    if "新增" in message or "更新" in message:
                        result_text += f"\n• ✅ 解析成功"
                    
                    # 提供详细信息按钮
                    keyboard = [
                        [InlineKeyboardButton("🌟 查看详情", callback_data='view_nodes')],
                        [InlineKeyboardButton("🎯 返回管理", callback_data='node_management')]
                    ]
                else:
                    keyboard = [[InlineKeyboardButton("🎯 返回管理", callback_data='node_management')]]
                
                logger.info(f"用户 {user_id} 节点添加成功: {message}")
                
            else:
                # 失败时提供更详细的错误信息
                result_text = f"❌ {message}"
                
                if vless_lines:
                    result_text += f"\n🎃 VLESS解析失败分析："
                    result_text += f"\n• 检测到 {len(vless_lines)} 个VLESS链接"
                    result_text += f"\n• 请检查链接格式是否完整"
                    result_text += f"\n• 确保包含必要参数: server, port, uuid"
                    
                    if vless_lines:
                        sample_link = vless_lines[0][:60] + "..." if len(vless_lines[0]) > 60 else vless_lines[0]
                        result_text += f"\n🎃 示例链接:\n{sample_link}"
                
                result_text += f"\n\n🎃 支持的格式:"
                result_text += f"\n• vless://uuid@server:port/?参数#名称"
                result_text += f"\n• 其他协议: ss://, vmess://, trojan://"
                result_text += f"\n• YAML配置格式"
                
                keyboard = [
                    [InlineKeyboardButton("🎃 重新尝试", callback_data='add_node')],
                    [InlineKeyboardButton("❌ 返回", callback_data='node_management')]
                ]
                
                logger.warning(f"用户 {user_id} 节点添加失败: {message}")
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
        except Exception as e:
            logger.error(f"处理添加节点时发生异常: {e}")
            import traceback
            logger.debug(f"详细错误: {traceback.format_exc()}")
            
            result_text = f"❌ 处理失败: {str(e)}"
            result_text += f"\n🎸 可能的原因："
            result_text += f"\n🎮 配置格式不正确"
            result_text += f"\n🎨 网络连接问题"
            result_text += f"\n🎳 服务器临时故障"
            
            keyboard = [
                [InlineKeyboardButton("🎳 重新尝试", callback_data='add_node')],
                [InlineKeyboardButton("❌ 返回", callback_data='node_management')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 重置用户状态
        self.user_states[update.effective_chat.id] = States.IDLE
        
        # 发送最终结果
        try:
            await progress_message.edit_text(result_text, reply_markup=reply_markup)
        except Exception as e:
            logger.warning(f"编辑消息失败，发送新消息: {e}")
            await update.message.reply_text(result_text, reply_markup=reply_markup)
    
    async def view_nodes(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1) -> None:
        """查看节点列表"""
        query = update.callback_query
        if query:
            await query.answer()
        
        page_data = data_manager.get_proxies_page(page)
        
        if not page_data['proxies'] and page == 1:
            text = "⚠️ 当前没有任何节点"
            keyboard = [[InlineKeyboardButton("❌ 返回", callback_data='node_management')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if query:
                await query.edit_message_text(text, reply_markup=reply_markup)
            else:
                await update.message.reply_text(text, reply_markup=reply_markup)
            return
        
        text = f"✨️ 节点列表 (第{page_data['current_page']}/{page_data['total_pages']}页)\n"
        text += f"总计: {page_data['total_count']} 个节点\n\n"
        
        start_index = (page - 1) * config.NODES_PER_PAGE + 1
        for i, proxy in enumerate(page_data['proxies'], start_index):
            text += UIHelper.format_proxy_display(proxy, i)
        
        reply_markup = UIHelper.create_pagination_keyboard(
            page_data['current_page'], 
            page_data['total_pages'],
            'view_page',
            'node_management'
        )
        
        if query:
            await query.edit_message_text(text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, reply_markup=reply_markup)
    
    async def search_nodes_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """搜索节点提示"""
        query = update.callback_query
        await query.answer()
        
        prompt_text = """🎉🎉 搜索节点

🎉🎉 请发送搜索关键词
🎉🎉 搜索范围：节点名称、服务器地址、协议类型

🎉🎉🎉 示例：US, 1.2.3.4, vmess, vless

发送关键词开始搜索..."""
        
        keyboard = [[InlineKeyboardButton("❌ 取消", callback_data='node_management')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        context.user_data['searching_nodes'] = True
        await query.edit_message_text(prompt_text, reply_markup=reply_markup)
    
    async def handle_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE, keyword: str) -> None:
        """处理搜索"""
        matching_proxies = data_manager.search_proxies(keyword)
        
        if not matching_proxies:
            result_text = f"✨️ 搜索结果\n\n❌ 未找到包含 '{keyword}' 的节点"
        else:
            result_text = f"✨️ 搜索结果\n\n找到 {len(matching_proxies)} 个匹配节点：\n\n"
            for i, proxy in enumerate(matching_proxies[:15], 1):
                result_text += UIHelper.format_proxy_display(proxy, i)
            if len(matching_proxies) > 15:
                result_text += f"... 还有 {len(matching_proxies) - 15} 个结果\n"
        
        keyboard = [
            [InlineKeyboardButton("♿️ 重新搜索", callback_data='search_nodes')],
            [InlineKeyboardButton("❌ 返回", callback_data='node_management')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(result_text, reply_markup=reply_markup)
        context.user_data.pop('searching_nodes', None)
    
    async def download_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """下载节点文件"""
        query = update.callback_query
        await query.answer()
        
        try:
            proxies = data_manager.load_proxies()
            if not proxies:
                await query.edit_message_text("❌ 当前没有任何节点")
                return
            
            filename = f"all_proxies_{int(time.time())}.txt"
            with open(filename, "w", encoding='utf-8') as f:
                yaml.dump(proxies, f, default_flow_style=False, 
                         allow_unicode=True, sort_keys=False)
            
            with open(filename, "rb") as f:
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=f,
                    filename=filename,
                    caption=f"🔥🔥 所有节点文件 ({len(proxies)} 个节点)"
                )
            
            try:
                os.remove(filename)
            except:
                pass
            
            keyboard = [[InlineKeyboardButton("🎯 返回管理", callback_data='node_management')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("✅ 文件发送成功", reply_markup=reply_markup)
            
        except Exception as e:
            await query.edit_message_text(f"❌ 下载失败: {str(e)}")
    
    async def select_nodes_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1) -> None:
        """多选节点菜单"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        if user_id not in self.selected_nodes:
            self.selected_nodes[user_id] = set()
        
        page_data = data_manager.get_proxies_page(page)
        
        if not page_data['proxies'] and page == 1:
            keyboard = [[InlineKeyboardButton("❌ 返回", callback_data='node_management')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("🎃🎃 当前没有任何节点", reply_markup=reply_markup)
            return
        
        selected_count = len(self.selected_nodes[user_id])
        text = f"✅ 多选节点 (第{page_data['current_page']}/{page_data['total_pages']}页)\n"
        text += f"已选择: {selected_count} 个 | 总计: {page_data['total_count']} 个\n\n"
        
        keyboard = []
        start_index = (page - 1) * config.NODES_PER_PAGE
        
        for i, proxy in enumerate(page_data['proxies']):
            name = proxy.get('name', '未知')
            display_name = name[:25] + "..." if len(name) > 25 else name
            is_selected = name in self.selected_nodes[user_id]
            prefix = "✅" if is_selected else "⬜"
            
            button_text = f"{prefix} {display_name} ({proxy.get('type', '').upper()})"
            keyboard.append([InlineKeyboardButton(button_text, 
                                                callback_data=f"toggle_select_{start_index + i}")])
        
        nav_buttons = []
        if page_data['has_prev']:
            nav_buttons.append(InlineKeyboardButton("⬅️ 上页", 
                                                  callback_data=f'select_page_{page - 1}'))
        nav_buttons.append(InlineKeyboardButton(f"{page}/{page_data['total_pages']}", 
                                              callback_data='noop'))
        if page_data['has_next']:
            nav_buttons.append(InlineKeyboardButton("➡️ 下页", 
                                                  callback_data=f'select_page_{page + 1}'))
        
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        action_buttons = []
        if selected_count > 0:
            action_buttons.extend([
                InlineKeyboardButton("⚠️️ 删除选中", callback_data='delete_selected'),
                InlineKeyboardButton("🎊 导出选中", callback_data='export_selected')
            ])
        
        action_buttons.extend([
            InlineKeyboardButton("🎊 全选", callback_data=f'select_all_{page}'),
            InlineKeyboardButton("❌ 清空", callback_data='clear_selection')
        ])
        
        if len(action_buttons) > 2:
            keyboard.append(action_buttons[:2])
            keyboard.append(action_buttons[2:])
        else:
            keyboard.append(action_buttons)
        
        keyboard.append([InlineKeyboardButton("🎯 返回管理", callback_data='node_management')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup)
    
    async def toggle_node_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """切换节点选择状态"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        if user_id not in self.selected_nodes:
            self.selected_nodes[user_id] = set()
        
        try:
            index = int(query.data.split('_')[-1])
            proxies = data_manager.load_proxies()
            
            if 0 <= index < len(proxies):
                node_name = proxies[index].get('name')
                
                if node_name in self.selected_nodes[user_id]:
                    self.selected_nodes[user_id].remove(node_name)
                else:
                    self.selected_nodes[user_id].add(node_name)
                
                current_page = (index // config.NODES_PER_PAGE) + 1
                await self.select_nodes_menu(update, context, current_page)
                
        except (ValueError, IndexError):
            await query.answer("❌ 操作失败", show_alert=True)
    
    async def delete_selected_nodes(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """删除选中节点确认"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        selected = self.selected_nodes.get(user_id, set())
        
        if not selected:
            await query.answer("❌ 未选择任何节点", show_alert=True)
            return
        
        confirm_text = f"""⚠️ 确认删除

⚠️ 将要删除 {len(selected)} 个节点
⚠️ 此操作不可撤销，确定要删除吗？"""
        
        keyboard = [
            [
                InlineKeyboardButton("✅ 确认删除", callback_data='confirm_delete_selected'),
                InlineKeyboardButton("❌ 取消", callback_data='select_nodes')
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(confirm_text, reply_markup=reply_markup)
    
    async def confirm_delete_selected(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """确认删除选中节点"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        selected = self.selected_nodes.get(user_id, set())
        
        if not selected:
            await query.edit_message_text("❌ 未选择任何节点")
            return
        
        success, message = data_manager.delete_proxies(list(selected))
        
        if success:
            self.selected_nodes[user_id] = set()
            result_text = f"✅ {message}"
        else:
            result_text = f"❌ {message}"
        
        keyboard = [[InlineKeyboardButton("🎯 返回管理", callback_data='node_management')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(result_text, reply_markup=reply_markup)
    
    async def export_selected_nodes(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """导出选中节点"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        selected = self.selected_nodes.get(user_id, set())
        
        if not selected:
            await query.answer("❌ 未选择任何节点", show_alert=True)
            return
        
        try:
            all_proxies = data_manager.load_proxies()
            selected_proxies = [proxy for proxy in all_proxies if proxy.get('name') in selected]
            
            if not selected_proxies:
                await query.edit_message_text("❌ 未找到选中的节点")
                return
            
            filename = f"selected_proxies_{int(time.time())}.txt"
            with open(filename, "w", encoding='utf-8') as f:
                yaml.dump(selected_proxies, f, default_flow_style=False, 
                         allow_unicode=True, sort_keys=False)
            
            with open(filename, "rb") as f:
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=f,
                    filename=filename,
                    caption=f"🎯 选中节点文件 ({len(selected_proxies)} 个节点)"
                )
            
            try:
                os.remove(filename)
            except:
                pass
            
            keyboard = [[InlineKeyboardButton("🎯 返回管理", callback_data='node_management')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("✅ 文件导出成功", reply_markup=reply_markup)
            
        except Exception as e:
            await query.edit_message_text(f"❌ 导出失败: {str(e)}")
    
    async def select_all_nodes(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """选择当前页所有节点"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        if user_id not in self.selected_nodes:
            self.selected_nodes[user_id] = set()
        
        try:
            page = int(query.data.split('_')[-1])
            page_data = data_manager.get_proxies_page(page)
            
            for proxy in page_data['proxies']:
                self.selected_nodes[user_id].add(proxy.get('name'))
            
            await self.select_nodes_menu(update, context, page)
            
        except (ValueError, IndexError):
            await query.answer("❌ 操作失败", show_alert=True)
    
    async def clear_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """清空选择"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        self.selected_nodes[user_id] = set()
        
        await self.select_nodes_menu(update, context, 1)