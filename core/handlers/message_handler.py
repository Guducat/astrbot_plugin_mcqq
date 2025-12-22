# filepath: e:\github desktop\AstrBot\data\plugins\astrbot_plugin_mcqq\core\handlers\message_handler.py
import uuid
from datetime import datetime
from typing import Dict, Any, List, Callable, Awaitable, TYPE_CHECKING, Optional
from astrbot.api.platform import AstrBotMessage, MessageMember, MessageType
from astrbot.api.message_components import Plain
from astrbot import logger

from ..events.minecraft_event import MinecraftMessageEvent
from ..config.server_types import Vanilla, Spigot, Fabric, Forge, Neoforge, McdrServer
from ..utils.bot_filter import BotFilter
from ..utils.death_message import normalize_death_message
from ..commands.command_factory import CommandFactory


class MessageHandler:
    """Minecraft消息处理器 - 重构后版本，专注于消息路由和基础处理"""
    
    def __init__(self, 
                 server_name: str,
                 qq_message_prefix: str,
                 enable_join_quit: bool,
                 bot_filter: BotFilter):
        """
        初始化消息处理器
        
        Args:
            server_name: 服务器名称
            qq_message_prefix: QQ消息前缀
            enable_join_quit: 是否启用进入/退出消息
            bot_filter: 假人过滤器
        """
        self.server_name = server_name
        self.qq_message_prefix = qq_message_prefix
        self.enable_join_quit = enable_join_quit
        self.bot_filter = bot_filter
        
        # 使用命令工厂创建命令注册表
        self.command_registry = CommandFactory.setup_command_registry(self)

    def get_qq_prefix(self, adapter=None) -> str:
        """获取转发到 QQ 的前缀（保留兼容；默认 [MC] 视为禁用）。"""
        raw_prefix = (self.qq_message_prefix or "").strip()
        if not raw_prefix:
            return ""
        if raw_prefix.lower() in ("[mc]", "none", "disable", "disabled", "禁用"):
            return ""
        return raw_prefix

    def _ts(self) -> str:
        """本地时间戳（HH:MM:SS）。"""
        return datetime.now().strftime("%H:%M:%S")

    def _format_mc_to_qq_chat(self, player_name: str, message_text: str) -> str:
        # QQ 侧不需要额外标签：[MC]/服务器ID 等，直接用“名字:内容”
        return f"{player_name}:{message_text}"

    def _extract_command_text(self, message_text: str, adapter=None) -> Optional[str]:
        """移除唤醒词并返回命令文本。未匹配唤醒词时返回 None。"""
        if not message_text:
            return None

        raw_text = message_text.strip()
        if not raw_text:
            return None

        wake_prefixes = []
        if adapter and getattr(adapter, "context", None):
            try:
                config = adapter.context.get_config()
                wake_prefixes = config.get("wake_prefix", []) or []
            except Exception as e:
                logger.debug(f"读取唤醒词配置失败: {e}")

        for prefix in wake_prefixes:
            if prefix and raw_text.startswith(prefix):
                return raw_text[len(prefix):].lstrip()

        # 兼容旧配置，默认识别单个 '#' 作为唤醒词
        if raw_text.startswith("#"):
            return raw_text[1:].lstrip()

        return None

    def get_server_class(self, server_type: str):
        """根据服务器类型获取对应的服务器类型对象"""
        server_classes = {
            "vanilla": Vanilla(),
            "spigot": Spigot(),
            "fabric": Fabric(),
            "forge": Forge(),
            "neoforge": Neoforge(),
            "mcdr": McdrServer()
        }
        return server_classes.get(server_type, Vanilla())
    
    async def handle_chat_message(self, 
                                data: Dict[str, Any], 
                                server_class,
                                bound_groups: List[str],
                                send_to_groups_callback: Callable[[List[str], str], Awaitable[None]],
                                send_mc_message_callback: Callable[[str], Awaitable[None]],
                                commit_event_callback: Callable[[MinecraftMessageEvent], None],
                                platform_meta,
                                adapter=None) -> bool:
        """
        处理聊天消息 - 简化版本，主要负责路由
        
        Args:
            data: 消息数据
            server_class: 服务器类型对象
            bound_groups: 绑定的群组列表
            send_to_groups_callback: 发送消息到群组的回调函数
            send_mc_message_callback: 发送消息到MC的回调函数
            commit_event_callback: 提交事件的回调函数
            platform_meta: 平台元数据
            adapter: 适配器实例
            
        Returns:
            bool: 是否处理了消息
        """
        player_data = data.get("player", {})
        player_name = player_data.get("nickname", player_data.get("display_name", "未知玩家"))
        message_text = data.get("message", "")

        command_text = self._extract_command_text(message_text, adapter)

        # 优先执行插件内注册的命令，未命中再交由 AstrBot 处理
        try:
            if self.command_registry and command_text is not None:
                handled = await self.command_registry.handle_command(
                    message_text=command_text,
                    data=data,
                    server_class=server_class,
                    bound_groups=bound_groups,
                    send_to_groups_callback=send_to_groups_callback,
                    send_mc_message_callback=send_mc_message_callback,
                    commit_event_callback=commit_event_callback,
                    platform_meta=platform_meta,
                    adapter=adapter
                )
                if handled:
                    return True
        except Exception as e:
            logger.error(f"执行 Minecraft 专用命令时出错: {e}")

        # MC 普通聊天自动转发到 QQ（可选）
        try:
            plugin = getattr(adapter, "plugin_instance", None) if adapter else None
            if plugin and getattr(plugin, "enable_mc_chat_to_qq_forward", False):
                # 默认不转发唤醒词/命令消息，避免刷屏
                if command_text is None and message_text and message_text.strip():
                    target_groups = bound_groups or []

                    # 每群/每服细粒度开关：mc_to_qq.chat
                    if adapter and hasattr(adapter, "binding_manager"):
                        binding_server_name = None
                        if isinstance(data, dict):
                            binding_server_name = data.get("_binding_server_name")
                        binding_server_name = binding_server_name or getattr(adapter, "server_name", None) or self.server_name
                        target_groups = [
                            gid for gid in target_groups
                            if adapter.binding_manager.get_group_flag(binding_server_name, gid, "mc_to_qq.chat", True)
                        ]

                    if target_groups:
                        formatted_message = self._format_mc_to_qq_chat(player_name, message_text.strip())
                        await send_to_groups_callback(target_groups, formatted_message)
        except Exception as e:
            logger.warning(f"MC聊天自动转发到QQ失败: {e}")

        logger.info(f"{player_name}: {message_text}")

        abm = AstrBotMessage()
        abm.type = MessageType.GROUP_MESSAGE
        abm.message_str = message_text
        abm.sender = MessageMember(
            user_id=f"minecraft_{player_name}",
            nickname=player_name
        )
        abm.message = [Plain(text=message_text)]
        abm.raw_message = {"content": message_text}
        abm.self_id = f"minecraft_{self.server_name}"
        abm.session_id = f"minecraft_{self.server_name}"
        abm.message_id = str(uuid.uuid4())

        # 创建消息事件
        message_event = MinecraftMessageEvent(
            message_str=message_text,
            message_obj=abm,
            platform_meta=platform_meta,
            session_id=f"minecraft_{self.server_name}",
            adapter=adapter,
            message_type=MessageType.GROUP_MESSAGE
        )

        # 设置回调函数，以便其他插件的响应可以发送回Minecraft
        async def on_response(response_message):
            if response_message and response_message.strip():
                await send_mc_message_callback(response_message)

        message_event.on_response = on_response

        commit_event_callback(message_event)

        return True
    
    async def create_astrbot_command_event(self, 
                                         command_text: str, 
                                         player_name: str, 
                                         platform_meta,
                                         send_mc_message_callback: Callable[[str], Awaitable[None]],
                                         adapter=None) -> MinecraftMessageEvent:
        """创建AstrBot命令事件"""
        # 创建一个虚拟的消息事件，用于执行指令
        abm = AstrBotMessage()
        abm.type = MessageType.GROUP_MESSAGE
        abm.message_str = command_text
        abm.sender = MessageMember(
            user_id=f"minecraft_{player_name}",
            nickname=player_name
        )
        abm.message = [Plain(text=command_text)]
        abm.raw_message = {"content": command_text}
        abm.self_id = f"minecraft_{self.server_name}"
        abm.session_id = f"minecraft_{self.server_name}"
        abm.message_id = str(uuid.uuid4())

        # 创建消息事件
        message_event = MinecraftMessageEvent(
            message_str=command_text,
            message_obj=abm,
            platform_meta=platform_meta,
            session_id=f"minecraft_{self.server_name}",
            adapter=adapter,
            message_type=MessageType.GROUP_MESSAGE  # 显式指定消息类型
        )

        # 标记该事件已通过唤醒词判定，确保 AstrBot 指令过滤器生效
        message_event.is_at_or_wake_command = True
        message_event.is_wake = True

        # 设置回调函数，将AstrBot的响应发送回Minecraft
        async def on_response(response_message):
            if response_message and response_message.strip():
                await send_mc_message_callback(response_message)

        message_event.on_response = on_response
        
        # 存储最后创建的事件，以便主适配器可以设置adapter引用
        self._last_event = message_event
        
        return message_event
    
    async def handle_player_join_quit(self, 
                                    data: Dict[str, Any], 
                                    event_name: str,
                                    server_class,
                                    bound_groups: List[str],
                                    send_to_groups_callback: Callable[[List[str], str], Awaitable[None]],
                                    adapter=None) -> bool:
        """
        处理玩家进入/退出消息
        
        Args:
            data: 消息数据
            event_name: 事件名称
            server_class: 服务器类型对象
            bound_groups: 绑定的群组列表
            send_to_groups_callback: 发送消息到群组的回调函数
            
        Returns:
            bool: 是否处理了消息
        """
        if not self.enable_join_quit or not event_name:
            logger.debug(f"跳过进入/退出消息处理: enable_join_quit={self.enable_join_quit}, event_name={event_name}")
            return False
            
        player_data = data.get("player", {})
        player_name = player_data.get("nickname", player_data.get("display_name", "未知玩家"))
        
        logger.info(f"处理玩家进入/退出事件: event_name={event_name}, player_name={player_name}, bound_groups={bound_groups}")

        # 过滤假人
        if self.bot_filter.is_bot_player(player_name):
            logger.debug(f"过滤假人 {player_name} 的进入/退出消息")
            return False

        # 构造进入/退出消息 - 通过检查事件名称判断是加入还是退出
        # 支持各种服务器类型的事件名称
        ts = self._ts()
        event_name_lower = event_name.lower()
        if "join" in event_name_lower or "loggedin" in event_name_lower:
            message = f"{ts} {player_name} 加入了游戏"
        elif "quit" in event_name_lower or "disconnect" in event_name_lower or "loggedout" in event_name_lower:
            message = f"{ts} {player_name} 离开了游戏"
        else:
            logger.warning(f"未识别的进入/退出事件类型: {event_name}")
            return False

        # 发送到绑定的QQ群
        if bound_groups:
            await send_to_groups_callback(bound_groups, message)
            logger.info(f"玩家 {player_name} {event_name} 消息已发送到QQ群")

        return True
    
    async def handle_player_death(self, 
                                data: Dict[str, Any], 
                                event_name: str,
                                server_class,
                                bound_groups: List[str],
                                send_to_groups_callback: Callable[[List[str], str], Awaitable[None]],
                                adapter=None) -> bool:
        """
        处理玩家死亡消息
        
        Args:
            data: 消息数据
            event_name: 事件名称
            server_class: 服务器类型对象
            bound_groups: 绑定的群组列表
            send_to_groups_callback: 发送消息到群组的回调函数
            
        Returns:
            bool: 是否处理了消息
        """
        # 检查是否为死亡事件（支持各种服务器类型）
        event_name_lower = event_name.lower()
        if "death" not in event_name_lower:
            return False
            
        player_data = data.get("player", {})
        player_name = player_data.get("nickname", player_data.get("display_name", "未知玩家"))
        death_message = data.get("death_message", data.get("message", f"{player_name} 死了"))

        # 过滤假人
        if self.bot_filter.is_bot_player(player_name):
            logger.debug(f"过滤假人 {player_name} 的死亡消息")
            return False

        # 构造死亡消息
        message = normalize_death_message(death_message, default_player_name=player_name) or f"{player_name} 死了"

        # 发送到绑定的QQ群
        if bound_groups:
            await send_to_groups_callback(bound_groups, message)
            logger.info(f"玩家 {player_name} 死亡消息已发送到QQ群")

        return True
