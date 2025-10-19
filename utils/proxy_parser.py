# utils/proxy_parser.py (增强版 - Part 1)
import base64
import json
import urllib.parse
import logging
import requests
import yaml
from typing import Optional, Dict, Any, Union, List

logger = logging.getLogger(__name__)

def skip_cn(ip):
    """跳过中国IP的函数"""
    try:
        api_url = f"http://ip-api.com/json/{ip}"
        api_response = requests.get(api_url, timeout=3).json()
        if api_response['status'] == 'success':
            return api_response['countryCode']
    except:
        return None

class ProxyParser:
    """
    统一代理解析器 - 支持链接和YAML格式
    遵循SOLID原则：SRP专注解析，OCP支持扩展，DRY避免重复
    """
    
    # YAML字段映射表（遵循DRY原则）
    YAML_FIELD_MAPPING = {
        'pbk': 'public-key',
        'sid': 'short-id', 
        'clientHelloVersion': 'client-hello-version',
        'servername': 'servername',
        'server': 'server',
        'port': 'port',
        'uuid': 'uuid',
        'name': 'name',
        'type': 'type',
        'network': 'network',
        'tls': 'tls',
        'udp': 'udp',
        'skip-cert-verify': 'skip-cert-verify',
        'flow': 'flow',
    }
    
    @staticmethod
    def _add_optional_field(node: Dict[str, Any], key: str, value: Any) -> None:
        """通用可选字段添加 - 遵循YAGNI原则"""
        if value and str(value).strip():
            node[key] = value
    
    @staticmethod
    def _add_optional_dict(node: Dict[str, Any], key: str, opts: Dict[str, Any]) -> None:
        """添加可选字典配置"""
        if opts:
            node[key] = opts
    
    @staticmethod
    def _get_param_value(params: Dict, key: str, default: str = '') -> str:
        """安全获取参数值 - 统一处理各种参数格式"""
        if not params or key not in params:
            return default
        
        value = params[key]
        if isinstance(value, list):
            value = value[0] if value else default
        elif value is None:
            value = default
            
        return value.strip() if isinstance(value, str) else str(value) if value else default
    
    @staticmethod
    def _parse_alpn_value(alpn_str: str) -> List[str]:
        """解析ALPN参数值为列表 - 遵循DRY原则"""
        if not alpn_str:
            return []
        
        # 处理URL编码
        alpn_str = urllib.parse.unquote(alpn_str)
        
        # 支持多种分隔符
        if ',' in alpn_str:
            return [a.strip() for a in alpn_str.split(',') if a.strip()]
        elif '%2C' in alpn_str:
            return [a.strip() for a in alpn_str.split('%2C') if a.strip()]
        else:
            return [alpn_str.strip()] if alpn_str.strip() else []
    
    @staticmethod
    def _decode_base64_param(param_value: str) -> str:
        """安全Base64解码"""
        if not param_value:
            return ''
        try:
            return base64.urlsafe_b64decode(param_value + '=' * (-len(param_value) % 4)).decode('utf-8')
        except Exception:
            return ''

    @staticmethod
    def _clean_vip_chars(name: str) -> str:
        """
        清理VIP相关字符 - 遵循DRY原则
        统一处理所有协议的名称清理逻辑
        """
        if not name:
            return name

        # VIP相关字符清理列表
        vip_patterns = ['VIP', 'vip', 'Vip', 'ViP', 'vIp', 'viP', 'vIP', 'VIp']

        cleaned_name = name
        for pattern in vip_patterns:
            cleaned_name = cleaned_name.replace(pattern, '')

        # 清理多余的空格、连字符、下划线等
        cleaned_name = cleaned_name.strip(' -_|')

        return cleaned_name if cleaned_name else name
        
    @staticmethod
    def parse_proxy(input_data: Union[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        统一代理解析入口 - 支持链接和字典格式
        遵循OCP原则：通过扩展支持新格式
        """
        if isinstance(input_data, str):
            input_data = input_data.strip()
            # 检查是否为协议链接
            protocol_prefixes = ['ss://', 'vmess://', 'ssr://', 'vless://', 'trojan://', 'hysteria://', 'hy2://', 'hysteria2://']
            if any(input_data.startswith(prefix) for prefix in protocol_prefixes):
                return ProxyParser.parse_proxy_link(input_data)
            
            # 尝试解析为YAML字符串
            try:
                yaml_data = yaml.safe_load(input_data)
                if isinstance(yaml_data, dict):
                    return ProxyParser._parse_yaml_config(yaml_data)
            except:
                pass
                
        elif isinstance(input_data, dict):
            return ProxyParser._parse_yaml_config(input_data)
        
        return None
    
    @staticmethod
    def parse_proxy_link(link: str) -> Optional[Dict[str, Any]]:
        """链接格式解析入口"""
        link = link.strip()
        
        parsers = {
            'ss://': ProxyParser._parse_ss,
            'vmess://': ProxyParser._parse_vmess,
            'ssr://': ProxyParser._parse_ssr,
            'vless://': ProxyParser._parse_vless,
            'trojan://': ProxyParser._parse_trojan,
            'hysteria://': ProxyParser._parse_hysteria,
            'hy2://': ProxyParser._parse_hysteria,
            'hysteria2://': ProxyParser._parse_hysteria,
        }
        
        for prefix, parser in parsers.items():
            if link.startswith(prefix):
                try:
                    result = parser(link)
                    if result:
                        logger.debug(f"解析{prefix}链接成功: {result.get('name', 'Unknown')}")
                        return result
                    else:
                        logger.warning(f"解析{prefix}链接返回None")
                        return None
                except Exception as e:
                    logger.error(f"解析{prefix}链接失败: {e}")
                    return None
            
        logger.error(f"未找到匹配的协议解析器")
        return None
    
    @staticmethod
    def _parse_vless(link: str) -> Optional[Dict[str, Any]]:
        """
        VLESS链接解析器 - 完整修复版
        遵循KISS原则：简化逻辑，专注核心功能
        """
        try:
            link = link.strip()
    
            if not link.startswith("vless://"):
                logger.warning("不是VLESS协议链接")
                return None
    
            link = link[8:]  # 移除 vless://
    
            # 解析名称部分
            name = "VLESS节点"
            if "#" in link:
                link, name_part = link.split("#", 1)
                name = urllib.parse.unquote(name_part)
                name = ProxyParser._clean_vip_chars(name)
    
            # 解析查询参数
            params = {}
            if "?" in link:
                link, query = link.split("?", 1)
                params = urllib.parse.parse_qs(query)
    
            # 解析核心部分
            if "@" not in link:
                # Base64编码格式
                try:
                    link = base64.urlsafe_b64decode(link + '=' * (-len(link) % 4)).decode('utf-8')
                except Exception:
                    logger.error("Base64解码失败")
                    return None
    
            if "@" not in link:
                logger.error("链接格式错误：缺少@分隔符")
                return None
    
            uuid_part, server_part = link.split("@", 1)
    
            # 处理UUID
            uuid = uuid_part
            if uuid.startswith('auto:'):
                uuid = uuid[5:]
    
            # 移除路径部分（如果存在）
            if "/" in server_part:
                server_part = server_part.split("/")[0]
    
            # 解析服务器和端口
            if server_part.startswith('['):
                # IPv6格式
                if "]:" not in server_part:
                    logger.error("IPv6格式错误")
                    return None
                server, port_str = server_part[1:].split("]:", 1)
            else:
                # IPv4格式
                if ":" not in server_part:
                    logger.error("缺少端口信息")
                    return None
                server, port_str = server_part.rsplit(":", 1)
    
            # 验证端口
            try:
                port = int(port_str)
                if port < 1 or port > 65535:
                    logger.error(f"端口超出范围: {port}")
                    return None
            except ValueError:
                logger.error(f"端口格式错误: {port_str}")
                return None
    
            # 验证必需字段
            if not uuid or not server:
                logger.error(f"必需字段缺失 - UUID: {bool(uuid)}, Server: {bool(server)}")
                return None
            
            # 构建基础配置
            node = {
                "name": name,
                "type": "vless",
                "server": server,
                "port": port,
                "uuid": uuid
            }
    
            # 处理参数配置
            if params:
                # 网络类型
                network = ProxyParser._get_param_value(params, "type", "tcp")
                node["network"] = network
    
                # 处理encryption参数（VLESS默认为none）
                encryption = ProxyParser._get_param_value(params, "encryption", "none")
    
                # Flow配置处理
                flow_value = ProxyParser._get_param_value(params, "flow")
                xtls_value = ProxyParser._get_param_value(params, "xtls")
    
                # 处理xtls参数到flow的映射
                if xtls_value:
                    xtls_int = int(xtls_value) if xtls_value.isdigit() else 0
                    if xtls_int == 2:
                        node["flow"] = "xtls-rprx-vision"
                    elif xtls_int == 1:
                        node["flow"] = "xtls-rprx-direct"
                elif flow_value and flow_value.strip():
                    node["flow"] = flow_value.strip()
    
                # TLS配置检测
                tls_value = ProxyParser._get_param_value(params, "tls")
                security = ProxyParser._get_param_value(params, "security", "none")
                pbk = ProxyParser._get_param_value(params, "pbk")
    
                # 更准确的TLS检测逻辑
                need_tls = (
                    tls_value in ["1", "true", "True"] or
                    security in ["tls", "reality"] or
                    bool(pbk and pbk.strip())
                )
    
                if need_tls:
                    node["tls"] = True
                    node["skip-cert-verify"] = False
    
                    # 服务器名称优先级：sni > peer > host > server
                    sni = (ProxyParser._get_param_value(params, "sni") or
                           ProxyParser._get_param_value(params, "peer") or
                           ProxyParser._get_param_value(params, "host") or
                           server)
    
                    if sni:
                        node["servername"] = sni
    
                    # 处理ALPN参数
                    alpn_value = ProxyParser._get_param_value(params, "alpn")
                    if alpn_value:
                        alpn_list = ProxyParser._parse_alpn_value(alpn_value)
                        if alpn_list:
                            node["alpn"] = alpn_list
    
                    # 客户端指纹
                    fp = ProxyParser._get_param_value(params, "fp")
                    if fp and fp.strip():
                        node["client-fingerprint"] = fp.strip()
    
                    # Reality配置
                    if pbk and pbk.strip():
                        reality_opts = {"public-key": pbk.strip()}
    
                        sid = ProxyParser._get_param_value(params, "sid")
                        if sid and str(sid).strip():
                            reality_opts["short-id"] = str(sid).strip()
    
                        node["reality-opts"] = reality_opts
    
                # WebSocket配置处理
                if network == "ws":
                    ws_opts = {}
                    
                    # 处理path参数
                    path = ProxyParser._get_param_value(params, "path", "/")
                    if path:
                        ws_opts["path"] = urllib.parse.unquote(path)
                    
                    # 处理host参数到headers
                    host = ProxyParser._get_param_value(params, "host")
                    if host:
                        ws_opts["headers"] = {"Host": host}
                    
                    if ws_opts:
                        node["ws-opts"] = ws_opts
    
                # gRPC配置处理
                elif network == "grpc":
                    grpc_opts = {}
                    service_name = ProxyParser._get_param_value(params, "serviceName")
                    if service_name:
                        grpc_opts["grpc-service-name"] = service_name
                    
                    if grpc_opts:
                        node["grpc-opts"] = grpc_opts
    
            else:
                # 无参数时的默认配置
                node["network"] = "tcp"
    
            # remarks参数处理，覆盖URL解析的名称
            remarks = ProxyParser._get_param_value(params, "remarks")
            if remarks:
                node["name"] = ProxyParser._clean_vip_chars(urllib.parse.unquote(remarks))
    
            # 尝试获取国家代码
            try:
                c_name = skip_cn(server)
                if c_name and not node["name"].startswith(c_name):
                    node["name"] = c_name + "|" + ProxyParser._clean_vip_chars(node["name"])
            except (NameError, Exception):
                pass
    
            logger.debug(f"VLESS节点解析成功: {node.get('name')}")
            return node
    
        except Exception as e:
            logger.error(f"解析VLESS链接失败: {e}")
            import traceback
            traceback.print_exc()
            return None
        # ==================== YAML格式解析器 ====================
    
    @staticmethod
    def _parse_yaml_config(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        YAML配置解析器统一入口
        遵循OCP原则：通过代理模式支持扩展不同类型解析器
        """
        try:
            proxy_type = config.get('type', '').lower()
    
            # 类型映射表 - 遵循DRY原则
            type_parsers = {
                'vmess': ProxyParser._parse_vmess_yaml,
                'ss': ProxyParser._parse_ss_yaml,
                'shadowsocks': ProxyParser._parse_ss_yaml,  # 别名支持
                'ssr': ProxyParser._parse_ssr_yaml,
                'shadowsocksr': ProxyParser._parse_ssr_yaml,  # 别名支持
                'vless': ProxyParser._parse_vless_yaml,
                'trojan': ProxyParser._parse_trojan_yaml,
                'hysteria': ProxyParser._parse_hysteria_yaml,
                'hysteria2': ProxyParser._parse_hysteria_yaml,
                'hy2': ProxyParser._parse_hysteria_yaml,
            }
    
            # 验证必需字段
            required_fields = ['server', 'port']
            for field in required_fields:
                if field not in config:
                    logger.error(f"YAML配置缺少必需字段: {field}")
                    return None
    
            # 调用对应解析器
            parser = type_parsers.get(proxy_type)
            if not parser:
                logger.error(f"不支持的代理类型: {proxy_type}")
                return None
    
            return parser(config)
    
        except Exception as e:
            logger.error(f"解析YAML配置失败: {e}")
            return None
    
    @staticmethod
    def _parse_vless_yaml(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """VLESS类型YAML配置解析 - 增强版"""
        try:
            original_name = config.get('name', f"VLESS_{config['server']}")
            cleaned_name = ProxyParser._clean_vip_chars(original_name)
            
            # 构建基础配置
            node = {
                'name': cleaned_name,
                'type': 'vless',
                'server': config['server'],
                'port': int(config['port']),
                'uuid': config['uuid'],
                'network': config.get('network', 'tcp'),
                'udp': config.get('udp', True),
            }
    
            # 处理Flow配置
            ProxyParser._add_optional_field(node, 'flow', config.get('flow'))
    
            # 处理TLS配置
            if config.get('tls', False):
                node['tls'] = True
                node['skip-cert-verify'] = config.get('skip-cert-verify', False)
    
                # 服务器名称配置
                servername = config.get('servername') or config.get('sni') or config['server']
                node['servername'] = servername
    
                # 处理ALPN配置
                if 'alpn' in config:
                    alpn = config['alpn']
                    if isinstance(alpn, str):
                        node['alpn'] = [alpn]
                    elif isinstance(alpn, list):
                        node['alpn'] = alpn
    
                # 客户端指纹
                ProxyParser._add_optional_field(node, 'client-fingerprint', config.get('client-fingerprint'))
    
                # Reality配置
                if 'reality-opts' in config:
                    reality_opts = {}
                    reality_config = config['reality-opts']
    
                    if 'public-key' in reality_config:
                        reality_opts['public-key'] = reality_config['public-key']
    
                    ProxyParser._add_optional_field(reality_opts, 'short-id', reality_config.get('short-id'))
    
                    if reality_opts:
                        node['reality-opts'] = reality_opts
    
            # 处理传输层配置
            network = config.get('network', 'tcp')
    
            if network == 'ws' and 'ws-opts' in config:
                node['ws-opts'] = config['ws-opts']
            elif network == 'grpc' and 'grpc-opts' in config:
                node['grpc-opts'] = config['grpc-opts']
            elif network == 'h2' and 'h2-opts' in config:
                node['h2-opts'] = config['h2-opts']
            elif network == 'kcp' and 'kcp-opts' in config:
                node['kcp-opts'] = config['kcp-opts']
    
            return node
    
        except Exception as e:
            logger.error(f"解析VLESS YAML配置失败: {e}")
            return None
    
    @staticmethod
    def _parse_vmess_yaml(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """VMess类型YAML配置解析"""
        try:
            node = {
                'name': ProxyParser._clean_vip_chars(config.get('name', f"VMess_{config['server']}")),
                'type': 'vmess',
                'server': config['server'],
                'port': int(config['port']),
                'uuid': config['uuid'],
                'alterId': config.get('alterId', 0),
                'cipher': config.get('cipher', 'auto'),
                'network': config.get('network', 'tcp'),
                'udp': config.get('udp', True),
            }
            
            if config.get('tls', False):
                node['tls'] = True
                ProxyParser._add_optional_field(node, 'servername', config.get('servername'))
                
                # 处理ALPN
                if 'alpn' in config:
                    alpn = config['alpn']
                    if isinstance(alpn, str):
                        node['alpn'] = [alpn]
                    elif isinstance(alpn, list):
                        node['alpn'] = alpn
            
            network = config.get('network', 'tcp')
            if network == 'ws' and 'ws-opts' in config:
                node['ws-opts'] = config['ws-opts']
            elif network == 'h2' and 'h2-opts' in config:
                node['h2-opts'] = config['h2-opts']
                
            return node
            
        except Exception as e:
            logger.error(f"解析VMess YAML配置失败: {e}")
            return None
    
    @staticmethod
    def _parse_ss_yaml(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Shadowsocks类型YAML配置解析"""
        try:
            node = {
                'name': ProxyParser._clean_vip_chars(config.get('name', f"SS_{config['server']}")),
                'type': 'ss',
                'server': config['server'],
                'port': int(config['port']),
                'cipher': config['cipher'],
                'password': config['password'],
                'udp': config.get('udp', True),
            }
            
            if 'plugin' in config:
                node['plugin'] = config['plugin']
                ProxyParser._add_optional_dict(node, 'plugin-opts', config.get('plugin-opts', {}))
                
            return node
            
        except Exception as e:
            logger.error(f"解析SS YAML配置失败: {e}")
            return None
    
    @staticmethod
    def _parse_ssr_yaml(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """SSR类型YAML配置解析"""
        try:
            node = {
                'name': ProxyParser._clean_vip_chars(config.get('name', f"SSR_{config['server']}")),
                'type': 'ssr',
                'server': config['server'],
                'port': int(config['port']),
                'cipher': config['cipher'],
                'password': config['password'],
                'protocol': config['protocol'],
                'obfs': config['obfs'],
                'udp': config.get('udp', True),
            }
            
            ProxyParser._add_optional_field(node, 'protocol-param', config.get('protocol-param'))
            ProxyParser._add_optional_field(node, 'obfs-param', config.get('obfs-param'))
            ProxyParser._add_optional_field(node, 'group', config.get('group'))
            
            return node
            
        except Exception as e:
            logger.error(f"解析SSR YAML配置失败: {e}")
            return None
    
    @staticmethod
    def _parse_trojan_yaml(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Trojan类型YAML配置解析"""
        try:
            node = {
                'name': ProxyParser._clean_vip_chars(config.get('name', f"Trojan_{config['server']}")),
                'type': 'trojan',
                'server': config['server'],
                'port': int(config['port']),
                'password': config['password'],
                'udp': config.get('udp', True),
            }
            
            ProxyParser._add_optional_field(node, 'sni', config.get('sni'))
            
            # 处理ALPN
            if 'alpn' in config:
                alpn = config['alpn']
                if isinstance(alpn, str):
                    node['alpn'] = [alpn]
                elif isinstance(alpn, list):
                    node['alpn'] = alpn
            
            return node
            
        except Exception as e:
            logger.error(f"解析Trojan YAML配置失败: {e}")
            return None
    
    @staticmethod
    def _parse_hysteria_yaml(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Hysteria类型YAML配置解析"""
        try:
            proxy_type = config.get('type', 'hysteria2')
            
            node = {
                'name': ProxyParser._clean_vip_chars(config.get('name', f"{proxy_type.title()}_{config['server']}")),
                'type': proxy_type,
                'server': config['server'],
                'port': int(config['port']),
                'password': config.get('password', ''),
                'udp': config.get('udp', True),
                'tfo': config.get('tfo', False),
            }
            
            # Hysteria2专有配置
            if proxy_type == 'hysteria2':
                ProxyParser._add_optional_field(node, 'up', config.get('up'))
                ProxyParser._add_optional_field(node, 'down', config.get('down'))
            
            ProxyParser._add_optional_field(node, 'sni', config.get('sni'))
            
            # 处理ALPN
            if 'alpn' in config:
                alpn = config['alpn']
                if isinstance(alpn, str):
                    node['alpn'] = [alpn]
                elif isinstance(alpn, list):
                    node['alpn'] = alpn
            
            if 'skip-cert-verify' in config:
                node['skip-cert-verify'] = config['skip-cert-verify']
            
            return node
            
        except Exception as e:
            logger.error(f"解析Hysteria YAML配置失败: {e}")
            return None
        
        # ==================== 链接格式解析器 ====================
    
    @staticmethod
    def _parse_ss(link: str) -> Optional[Dict[str, Any]]:
        """Shadowsocks链接解析 - 支持插件配置"""
        try:
            name = "SS节点"
            if '#' in link:
                link, name_part = link.split('#', 1)
                name = urllib.parse.unquote(name_part)
                name = ProxyParser._clean_vip_chars(name)
    
            link = link[5:]  # 移除 ss://
            
            params = {}
            if '?' in link:
                link, query_part = link.split('?', 1)
                plugin_str = urllib.parse.unquote(query_part)
                if 'plugin=' in plugin_str:
                    params['plugin'] = plugin_str.split('plugin=')[1]
            
            # 解析认证和服务器信息
            if '@' not in link:
                auth_part = link
                server_part = ""
            else:
                auth_part, server_part = link.rsplit('@', 1)
            
            try:
                decoded = base64.urlsafe_b64decode(auth_part + '=' * (-len(auth_part) % 4)).decode('utf-8')
                method, password = decoded.split(':', 1)
            except Exception:
                if ':' in auth_part:
                    method, password = auth_part.split(':', 1)
                else:
                    return None
    
            if not server_part: 
                return None
    
            # 兼容IPv6地址
            if server_part.startswith('['):
                server, port = server_part[1:].split("]:", 1)
            else:
                server, port = server_part.rsplit(':', 1)
    
            try:
                c_name = skip_cn(server)
                if c_name:
                    name = c_name + "|" + ProxyParser._clean_vip_chars(name)
            except (NameError, Exception):
                pass
    
            node = {
                'name': name, 
                'type': 'ss', 
                'server': server,
                'port': int(port), 
                'cipher': method, 
                'password': password,
                'udp': True
            }
    
            # 处理插件配置
            if 'plugin' in params and params['plugin']:
                plugin_data = params['plugin'].split(';')
                plugin_type = plugin_data[0]
                
                if plugin_type == 'obfs':
                    node['plugin'] = 'obfs'
                    opts = {'mode': 'http'}
                    for p in plugin_data[1:]:
                        if 'obfs=' in p: 
                            opts['mode'] = p.split('=')[1]
                        if 'obfs-host=' in p: 
                            host_value = p.split('=')[1]
                            if host_value:
                                opts['host'] = host_value
                    node['plugin-opts'] = opts
    
                elif plugin_type == 'v2ray-plugin':
                    node['plugin'] = 'v2ray-plugin'
                    opts = {'mode': 'websocket'}
                    for p in plugin_data[1:]:
                        if p == 'tls': 
                            opts['tls'] = True
                        if 'host=' in p: 
                            host_value = p.split('=')[1]
                            if host_value:
                                opts['host'] = host_value
                        if 'path=' in p: 
                            path_value = p.split('=')[1]
                            if path_value:
                                opts['path'] = path_value
                    node['plugin-opts'] = opts
            
            return node
    
        except Exception as e:
            logger.error(f"解析SS链接失败: {e}")
            return None
    
    @staticmethod
    def _parse_ssr(link: str) -> Optional[Dict[str, Any]]:
        """SSR链接解析 - 支持混淆和协议参数"""
        try:
            link = link[6:]  # 移除 ssr://
            decoded_str = base64.urlsafe_b64decode(link + '=' * (-len(link) % 4)).decode('utf-8')
            
            parts = decoded_str.split(':')
            if len(parts) != 6:
                return None
    
            server = parts[0]
            port = int(parts[1])
            protocol = parts[2]
            method = parts[3]
            obfs = parts[4]
            
            password_part, params_part = parts[5].split('/?')
            password = base64.urlsafe_b64decode(password_part + '=' * (-len(password_part) % 4)).decode('utf-8')
            
            params = urllib.parse.parse_qs(params_part)
            
            name_b64 = params.get('remarks', [''])[0]
            name = base64.urlsafe_b64decode(name_b64 + '=' * (-len(name_b64) % 4)).decode('utf-8') if name_b64 else f"SSR_{server}"
            
            try:
                c_name = skip_cn(server)
                if c_name:
                    name = c_name + "|" + ProxyParser._clean_vip_chars(name)
            except (NameError, Exception):
                pass
    
            node = {
                'name': name,
                'type': 'ssr',
                'server': server,
                'port': port,
                'cipher': method,
                'password': password,
                'protocol': protocol,
                'obfs': obfs,
                'udp': True,
            }
            
            # 处理可选参数
            group_b64 = params.get('group', [''])[0]
            if group_b64:
                group = base64.urlsafe_b64decode(group_b64 + '=' * (-len(group_b64) % 4)).decode('utf-8')
                if group and group != "Default":
                    node['group'] = group
    
            obfs_param = params.get('obfsparam', [''])[0]
            if obfs_param:
                decoded_obfs_param = base64.urlsafe_b64decode(obfs_param + '=' * (-len(obfs_param) % 4)).decode('utf-8')
                if decoded_obfs_param:
                    node['obfs-param'] = decoded_obfs_param
    
            protocol_param = params.get('protoparam', [''])[0]
            if protocol_param:
                decoded_protocol_param = base64.urlsafe_b64decode(protocol_param + '=' * (-len(protocol_param) % 4)).decode('utf-8')
                if decoded_protocol_param:
                    node['protocol-param'] = decoded_protocol_param
            
            return node
        
        except Exception as e:
            logger.error(f"解析SSR链接失败: {e}")
            return None
    
    @staticmethod
    def _parse_vmess(link: str) -> Optional[Dict[str, Any]]:
        """VMess链接解析 - 支持WebSocket和HTTP/2传输"""
        try:
            link = link[8:]  # 移除 vmess://
            decoded_str = base64.urlsafe_b64decode(link + '=' * (-len(link) % 4)).decode('utf-8')
            config = json.loads(decoded_str)
    
            server = config.get('add')
            name = config.get('ps', 'VMess节点')
            
            try:
                c_name = skip_cn(server)
                if c_name:
                    name = c_name + "|" + ProxyParser._clean_vip_chars(name)
            except (NameError, Exception):
                pass
    
            node = {
                'name': name,
                'type': 'vmess',
                'server': server,
                'port': int(config.get('port', 443)),
                'uuid': config.get('id'),
                'alterId': int(config.get('aid', 0)),
                'cipher': config.get('scy', 'auto'),
                'udp': True,
            }
    
            # 处理网络类型
            network = config.get('net', 'tcp')
            node['network'] = network
            
            # WebSocket配置
            if network == 'ws':
                ws_opts = {}
                ws_path = config.get('path', '/')
                ws_host = config.get('host', '')
                
                # 兼容Qv2ray的header格式
                if isinstance(config.get('headers'), dict):
                    ws_host = config['headers'].get('Host', ws_host)
    
                if ws_path and ws_path != '/':
                    ws_opts['path'] = ws_path
                
                if ws_host:
                    ws_opts['headers'] = {'Host': ws_host}
                
                if ws_opts:
                    node['ws-opts'] = ws_opts
            
            # HTTP/2配置
            elif network == 'h2':
                h2_opts = {}
                h2_path = config.get('path')
                h2_host = config.get('host')
                
                if h2_path:
                    h2_opts['path'] = h2_path
                if h2_host:
                    h2_opts['host'] = h2_host.split(',')
                
                if h2_opts:
                    node['h2-opts'] = h2_opts
    
            # TLS配置
            if config.get('tls') in ['tls', True]:
                node['tls'] = True
                node['skip-cert-verify'] = False
                
                sni = config.get('sni', config.get('host', ''))
                if sni:
                    node['servername'] = sni
                
                # 处理ALPN
                alpn = config.get('alpn')
                if alpn:
                    if isinstance(alpn, str):
                        node['alpn'] = ProxyParser._parse_alpn_value(alpn)
                    elif isinstance(alpn, list):
                        node['alpn'] = alpn
            
            return node
    
        except Exception as e:
            logger.error(f"解析VMess链接失败: {e}")
            return None
    
    @staticmethod
    def _parse_trojan(link: str) -> Optional[Dict[str, Any]]:
        """Trojan链接解析 - 支持TLS和传输层配置"""
        try:
            link = link[9:]  # 移除 trojan://
            
            name = "Trojan节点"
            if '#' in link:
                link, name = link.split('#', 1)
                name = ProxyParser._clean_vip_chars(urllib.parse.unquote(name))
            
            params = {}
            if '?' in link:
                link, query = link.split('?', 1)
                params = urllib.parse.parse_qs(query)
            
            if '@' not in link:
                return None
                
            password, server_part = link.split('@', 1)
            
            # 处理IPv6地址
            if server_part.startswith('['):
                server, port = server_part[1:].split("]:", 1)
            else:
                server, port = server_part.rsplit(':', 1)
            
            try:
                c_name = skip_cn(server)
                if c_name:
                    name = c_name + "|" + ProxyParser._clean_vip_chars(name)
            except (NameError, Exception):
                pass
            
            node = {
                'name': name,
                'type': 'trojan',
                'server': server,
                'port': int(port),
                'password': password,
                'udp': True
            }
            
            # 处理TLS配置
            ProxyParser._add_optional_field(node, 'sni', ProxyParser._get_param_value(params, 'sni'))
            
            # 处理ALPN参数
            alpn_value = ProxyParser._get_param_value(params, 'alpn')
            if alpn_value:
                alpn_list = ProxyParser._parse_alpn_value(alpn_value)
                if alpn_list:
                    node['alpn'] = alpn_list
            
            # 处理跳过证书验证
            skip_cert = ProxyParser._get_param_value(params, 'allowInsecure')
            if skip_cert and skip_cert in ['1', 'true', 'True']:
                node['skip-cert-verify'] = True
            
            # 处理传输层
            network = ProxyParser._get_param_value(params, 'type', 'tcp')
            if network != 'tcp':
                node['network'] = network
                
                if network == 'ws':
                    ws_opts = {}
                    path = ProxyParser._get_param_value(params, 'path')
                    if path:
                        ws_opts['path'] = urllib.parse.unquote(path)
                    
                    host = ProxyParser._get_param_value(params, 'host')
                    if host:
                        ws_opts['headers'] = {'Host': host}
                        
                    if ws_opts:
                        node['ws-opts'] = ws_opts
            
            return node
            
        except Exception as e:
            logger.error(f"解析Trojan链接失败: {e}")
            return None
    
    @staticmethod
    def _parse_hysteria(link: str) -> Optional[Dict[str, Any]]:
        """Hysteria/Hysteria2链接解析 - 完整支持所有参数"""
        try:
            original_link = link
            
            # 处理协议前缀
            if link.startswith('hysteria2://'):
                link = link[12:]
                default_type = 'hysteria2'
            elif link.startswith('hysteria://'):
                link = link[11:]
                default_type = 'hysteria'
            elif link.startswith('hy2://'):
                link = link[6:]
                default_type = 'hysteria2'
            else:
                return None
            
            # 解析名称部分
            name = f"{default_type.title()}节点"
            if '#' in link:
                link, name_part = link.split('#', 1)
                name = ProxyParser._clean_vip_chars(urllib.parse.unquote(name_part))
            
            # 解析查询参数
            params = {}
            if '?' in link:
                link, query = link.split('?', 1)
                params = urllib.parse.parse_qs(query)
            
            # 解析核心部分：password@server:port 或 server:port
            server = ""
            port = 443
            password = ""
            
            if '@' in link:
                password, server_part = link.split('@', 1)
            else:
                server_part = link
            
            # 处理server:port
            if ':' in server_part:
                if server_part.startswith('['):
                    # IPv6格式
                    server, port_str = server_part[1:].split("]:", 1)
                else:
                    server, port_str = server_part.rsplit(':', 1)
                try:
                    port = int(port_str)
                except ValueError:
                    port = 443
            else:
                server = server_part
            
            # 基础参数验证
            if not server:
                logger.error(f"Hysteria链接缺少服务器地址: {original_link}")
                return None
            
            # 获取国家代码
            try:
                c_name = skip_cn(server)
                if c_name:
                    name = c_name + "|" + ProxyParser._clean_vip_chars(name)
            except (NameError, Exception):
                pass
            
            # 构建基础节点配置
            node = {
                'name': name,
                'type': default_type,
                'server': server,
                'port': port,
                'udp': True,
            }
            
            # 处理密码/认证
            if password:
                node['password'] = password
            elif 'auth' in params:
                node['password'] = ProxyParser._get_param_value(params, 'auth')
            
            # SNI配置：peer参数映射到sni字段
            peer = ProxyParser._get_param_value(params, 'peer')
            if peer:
                node['sni'] = peer
            
            # TLS验证配置：insecure参数映射到skip-cert-verify
            insecure = ProxyParser._get_param_value(params, 'insecure')
            if insecure:
                node['skip-cert-verify'] = insecure in ['1', 'true', 'True']
            else:
                node['skip-cert-verify'] = False
            
            # ALPN协议配置
            alpn_value = ProxyParser._get_param_value(params, 'alpn')
            if alpn_value:
                alpn_list = ProxyParser._parse_alpn_value(alpn_value)
                if alpn_list:
                    node['alpn'] = alpn_list
            
            # TFO (TCP Fast Open) - 默认为false
            node['tfo'] = False
            tfo = ProxyParser._get_param_value(params, 'tfo')
            if tfo and tfo in ['1', 'true', 'True']:
                node['tfo'] = True
            
            # 处理速度配置（仅Hysteria2）
            if default_type == 'hysteria2':
                up_speed = ProxyParser._get_param_value(params, 'up', '10')
                down_speed = ProxyParser._get_param_value(params, 'down', '50')
                
                # 只有当不是默认值时才添加
                if up_speed != '10':
                    node['up'] = up_speed
                if down_speed != '50':
                    node['down'] = down_speed
            
            # 处理混淆配置
            ProxyParser._add_optional_field(node, 'obfs', ProxyParser._get_param_value(params, 'obfs'))
            ProxyParser._add_optional_field(node, 'obfs-password', ProxyParser._get_param_value(params, 'obfsParam'))
            
            # Fast Open配置
            fastopen = ProxyParser._get_param_value(params, 'fastopen')
            if fastopen and fastopen in ['1', 'true', 'True']:
                node['fast-open'] = True
            
            # 处理端口跳跃
            mport = ProxyParser._get_param_value(params, 'mport')
            if mport:
                node['ports'] = mport
            
            return node
            
        except Exception as e:
            logger.error(f"解析Hysteria链接失败: {e} | 原始链接: {original_link[:50]}...")
            return None