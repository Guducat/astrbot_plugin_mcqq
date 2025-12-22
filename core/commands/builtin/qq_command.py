"""QQ转发命令处理器"""
from typing import Dict, Any, List, Callable, Awaitable
from astrbot import logger

from ..base_command import BaseCommand


class QQCommand(BaseCommand):
    """处理QQ转发指令"""
    
    def __init__(self, message_handler):
        super().__init__(prefix="qq", priority=100)
        self.message_handler = message_handler
    
    async def execute(self, 
                     message_text: str,
                     data: Dict[str, Any],
                     server_class,
                     bound_groups: List[str],
                     send_to_groups_callback: Callable[[List[str], str], Awaitable[None]],
                     send_mc_message_callback: Callable[[str], Awaitable[None]],
                     commit_event_callback: Callable,
                     platform_meta,
                     adapter=None) -> bool:
        """执行QQ转发指令"""
        player_data = data.get("player", {})
        player_name = player_data.get("nickname", player_data.get("display_name", "未知玩家"))
        
        # 获取要转发的消息内容
        qq_message = self.remove_prefix(message_text)
        if not qq_message:
            await send_mc_message_callback("❌ 请提供要转发到QQ的消息内容")
            return True

        # 全局开关（插件级）：是否允许 MC 侧使用 #qq 指令
        try:
            plugin = getattr(adapter, "plugin_instance", None) if adapter else None
            if plugin is not None and hasattr(plugin, "enable_mc_qq_command") and not getattr(plugin, "enable_mc_qq_command", True):
                await send_mc_message_callback("❌ 管理员已关闭 MC→QQ 的 #qq 指令转发功能")
                return True
        except Exception:
            pass
        
        # 过滤假人
        if self.message_handler.bot_filter.is_bot_player(player_name):
            logger.debug(f"过滤假人 {player_name} 的QQ转发消息")
            return True
        
        # 构造转发消息
        formatted_message = f"{player_name}:{qq_message}"
        
        # 发送到绑定的QQ群（支持每群/每服细粒度开关：mc_to_qq.qq_command）
        target_groups = bound_groups or []
        try:
            if adapter and hasattr(adapter, "binding_manager"):
                binding_server_name = None
                if isinstance(data, dict):
                    binding_server_name = data.get("_binding_server_name")
                binding_server_name = binding_server_name or getattr(adapter, "server_name", None) or self.message_handler.server_name
                target_groups = [
                    gid for gid in target_groups
                    if adapter.binding_manager.get_group_flag(binding_server_name, gid, "mc_to_qq.qq_command", True)
                ]
        except Exception as e:
            logger.debug(f"过滤 #qq 目标群失败: {e}")

        if target_groups:
            await send_to_groups_callback(target_groups, formatted_message)
            logger.info(f"玩家 {player_name} 通过QQ指令发送消息到群聊: {qq_message}")
        else:
            await send_mc_message_callback("❌ 当前服务器没有启用 #qq 的绑定QQ群（或未绑定）")
        
        return True
    
    def get_help_text(self) -> str:
        """获取帮助文本"""
        return "<唤醒词>qq <消息> - 将消息转发到绑定的QQ群"
