# handlers/proxy_sync.py
"""
代理同步处理器 - 遵循SOLID原则的设计
提供手动同步和自动更新功能，支持多协议解析
"""

import asyncio
import logging
import requests
import yaml
import re
import time
import base64
import urllib.parse
import json
from typing import Dict, List, Optional, Set, Tuple, Union, Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from config import config
from data_manager import data_manager
import os
from datetime import datetime, timedelta

# 统一使用核心解析器，消除重复实现
from utils.proxy_parser import ProxyParser as CoreProxyParser

logger = logging.getLogger(__name__)


class ProtocolType(Enum):
    """支持的协议类型"""
    SS = "ss"
    SSR = "ssr"
    VMESS = "vmess"
    TROJAN = "trojan"
    VLESS = "vless"
    HY2 = "hy2"
    YAML = "yaml"
    UNKNOWN = "unknown"


@dataclass
class ProxySource:
    """代理源配置类"""
    name: str
    url: str
    enabled: bool = True
    protocol_hint: Optional[ProtocolType] = None
    success_count: int = 0
    fail_count: int = 0
    last_sync: Optional[float] = None
    last_proxy_count: int = 0
    sync_interval_minutes: int = 60
    next_sync_timestamp: Optional[float] = None

    @property
    def success_rate(self) -> float:
        """计算成功率"""
        total = self.success_count + self.fail_count
        return (self.success_count / total * 100) if total > 0 else 0

    @property
    def status_emoji(self) -> str:
        """状态表情"""
        if not self.enabled:
            return "⏸️"
        elif self.success_rate >= 80:
            return "✅"
        elif self.success_rate >= 50:
            return "⚠️"
        else:
            return "❌"

    def to_dict(self) -> Dict:
        data = self.__dict__.copy()
        if self.protocol_hint:
            data['protocol_hint'] = self.protocol_hint.value
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> 'ProxySource':
        if 'protocol_hint' in data and data['protocol_hint'] is not None:
            data['protocol_hint'] = ProtocolType(data['protocol_hint'])
        return cls(**data)


@dataclass
class ProxyInfo:
    """代理信息数据类 - 使用server:port作为唯一标识"""
    ip: str
    port: int
    country_code: Optional[str] = None
    name: Optional[str] = None
    data: Optional[Dict] = None
    protocol: Optional[ProtocolType] = None
    source: Optional[str] = None

    @property
    def unique_key(self) -> str:
        """获取代理的唯一标识符 - 基于server和port"""
        return f"{self.ip}:{self.port}"

    @property
    def display_info(self) -> str:
        """显示信息"""
        protocol_str = f"[{self.protocol.value.upper()}]" if self.protocol else ""
        return f"{protocol_str}{self.name} - {self.unique_key}"


class RateLimitedCountryProvider:
    """限速的国家代码提供者 - 保持原有实现"""

    def __init__(self, timeout: int = 3, delay: float = 1.5):
        self.timeout = timeout
        self.delay = delay
        self.api_url = "http://ip-api.com/json/{}"
        self.last_request_time = 0
        self.cache = {}

    async def get_country_code(self, ip: str) -> Optional[str]:
        """获取IP的国家代码（带限速）"""
        if ip in self.cache:
            return self.cache[ip]

        try:
            current_time = time.time()
            time_since_last = current_time - self.last_request_time
            if time_since_last < self.delay:
                await asyncio.sleep(self.delay - time_since_last)

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.get(self.api_url.format(ip), timeout=self.timeout)
            )

            self.last_request_time = time.time()
            api_response = response.json()

            if api_response.get('status') == 'success':
                country_code = api_response.get('countryCode')
                self.cache[ip] = country_code
                return country_code

        except Exception as e:
            logger.warning(f"获取IP {ip} 国家代码失败: {e}")

        return None
        
class SimpleContentParser:
    """
    简化的内容解析器（适配器）- 统一委托给 utils.proxy_parser.ProxyParser
    遵循DRY：不重复实现协议解析
    """

    SUPPORTED_PREFIXES = ('ss://', 'ssr://', 'vmess://', 'vless://', 'trojan://', 'hy2://', 'hysteria://', 'hysteria2://')

    @staticmethod
    def _try_base64_decode_keep_newlines(content: str) -> str:
        """尽可能解码base64，若解码后包含协议标识则返回解码文本，否则返回原文"""
        raw = content.strip()
        def contains_proto(s: str) -> bool:
            low = s.lower()
            return any(p in low for p in ['ss://', 'ssr://', 'vmess://', 'vless://', 'trojan://', 'hy2://', 'hysteria2://', 'proxies:', 'server:', 'port:'])
        candidates = [
            lambda d: base64.b64decode(d),
            lambda d: base64.urlsafe_b64decode(d + '=='),
            lambda d: base64.b64decode(d + '=='),
            lambda d: base64.b64decode(d.replace('\n', '').replace('\r', '')),
        ]
        for fn in candidates:
            try:
                out = fn(raw).decode('utf-8')
                if contains_proto(out):
                    return out.strip()
            except Exception:
                continue
        return content

    @staticmethod
    def _detect_yaml_block(text: str) -> bool:
        low = text.strip().lower()
        return ('proxies:' in low) or ('server:' in low and 'port:' in low) or low.startswith('- name:') or low.startswith('name:')

    def parse_proxies(self, content: str, source_name: str = "") -> List['ProxyInfo']:
        """
        将内容解析为 ProxyInfo 列表：
        - 支持纯链接列表/混合内容
        - 支持base64包装
        - 支持YAML（含proxies列表或直接list/dict）
        """
        from utils.proxy_parser import ProxyParser as Core

        decoded = self._try_base64_decode_keep_newlines(content)
        text = decoded.strip()

        proxies: List[ProxyInfo] = []

        # YAML 优先
        if self._detect_yaml_block(text):
            try:
                data = yaml.safe_load(text)
                items = []
                if isinstance(data, dict) and 'proxies' in data and isinstance(data['proxies'], list):
                    items = data['proxies']
                elif isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    items = [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    p = Core.parse_proxy(item)
                    if p and p.get('server') and p.get('port'):
                        proto = p.get('type', 'unknown').lower()
                        protocol = ProtocolType(proto) if proto in ProtocolType._value2member_map_ else ProtocolType.UNKNOWN
                        proxies.append(ProxyInfo(
                            ip=str(p['server']),
                            port=int(p['port']),
                            protocol=protocol,
                            name=p.get('name', ''),
                            data=p,
                            source=source_name
                        ))
                return proxies
            except Exception as e:
                logger.warning(f"YAML解析失败，回退为逐行解析: {e}")

        # 逐行解析
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if len(lines) == 1:
            # 可能是连续协议字符串，尝试智能切割
            s = lines[0]
            pattern = r'(?=(vless://|vmess://|ss://|ssr://|trojan://|hy2://|hysteria2://))'
            parts = [p for p in re.split(pattern, s) if p]
            # 重组：因为split保留了前瞻分组，需拼接
            merged = []
            buf = ""
            for part in parts:
                if any(part.startswith(pfx) for pfx in self.SUPPORTED_PREFIXES):
                    if buf:
                        merged.append(buf)
                    buf = part
                else:
                    buf += part
            if buf:
                merged.append(buf)
            lines = [l for l in merged if l.strip()]

        for line in lines:
            # 去除前缀干扰（如包含状态文本）
            first_hit = min([line.find(p) for p in self.SUPPORTED_PREFIXES if p in line] + [10**9])
            if first_hit != 10**9:
                line = line[first_hit:]

            candidate = None
            if any(line.startswith(p) for p in self.SUPPORTED_PREFIXES):
                candidate = CoreProxyParser.parse_proxy_link(line)
            else:
                # 尝试作为YAML单条或通用解析
                candidate = CoreProxyParser.parse_proxy(line)

            if candidate and candidate.get('server') and candidate.get('port'):
                proto = candidate.get('type', 'unknown').lower()
                protocol = ProtocolType(proto) if proto in ProtocolType._value2member_map_ else ProtocolType.UNKNOWN
                proxies.append(ProxyInfo(
                    ip=str(candidate['server']),
                    port=int(candidate['port']),
                    protocol=protocol,
                    name=candidate.get('name', ''),
                    data=candidate,
                    source=source_name
                ))

        return proxies
        
        
        
class ProxyNameGenerator:
    """代理名称生成器"""

    def __init__(self, country_provider: RateLimitedCountryProvider):
        self.country_provider = country_provider

    async def generate_name(self, proxy_info: ProxyInfo) -> str:
        if not proxy_info.country_code:
            proxy_info.country_code = await self.country_provider.get_country_code(proxy_info.ip)
        country = proxy_info.country_code or "未知"
        return f"{country}|{proxy_info.unique_key}"


class ProxyMerger:
    """代理合并器 - 基于server和port查重"""

    def __init__(self, name_generator: ProxyNameGenerator):
        self.name_generator = name_generator

    async def merge_proxies(self, existing_proxies: List[ProxyInfo], new_proxies: List[ProxyInfo]) -> Tuple[
        List[ProxyInfo], Dict[str, int]]:

        merged_proxies_map: Dict[str, ProxyInfo] = {p.unique_key: p for p in existing_proxies}

        stats = {'added': 0, 'updated': 0, 'total_new_incoming': len(new_proxies), 'by_protocol': {}, 'by_source': {}}

        for new_proxy_candidate in new_proxies:
            if new_proxy_candidate.protocol:
                p_name = new_proxy_candidate.protocol.value
                stats['by_protocol'][p_name] = stats['by_protocol'].get(p_name, 0) + 1
            if new_proxy_candidate.source:
                stats['by_source'][new_proxy_candidate.source] = stats['by_source'].get(new_proxy_candidate.source, 0) + 1

            unique_key = new_proxy_candidate.unique_key

            if unique_key in merged_proxies_map:
                existing_proxy_obj = merged_proxies_map[unique_key]
                original_name = existing_proxy_obj.name

                await self.name_generator.generate_name(new_proxy_candidate)

                # 更新基础数据
                existing_proxy_obj.ip = new_proxy_candidate.ip
                existing_proxy_obj.port = new_proxy_candidate.port
                existing_proxy_obj.country_code = new_proxy_candidate.country_code
                existing_proxy_obj.protocol = new_proxy_candidate.protocol
                existing_proxy_obj.source = new_proxy_candidate.source
                existing_proxy_obj.data = new_proxy_candidate.data

                # 保留旧的非空名称，否则用新生成名称
                if original_name:
                    existing_proxy_obj.name = original_name
                    if existing_proxy_obj.data and 'name' in existing_proxy_obj.data:
                        existing_proxy_obj.data['name'] = original_name

                stats['updated'] += 1
            else:
                await self.name_generator.generate_name(new_proxy_candidate)
                if new_proxy_candidate.data:
                    new_proxy_candidate.data['name'] = new_proxy_candidate.name
                merged_proxies_map[unique_key] = new_proxy_candidate
                stats['added'] += 1

        return list(merged_proxies_map.values()), stats


class ProxyFetcher:
    """代理获取器 - 增强原始响应体处理"""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    async def fetch_from_url(self, url: str) -> Optional[str]:
        try:
            loop = asyncio.get_event_loop()
            headers = {"User-Agent": "Clash/2023.01.01"}
            response = await loop.run_in_executor(None, lambda: requests.get(url, headers=headers, timeout=self.timeout))
            response.raise_for_status()
            content_bytes = response.content
            encoding = response.encoding if response.encoding else 'utf-8'
            content = content_bytes.decode(encoding).strip()
            if not content:
                logger.warning(f"ProxyFetcher: 从 {url} 获取到空内容")
                return None
            return content
        except Exception as e:
            logger.error(f"ProxyFetcher: 从 {url} 获取代理失败: {e}")
            return None


class SourceScheduler:
    """负责调度各个代理源的自动同步。"""

    def __init__(self, source_manager: 'ProxySourceManager',
                 sync_callback: Callable[[str], Awaitable[Dict]],
                 admin_send_callback: Callable[[ContextTypes.DEFAULT_TYPE, str, str], Awaitable[None]]):
        self.source_manager = source_manager
        self.sync_callback = sync_callback
        self.admin_send_callback = admin_send_callback
        self._scheduler_task: Optional[asyncio.Task] = None
        self.is_running = False
        self.scheduler_loop_interval = 30

    async def start_scheduler(self, context: ContextTypes.DEFAULT_TYPE):
        if self.is_running:
            return
        self.is_running = True
        logger.info("代理源调度器已启动。")
        self._scheduler_task = asyncio.create_task(self._run_loop(context))

    def stop_scheduler(self):
        if not self.is_running:
            return
        self.is_running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            self._scheduler_task = None
        logger.info("代理源调度器已停止。")

    async def _run_loop(self, context: ContextTypes.DEFAULT_TYPE):
        while self.is_running:
            try:
                due_sources = self.source_manager.get_due_sources()
                if due_sources:
                    logger.info(f"调度器发现 {len(due_sources)} 个到期源，准备同步。")
                    for source in due_sources:
                        logger.info(f"正在同步到期源: {source.name}")
                        try:
                            sync_result = await self.sync_callback(source.name)
                            if sync_result['success']:
                                report = ProxySyncHandler._generate_sync_report_static(sync_result)
                                await self.admin_send_callback(context,
                                                               f"**自动同步报告 - 源: {source.name}**\n\n{report}",
                                                               f"自动同步({source.name})")
                            else:
                                error_msg = f"❌ **自动同步失败 - 源: {source.name}**\n\n错误: {sync_result.get('error', '未知错误')}"
                                await self.admin_send_callback(context, error_msg, f"自动同步失败({source.name})")
                        except Exception as e:
                            logger.error(f"同步源 {source.name} 时发生异常: {e}")
                            error_msg = f"❌ **自动同步异常 - 源: {source.name}**\n\n错误: {str(e)}"
                            await self.admin_send_callback(context, error_msg, f"自动同步异常({source.name})")
            except asyncio.CancelledError:
                logger.info("调度器循环被取消。")
                break
            except Exception as e:
                logger.critical(f"调度器主循环发生严重错误: {e}")
                await asyncio.sleep(60)
            finally:
                await asyncio.sleep(self.scheduler_loop_interval)
                
class ProxyParserAdapter:
    """
    适配器：对外暴露统一的 parse_proxies(content, source_name)
    内部委派给 SimpleContentParser（其又委托 utils.proxy_parser.ProxyParser）
    """
    def __init__(self):
        self._impl = SimpleContentParser()

    def parse_proxies(self, content: str, source_name: str = "") -> List[ProxyInfo]:
        return self._impl.parse_proxies(content, source_name)


class ProxySourceManager:
    """代理源管理器 - 管理多个代理源配置，支持持久化和获取待调度源。"""

    def __init__(self):
        self.sources: Dict[str, ProxySource] = {}
        self.source_config_file = config.SOURCE_CONFIG_FILE
        self._load_sources()

    def _load_sources(self):
        """从文件加载同步源配置。如果文件不存在或加载失败，则加载默认源并保存。"""
        if not os.path.exists(self.source_config_file):
            logger.info(f"源配置文件 {self.source_config_file} 不存在，加载默认源。")
            self._load_default_sources()
            self._save_sources()
            return
        try:
            with open(self.source_config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for source_dict in data:
                    source = ProxySource.from_dict(source_dict)
                    if source.next_sync_timestamp is None:
                        source.next_sync_timestamp = time.time()
                    self.sources[source.name] = source
            logger.info(f"成功从 {self.source_config_file} 加载 {len(self.sources)} 个同步源。")
        except Exception as e:
            logger.error(f"加载同步源配置失败: {e}，将使用默认源并尝试修复。")
            self.sources = {}
            self._load_default_sources()
            self._save_sources()

    def _save_sources(self):
        """将同步源配置保存到文件。"""
        try:
            os.makedirs(os.path.dirname(self.source_config_file), exist_ok=True)
            with open(self.source_config_file, 'w', encoding='utf-8') as f:
                json.dump([source.to_dict() for source in self.sources.values()], f, indent=4, ensure_ascii=False)
            logger.info(f"成功保存 {len(self.sources)} 个同步源到 {self.source_config_file}。")
        except Exception as e:
            logger.error(f"保存同步源配置失败: {e}")

    def _load_default_sources(self):
        """加载默认同步源配置 - 仅在文件不存在或加载失败时调用。"""
        self.sources.clear()
        source_configs = [
            {"name": "主源", "url": "https://zh.jikun.fun/share/col/江江公益?token=1yGRuU-x6r_zEz28cE_pE", "enabled": True, "protocol_hint": None,
             "sync_interval_minutes": 180},
            {"name": "skr源", "url": "http://127.0.0.1:3215/getnode", "enabled": True, "protocol_hint": None,
             "sync_interval_minutes": 180},
            {"name": "SS源", "url": "https://raw.githubusercontent.com/iosDG001/_/refs/heads/main/SS", "enabled": True,
             "protocol_hint": None, "sync_interval_minutes": 180},
            {"name": "Trojan源", "url": "https://raw.githubusercontent.com/iosDG001/_/refs/heads/main/SLVPN",
             "enabled": True, "protocol_hint": None, "sync_interval_minutes": 180},
            {"name": "VV节点源", "url": "https://raw.githubusercontent.com/iosDG001/_/refs/heads/main/VVV",
             "enabled": True, "protocol_hint": None, "sync_interval_minutes": 180}
        ]
        for config_dict in source_configs:
            source = ProxySource.from_dict(config_dict)
            source.next_sync_timestamp = time.time()
            self.sources[source.name] = source
        logger.info(f"加载了 {len(self.sources)} 个默认同步源。")

    def add_source(self, name: str, url: str, protocol_hint: Optional[ProtocolType] = None,
                   sync_interval_minutes: int = 60) -> bool:
        if name in self.sources:
            return False
        source = ProxySource(name, url, True, protocol_hint, sync_interval_minutes=sync_interval_minutes,
                             next_sync_timestamp=time.time())
        self.sources[name] = source
        self._save_sources()
        return True

    def remove_source(self, name: str) -> bool:
        if name in self.sources:
            del self.sources[name]
            self._save_sources()
            return True
        return False

    def enable_source(self, name: str, enabled: bool = True) -> bool:
        if name in self.sources:
            source = self.sources[name]
            source.enabled = enabled
            if enabled:
                source.next_sync_timestamp = time.time()
            self._save_sources()
            return True
        return False

    def set_source_interval(self, name: str, interval_minutes: int) -> bool:
        if name in self.sources:
            source = self.sources[name]
            source.sync_interval_minutes = interval_minutes
            source.next_sync_timestamp = time.time() + interval_minutes * 60
            self._save_sources()
            return True
        return False

    def update_source_stats(self, name: str, success: bool, proxy_count: int = 0):
        if name in self.sources:
            source = self.sources[name]
            if success:
                source.success_count += 1
                source.last_proxy_count = proxy_count
            else:
                source.fail_count += 1
            source.last_sync = time.time()
            source.next_sync_timestamp = time.time() + source.sync_interval_minutes * 60
            self._save_sources()

    def get_enabled_sources(self) -> List[ProxySource]:
        return [source for source in self.sources.values() if source.enabled]

    def get_source_by_name(self, name: str) -> Optional[ProxySource]:
        return self.sources.get(name)

    def get_due_sources(self) -> List[ProxySource]:
        return [s for s in self.sources.values() if
                s.enabled and (s.next_sync_timestamp is None or s.next_sync_timestamp <= time.time())]
                
class ProxySyncHandler:
    """代理同步处理器主类"""

    def __init__(self):
        self.country_provider = RateLimitedCountryProvider(delay=1.5)
        self.name_generator = ProxyNameGenerator(self.country_provider)
        self.merger = ProxyMerger(self.name_generator)
        self.fetcher = ProxyFetcher()
        # 使用适配器，内部委派至 utils.proxy_parser.ProxyParser
        self.parser = ProxyParserAdapter()
        self.source_manager = ProxySourceManager()
        self.scheduler = SourceScheduler(self.source_manager, self._sync_single_source, self._send_report_to_admins)
        self.user_states = {}
        self.last_sync_time = None
        self.total_synced_proxies = len(data_manager.load_proxies())

    def check_admin_permission(self, user_id: int) -> bool:
        return user_id in config.ADMIN_IDS

    @staticmethod
    def _generate_sync_report_static(result: Dict) -> str:
        if not result['success']:
            return f"❌ **同步失败**\n\n错误: {result.get('error', '未知错误')}"
        stats = result['stats']
        source_results = result.get('source_results', {})
        source_report = [f"• **{name}**: {count} 个代理" if isinstance(count, int) else f"• **{name}**: {count}" for
                         name, count in source_results.items()]
        source_text = "\n".join(source_report) if source_report else "无"
        protocol_text = ""
        if stats.get('by_protocol'):
            protocol_stats = [f"• {protocol.upper()}: {count} 个" for protocol, count in stats['by_protocol'].items()]
            protocol_text = f"\n\n📋 **协议分布**:\n" + "\n".join(protocol_stats)
        duplicate_info = ""
        if stats.get('updated', 0) > 0 or stats.get('added', 0) > 0:
            duplicate_info = f"\n\n🔄 **去重信息**:\n• 基于 server:port 查重\n• 覆盖重复代理: {stats.get('updated', 0)} 个"
        source_contrib_text = ""
        if stats.get('by_source'):
            source_stats = [f"• {source_name}: {count} 个" for source_name, count in stats['by_source'].items()]
            source_contrib_text = f"\n\n📈 **源贡献**:\n" + "\n".join(source_stats)
        return f"""✅ **代理同步完成**

     **同步统计**:
    • 新增代理: {stats.get('added', 0)} 个
    • 更新代理: {stats.get('updated', 0)} 个
    • 获取总数: {stats.get('total_new', 0)} 个
    • 最终总数: {result.get('total_proxies', 0)} 个

     **数据源结果**:
    {source_text}{protocol_text}{duplicate_info}{source_contrib_text}

     同步时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"""

    async def _send_report_to_admins(self, context: ContextTypes.DEFAULT_TYPE, report: str, sync_type: str) -> None:
        full_report = f" **{sync_type}报告**\n\n{report}"
        for admin_id in config.ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=full_report)
            except Exception as e:
                logger.warning(f"发送报告给管理员 {admin_id} 失败: {e}")

    async def add_source_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self.check_admin_permission(update.effective_user.id): 
            await query.answer("❌ 需要管理员权限"); 
            return
        await query.answer()
        self.user_states[update.effective_chat.id] = 'adding_source'
        await query.edit_message_text(
            """➕ **添加同步源**\n\n    请发送源配置，格式：\n    源名称|URL|协议类型(可选)|同步间隔(分钟,可选)\n\n    示例：\n    主要源|https://example.com/main.txt\n    SS源|https://example.com/ss.txt|ss|30\n\n    📋 **支持协议**: Vless，SS, SSR, VMess, Trojan, Hysteria2, YAML\n    🔄 **自动同步**: 添加成功后会自动进行一次同步测试\n\n    发送 /cancel 取消添加""",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 返回源管理", callback_data="source_management")]]))

    async def remove_source_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self.check_admin_permission(update.effective_user.id): 
            await query.answer("❌ 需要管理员权限"); 
            return
        await query.answer()
        if not self.source_manager.sources:
            await query.edit_message_text("❌ 暂无源可删除", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 返回源管理", callback_data="source_management")]]))
            return
        keyboard = [[InlineKeyboardButton(f"🗑️ 删除 {name}", callback_data=f"delete_source_{name}")] for name in
                    self.source_manager.sources.keys()]
        keyboard.append([InlineKeyboardButton("🔙 返回源管理", callback_data="source_management")])
        await query.edit_message_text("🗑️ **删除同步源**\n\n请选择要删除的源：",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    async def refresh_sources(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self.check_admin_permission(update.effective_user.id): 
            await query.answer("❌ 需要管理员权限"); 
            return
        await query.answer("正在刷新源状态...")
        await query.edit_message_text("🔄 正在检测所有源的连接状态...")
        if not self.source_manager.sources:
            await query.edit_message_text("❌ 暂无源可刷新", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 返回源管理", callback_data="source_management")]]))
            return
        refresh_results = []
        for name, source in self.source_manager.sources.items():
            try:
                start_time = time.time()
                content = await self.fetcher.fetch_from_url(source.url)
                response_time = (time.time() - start_time) * 1000
                if content:
                    proxies = self.parser.parse_proxies(content, source_name=name)
                    if proxies:
                        if source.protocol_hint is None or source.protocol_hint == ProtocolType.UNKNOWN:
                            for proxy in proxies[:3]:
                                if proxy.protocol and proxy.protocol != ProtocolType.UNKNOWN: 
                                    source.protocol_hint = proxy.protocol; 
                                    break
                        self.source_manager.update_source_stats(name, True, len(proxies))
                        refresh_results.append(f"✅ {name}: {len(proxies)} 个代理 ({response_time:.0f}ms)")
                    else:
                        self.source_manager.update_source_stats(name, False); 
                        refresh_results.append(f"⚠️ {name}: 解析失败 ({response_time:.0f}ms)")
                else:
                    self.source_manager.update_source_stats(name, False); 
                    refresh_results.append(f"⚠️ {name}: 空内容 ({response_time:.0f}ms)")
            except Exception:
                self.source_manager.update_source_stats(name, False); 
                refresh_results.append(f"❌ {name}: 连接失败")
        await query.edit_message_text(f"🔄 **源状态刷新完成**\n\n" + "\n".join(refresh_results),
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 查看详情",
                                                                                               callback_data="list_sources"),
                                                                          InlineKeyboardButton("🔙 返回源管理",
                                                                                               callback_data="source_management")]]))

    async def handle_add_source(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        if self.user_states.get(chat_id) != 'adding_source':
            return
        text = update.message.text.strip()
        if text.lower() == '/cancel':
            self.user_states.pop(chat_id, None)
            await update.message.reply_text("已取消添加。", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 返回源管理", callback_data="source_management")]]))
            return
        parts = text.split('|')
        if len(parts) < 2: 
            await update.message.reply_text("❌ 格式错误，请使用：源名称|URL|协议(可选)|间隔(分钟,可选)"); 
            return
        name, url, protocol_hint, sync_interval = parts[0].strip(), parts[1].strip(), None, 60
        if len(parts) >= 3 and parts[2].strip(): 
            try:
                protocol_hint = ProtocolType(parts[2].strip().lower())
            except Exception:
                protocol_hint = None
        if len(parts) >= 4:
            try:
                sync_interval = int(parts[3].strip())
            except ValueError:
                await update.message.reply_text("❌ 间隔必须是数字。"); 
                return
        if self.source_manager.add_source(name, url, protocol_hint, sync_interval):
            self.user_states.pop(chat_id, None)
            test_message = await update.message.reply_text(f"✅ 源添加成功！正在进行首次同步测试...")
            try:
                sync_result = await self._sync_single_source(name)
                protocol_text = f" (协议: {protocol_hint.value.upper()})" if protocol_hint else ""
                if sync_result['success']:
                    cleaned_report = self._generate_sync_report_static(sync_result).replace('✅ **代理同步完成**', '').strip()
                    await test_message.edit_text(
                        f"✅ **源添加并首次同步成功**\n\n    📋 **源信息**:\n    • 源名称: {name}\n    • URL: {url}{protocol_text}\n    • 同步间隔: {sync_interval} 分钟\n\n    {cleaned_report}",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 查看源列表",
                                                                                 callback_data="list_sources"),
                                                            InlineKeyboardButton("🔙 返回源管理",
                                                                                 callback_data="source_management")]]))
                else:
                    error_msg = sync_result.get('error', '未知错误')
                    await test_message.edit_text(
                        f"⚠️ **源已添加，但首次同步失败**\n\n    📋 **源信息**:\n    • 源名称: {name}\n    • URL: {url}{protocol_text}\n\n    ❌ **同步错误**: {error_msg}",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 重试",
                                                                                 callback_data=f"sync_single_{name}"),
                                                            InlineKeyboardButton("🔙 返回源管理",
                                                                                 callback_data="source_management")]]))
            except Exception as e:
                await test_message.edit_text(f"⚠️ **源已添加，但自动同步异常**\n\n    ❌ **异常**: {str(e)}",
                                             reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 重试",
                                                                                                      callback_data=f"sync_single_{name}"),
                                                                                 InlineKeyboardButton("🔙 返回源管理",
                                                                                                      callback_data="source_management")]]))
        else:
            await update.message.reply_text(f"❌ 添加失败，源 '{name}' 已存在")

    async def handle_delete_source(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        source_name = query.data[14:]
        if not self.check_admin_permission(update.effective_user.id): 
            await query.answer("❌ 需要管理员权限"); 
            return
        source = self.source_manager.get_source_by_name(source_name)
        if not source: 
            await query.answer("❌ 源不存在"); 
            return
        keyboard = [[InlineKeyboardButton("✅ 确认删除", callback_data=f"confirm_delete_{source_name}"),
                     InlineKeyboardButton("❌ 取消", callback_data="remove_source")]]
        await query.edit_message_text(
            f"⚠️ **确认删除源**\n\n源名称: {source_name}\nURL: {source.url}\n\n确定要删除这个源吗？",
            reply_markup=InlineKeyboardMarkup(keyboard))

    async def handle_confirm_delete_source(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        source_name = query.data[15:]
        if self.source_manager.remove_source(source_name):
            await query.answer(f"✅ 已删除源: {source_name}")
            await query.edit_message_text(f"✅ **删除成功**\n\n源 '{source_name}' 已被删除",
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回源管理",
                                                                                                   callback_data="source_management")]]))
        else:
            await query.answer("❌ 删除失败"); 
            await query.edit_message_text(f"❌ 删除失败，源 '{source_name}' 不存在",
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                                              "🔙 返回源管理", callback_data="source_management")]]))

    async def show_sync_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self.check_admin_permission(update.effective_user.id): 
            await query.answer("❌ 需要管理员权限"); 
            return
        await query.answer()
        # 自动更新按钮
        auto_sync_button = [
            InlineKeyboardButton("⏹️ 停止自动", callback_data="stop_auto_sync")
        ] if self.scheduler.is_running else [
            InlineKeyboardButton("▶️ 启动自动", callback_data="start_auto_sync")
        ]

        keyboard = [
            [
                InlineKeyboardButton("🔄 手动同步", callback_data="manual_sync"),
                InlineKeyboardButton("🔗 源管理", callback_data="source_management")
            ],
            [
                InlineKeyboardButton("📊 同步状态", callback_data="sync_status"),
                InlineKeyboardButton("⚙️ 全局设置", callback_data="sync_settings")
            ],
            auto_sync_button,
            [InlineKeyboardButton("🔙 返回管理菜单", callback_data="user_management")]
        ]
        enabled_sources, total_sources = len(self.source_manager.get_enabled_sources()), len(self.source_manager.sources)
        status_text = "🟢 运行中" if self.scheduler.is_running else "🔴 已停止"
        last_sync = time.strftime('%Y-%m-%d %H:%M:%S',
                                  time.localtime(self.last_sync_time)) if self.last_sync_time else "从未同步"
        text = f"""🔄 **代理同步管理**\n\n📊 **系统状态**:\n• 同步源: {enabled_sources}/{total_sources} 个启用\n• 自动更新: {status_text} (按源独立定时)\n• 上次全局同步: {last_sync}\n• 代理总数: {self.total_synced_proxies} 个\n\n🔗 **支持协议**: SS, SSR, VMess, Trojan, Hysteria2, YAML\n\n选择操作："""
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def manual_sync(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self.check_admin_permission(update.effective_user.id): 
            await query.answer("❌ 需要管理员权限"); 
            return
        await query.answer()
        await query.edit_message_text(" 正在同步所有启用源，请稍候...")
        try:
            result = await self._sync_proxies()
            if result['success']:
                await query.edit_message_text(self._generate_sync_report_static(result),
                                              reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                                                  " 返回同步菜单", callback_data="proxy_sync")]]))
            else:
                await query.edit_message_text(f"❌ 同步失败: {result.get('error', '未知错误')}",
                                              reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                                                  " 返回同步菜单", callback_data="proxy_sync")]]))
        except Exception as e:
            logger.error(f"手动同步失败: {e}"); 
            await query.edit_message_text(f"❌ 同步过程中发生错误: {str(e)}",
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                                              " 返回同步菜单", callback_data="proxy_sync")]]))

    async def sync_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self.check_admin_permission(update.effective_user.id): 
            await query.answer("❌ 需要管理员权限"); 
            return
        await query.answer()
        keyboard = [[InlineKeyboardButton(" 重置设置", callback_data="reset_sync_settings")],
                    [InlineKeyboardButton(" 返回同步菜单", callback_data="proxy_sync")]]
        text = f"⚙️ **全局同步设置**\n\n    此菜单包含影响整体同步行为的设置。\n    每个源的同步间隔和启用/禁用状态在 '🔗 源管理' 中设置。\n\n     **国家查询延迟**: {self.country_provider.delay} 秒\n\n    选择要修改的设置："
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def source_management(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self.check_admin_permission(update.effective_user.id): 
            await query.answer("❌ 需要管理员权限"); 
            return
        await query.answer()
        keyboard = [
            [
                InlineKeyboardButton("➕ 添加源", callback_data="add_source"),
                InlineKeyboardButton("🗑️ 删除源", callback_data="remove_source")
            ],
            [
                InlineKeyboardButton("📋 源列表", callback_data="list_sources"),
                InlineKeyboardButton("🔄 刷新状态", callback_data="refresh_sources")
            ],
            [
                InlineKeyboardButton("⏱️ 设置间隔", callback_data="set_source_interval_prompt"),
                InlineKeyboardButton("🎯 选择同步", callback_data="selective_sync")
            ],
            [InlineKeyboardButton("🔙 返回同步菜单", callback_data="proxy_sync")]
        ]
        enabled_count, total_count = len(self.source_manager.get_enabled_sources()), len(self.source_manager.sources)
        text = f"🔗 **同步源管理**\n\n📊 **源统计**:\n• 总源数: {total_count} 个\n• 启用数: {enabled_count} 个\n• 禁用数: {total_count - enabled_count} 个\n\n🛠️ **管理功能**:\n• 添加/删除同步源\n• 启用/禁用源 (在 '源列表' 中操作)\n• 设置每个源的独立同步间隔\n• 查看源状态和统计\n• 选择性同步特定源\n\n选择操作："
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def list_sources(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self.check_admin_permission(update.effective_user.id): 
            await query.answer("❌ 需要管理员权限"); 
            return
        await query.answer()
        if not self.source_manager.sources:
            await query.edit_message_text("📋 **同步源列表**\n\n暂无配置的同步源", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(" 返回源管理", callback_data="source_management")]]))
            return
        sources_info = []
        for name, source in self.source_manager.sources.items():
            last_sync = time.strftime('%m-%d %H:%M', time.localtime(source.last_sync)) if source.last_sync else "从未同步"
            next_sync_display = "立即"
            if source.enabled and source.next_sync_timestamp:
                time_left = source.next_sync_timestamp - time.time()
                if time_left > 0:
                    h, m, s = int(time_left // 3600), int((time_left % 3600) // 60), int(time_left % 60)
                    next_sync_display = f"{h}时{m}分后" if h > 0 else (f"{m}分后" if m > 0 else f"{s}秒后")
                else:
                    next_sync_display = "已到期"
            elif not source.enabled:
                next_sync_display = "已禁用"
            protocol_hint = source.protocol_hint.value.upper() if source.protocol_hint else "自动检测"
            info = f"{source.status_emoji} **{name}**\n   🔗 {source.url}\n   📊 成功率: {source.success_rate:.1f}% | 协议: {protocol_hint}\n   📈 代理数: {source.last_proxy_count} | 上次: {last_sync}\n   ⏱️ 间隔: {source.sync_interval_minutes}分钟 | 下次: {next_sync_display}"
            sources_info.append(info)
        keyboard = [[InlineKeyboardButton(f"{'禁用' if source.enabled else '启用'} {name}",
                                          callback_data=f"toggle_source_{name}")] for name, source in
                    self.source_manager.sources.items()]
        keyboard.append([InlineKeyboardButton(" 返回源管理", callback_data="source_management")])
        text = f"📋 **同步源列表**\n\n" + "\n\n".join(
            sources_info) + "\n\n📖 **状态说明**:\n✅ 成功率 ≥ 80% | ⚠️ 成功率 ≥ 50% | ❌ 成功率 < 50% | ⏸️ 已禁用"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def selective_sync(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self.check_admin_permission(update.effective_user.id): 
            await query.answer("❌ 需要管理员权限"); 
            return
        await query.answer()
        sources = self.source_manager.get_enabled_sources()
        if not sources: 
            await query.edit_message_text("❌ 没有可用的同步源", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔗 源管理", callback_data="source_management")]])); 
            return
        keyboard = [[InlineKeyboardButton(f"{s.status_emoji} 同步 {s.name}", callback_data=f"sync_single_{s.name}")] for
                    s in sources]
        keyboard.extend([[InlineKeyboardButton("🔄 同步所有源", callback_data="sync_all_sources")],
                         [InlineKeyboardButton(" 返回源管理", callback_data="source_management")]])
        await query.edit_message_text(f"🎯 **选择性同步**\n\n📊 **可用源**: {len(sources)} 个\n\n请选择要同步的源：",
                                      reply_markup=InlineKeyboardMarkup(keyboard))
                                      
                                      
    async def _sync_proxies(self) -> Dict:
        try:
            existing_proxies = [ProxyInfo(ip=p['server'], port=p['port'], name=p.get('name', ''), data=p) for p in
                                data_manager.load_proxies() if p.get('server') and p.get('port')]
            all_new_proxies, source_results = [], {}
            enabled_sources = self.source_manager.get_enabled_sources()
            if not enabled_sources: 
                return {'success': False, 'error': '没有启用任何同步源'}
            for source in enabled_sources:
                try:
                    content = await self.fetcher.fetch_from_url(source.url)
                    if content:
                        new_proxies = self.parser.parse_proxies(content, source_name=source.name)
                        all_new_proxies.extend(new_proxies)
                        source_results[source.name] = len(new_proxies)
                        self.source_manager.update_source_stats(source.name, True, len(new_proxies))
                    else:
                        source_results[source.name] = 0
                        self.source_manager.update_source_stats(source.name, False)
                except Exception as e:
                    source_results[source.name] = f"错误: {str(e)}"
                    self.source_manager.update_source_stats(source.name, False)
            if not all_new_proxies: 
                return {'success': False, 'error': '没有从任何源获取到有效新代理数据',
                        'source_results': source_results}
            merged_proxies, stats = await self.merger.merge_proxies(existing_proxies, all_new_proxies)
            proxy_data_list = [p.data for p in merged_proxies if p.data]
            with open(config.PROXIES_FILE, 'w', encoding='utf-8') as f:
                yaml.dump(proxy_data_list, f, default_flow_style=False, allow_unicode=True, sort_keys=False, indent=2)
            self.last_sync_time, self.total_synced_proxies = time.time(), len(merged_proxies)
            logger.info(f"成功保存 {len(merged_proxies)} 个代理到 {config.PROXIES_FILE}")
            stats['total_new'] = len(all_new_proxies)
            return {'success': True, 'stats': stats, 'source_results': source_results,
                    'total_proxies': len(merged_proxies)}
        except Exception as e:
            logger.error(f"同步代理失败: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _sync_single_source(self, source_name: str) -> Dict:
        try:
            source = self.source_manager.get_source_by_name(source_name)
            if not source or not source.enabled:
                if source:
                    self.source_manager.update_source_stats(source_name, False)
                return {'success': False, 'error': f'源 {source_name} 不存在或已禁用'}
            existing_proxies = [ProxyInfo(ip=p['server'], port=p['port'], name=p.get('name', ''), data=p) for p in
                                data_manager.load_proxies() if p.get('server') and p.get('port')]
            content = await self.fetcher.fetch_from_url(source.url)
            if not content: 
                self.source_manager.update_source_stats(source_name, False)
                return {'success': False, 'error': f'从源 {source_name} 获取内容失败'}
            new_proxies = self.parser.parse_proxies(content, source_name=source_name)
            if not new_proxies: 
                self.source_manager.update_source_stats(source_name, False)
                return {'success': False, 'error': f'从源 {source_name} 没有解析到代理'}
            merged_proxies, stats = await self.merger.merge_proxies(existing_proxies, new_proxies)
            proxy_data_list = [p.data for p in merged_proxies if p.data]
            with open(config.PROXIES_FILE, 'w', encoding='utf-8') as f:
                yaml.dump(proxy_data_list, f, default_flow_style=False, allow_unicode=True, sort_keys=False, indent=2)
            self.source_manager.update_source_stats(source_name, True, len(new_proxies))
            self.total_synced_proxies = len(merged_proxies)
            stats['total_new'] = len(new_proxies)
            return {'success': True, 'stats': stats, 'source_results': {source_name: len(new_proxies)},
                    'total_proxies': len(merged_proxies)}
        except Exception as e:
            logger.error(f"同步源 {source_name} 失败: {e}")
            self.source_manager.update_source_stats(source_name, False)
            return {'success': False, 'error': str(e)}
    
    async def start_auto_sync(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self.check_admin_permission(update.effective_user.id): 
            await query.answer("❌ 需要管理员权限"); 
            return
        if not self.source_manager.get_enabled_sources(): 
            await query.answer("❌ 请先添加并启用同步源", show_alert=True); 
            return
        await query.answer()
        await self.scheduler.start_scheduler(context)
        await query.edit_message_text(
            f"✅ **自动更新已启动**\n\n 启用源: {len(self.source_manager.get_enabled_sources())} 个",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(" 返回同步菜单", callback_data="proxy_sync")]]))
    
    async def stop_auto_sync(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        self.scheduler.stop_scheduler()
        await query.edit_message_text("⏹️ **自动更新已停止**", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(" 返回同步菜单", callback_data="proxy_sync")]]))
    
    async def set_sync_sources_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.add_source_prompt(update, context)
    
    async def handle_set_sync_sources(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.handle_add_source(update, context)
    
    async def set_source_interval_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not self.check_admin_permission(update.effective_user.id): 
            await query.answer("❌ 需要管理员权限"); 
            return
        await query.answer()
        sources = self.source_manager.sources.values()
        if not sources: 
            await query.edit_message_text("❌ 暂无源可设置", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 返回源管理", callback_data="source_management")]])); 
            return
        keyboard = [[InlineKeyboardButton(f"⏱️ {s.name} ({s.sync_interval_minutes}分钟)",
                                          callback_data=f"set_interval_for_{s.name}")] for s in sources]
        keyboard.append([InlineKeyboardButton("🔙 返回源管理", callback_data="source_management")])
        await query.edit_message_text("⏱️ **设置源同步间隔**\n\n请选择要设置的源：",
                                      reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def handle_set_interval_for_source(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        source_name = query.data[len("set_interval_for_"):]
        if not self.check_admin_permission(update.effective_user.id): 
            await query.answer("❌ 需要管理员权限"); 
            return
        source = self.source_manager.get_source_by_name(source_name)
        if not source: 
            await query.answer("❌ 源不存在。"); 
            return
        self.user_states[update.effective_chat.id] = f'setting_interval_{source_name}'
        await query.edit_message_text(
            f"⏱️ **设置源 '{source_name}' 的同步间隔**\n\n当前: {source.sync_interval_minutes} 分钟\n\n请发送新的间隔（分钟）：",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 返回源管理", callback_data="source_management")]]))
    
    async def handle_interval_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        state = self.user_states.get(chat_id)
        if not state or not state.startswith('setting_interval_'):
            return
        source_name = state[len('setting_interval_'):]
        if update.message.text.lower() == '/cancel':
            self.user_states.pop(chat_id, None)
            await update.message.reply_text("已取消。", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 返回源管理", callback_data="source_management")]]))
            return
        try:
            interval = int(update.message.text.strip())
            if interval < 5: 
                await update.message.reply_text("❌ 间隔不能少于5分钟。"); 
                return
            if self.source_manager.set_source_interval(source_name, interval):
                self.user_states.pop(chat_id, None)
                await update.message.reply_text(f"✅ 源 '{source_name}' 间隔已设为 {interval} 分钟。",
                                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 查看源列表",
                                                                                                         callback_data="list_sources"),
                                                                                    InlineKeyboardButton("🔙 返回源管理",
                                                                                                         callback_data="source_management")]]))
            else:
                await update.message.reply_text("❌ 设置失败。")
        except ValueError:
            await update.message.reply_text("❌ 请输入有效的数字。")
    
    async def test_sync_sources(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.refresh_sources(update, context)
    
    async def reset_sync_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        self.scheduler.stop_scheduler()
        self.source_manager = ProxySourceManager()
        self.last_sync_time, self.total_synced_proxies = None, 0
        await query.edit_message_text("✅ **设置已重置**", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 返回设置", callback_data="sync_settings")]]))
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理消息输入 - 增加对设置源间隔状态的处理。"""
        chat_id = update.effective_chat.id
        state = self.user_states.get(chat_id)
    
        if state == 'adding_source':
            await self.handle_add_source(update, context)
        elif state and state.startswith('setting_interval_'):
            await self.handle_interval_input(update, context)
        else:
            # 非本模块状态，交由主消息处理器处理
            pass
    
    async def show_sync_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        status_text = "🟢 运行中" if self.scheduler.is_running else "🔴 已停止"
        enabled_sources, total_sources = self.source_manager.get_enabled_sources(), len(self.source_manager.sources)
        healthy_sources = len([s for s in enabled_sources if s.success_rate >= 80])
        protocol_stats = {}
        try:
            for p in data_manager.load_proxies(): 
                protocol_stats[p.get('type', 'unknown')] = protocol_stats.get(p.get('type', 'unknown'), 0) + 1
        except Exception:
            pass
        protocol_text = "\n\n📋 **当前代理协议分布**:\n" + "\n".join(
            [f"• {k.upper()}: {v} 个" for k, v in protocol_stats.items()]) if protocol_stats else ""
        last_sync_text = time.strftime('%Y-%m-%d %H:%M:%S',
                                       time.localtime(self.last_sync_time)) if self.last_sync_time else "从未同步"
        source_status_list = []
        for name, source in self.source_manager.sources.items():
            next_sync_str = "立即"
            if source.enabled and source.next_sync_timestamp:
                rem = int(source.next_sync_timestamp - time.time())
                if rem > 0:
                    next_sync_str = f"{rem // 3600}h{(rem % 3600) // 60}m" if rem > 3600 else f"{(rem % 3600) // 60}m{rem % 60}s"
                else:
                    next_sync_str = "已到期"
            elif not source.enabled:
                next_sync_str = "已禁用"
            source_status_list.append(
                f"  {source.status_emoji} {name} (间隔:{source.sync_interval_minutes}m, 下次:{next_sync_str})")
        source_status_text = "\n\n🔗 **源状态**:\n" + "\n".join(source_status_list) if source_status_list else ""
        text = f"""📊 **系统同步状态**
    
    🔄 **自动更新**: {status_text} (间隔: {self.scheduler.scheduler_loop_interval}秒)
    🔗 **同步源**: {len(enabled_sources)}/{total_sources} 个启用
    ✅ **健康源**: {healthy_sources} 个 (成功率≥80%)
    🌍 **国家查询**: 限速模式 ({self.country_provider.delay}秒间隔)
    
    📈 **运行统计**:
    • 代理总数: {self.total_synced_proxies} 个
    • 上次全局同步: {last_sync_text}
    • IP缓存: {len(self.country_provider.cache)} 个{protocol_text}{source_status_text}"""
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 刷新状态",
                                                                                                     callback_data="sync_status"),
                                                                                InlineKeyboardButton("🔙 返回同步菜单",
                                                                                                     callback_data="proxy_sync")]]))
    
    async def show_sync_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        log_entries = []
        all_synced_sources = sorted([s for s in self.source_manager.sources.values() if s.last_sync is not None],
                                    key=lambda x: x.last_sync, reverse=True)
        for source in all_synced_sources[:10]:
            log_entries.append(
                f"• {time.strftime('%m-%d %H:%M', time.localtime(source.last_sync))} - {source.name}: {source.status_emoji} ({source.last_proxy_count} 个代理, {source.success_rate:.1f}%)")
        logs_text = "\n".join(log_entries) if log_entries else "暂无同步记录"
        await query.edit_message_text(f"📋 **同步日志**\n\n    📈 **最近10次同步记录**:\n    {logs_text}",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 刷新日志",
                                                                                               callback_data="sync_logs"),
                                                                          InlineKeyboardButton("🔙 返回同步菜单",
                                                                                               callback_data="proxy_sync")]]))
    
    async def handle_sync_single_source(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        source_name = query.data[12:]
        if not self.check_admin_permission(update.effective_user.id): 
            await query.answer("❌ 需要管理员权限"); 
            return
        await query.answer()
        await query.edit_message_text(f"🔄 正在同步源: {source_name}，请稍候...")
        try:
            result = await self._sync_single_source(source_name)
            if result['success']:
                await query.edit_message_text(self._generate_sync_report_static(result),
                                              reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎯 继续选择同步",
                                                                                                       callback_data="selective_sync"),
                                                                                  InlineKeyboardButton(
                                                                                      " 返回同步菜单",
                                                                                      callback_data="proxy_sync")]]))
            else:
                await query.edit_message_text(f"❌ 同步源 {source_name} 失败: {result.get('error', '未知错误')}",
                                              reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎯 返回选择同步",
                                                                                                       callback_data="selective_sync")]]))
        except Exception as e:
            await query.edit_message_text(f"❌ 同步源 {source_name} 时发生错误: {str(e)}",
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎯 返回选择同步",
                                                                                                   callback_data="selective_sync")]]))
    
    async def handle_toggle_source(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        source_name = query.data[14:]
        if not self.check_admin_permission(update.effective_user.id): 
            await query.answer("❌ 需要管理员权限"); 
            return
        source = self.source_manager.get_source_by_name(source_name)
        if not source: 
            await query.answer("❌ 源不存在"); 
            return
        new_status = not source.enabled
        self.source_manager.enable_source(source_name, new_status)
        await query.answer(f"✅ 已{'启用' if new_status else '禁用'}源: {source_name}")
        await self.list_sources(update, context)
    
    async def sync_all_sources_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.manual_sync(update, context)
    
    async def test_deduplication(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        results = []
        try:
            existing_data = data_manager.load_proxies()
            results.append(f"📄 当前文件中的代理数量: {len(existing_data)}")
            server_port_map = {ProxyInfo(ip=p['server'], port=p['port']).unique_key: 0 for p in existing_data if p.get('server') and p.get('port')}
            for p in existing_data:
                key = ProxyInfo(ip=p['server'], port=p['port']).unique_key
                server_port_map[key] += 1
            duplicates = {k: v for k, v in server_port_map.items() if v > 1}
            if duplicates:
                results.append(f"⚠️ 发现重复项: {len(duplicates)} 个")
                for k, v in list(duplicates.items())[:5]:
                    results.append(f"  • {k}: {v} 次")
            else:
                results.append("✅ 未发现重复项")
        except Exception as e:
            results.append(f"❌ 测试失败: {str(e)}")
        await query.edit_message_text(f"🔍 **去重功能测试**\n\n" + "\n".join(results), reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔄 重新测试", callback_data="test_deduplication"),
              InlineKeyboardButton("🔙 返回", callback_data="sync_status")]]))
          
          
def register_proxy_sync_handlers(application):
    """
    优化的注册函数，确保所有回调都被正确注册
    """
    handler = ProxySyncHandler()

    # 定义所有需要注册的回调（确保完整覆盖）
    callback_definitions = [
        ("proxy_sync", handler.show_sync_menu),
        ("source_management", handler.source_management),
        ("manual_sync", handler.manual_sync),
        ("sync_settings", handler.sync_settings),
        ("add_source", handler.add_source_prompt),
        ("remove_source", handler.remove_source_prompt),
        ("list_sources", handler.list_sources),
        ("refresh_sources", handler.refresh_sources),
        ("selective_sync", handler.selective_sync),
        ("sync_all_sources", handler.sync_all_sources_callback),
        ("set_source_interval_prompt", handler.set_source_interval_prompt),
        ("test_sync_sources", handler.test_sync_sources),
        ("reset_sync_settings", handler.reset_sync_settings),
        ("start_auto_sync", handler.start_auto_sync),
        ("stop_auto_sync", handler.stop_auto_sync),
        ("sync_status", handler.show_sync_status),
        ("sync_logs", handler.show_sync_logs),
        ("test_deduplication", handler.test_deduplication)
    ]

    # 注册精确匹配的回调处理器，使用最高优先级
    for pattern, callback_func in callback_definitions:
        application.add_handler(
            CallbackQueryHandler(callback_func, pattern=f"^{pattern}$"),
            group=0
        )
        logger.info(f"注册回调处理器: {pattern}")

    # 注册前缀匹配的回调处理器
    prefix_handlers = [
        (r"^sync_single_", handler.handle_sync_single_source),
        (r"^toggle_source_", handler.handle_toggle_source),
        (r"^delete_source_", handler.handle_delete_source),
        (r"^confirm_delete_", handler.handle_confirm_delete_source),
        (r"^set_interval_for_", handler.handle_set_interval_for_source),
    ]

    for pattern, callback_func in prefix_handlers:
        application.add_handler(
            CallbackQueryHandler(callback_func, pattern=pattern),
            group=0
        )
        logger.info(f"注册前缀回调处理器: {pattern}")

    return handler
    
    
    