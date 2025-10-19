# data_manager.py (修复版 - 增强VLESS解析)
import os
import json
import yaml
import logging
import math
import time
from typing import List, Dict, Any, Tuple
from config import config

logger = logging.getLogger(__name__)

class DataManager:
    """数据管理器 - 统一文件操作"""
    
    def __init__(self):
        self.admin_ids = config.ADMIN_IDS.copy()
        self.user_permissions = {}
        self._load_config()
    
    def _load_config(self):
        """加载配置文件"""
        try:
            if os.path.exists(config.CONFIG_FILE):
                with open(config.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.user_permissions = data.get('user_permissions', {})
                    self.admin_ids = data.get('admin_ids', self.admin_ids)
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
    
    def _save_config(self):
        """保存配置文件"""
        try:
            data = {
                'user_permissions': self.user_permissions,
                'admin_ids': self.admin_ids
            }
            with open(config.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
    
    def load_proxies(self) -> List[Dict[str, Any]]:
        """加载代理列表"""
        try:
            if os.path.exists(config.PROXIES_FILE):
                with open(config.PROXIES_FILE, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        return yaml.safe_load(content) or []
            return []
        except Exception as e:
            logger.error(f"加载代理文件失败: {e}")
            return []
    
    def save_proxies(self, proxies: List[Dict[str, Any]]) -> bool:
        """保存代理列表"""
        try:
            with open(config.PROXIES_FILE, 'w', encoding='utf-8') as f:
                if proxies:
                    yaml.dump(proxies, f, default_flow_style=False, 
                             allow_unicode=True, sort_keys=False)
                else:
                    f.write("")
            return True
        except Exception as e:
            logger.error(f"保存代理文件失败: {e}")
            return False
    
    def add_proxies(self, proxy_text: str) -> Tuple[bool, str]:
        """
        【修复版】批量添加代理 - 增强VLESS支持和错误处理
        遵循SOLID原则：SRP专注解析，OCP支持扩展，DRY避免重复
        """
        from utils.proxy_parser import ProxyParser
        
        try:
            lines = proxy_text.strip().split('\n')
            new_nodes = []
            failed_lines = []
            detailed_errors = []
            
            logger.info(f"开始解析 {len(lines)} 行配置")
            
            for line_num, line in enumerate(lines,1):
                line = line.strip()
                if not line:
                    continue

                logger.debug(f"解析第{line_num}行: {line[:50]}...")
                proxy_config = None
                parse_error = None
                
                try:
                    # 【修复1】优先检查是否为协议链接格式
                    if self._is_protocol_link(line):

                        logger.debug(f"检测到协议链接: {line.split('://')[0]}://")
                        
                        # 直接调用链接解析器
                        proxy_config = ProxyParser.parse_proxy_link(line)
                        
                        if proxy_config:
                            logger.debug(f"链接解析成功: {proxy_config.get('name', 'Unknown')}")
                        else:
                            parse_error = "协议链接解析失败"
                            logger.warning(f"第{line_num}行链接解析失败")
                    
                    # 【修复2】如果不是链接，尝试YAML解析或JSON单行
                    elif not proxy_config:
                        keys_to_check_correct = ['"name":', '"type":', '"server":']
                        result_correct = any(key in line for key in keys_to_check_correct)
                        try:
                            if result_correct:
                                data = json.loads(line.replace("-",""))
                                yaml_data = yaml.dump(data, allow_unicode=True)
                                yaml_data = yaml.safe_load(yaml_data)

                                if isinstance(yaml_data, dict) and yaml_data.get('type'):
                                    proxy_config = ProxyParser.parse_proxy(yaml_data)
                                    if proxy_config:
                                        logger.debug(f"YAML解析成功: {proxy_config.get('name', 'Unknown')}")
                        except yaml.YAMLError as ye:
                            parse_error = f"YAML格式错误: {str(ye)}"
                        except Exception as e:
                            parse_error = f"YAML解析异常: {str(e)}"
                    
                    # 【修复3】最后尝试统一解析入口
                    if not proxy_config:
                        try:
                            proxy_config = ProxyParser.parse_proxy(line)
                            if proxy_config:
                                logger.debug("统一入口解析成功")
                        except Exception as e:
                            parse_error = f"统一解析失败: {str(e)}"
                
                except Exception as e:
                    parse_error = f"解析异常: {str(e)}"
                    logger.error(f"第{line_num}行解析异常: {e}")
                
                if proxy_config and self._validate_proxy_config(proxy_config):
                    # 【修复4】确保必要字段完整
                    proxy_config = self._normalize_proxy_config(proxy_config)
                    new_nodes.append(proxy_config)
                    logger.debug(f"第{line_num}行解析成功")
                else:
                    failed_line_info = f"第{line_num}行: {line[:50]}..."
                    if parse_error:
                        failed_line_info += f" ({parse_error})"
                    failed_lines.append(failed_line_info)
                    detailed_errors.append({
                        'line_num': line_num,
                        'content': line[:100],
                        'error': parse_error or "未知格式或验证失败"
                    })
            
            # 【修复5】改进结果处理和错误报告
            if not new_nodes:
                error_msg = "❌ 没有找到有效的代理配置"
                if failed_lines:
                    error_msg += f"\n\n解析失败的行:\n" + "\n".join(failed_lines[:3])
                    if len(failed_lines) > 3:
                        error_msg += f"\n... 还有 {len(failed_lines) - 3} 行失败"
                
                # 添加详细错误信息用于调试
                logger.error("解析失败详情:")
                for err in detailed_errors[:5]:  # 只记录前5个错误
                    logger.error(f"  行{err['line_num']}: {err['error']}")
                
                return False, error_msg
            
            # 【修复6】智能去重和追加逻辑
            existing_proxies = self.load_proxies()
            existing_names = {proxy.get('name'): i for i, proxy in enumerate(existing_proxies)}
            
            added_count = 0
            updated_count = 0
            
            for node in new_nodes:
                node_name = node.get('name')
                if not node_name:
                    continue
                    
                if node_name in existing_names:
                    # 更新现有节点
                    index = existing_names[node_name]
                    existing_proxies[index] = self._merge_proxy_configs(existing_proxies[index], node)
                    updated_count += 1
                    logger.debug(f"更新节点: {node_name}")
                else:
                    # 添加新节点
                    existing_proxies.append(node)
                    existing_names[node_name] = len(existing_proxies) - 1
                    added_count += 1
                    logger.debug(f"添加节点: {node_name}")
            
            # 保存结果
            if added_count > 0 or updated_count > 0:
                if self.save_proxies(existing_proxies):
                    result_parts = []
                    if added_count > 0:
                        result_parts.append(f"新增 {added_count} 个")
                    if updated_count > 0:
                        result_parts.append(f"更新 {updated_count} 个")
                    if failed_lines:
                        result_parts.append(f"失败 {len(failed_lines)} 个")
                    
                    result_msg = f"✅ 成功处理: " + "、".join(result_parts)
                    logger.info(result_msg)
                    return True, result_msg
                else:
                    return False, "❌ 保存文件失败"
            else:
                return False, f"❌ 所有配置都解析失败（共{len(failed_lines)}个）"
                
        except Exception as e:
            logger.error(f"批量添加代理失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False, f"❌ 添加代理失败: {str(e)}"
    
    def _is_protocol_link(self, line: str) -> bool:
        """检查是否为协议链接"""
        protocol_prefixes = ['ss://', 'vmess://', 'ssr://', 'vless://', 'trojan://', 'hysteria://', 'hy2://', 'hysteria2://']
        return any(line.startswith(prefix) for prefix in protocol_prefixes)
    
    def _validate_proxy_config(self, config: Dict[str, Any]) -> bool:
        """验证代理配置的完整性"""
        if not isinstance(config, dict):
            return False
        
        required_fields = ['name', 'type', 'server', 'port']
        for field in required_fields:
            if field not in config or not config[field]:
                logger.warning(f"代理配置缺少必需字段: {field}")
                return False
        
        # 验证端口范围
        try:
            port = int(config['port'])
            if port < 1 or port > 65535:
                logger.warning(f"端口号超出范围: {port}")
                return False
        except (ValueError, TypeError):
            logger.warning(f"端口号格式错误: {config['port']}")
            return False
        
        return True
    
    def _normalize_proxy_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """标准化代理配置"""
        return {k: v for k, v in config.items() if v is not None and v != ''}
    
    def get_proxies_page(self, page: int, per_page: int = None) -> Dict[str, Any]:
        """分页获取代理"""
        if per_page is None:
            per_page = config.NODES_PER_PAGE
            
        proxies = self.load_proxies()
        total = len(proxies)
        total_pages = math.ceil(total / per_page) if total > 0 else 1
        
        start = (page - 1) * per_page
        end = start + per_page
        
        return {
            'proxies': proxies[start:end],
            'current_page': page,
            'total_pages': total_pages,
            'total_count': total,
            'has_prev': page > 1,
            'has_next': page < total_pages
        }
    
    def delete_proxies(self, proxy_names: List[str]) -> Tuple[bool, str]:
        """批量删除代理"""
        try:
            proxies = self.load_proxies()
            original_count = len(proxies)
            
            # 过滤掉要删除的代理
            proxies = [proxy for proxy in proxies if proxy.get('name') not in proxy_names]
            deleted_count = original_count - len(proxies)
            
            if deleted_count == 0:
                return False, "未找到要删除的代理"
            
            if self.save_proxies(proxies):
                return True, f"成功删除 {deleted_count} 个代理"
            else:
                return False, "保存文件失败"
                
        except Exception as e:
            logger.error(f"批量删除失败: {e}")
            return False, f"删除失败: {str(e)}"
    
    def search_proxies(self, keyword: str) -> List[Dict[str, Any]]:
        """搜索代理"""
        proxies = self.load_proxies()
        keyword = keyword.lower()
        
        matching_proxies = []
        for proxy in proxies:
            name = proxy.get('name', '').lower()
            server = proxy.get('server', '').lower()
            proxy_type = proxy.get('type', '').lower()
            
            if keyword in name or keyword in server or keyword in proxy_type:
                matching_proxies.append(proxy)
        
        return matching_proxies
    
    def get_user_permission(self, user_id: int) -> str:
        """获取用户权限"""
        if user_id in self.admin_ids:
            return "admin"
        return self.user_permissions.get(str(user_id), config.Permissions.GUEST)
    
    def set_user_permission(self, user_id: int, permission: str) -> None:
        """设置用户权限"""
        self.user_permissions[str(user_id)] = permission
        self._save_config()
    
    def append_single_proxy(self, proxy_config: Dict[str, Any], source: str = "") -> Tuple[bool, str]:
        """追加单个代理配置 - 支持同名更新"""
        try:
            existing_proxies = self.load_proxies()
            existing_dict = {proxy.get('name'): proxy for proxy in existing_proxies}
            
            proxy_name = proxy_config.get('name')
            if not proxy_name:
                return False, "代理名称不能为空"
            
            # 验证配置
            if not self._validate_proxy_config(proxy_config):
                return False, f"代理配置验证失败: {proxy_name}"
            
            # 添加元数据
            proxy_config['_source'] = source
            proxy_config['_scan_time'] = time.time()
            
            if proxy_name in existing_dict:
                # 更新现有代理
                old_proxy = existing_dict[proxy_name]
                updated_proxy = self._merge_proxy_configs(old_proxy, proxy_config)
                existing_dict[proxy_name] = updated_proxy
                action = "更新"
            else:
                # 新增代理
                existing_dict[proxy_name] = proxy_config
                action = "新增"
            
            # 保存更新后的列表
            final_proxies = list(existing_dict.values())
            if self.save_proxies(final_proxies):
                return True, f"{action}代理: {proxy_name}"
            else:
                return False, "保存文件失败"
                
        except Exception as e:
            logger.error(f"追加单个代理失败: {e}")
            return False, f"操作失败: {str(e)}"
    
    def _merge_proxy_configs(self, old_config: Dict[str, Any], new_config: Dict[str, Any]) -> Dict[str, Any]:
        """合并代理配置 - 智能更新"""
        merged = old_config.copy()
        
        # 更新所有字段，保留历史信息
        for key, value in new_config.items():
            if key.startswith('_'):
                # 元数据特殊处理
                if key == '_scan_time':
                    merged['_last_scan'] = value
                elif key == '_source':
                    merged['_last_source'] = value
                else:
                    merged[key] = value
            else:
                # 配置数据直接更新
                merged[key] = value
        
        return merged

# 创建全局实例
data_manager = DataManager()