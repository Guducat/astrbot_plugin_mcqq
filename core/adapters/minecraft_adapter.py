import asyncio
import json
import os
import uuid
from typing import Dict, List, Any, Awaitable, Optional
from pathlib import Path
import subprocess
import psutil

from astrbot.api.platform import Platform, AstrBotMessage, MessageMember, PlatformMetadata, MessageType
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain, Image
from astrbot.core.platform.register import register_platform_adapter
from astrbot.core.star.star_tools import StarTools
from astrbot import logger

from .base_adapter import BaseMinecraftAdapter
from ..events.minecraft_event import MinecraftMessageEvent
from ..config.server_types import Vanilla, Spigot, Fabric, Forge, Neoforge
from ..managers.group_binding_manager import GroupBindingManager
from ..managers.websocket_manager import WebSocketManager
from ..managers.message_sender import MessageSender
from ..utils.bot_filter import BotFilter
from ..utils.death_message import normalize_death_message, format_death
from ..handlers.message_handler import MessageHandler

@register_platform_adapter(
    "minecraft", 
    "Minecraft服务器适配器", 
    # logo_path="minecraft.png",  # 新增：指定logo文件路径
    default_config_tmpl={
        "adapter_id": "minecraft_server_1",  # 添加适配器ID配置
        "ws_url": "ws://127.0.0.1:8080/minecraft/ws",
        "server_name": "Server",
        "Authorization": "",
        "enable_join_quit_messages": True,
        "qq_message_prefix": "[MC]",
        "qq_platform_id": "",
        "max_reconnect_retries": 5,
        "reconnect_interval": 3,
        "filter_bots": True,
        "bot_prefix": ["bot_", "Bot_"],
        "bot_suffix": [],
        "rcon_enabled": False,
        "rcon_host": "localhost",
        "rcon_port": 25575,
        "rcon_password": ""
    }
)
class MinecraftPlatformAdapter(BaseMinecraftAdapter):
    def __init__(self, platform_config: dict, platform_settings: dict, event_queue: asyncio.Queue) -> None:
        super().__init__(platform_config, platform_settings, event_queue)
        
        # 上下文引用，用于发送消息
        self.context = None
        
        # 插件实例引用，用于访问广播管理器和路由器
        self.plugin_instance = None
        
        # 路由器引用
        self.router = None

        # 从配置中获取WebSocket连接信息
        self.ws_url = self.config.get("ws_url", "ws://127.0.0.1:8080/minecraft/ws")
        self._server_name = self.config.get("server_name", "Server")
        self.Authorization = self.config.get("Authorization", "")
        self.enable_join_quit = self.config.get("enable_join_quit_messages", True)
        self.qq_message_prefix = self.config.get("qq_message_prefix", "[MC]")
        
        # 从配置中获取重连参数
        self.reconnect_interval = self.config.get("reconnect_interval", 3)  # 重连间隔(秒)
        self.max_retries = self.config.get("max_reconnect_retries", 5)  # 最大重试次数
        
        # 初始化数据目录
        self.data_dir = str(StarTools.get_data_dir("mcqq"))

        # 初始化各个管理器
        self.binding_manager = GroupBindingManager(self.data_dir)
        self.bot_filter = BotFilter(
            filter_enabled=self.config.get("filter_bots", True),
            prefix_list=self.config.get("bot_prefix", ["bot_", "Bot_"]),
            suffix_list=self.config.get("bot_suffix", [])
        )
        self.message_handler = MessageHandler(
            server_name=self._server_name,
            qq_message_prefix=self.qq_message_prefix,
            enable_join_quit=self.enable_join_quit,
            bot_filter=self.bot_filter,
        )

        # 加载绑定关系
        self.binding_manager.load_bindings()

        # WebSocket连接头信息
        self.headers = {
            "x-self-name": self._server_name,
            "x-client-origin": "astrbot",
            "Authorization": f"Bearer {self.Authorization}" if self.Authorization else ""  # 添加Bearer前缀
        }

        # 初始化WebSocket管理器和消息发送器
        self.websocket_manager = WebSocketManager(
            ws_url=self.ws_url,
            headers=self.headers,
            reconnect_interval=self.reconnect_interval,
            max_retries=self.max_retries
        )
        self.message_sender = MessageSender(self.websocket_manager)
        
        # 设置消息处理回调
        self.websocket_manager.set_message_handler(self.handle_mc_message)
        
    @property
    def server_name(self) -> str:
        """获取服务器名称"""
        return self._server_name

    def meta(self) -> PlatformMetadata:
        return PlatformMetadata(
            name="minecraft",
            description="Minecraft服务器适配器",
            id=self.config.get("adapter_id") or self.config.get("id")
        )

    async def run(self) -> Awaitable[Any]:
        """启动WebSocket客户端，维持与鹊桥模组的连接"""
        # 在开始接收消息前，等待插件实例设置路由器引用
        # 最多等待35秒（插件最多等待30秒+5秒缓冲），每0.5秒检查一次
        max_wait_time = 35
        wait_interval = 0.5
        elapsed = 0
        
        logger.debug(f"[{self.adapter_id}] 等待插件设置路由器引用...")
        
        while self.router is None and elapsed < max_wait_time:
            await asyncio.sleep(wait_interval)
            elapsed += wait_interval
            
        if self.router is None:
            logger.warning(f"[{self.adapter_id}] ⚠️ 等待 {max_wait_time} 秒后路由器仍未设置，将以单服务器模式运行")
        else:
            logger.info(f"[{self.adapter_id}] ✅ 路由器已设置（等待 {elapsed:.1f} 秒），启用多服务器消息转发功能")
        
        # 直接运行并等待 WebSocket 循环，由 PlatformManager 统一托管任务
        await self.websocket_manager.start()

    async def handle_mc_message(self, message: str):
        """处理从Minecraft服务器接收到的消息"""
        try:
            data = json.loads(message)
            try:
                plugin = getattr(self, "plugin_instance", None)
                if plugin and getattr(plugin, "debug_mode", False):
                    logger.info(f"[{self.adapter_id}] [WS<-MC] {data}")
                else:
                    logger.debug(f"收到Minecraft消息: {data}")
            except Exception:
                logger.debug(f"收到Minecraft消息: {data}")

            # 获取事件名称和服务器名称
            server_type = (data.get("server_type") or "").strip().lower()
            # 兼容：极少数实现可能把服务端类型放在 sub_type
            if not server_type:
                maybe_server_type = (data.get("sub_type") or "").strip().lower()
                if maybe_server_type in {"vanilla", "spigot", "paper", "fabric", "forge", "neoforge", "mcdr", "origin", "velocity"}:
                    server_type = maybe_server_type
                else:
                    server_type = "vanilla"

            event_name = data.get("event_name", "") or ""
            payload_server_name = data.get("server_name", "") or ""
            post_type = (data.get("post_type") or "").strip().lower()
            sub_type = (data.get("sub_type") or "").strip().lower()

            # 根据server_type获取对应的服务器类型对象
            server_class = self.message_handler.get_server_class(server_type)

            # 获取关联的群聊列表
            # 注意：绑定关系以“适配器配置的 server_name”为key；部分服务端实现上报的 server_name 可能不同，
            # 会导致 MC->QQ/#qq 查不到绑定群，表现为“没调用发送/发不出去”。
            binding_server_name = self._server_name
            bound_groups = self.binding_manager.get_bound_groups(binding_server_name)
            if not bound_groups and payload_server_name and payload_server_name != self._server_name:
                fallback_groups = self.binding_manager.get_bound_groups(payload_server_name)
                if fallback_groups:
                    logger.warning(
                        f"[{self.adapter_id}] 绑定群 key 疑似不一致：配置 server_name={self._server_name}，"
                        f"上报 server_name={payload_server_name}；已使用上报值找到绑定群。"
                    )
                    bound_groups = fallback_groups
                    binding_server_name = payload_server_name
                else:
                    logger.debug(
                        f"[{self.adapter_id}] 未找到绑定群：config_server_name={self._server_name}, "
                        f"payload_server_name={payload_server_name}"
                    )

            # 下游命令/转发需要知道本次使用哪个 key 来查绑定/配置
            if isinstance(data, dict):
                data["_binding_server_name"] = binding_server_name
            
            # 响应包（如 broadcast 等 API 返回）不参与事件处理
            if post_type == "response":
                try:
                    plugin = getattr(self, "plugin_instance", None)
                    if plugin and getattr(plugin, "debug_mode", False):
                        logger.info(f"[{self.adapter_id}] [WS<-MC][response] {data}")
                    else:
                        logger.debug(f"[{self.adapter_id}] 收到 response: {data}")
                except Exception:
                    logger.debug(f"[{self.adapter_id}] 收到 response: {data}")
                return

            # 使用映射表简化事件处理（兼容部分实现直接用 event_name）
            event_handlers = {
                getattr(server_class, "chat", None): self._handle_chat_event,
                getattr(server_class, "join", None): self._handle_join_event,
                getattr(server_class, "quit", None): self._handle_quit_event,
                getattr(server_class, "death", None): self._handle_death_event,
                getattr(server_class, "player_command", None): self._handle_player_command_event,
            }

            # 查找并执行对应的处理器
            # 优先使用 QueQiao 字段 post_type/sub_type（参考 wiki: 4. 基本事件类型 / 4.3 Fabric / 4.5 NeoForge）
            handler = None
            if post_type == "message":
                if sub_type in {"chat", "player_chat"}:
                    handler = self._handle_chat_event
                elif sub_type == "player_command":
                    handler = self._handle_player_command_event
                elif sub_type in {"death", "player_death"}:
                    handler = self._handle_death_event
            elif post_type == "notice":
                if sub_type in {"join", "player_join"}:
                    handler = self._handle_join_event
                elif sub_type in {"quit", "player_quit"}:
                    handler = self._handle_quit_event
                elif sub_type in {"death", "player_death"}:
                    handler = self._handle_death_event

            if handler is None and event_name:
                handler = event_handlers.get(event_name)

            if handler:
                await handler(data, server_class, bound_groups)
                return

            # 兼容：部分实现可能使用不同的字段/命名，这里做简单兜底（尽量覆盖所有事件但不误判）
            event_name_lower = (event_name or "").lower()

            # death 事件：优先看 sub_type / death 字段 / event_name
            if sub_type in {"death", "player_death"} or ("death" in data) or ("death" in event_name_lower):
                await self._handle_death_event(data, server_class, bound_groups)
                return

            # join/quit 事件：优先看 sub_type / event_name
            if sub_type in {"join", "player_join"} or ("join" in event_name_lower or "loggedin" in event_name_lower):
                await self._handle_join_event(data, server_class, bound_groups)
                return
            if sub_type in {"quit", "player_quit"} or ("quit" in event_name_lower or "disconnect" in event_name_lower or "loggedout" in event_name_lower):
                await self._handle_quit_event(data, server_class, bound_groups)
                return

            # chat 事件：必须有 message 且看起来像聊天（避免把其他 message 事件当聊天）
            if (sub_type in {"chat", "player_chat"} or "chat" in event_name_lower) and isinstance(data.get("message"), str):
                await self._handle_chat_event(data, server_class, bound_groups)
                return

            # player_command：只记录，不当作聊天
            if sub_type == "player_command" or "command" in event_name_lower:
                await self._handle_player_command_event(data, server_class, bound_groups)
                return

            # 对于其他未识别的事件，记录日志但不进行处理
            try:
                plugin = getattr(self, "plugin_instance", None)
                if plugin and getattr(plugin, "debug_mode", False):
                    logger.info(
                        f"[{self.adapter_id}] 未识别事件，已跳过: post_type={post_type}, sub_type={sub_type}, event_name={event_name}, keys={list(data.keys())}"
                    )
                else:
                    logger.debug(
                        f"[{self.adapter_id}] 未识别事件，已跳过: post_type={post_type}, sub_type={sub_type}, event_name={event_name}"
                    )
            except Exception:
                logger.debug(f"[{self.adapter_id}] 未识别事件，已跳过: post_type={post_type}, sub_type={sub_type}, event_name={event_name}")

        except json.JSONDecodeError:
            logger.error(f"无法解析JSON消息: {message}")
        except Exception as e:
            logger.error(f"处理Minecraft消息时出错: {str(e)}")

    async def _handle_chat_event(self, data, server_class, bound_groups):
        """处理聊天消息事件"""
        player_data = data.get("player") if isinstance(data.get("player"), dict) else {}
        player_name = player_data.get("display_name") or player_data.get("nickname") or ""
        message_content = data.get("message", "")
        if not isinstance(message_content, str):
            message_content = str(message_content) if message_content is not None else ""
        message_content = message_content.strip()

        # 保护：避免把 player_command 等误判成聊天，造成空消息污染
        if not message_content:
            logger.debug(
                f"[{self.adapter_id}] 聊天消息为空，已跳过: sub_type={data.get('sub_type')}, event_name={data.get('event_name')}"
            )
            return
        
        logger.debug(f"[{self.adapter_id}] 收到聊天消息: 玩家={player_name}, 消息={message_content}")
        
        # 路由消息到其他适配器（排除假人消息）
        if self.router:
            if player_name and not self.bot_filter.is_bot_player(player_name):
                logger.debug(f"[{self.adapter_id}] 开始路由聊天消息到其他适配器")
                await self.router.route_chat_message(self.adapter_id, message_content, player_name)
            elif self.bot_filter.is_bot_player(player_name):
                logger.debug(f"[{self.adapter_id}] 跳过假人消息: {player_name}")
        
        # 原有的消息处理逻辑
        await self.message_handler.handle_chat_message(
            data=data,
            server_class=server_class,
            bound_groups=bound_groups,
            send_to_groups_callback=self.send_to_bound_groups,
            send_mc_message_callback=self.send_mc_message,
            commit_event_callback=self.commit_event,
            platform_meta=self.meta(),
            adapter=self
        )
        
        # 设置adapter引用
        if hasattr(self.message_handler, '_last_event'):
            self.message_handler._last_event.adapter = self

    async def _handle_join_event(self, data, server_class, bound_groups):
        """处理玩家加入事件"""
        player_data = data.get("player") if isinstance(data.get("player"), dict) else {}
        player_name = player_data.get("display_name") or player_data.get("nickname") or ""
            
        logger.debug(f"[{self.adapter_id}] 收到玩家加入: {player_name}")
        
        # 路由加入消息到其他适配器（排除假人）
        if self.router:
            if player_name and not self.bot_filter.is_bot_player(player_name):
                logger.debug(f"[{self.adapter_id}] 开始路由加入消息到其他适配器")
                await self.router.route_player_join(self.adapter_id, player_name)
            elif self.bot_filter.is_bot_player(player_name):
                logger.debug(f"[{self.adapter_id}] 跳过假人加入消息: {player_name}")
            
        # 原有的处理逻辑
        binding_server_name = data.get("_binding_server_name", self._server_name) if isinstance(data, dict) else self._server_name
        filtered_groups = bound_groups or []
        # 全局开关（插件级）
        try:
            plugin = getattr(self, "plugin_instance", None)
            if plugin is not None and hasattr(plugin, "enable_join_quit_messages") and not getattr(plugin, "enable_join_quit_messages", True):
                filtered_groups = []
        except Exception:
            pass

        if filtered_groups:
            filtered_groups = [
                gid for gid in filtered_groups
                if self.binding_manager.get_group_flag(binding_server_name, gid, "mc_to_qq.join_quit", True)
            ]

        await self.message_handler.handle_player_join_quit(
            data=data,
            event_name=(data.get("sub_type") or data.get("event_name") or server_class.join),
            server_class=server_class,
            bound_groups=filtered_groups,
            send_to_groups_callback=self.send_to_bound_groups,
            adapter=self
        )

    async def _handle_quit_event(self, data, server_class, bound_groups):
        """处理玩家退出事件"""
        player_data = data.get("player") if isinstance(data.get("player"), dict) else {}
        player_name = player_data.get("display_name") or player_data.get("nickname") or ""

        logger.debug(f"[{self.adapter_id}] 收到玩家退出: {player_name}")
            
        # 路由退出消息到其他适配器（排除假人）
        if self.router:
            if player_name and not self.bot_filter.is_bot_player(player_name):
                logger.debug(f"[{self.adapter_id}] 开始路由退出消息到其他适配器")
                await self.router.route_player_quit(self.adapter_id, player_name)
            elif self.bot_filter.is_bot_player(player_name):
                logger.debug(f"[{self.adapter_id}] 跳过假人退出消息: {player_name}")
            
        # 原有的处理逻辑
        binding_server_name = data.get("_binding_server_name", self._server_name) if isinstance(data, dict) else self._server_name
        filtered_groups = bound_groups or []
        # 全局开关（插件级）
        try:
            plugin = getattr(self, "plugin_instance", None)
            if plugin is not None and hasattr(plugin, "enable_join_quit_messages") and not getattr(plugin, "enable_join_quit_messages", True):
                filtered_groups = []
        except Exception:
            pass

        if filtered_groups:
            filtered_groups = [
                gid for gid in filtered_groups
                if self.binding_manager.get_group_flag(binding_server_name, gid, "mc_to_qq.join_quit", True)
            ]

        await self.message_handler.handle_player_join_quit(
            data=data,
            event_name=(data.get("sub_type") or data.get("event_name") or server_class.quit),
            server_class=server_class,
            bound_groups=filtered_groups,
            send_to_groups_callback=self.send_to_bound_groups,
            adapter=self
        )

    async def _handle_death_event(self, data, server_class, bound_groups):
        """处理玩家死亡事件"""
        player_data = data.get("player") if isinstance(data.get("player"), dict) else {}
        player_name = player_data.get("display_name") or player_data.get("nickname") or ""

        death_payload = data.get("death") if isinstance(data.get("death"), dict) else None
        death_message_raw = data.get("death_message", data.get("message", "")) if isinstance(data, dict) else ""
        if not isinstance(death_message_raw, str):
            death_message_raw = str(death_message_raw) if death_message_raw is not None else ""

        # 用 key/args 优先（更稳定），否则用 message/text 归一化
        death_message = ""
        try:
            death_style = "official"
            try:
                plugin = getattr(self, "plugin_instance", None)
                if plugin and getattr(plugin, "death_message_style", None):
                    death_style = str(getattr(plugin, "death_message_style")).strip().lower() or "official"
            except Exception:
                death_style = "official"

            if death_payload:
                death_message = format_death(death_payload, default_player_name=player_name, style=death_style)
            if not death_message and death_message_raw:
                death_message = normalize_death_message(
                    death_message_raw,
                    default_player_name=player_name,
                    style=death_style,
                )
        except Exception:
            death_message = death_message_raw.strip()

        # 路由死亡消息到其他适配器
        if self.router and death_message:
            await self.router.route_player_death(self.adapter_id, death_message)
            
        # 原有的处理逻辑
        binding_server_name = data.get("_binding_server_name", self._server_name) if isinstance(data, dict) else self._server_name
        filtered_groups = bound_groups or []
        # 全局开关（插件级）
        try:
            plugin = getattr(self, "plugin_instance", None)
            if plugin is not None and hasattr(plugin, "enable_death_messages") and not getattr(plugin, "enable_death_messages", True):
                filtered_groups = []
        except Exception:
            pass

        if filtered_groups:
            filtered_groups = [
                gid for gid in filtered_groups
                if self.binding_manager.get_group_flag(binding_server_name, gid, "mc_to_qq.death", True)
            ]

        await self.message_handler.handle_player_death(
            data=data,
            event_name=(data.get("sub_type") or data.get("event_name") or getattr(server_class, "death", "death")),
            server_class=server_class,
            bound_groups=filtered_groups,
            send_to_groups_callback=self.send_to_bound_groups,
            adapter=self
        )

    async def _handle_player_command_event(self, data, server_class, bound_groups):
        """处理玩家命令事件（仅用于排查，不当作聊天转发/触发 AstrBot 事件）"""
        player_data = data.get("player") if isinstance(data.get("player"), dict) else {}
        player_name = player_data.get("display_name") or player_data.get("nickname") or ""

        # QueQiao 不同端可能使用 message 或 command 字段
        cmd = data.get("command") if isinstance(data, dict) else None
        if not cmd:
            cmd = data.get("message") if isinstance(data, dict) else None
        cmd_text = cmd if isinstance(cmd, str) else (str(cmd) if cmd is not None else "")
        cmd_text = cmd_text.strip()

        try:
            plugin = getattr(self, "plugin_instance", None)
            if plugin and getattr(plugin, "debug_mode", False):
                logger.info(f"[{self.adapter_id}] [MC Command] {player_name}: {cmd_text}")
            else:
                logger.debug(f"[{self.adapter_id}] [MC Command] {player_name}: {cmd_text}")
        except Exception:
            logger.debug(f"[{self.adapter_id}] [MC Command] {player_name}: {cmd_text}")

    async def send_to_bound_groups(self, group_ids: List[str], message: str):
        """发送消息到绑定的QQ群"""
        def _get_platform_instances() -> List[Any]:
            if not getattr(self, "context", None):
                return []
            pm = getattr(self.context, "platform_manager", None)
            if not pm:
                return []

            # AstrBot 不同版本可能暴露不同字段/方法
            for attr in ("platform_insts", "platforms"):
                try:
                    insts = getattr(pm, attr, None)
                    if insts:
                        return list(insts)
                except Exception:
                    pass

            for meth in ("get_insts", "get_platforms"):
                try:
                    fn = getattr(pm, meth, None)
                    if callable(fn):
                        insts = fn()
                        if insts:
                            return list(insts)
                except Exception:
                    pass
            return []

        def _get_platform_id(p) -> Optional[str]:
            try:
                meta = p.meta() if hasattr(p, "meta") else None
            except Exception:
                meta = None
            candidates = [
                getattr(meta, "id", None) if meta else None,
                getattr(p, "adapter_id", None),
                getattr(p, "id", None),
            ]
            platform_config = getattr(p, "config", None)
            if isinstance(platform_config, dict):
                candidates.extend([platform_config.get("adapter_id"), platform_config.get("id")])
            return next((c for c in candidates if isinstance(c, str) and c.strip()), None)

        # 优先使用配置显式指定 QQ 平台 ID（避免自动识别失败）
        qq_adapter_id = (self.config.get("qq_platform_id") or "").strip() or None
        platforms = _get_platform_instances()

        if not qq_adapter_id and platforms:
            qq_names = {"aiocqhttp", "aiocqhttp_platform"}
            for p in platforms:
                try:
                    meta = p.meta() if hasattr(p, "meta") else None
                    platform_name = (getattr(meta, "name", "") or "").strip()
                    if platform_name in qq_names:
                        qq_adapter_id = _get_platform_id(p)
                        break
                except Exception:
                    continue

        if not qq_adapter_id and platforms:
            try:
                available = []
                for p in platforms:
                    try:
                        meta = p.meta() if hasattr(p, "meta") else None
                        platform_name = getattr(meta, "name", None) if meta else None
                        platform_id = _get_platform_id(p)
                        available.append(f"{platform_name or p.__class__.__name__}:{platform_id or 'unknown'}")
                    except Exception:
                        continue
                logger.warning(f"未找到 QQ 平台适配器（aiocqhttp/aiocqhttp_platform），可用平台: {available}")
            except Exception:
                pass

        if not qq_adapter_id:
            logger.warning("未找到 QQ 平台适配器实例或其 ID，无法向QQ群发送消息。请确认已启用 QQ 平台并检查其平台 ID，或在 Minecraft 适配器配置中填写 qq_platform_id。")
            return

        for group_id in group_ids:
            try:
                if hasattr(self, 'context') and self.context:
                    session = f"{qq_adapter_id}:GroupMessage:{group_id}"
                    message_chain = MessageChain().message(message)
                    try:
                        await self.context.send_message(session, message_chain)
                        try:
                            plugin = getattr(self, "plugin_instance", None)
                            if plugin and getattr(plugin, "debug_mode", False):
                                logger.info(f"已发送消息到群 {group_id}（平台ID={qq_adapter_id}）")
                            else:
                                logger.debug(f"已发送消息到群 {group_id}（平台ID={qq_adapter_id}）")
                        except Exception:
                            logger.debug(f"已发送消息到群 {group_id}（平台ID={qq_adapter_id}）")
                    except Exception as e:
                        logger.warning(f"发送消息到群 {group_id} 失败: {str(e)}")
                else:
                    logger.warning(f"context 未设置，无法发送消息到群 {group_id}")
            except Exception as e:
                logger.error(f"发送消息到群 {group_id} 时出错: {str(e)}")

    async def is_connected(self) -> bool:
        """实现基类的连接状态检查方法"""
        return self.websocket_manager.connected

    async def send_mc_message(self, message: str, sender: str = None):
        """发送消息到Minecraft服务器"""
        return await self.message_sender.send_broadcast_message(message, sender)

    async def send_rich_message(self, text: str, click_url: str="", hover_text: str="", images: List[str]=None, color: str = "#E6E6FA"):
        """发送富文本消息到Minecraft服务器"""
        return await self.message_sender.send_rich_message(text, click_url, hover_text, images, color)

    async def send_private_message(self, uuid: str, components: List[Dict[str, Any]]):
        """发送私聊消息到指定玩家"""
        return await self.message_sender.send_private_message(uuid, components)

    async def terminate(self):
        """终止平台适配器"""
        # 关闭 websocket 连接
        await self.websocket_manager.close()
        
        # 清理平台适配器注册信息
        try:
            from astrbot.core.platform.register import platform_cls_map, platform_registry
            logger.debug(f"清理前 platform_cls_map: {list(platform_cls_map.keys())}")
            logger.debug(f"清理前 platform_registry: {[p.name for p in platform_registry]}")
            
            if "minecraft" in platform_cls_map:
                del platform_cls_map["minecraft"]
            # 从注册表中移除
            for i, platform_metadata in enumerate(platform_registry):
                if platform_metadata.name == "minecraft":
                    del platform_registry[i]
                    break
                    
            logger.debug(f"清理后 platform_cls_map: {list(platform_cls_map.keys())}")
            logger.debug(f"清理后 platform_registry: {[p.name for p in platform_registry]}")
        except Exception as e:
            logger.error(f"清理 Minecraft 平台适配器注册信息失败: {str(e)}")
            
        logger.info("Minecraft平台适配器已被优雅地关闭")

    # 绑定和解绑群聊的方法（委托给GroupBindingManager）
    async def bind_group(self, group_id: str, server_name: str = None) -> bool:
        """绑定群聊与Minecraft服务器"""
        if server_name is None:
            server_name = self._server_name
        return self.binding_manager.bind_group(group_id, server_name)

    async def unbind_group(self, group_id: str, server_name: str = None) -> bool:
        """解除群聊与Minecraft服务器的绑定"""
        if server_name is None:
            server_name = self._server_name
        return self.binding_manager.unbind_group(group_id, server_name)

    def is_group_bound(self, group_id: str, server_name: str = None) -> bool:
        """检查群聊是否与Minecraft服务器绑定"""
        if server_name is None:
            server_name = self._server_name
        return self.binding_manager.is_group_bound(group_id, server_name)

    def is_bot_player(self, player_name: str) -> bool:
        """检查玩家是否为假人（委托给BotFilter）"""
        return self.bot_filter.is_bot_player(player_name)

    
