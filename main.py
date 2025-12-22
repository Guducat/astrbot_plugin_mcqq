import asyncio
from typing import Optional, List, Any

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain
from astrbot import logger
from astrbot.core.platform.manager import PlatformManager
from astrbot.core.star.star_tools import StarTools

# 常量定义
PLUGIN_DATA_DIR = "mcqq"

# 导入平台适配器
from .core.adapters.minecraft_adapter import MinecraftPlatformAdapter
# 导入管理器
from .core.managers.rcon_manager import RconManager
from .core.managers.broadcast_config import BroadcastConfigManager
from .core.managers.broadcast_sender import BroadcastSender
from .core.managers.broadcast_scheduler import BroadcastScheduler
# 导入命令处理器
from .core.handlers.command_handler import CommandHandler
# 导入路由管理器
from .core.routing.adapter_router import AdapterRouter

@register("mcqq Another！", "Akiyo-dayo", "通过鹊桥模组实现Minecraft平台适配器，以及mcqq互联的插件，支持QQ群与MC双向自动转发", "1.9.0", "https://github.com/Akiyo-dayo/astrbot_plugin_mcqq")
class MCQQPlugin(Star):
    def __init__(self, context: Context, config: Any = None):
        super().__init__(context)

        # 获取平台管理器
        self.platform_manager = None
        self.minecraft_adapter = None
        
        # 初始化标志
        self._initialization_complete = False

        # 获取数据目录
        self.data_dir = StarTools.get_data_dir(PLUGIN_DATA_DIR)
        
        # 读取插件配置
        # AstrBot 会在插件存在 `_conf_schema.json` 时，将插件配置作为第二个参数传入 __init__（见官方文档）。
        # 旧版本/兼容场景下可能不传入，则回退到 Context.get_config()（这是全局配置，可能无法反映 WebUI 的插件配置）。
        self.config = config if config is not None else self.context.get_config()
        self._apply_config(self.config)

        # 初始化管理器
        self.rcon_manager = RconManager()
        self.broadcast_config_manager = BroadcastConfigManager(str(self.data_dir))
        self.broadcast_sender = BroadcastSender()
        self.broadcast_scheduler = BroadcastScheduler(self, self.broadcast_config_manager, self._broadcast_callback)
        
        # 初始化路由管理器
        self.adapter_router = AdapterRouter(str(self.data_dir))
        
        # 初始化命令处理器
        self.command_handler = CommandHandler(self)

        # 初始化平台适配器 - 使用 ensure_future 而不是 create_task 以确保任务创建
        self._init_task = asyncio.ensure_future(self._initialize_all())
        
    async def _initialize_all(self):
        """统一的初始化流程，确保按顺序完成"""
        try:
            # 初始化平台适配器
            await self.initialize_adapter()
            # 初始化RCON连接 (将从适配器配置读取设置)
            await self.initialize_rcon()
            # 启动整点广播任务
            await self.start_hourly_broadcast()
            
            self._initialization_complete = True
            logger.info("✨ MCQQ插件初始化完成")
        except Exception as e:
            logger.error(f"❌ MCQQ插件初始化失败: {str(e)}")

    async def initialize_adapter(self):
        """初始化Minecraft平台适配器"""
        # 主动轮询等待平台管理器和适配器初始化完成
        max_wait_time = 30  # 最多等待30秒
        check_interval = 1  # 每1秒检查一次
        elapsed = 0
        
        logger.info("等待平台管理器和Minecraft适配器初始化...")

        # 获取平台管理器 - 尝试从多个可能的位置获取
        while elapsed < max_wait_time:
            self.platform_manager = None
            
            # 方法1: 从 context 属性中查找
            for attr_name in dir(self.context):
                try:
                    attr = getattr(self.context, attr_name)
                    if isinstance(attr, PlatformManager):
                        self.platform_manager = attr
                        logger.debug(f"从 context.{attr_name} 找到平台管理器")
                        break
                except Exception as e:
                    continue
            
            # 方法2: 尝试直接访问（适用于热重载）
            if not self.platform_manager:
                try:
                    if hasattr(self.context, 'platform_manager'):
                        self.platform_manager = self.context.platform_manager
                        logger.debug("从 context.platform_manager 找到平台管理器")
                except Exception:
                    pass
            
            if self.platform_manager:
                # 检查是否有 Minecraft 适配器
                minecraft_adapters = [p for p in self.platform_manager.platform_insts 
                                     if isinstance(p, MinecraftPlatformAdapter)]
                if minecraft_adapters:
                    logger.info(f"✅ 在 {elapsed} 秒后找到平台管理器和 {len(minecraft_adapters)} 个 Minecraft 适配器")
                    break
                else:
                    logger.debug(f"平台管理器已找到，但暂未发现 Minecraft 适配器 (已等待 {elapsed}s)")
            
            await asyncio.sleep(check_interval)
            elapsed += check_interval
        
        if not self.platform_manager:
            logger.error("❌ 无法获取平台管理器，Minecraft平台适配器将无法正常工作")
            return

        # 查找所有Minecraft平台适配器
        minecraft_adapters = []
        for platform in self.platform_manager.platform_insts:
            if isinstance(platform, MinecraftPlatformAdapter):
                minecraft_adapters.append(platform)
                logger.info(f"🔍 找到Minecraft平台适配器: {platform.adapter_id} ({platform.server_name})")

                # 设置上下文引用，以便适配器可以使用context.send_message方法
                platform.context = self.context
                # 设置插件实例引用
                platform.plugin_instance = self
                # 设置路由器引用 - 重要：必须在适配器开始接收消息前设置
                platform.router = self.adapter_router
                logger.info(f"✅ 为适配器 {platform.adapter_id} 设置路由器引用")
                
                # 同步插件配置到适配器（覆盖适配器自己的配置）
                platform.message_handler.enable_join_quit = self.enable_join_quit_messages
                logger.info(f"📝 适配器 {platform.adapter_id} 的 enable_join_quit 设置为: {self.enable_join_quit_messages}")
                
                # 注册到路由管理器
                self.adapter_router.register_adapter(platform)
                logger.info(f"📝 适配器 {platform.adapter_id} 已注册到路由管理器")
                
        logger.info(f"📊 总共找到 {len(minecraft_adapters)} 个Minecraft适配器")
        if minecraft_adapters:
            logger.info(f"🔗 路由管理器中注册的适配器: {list(self.adapter_router.adapters.keys())}")
                
        if minecraft_adapters:
            # 默认使用第一个适配器作为主适配器
            self.minecraft_adapter = minecraft_adapters[0]
            logger.info(f"⭐ 已设置主适配器: {self.minecraft_adapter.adapter_id}")
        else:
            self.minecraft_adapter = None
            logger.warning("⚠️ 未找到任何Minecraft平台适配器，请确保适配器已正确注册并启用")

    async def initialize_rcon(self):
        """初始化RCON客户端并尝试连接"""
        # 等待适配器初始化完成 - 依赖于initialize_adapter
        await asyncio.sleep(1)

        await self.rcon_manager.initialize(self.minecraft_adapter)

    async def start_hourly_broadcast(self):
        """启动整点广播任务"""
        # 等待适配器初始化 - 依赖于initialize_adapter
        await asyncio.sleep(1)
        self.broadcast_scheduler.start()

    async def _broadcast_callback(self, adapters, components):
        """广播回调函数"""
        if adapters:
            return await self.broadcast_sender.send_rich_broadcast(adapters, components)
        return False

    def _reload_config(self):
        """重新加载插件配置"""
        try:
            # 若 AstrBotConfig 支持从文件刷新，优先刷新
            for meth in ("reload_config", "load_config", "reload", "refresh"):
                try:
                    fn = getattr(self.config, meth, None)
                    if callable(fn):
                        fn()
                        break
                except Exception:
                    continue

            self._apply_config(self.config)
            
            logger.info(
                "📝 配置已重新加载: "
                f"enable_qq_to_mc_forward={self.enable_qq_to_mc_forward}, "
                f"debug_mode={getattr(self, 'debug_mode', False)}, "
                f"enable_join_quit_messages={self.enable_join_quit_messages}, "
                f"qq_image_forward_mode={self.qq_image_forward_mode}, "
                f"enable_mc_chat_to_qq_forward={self.enable_mc_chat_to_qq_forward}, "
                f"enable_death_messages={self.enable_death_messages}, "
                f"enable_mc_qq_command={self.enable_mc_qq_command}"
            )
            
            # 同步配置到所有适配器
            if self.platform_manager:
                for platform in self.platform_manager.platform_insts:
                    if isinstance(platform, MinecraftPlatformAdapter):
                        platform.message_handler.enable_join_quit = self.enable_join_quit_messages
                        logger.info(f"✅ 适配器 {platform.adapter_id} 配置已更新")
            
            return True
        except Exception as e:
            logger.error(f"❌ 重新加载配置失败: {str(e)}")
            return False

    def _apply_config(self, cfg: Any):
        """将配置字典应用到插件实例（cfg 需支持 dict.get）。"""
        try:
            self.enable_qq_to_mc_forward = cfg.get("enable_qq_to_mc_forward", True)
            self.debug_mode = cfg.get("debug_mode", False)
            self.qq_forward_message_color = cfg.get("qq_forward_message_color", "#00BFFF")
            self.qq_image_forward_mode = (cfg.get("qq_image_forward_mode", "clean") or "clean").strip().lower()
            self.enable_join_quit_messages = cfg.get("enable_join_quit_messages", True)
            self.enable_mc_chat_to_qq_forward = cfg.get("enable_mc_chat_to_qq_forward", False)
            self.enable_death_messages = cfg.get("enable_death_messages", True)
            self.enable_mc_qq_command = cfg.get("enable_mc_qq_command", True)
        except Exception:
            # 极端兼容：cfg 不是 dict-like 时全部回退默认
            self.enable_qq_to_mc_forward = True
            self.debug_mode = False
            self.qq_forward_message_color = "#00BFFF"
            self.qq_image_forward_mode = "clean"
            self.enable_join_quit_messages = True
            self.enable_mc_chat_to_qq_forward = False
            self.enable_death_messages = True
            self.enable_mc_qq_command = True

    async def get_all_minecraft_adapter(self) -> List[MinecraftPlatformAdapter]:
        """获取所有Minecraft平台适配器"""
        minecraft_adapters = []

        if self.platform_manager:
            for platform in self.platform_manager.platform_insts:
                if isinstance(platform, MinecraftPlatformAdapter):
                    minecraft_adapters.append(platform)
                    logger.debug(f"找到Minecraft平台适配器: {platform.adapter_id}")

        if not minecraft_adapters:
            logger.warning("未找到任何Minecraft平台适配器，请确保适配器已正确注册并启用")

        return minecraft_adapters

    async def _handle_command(self, event: AstrMessageEvent, handler_method, is_async=True):
        """统一的命令处理方法，减少重复代码"""
        # 检查初始化是否完成
        if not self._initialization_complete:
            yield event.plain_result("⏳ 插件正在初始化中，请稍后再试...")
            return
            
        event.should_call_llm(True)
        result = await handler_method(event) if is_async else handler_method(event)
        yield event.plain_result(result)

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_qq_group_message(self, event: AstrMessageEvent):
        """
        监听QQ群消息并转发到绑定的Minecraft服务器（无需唤醒词）
        
        特性：
        1. 只转发绑定了MC服务器的群消息
        2. 自动过滤机器人自己发送的消息
        3. 支持文本和图片（图片会转换为URL）
        4. 不会触发LLM响应
        5. 可通过配置文件开关
        """
        # 检查功能是否启用
        if not self.enable_qq_to_mc_forward:
            return
        
        # 等待初始化完成
        if not self._initialization_complete:
            return
        
        # 只处理 QQ 平台的消息（兼容 aiocqhttp / aiocqhttp_platform）
        platform_name = (event.get_platform_name() or "").strip()
        if platform_name not in ("aiocqhttp", "aiocqhttp_platform"):
            return
        
        # 获取群号
        group_id = event.get_group_id()
        if not group_id:
            return

        # 尽量获取群名，用于 MC 内显示；拿不到就回退到群号
        group_name = None
        try:
            if hasattr(event, "get_group_name") and callable(getattr(event, "get_group_name")):
                group_name = event.get_group_name()
        except Exception:
            group_name = None
        try:
            if not group_name and hasattr(event, "message_obj") and getattr(event.message_obj, "group_name", None):
                group_name = getattr(event.message_obj, "group_name", None)
        except Exception:
            pass

        group_display = (str(group_name).strip() if group_name else str(group_id).strip())
        group_display = group_display.replace("\n", " ").replace("\r", " ")
        
        # 检查该群是否绑定了任何MC服务器
        adapters = self.adapter_router.get_all_adapters()
        bound_adapters = []
        for adapter in adapters:
            try:
                if not adapter.is_group_bound(group_id):
                    continue

                # 每群/每服细粒度开关：qq_to_mc.forward
                server_name = getattr(adapter, "server_name", None) or getattr(adapter, "_server_name", None)
                if server_name and hasattr(adapter, "binding_manager"):
                    if not adapter.binding_manager.get_group_flag(server_name, group_id, "qq_to_mc.forward", True):
                        continue

                bound_adapters.append(adapter)
            except Exception:
                continue
        
        if not bound_adapters:
            # 该群未绑定任何MC服务器，不处理
            return
        
        # 获取发送者信息
        sender_name = event.get_sender_name() or "未知用户"
        sender_id = event.get_sender_id()
        
        # 过滤机器人自己发送的消息
        self_id = event.get_self_id()
        if sender_id == self_id:
            return
        
        # 获取消息内容
        message_text = event.message_str.strip()
        if not message_text:
            # 纯图片消息也处理
            pass
        
        # 提取图片URL
        image_urls = []
        for msg_component in event.get_messages():
            component_type = msg_component.__class__.__name__
            if component_type == "Image":
                if hasattr(msg_component, 'url') and msg_component.url:
                    image_urls.append(str(msg_component.url))
        
        # 如果既没有文本也没有图片，不处理
        if not message_text and not image_urls:
            return
        
        # 构造转发消息
        # 格式：用户名:消息内容（MC 侧自带标签，这里不再附加群名/前缀）
        image_mode = (self.qq_image_forward_mode or "clean").strip().lower()
        if image_mode not in ("clean", "cicode", "raw"):
            image_mode = "clean"

        forward_text = ""
        send_images = None

        if image_urls:
            if image_mode == "raw":
                # 不修改：沿用旧逻辑（仍会附带图片URL组件）
                forward_text = f"{sender_name}:{message_text.strip()}" if message_text else f"{sender_name}:发送了图片"
                send_images = image_urls
            elif image_mode == "cicode":
                # 增强：把图片编码为 CICode，避免 OneBot 图片段导致的服务端转换失败
                safe_urls = [(u or "").strip().replace(",", "%2C") for u in image_urls if u and str(u).strip()]
                cicode_parts = [f"[[CICode,url={u},name=Image]]" for u in safe_urls]
                if message_text:
                    forward_text = f"{sender_name}:{message_text.strip()} " + " ".join(cicode_parts)
                else:
                    forward_text = f"{sender_name}:发送了图片 " + " ".join(cicode_parts)
                send_images = None
            else:
                # clean（默认）：清洗为“发送了图片”，不再附带图片URL/组件，最大兼容
                if message_text:
                    forward_text = f"{sender_name}:{message_text.strip()}（含图片）"
                else:
                    forward_text = f"{sender_name}:发送了图片"
                send_images = None
        else:
            forward_text = f"{sender_name}:{message_text.strip()}"
            send_images = None
        
        # 转发到所有绑定该群的MC服务器
        success_count = 0
        for adapter in bound_adapters:
            if await adapter.is_connected():
                try:
                    # 发送富文本消息（包含图片）
                    await adapter.send_rich_message(
                        text=forward_text,
                        hover_text=f"来自群 {group_display} ({group_id})",
                        images=send_images,
                        color=self.qq_forward_message_color  # 使用配置的颜色
                    )
                    success_count += 1
                    logger.debug(f"已转发QQ群 {group_id} 的消息到MC服务器 {adapter.adapter_id}")
                except Exception as e:
                    logger.error(f"转发消息到MC服务器 {adapter.adapter_id} 失败: {str(e)}")
        
        if success_count > 0:
            logger.info(f"✉️ QQ→MC: {sender_name}: {message_text[:30]}... (转发到{success_count}个服务器)")
        
        # 阻止该消息触发LLM和其他默认处理
        event.should_call_llm(False)
        # 不停止事件传播，让其他插件也能处理

    @filter.command("mcbind")
    async def mc_bind_command(self, event: AstrMessageEvent):
        """绑定群聊与Minecraft服务器的命令"""
        async for result in self._handle_command(event, self.command_handler.handle_bind_command):
            yield result

    @filter.command("mcunbind")
    async def mc_unbind_command(self, event: AstrMessageEvent):
        """解除群聊与Minecraft服务器的绑定命令"""
        async for result in self._handle_command(event, self.command_handler.handle_unbind_command):
            yield result

    @filter.command("mcstatus")
    async def mc_status_command(self, event: AstrMessageEvent):
        """显示Minecraft服务器连接状态和绑定信息的命令"""
        async for result in self._handle_command(event, self.command_handler.handle_status_command):
            yield result

    @filter.command("mc设置")
    async def mc_settings_command(self, event: AstrMessageEvent):
        """配置本群在某服务器下的互通细项开关"""
        async for result in self._handle_command(event, self.command_handler.handle_settings_command):
            yield result

    @filter.command("mcsay")
    async def mc_say_command(self, event: AstrMessageEvent):
        """向Minecraft服务器发送消息的命令"""
        async for result in self._handle_command(event, self.command_handler.handle_say_command):
            yield result

    @filter.command("mc帮助")
    async def mc_help_command(self, event: AstrMessageEvent):
        """显示Minecraft相关命令的帮助信息"""
        async for result in self._handle_command(event, self.command_handler.handle_help_command, False):
            yield result

    @filter.command("mcreload")
    async def mc_reload_config_command(self, event: AstrMessageEvent):
        """重新加载插件配置"""
        try:
            if self._reload_config():
                yield event.plain_result("✅ 配置已重新加载\n"
                                       f"• QQ→MC转发: {'开启' if self.enable_qq_to_mc_forward else '关闭'}\n"
                                       f"• 调试模式: {'开启' if getattr(self, 'debug_mode', False) else '关闭'}\n"
                                       f"• MC聊天→QQ: {'开启' if self.enable_mc_chat_to_qq_forward else '关闭'}\n"
                                       f"• 进入/退出消息: {'开启' if self.enable_join_quit_messages else '关闭'}\n"
                                       f"• 死亡消息: {'开启' if self.enable_death_messages else '关闭'}\n"
                                       f"• #qq指令: {'开启' if self.enable_mc_qq_command else '关闭'}\n"
                                       "（群内细项：/mc设置）")
            else:
                yield event.plain_result("❌ 配置重新加载失败，请查看日志")
        except Exception as e:
            yield event.plain_result(f"❌ 重新加载配置时出错: {str(e)}")

    @filter.command("rcon")
    async def rcon_command(self, event: AstrMessageEvent):
        """通过RCON执行Minecraft服务器指令"""
        async for result in self._handle_command(event, self.command_handler.handle_rcon_command):
            yield result

    @filter.command("mc广播设置")
    async def mc_broadcast_config_command(self, event: AstrMessageEvent):
        """配置整点广播内容的命令"""
        async for result in self._handle_command(event, self.command_handler.handle_broadcast_config_command):
            yield result

    @filter.command("mc广播开关")
    async def mc_broadcast_toggle_command(self, event: AstrMessageEvent):
        """开启或关闭整点广播的命令"""
        async for result in self._handle_command(event, self.command_handler.handle_broadcast_toggle_command):
            yield result

    @filter.command("mc广播清除")
    async def mc_broadcast_clear_command(self, event: AstrMessageEvent):
        """清除自定义广播内容的命令"""
        async for result in self._handle_command(event, self.command_handler.handle_broadcast_clear_command):
            yield result

    @filter.command("mc广播测试")
    async def mc_broadcast_test_command(self, event: AstrMessageEvent):
        """测试整点广播的命令"""
        async for result in self._handle_command(event, self.command_handler.handle_broadcast_test_command):
            yield result

    @filter.command("mc自定义广播")
    async def mc_custom_broadcast_command(self, event: AstrMessageEvent):
        """发送自定义富文本广播的命令"""
        async for result in self._handle_command(event, self.command_handler.handle_custom_broadcast_command):
            yield result

    @filter.command("mc玩家列表")
    async def mc_player_list_command(self, event: AstrMessageEvent):
        """获取Minecraft服务器玩家列表的命令"""
        async for result in self._handle_command(event, self.command_handler.handle_player_list_command):
            yield result

    async def terminate(self):
        """插件终止时的清理工作"""
        logger.info("插件终止")
        
        # 保存路由器配置
        await self.adapter_router.save_config()
        
        # 关闭所有适配器
        await self.adapter_router.close_all_adapters()
        
        # 保存广播配置
        self.broadcast_config_manager.save_config()
        
        # 关闭RCON连接
        await self.rcon_manager.close()
        
        # 取消整点广播任务
        self.broadcast_scheduler.stop()
        
        # 清理平台适配器注册信息
        try:
            from astrbot.core.platform.register import platform_cls_map, platform_registry
            logger.debug(f"清理前 platform_cls_map: {list(platform_cls_map.keys())}")
            logger.debug(f"清理前 platform_registry: {[p.name for p in platform_registry]}")
            
            if "minecraft" in platform_cls_map:
                del platform_cls_map["minecraft"]
            for i, platform_metadata in enumerate(platform_registry):
                if platform_metadata.name == "minecraft":
                    del platform_registry[i]
                    break
                    
            logger.debug(f"清理后 platform_cls_map: {list(platform_cls_map.keys())}")
            logger.debug(f"清理后 platform_registry: {[p.name for p in platform_registry]}")
        except Exception as e:
            logger.error(f"清理 Minecraft 平台适配器注册信息失败: {str(e)}")

    async def get_minecraft_adapter(self, server_name: Optional[str] = None) -> Optional[MinecraftPlatformAdapter]:
        """获取指定的Minecraft平台适配器，如果未指定则获取主适配器"""
        if server_name:
            for adapter in self.adapter_router.get_all_adapters():
                if adapter.server_name == server_name or adapter.adapter_id == server_name:
                    return adapter
            return None
        return self.minecraft_adapter
