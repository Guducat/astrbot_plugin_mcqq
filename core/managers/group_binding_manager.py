import json
import os
import copy
from typing import Dict, List, Any, Optional
from astrbot import logger


class GroupBindingManager:
    """群聊与服务器绑定关系管理器"""

    # 绑定后每个群/每个服务器的默认设置（可被 /mc设置 调整）
    DEFAULT_BINDING_SETTINGS: Dict[str, Dict[str, bool]] = {
        # QQ 群 → MC（群消息自动转发）
        "qq_to_mc": {
            "forward": True,
        },
        # MC → QQ 群（事件转发 / 指令）
        "mc_to_qq": {
            "chat": True,
            "join_quit": True,
            "death": True,
            "qq_command": True,
        },
    }
    
    def __init__(self, data_dir: str):
        """
        初始化绑定管理器
        
        Args:
            data_dir: 数据目录路径
        """
        self.data_dir = data_dir
        self.bindings_file = os.path.join(data_dir, "group_bindings.json")
        # 结构：{ server_name: { group_id(str): settings(dict) } }
        self.group_bindings: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def _default_settings(self) -> Dict[str, Any]:
        return copy.deepcopy(self.DEFAULT_BINDING_SETTINGS)

    def _merge_defaults(self, settings: Any) -> Dict[str, Any]:
        """将旧/不完整 settings 合并为完整结构，仅保留已知 bool 字段。"""
        merged = self._default_settings()
        if not isinstance(settings, dict):
            return merged

        for section in ("qq_to_mc", "mc_to_qq"):
            raw_section = settings.get(section)
            if not isinstance(raw_section, dict):
                continue
            for key in merged[section].keys():
                if isinstance(raw_section.get(key), bool):
                    merged[section][key] = raw_section[key]

        return merged

    def _normalize_loaded_bindings(self, raw: Any) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """
        兼容旧格式：
        - 旧：{ server_name: ["123","456"] }
        - 新：{ server_name: { "123": {settings...}, "456": {settings...} } }
        """
        if not isinstance(raw, dict):
            return {}

        normalized: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for server_name, groups in raw.items():
            if isinstance(groups, list):
                normalized[server_name] = {
                    str(gid).strip(): self._default_settings()
                    for gid in groups
                    if gid is not None and str(gid).strip()
                }
            elif isinstance(groups, dict):
                normalized_groups: Dict[str, Dict[str, Any]] = {}
                for gid, settings in groups.items():
                    gid_str = str(gid).strip()
                    if not gid_str:
                        continue
                    normalized_groups[gid_str] = self._merge_defaults(settings)
                normalized[server_name] = normalized_groups
            else:
                normalized[server_name] = {}

        return normalized

    def _get_nested_bool(self, obj: Any, path: str, default: bool = False) -> bool:
        if not path:
            return default
        cur = obj
        for key in path.split("."):
            if not isinstance(cur, dict) or key not in cur:
                return default
            cur = cur[key]
        return cur if isinstance(cur, bool) else default

    def _set_nested_bool(self, obj: Dict[str, Any], path: str, value: bool):
        keys = [k for k in (path or "").split(".") if k]
        if not keys:
            return
        cur: Dict[str, Any] = obj
        for key in keys[:-1]:
            nxt = cur.get(key)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[key] = nxt
            cur = nxt
        cur[keys[-1]] = bool(value)
    
    def _ensure_file_exists(self):
        """确保绑定文件和目录存在"""
        os.makedirs(os.path.dirname(self.bindings_file), exist_ok=True)
        if not os.path.exists(self.bindings_file):
            with open(self.bindings_file, 'w', encoding='utf-8') as f:
                json.dump({}, f)
    
    def _safe_file_operation(self, operation_func, default_value=None):
        """安全的文件操作包装器"""
        try:
            return operation_func()
        except Exception as e:
            logger.error(f"文件操作失败: {str(e)}")
            return default_value
        
    def load_bindings(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """从文件加载群聊与服务器的绑定关系"""
        def _load():
            self._ensure_file_exists()
            with open(self.bindings_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        loaded_bindings = self._safe_file_operation(_load, {})
        if loaded_bindings is not None:
            normalized = self._normalize_loaded_bindings(loaded_bindings)
            self.group_bindings = normalized

            # 发现旧格式时自动升级一次
            try:
                need_upgrade = any(isinstance(v, list) for v in (loaded_bindings or {}).values())
                if need_upgrade:
                    self.save_bindings()
            except Exception:
                pass

            logger.info(f"已从 {self.bindings_file} 加载群聊绑定配置")
        else:
            self.group_bindings = {}
            logger.info("绑定配置文件不存在或加载失败，使用空配置")
        
        return self.group_bindings

    def save_bindings(self):
        """保存群聊与服务器的绑定关系到文件"""
        def _save():
            self._ensure_file_exists()
            with open(self.bindings_file, 'w', encoding='utf-8') as f:
                json.dump(self.group_bindings, f, ensure_ascii=False, indent=2)
        
        if self._safe_file_operation(_save) is not False:
            logger.info(f"已保存群聊绑定配置到 {self.bindings_file}")

    def bind_group(self, group_id: str, server_name: str, settings: Optional[Dict[str, Any]] = None) -> bool:
        """
        绑定群聊与Minecraft服务器
        
        Args:
            group_id: 群聊ID
            server_name: 服务器名称
            
        Returns:
            bool: 绑定成功返回True，已存在返回False
        """
        group_id = str(group_id).strip()
        if not group_id:
            return False

        if server_name not in self.group_bindings:
            self.group_bindings[server_name] = {}

        if group_id in self.group_bindings[server_name]:
            return False  # 已经绑定

        self.group_bindings[server_name][group_id] = self._merge_defaults(settings)
        self.save_bindings()
        return True

    def unbind_group(self, group_id: str, server_name: str) -> bool:
        """
        解除群聊与Minecraft服务器的绑定
        
        Args:
            group_id: 群聊ID
            server_name: 服务器名称
            
        Returns:
            bool: 解绑成功返回True，不存在返回False
        """
        group_id = str(group_id).strip()
        if server_name in self.group_bindings and group_id in self.group_bindings[server_name]:
            del self.group_bindings[server_name][group_id]
            self.save_bindings()
            return True
        return False

    def is_group_bound(self, group_id: str, server_name: str) -> bool:
        """
        检查群聊是否与Minecraft服务器绑定
        
        Args:
            group_id: 群聊ID
            server_name: 服务器名称
            
        Returns:
            bool: 已绑定返回True，未绑定返回False
        """
        group_id = str(group_id).strip()
        return server_name in self.group_bindings and group_id in self.group_bindings[server_name]
    
    def get_bound_groups(self, server_name: str) -> List[str]:
        """
        获取服务器绑定的群聊列表
        
        Args:
            server_name: 服务器名称
            
        Returns:
            List[str]: 绑定的群聊ID列表
        """
        groups = self.group_bindings.get(server_name, {})
        if isinstance(groups, dict):
            return list(groups.keys())
        if isinstance(groups, list):
            # 极端情况下未规范化数据，做兼容
            return [str(g) for g in groups]
        return []

    def get_group_settings(self, server_name: str, group_id: str) -> Optional[Dict[str, Any]]:
        """获取某个群在指定服务器下的设置。"""
        group_id = str(group_id).strip()
        groups = self.group_bindings.get(server_name, {})
        if not isinstance(groups, dict):
            return None
        settings = groups.get(group_id)
        return copy.deepcopy(settings) if isinstance(settings, dict) else None

    def get_group_flag(self, server_name: str, group_id: str, path: str, default: bool = False) -> bool:
        """读取某个群的 bool 配置（path 例如 mc_to_qq.chat / qq_to_mc.forward）。"""
        group_id = str(group_id).strip()
        groups = self.group_bindings.get(server_name, {})
        if not isinstance(groups, dict):
            return default
        settings = groups.get(group_id)
        if not isinstance(settings, dict):
            return default
        return self._get_nested_bool(settings, path, default)

    def set_group_flag(self, server_name: str, group_id: str, path: str, value: bool) -> bool:
        """设置某个群的 bool 配置并持久化。"""
        group_id = str(group_id).strip()
        if not group_id:
            return False

        groups = self.group_bindings.get(server_name)
        if not isinstance(groups, dict) or group_id not in groups or not isinstance(groups.get(group_id), dict):
            return False

        groups[group_id] = self._merge_defaults(groups[group_id])
        self._set_nested_bool(groups[group_id], path, bool(value))
        self.save_bindings()
        return True

    def get_enabled_groups(self, server_name: str, path: str, default: bool = False) -> List[str]:
        """按某个 bool 开关筛选群（例如 mc_to_qq.chat）。"""
        groups = self.group_bindings.get(server_name, {})
        if not isinstance(groups, dict):
            return []
        enabled: List[str] = []
        for gid, settings in groups.items():
            if self._get_nested_bool(settings, path, default):
                enabled.append(str(gid))
        return enabled
    
    def get_all_bindings(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """
        获取所有绑定关系
        
        Returns:
            Dict[str, Dict[str, Dict[str, Any]]]: 所有绑定关系字典
        """
        return copy.deepcopy(self.group_bindings)
