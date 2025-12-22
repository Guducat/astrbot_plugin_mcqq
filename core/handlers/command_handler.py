"""命令处理器模块，集中管理所有命令的处理逻辑"""
import asyncio
from typing import Optional
from astrbot.api.event import AstrMessageEvent
from astrbot import logger
import base64, uuid
from astrbot.core.star.star_tools import StarTools
import os
import json


class AdapterNotFoundError(Exception):
    """当找不到适配器时引发的异常"""
    pass


class Messages:
    """命令响应消息常量"""
    ADMIN_REQUIRED = "⛔ 只有管理员才能使用此命令"
    GROUP_REQUIRED = "❌ 此命令只能在群聊中使用"
    ADAPTER_NOT_FOUND = "❌ 未找到Minecraft平台适配器，请确保适配器已正确注册并启用"
    BIND_SUCCESS = "✅ 成功将本群与Minecraft服务器 {} 绑定"
    BIND_ALREADY = "ℹ️ 此群已经与Minecraft服务器 {} 绑定"
    UNBIND_SUCCESS = "✅ 成功解除本群与Minecraft服务器 {} 的绑定"
    UNBIND_NOT_BOUND = "ℹ️ 此群未与Minecraft服务器 {} 绑定"


class CommandHandler:
    """命令处理器类，用于分离命令处理逻辑"""
    
    def __init__(self, plugin_instance):
        self.plugin = plugin_instance
    
    def _decorator_require_admin(self, func):
        """管理员权限检查装饰器"""
        async def wrapper(event: AstrMessageEvent):
            if not event.is_admin():
                return Messages.ADMIN_REQUIRED
            return await func(event)
        return wrapper
    
    def _decorator_require_group(self, func):
        """群聊环境检查装饰器"""
        async def wrapper(event: AstrMessageEvent):
            group_id = event.get_group_id()
            if not group_id:
                return Messages.GROUP_REQUIRED
            return await func(event)
        return wrapper
    
    async def _get_target_adapter(self, server_name=None):
        """获取目标适配器的公共方法"""
        if server_name:
            for adapter in self.plugin.adapter_router.get_all_adapters():
                if adapter.server_name == server_name or adapter.adapter_id == server_name:
                    return adapter
            raise AdapterNotFoundError(f"❌ 未找到名为 {server_name} 的Minecraft适配器")
        
        adapter = await self.plugin.get_minecraft_adapter()
        if not adapter:
            raise AdapterNotFoundError(Messages.ADAPTER_NOT_FOUND)
        return adapter

    async def handle_bind_command(self, event: AstrMessageEvent):
        """处理mcbind命令，支持多服务器参数"""
        return await self._decorator_require_admin(self._decorator_require_group(self._handle_bind_logic))(event)
    
    async def handle_unbind_command(self, event: AstrMessageEvent):
        """处理mcunbind命令，支持多服务器参数"""
        return await self._decorator_require_admin(self._decorator_require_group(self._handle_unbind_logic))(event)
    
    async def _handle_binding_command(self, event: AstrMessageEvent, action: str):
        """绑定/解绑命令的公共逻辑"""
        group_id = event.get_group_id()
        tokens = event.message_str.strip().split()
        server_name = tokens[1] if len(tokens) > 1 else None

        try:
            adapter = await self._get_target_adapter(server_name)
        except AdapterNotFoundError as e:
            return str(e)

        if action == "bind":
            success = await adapter.bind_group(group_id)
            if success:
                logger.info(f"群聊 {group_id} 与服务器 {adapter.adapter_id} 绑定")
                return Messages.BIND_SUCCESS.format(adapter.adapter_id)
            else:
                return Messages.BIND_ALREADY.format(adapter.adapter_id)
        elif action == "unbind":
            success = await adapter.unbind_group(group_id)
            if success:
                logger.info(f"解除群聊 {group_id} 与服务器 {adapter.server_name} 的绑定")
                return Messages.UNBIND_SUCCESS.format(adapter.server_name)
            else:
                return Messages.UNBIND_NOT_BOUND.format(adapter.server_name)
    
    async def _handle_bind_logic(self, event: AstrMessageEvent):
        """绑定命令的核心逻辑"""
        return await self._handle_binding_command(event, "bind")
    
    async def _handle_unbind_logic(self, event: AstrMessageEvent):
        """解绑命令的核心逻辑"""
        return await self._handle_binding_command(event, "unbind")
    
    async def handle_status_command(self, event: AstrMessageEvent):
        """处理mcstatus命令"""
        group_id = event.get_group_id()
        
        # 获取所有适配器
        adapters = self.plugin.adapter_router.get_all_adapters()
        if not adapters:
            return "❌ 未找到任何Minecraft平台适配器，请确保适配器已正确注册并启用"

        # 构建状态消息
        # 注意：若插件未按 AstrBot 约定接收 config 参数（AstrBotConfig），则可能一直使用默认值；
        # 当前版本已支持 __init__(context, config) 来确保 WebUI 配置能被正确读取。
        status_msg = (
            "Minecraft适配器状态:\n"
            "全局开关（/mcreload 生效）:\n"
            f"• QQ→MC自动转发: {'✅ 开启' if getattr(self.plugin, 'enable_qq_to_mc_forward', False) else '❌ 关闭'}\n"
            f"• MC→QQ聊天: {'✅ 开启' if getattr(self.plugin, 'enable_mc_chat_to_qq_forward', False) else '❌ 关闭'}\n"
            f"• MC→QQ进退: {'✅ 开启' if getattr(self.plugin, 'enable_join_quit_messages', False) else '❌ 关闭'}\n"
            f"• MC→QQ死亡: {'✅ 开启' if getattr(self.plugin, 'enable_death_messages', True) else '❌ 关闭'}\n"
            f"• MC→QQ #qq: {'✅ 开启' if getattr(self.plugin, 'enable_mc_qq_command', True) else '❌ 关闭'}\n"
            "群内细项（每群/每服）：/mc设置\n"
        )
        
        connected_count = 0
        bound_count = 0
        
        for i, adapter in enumerate(adapters, 1):
            # 检查连接状态
            is_connected = await adapter.is_connected()
            if is_connected:
                connected_count += 1
                
            # 检查绑定状态（仅在群聊中检查）
            is_bound = False
            if group_id:
                is_bound = adapter.is_group_bound(group_id)
                if is_bound:
                    bound_count += 1
            
            # 添加适配器状态信息
            status_msg += f"{i}. {adapter.server_name} ({adapter.adapter_id})\n"
            status_msg += f"   连接: {'✅ 已连接' if is_connected else '❌ 未连接'}\n"
            
            if group_id:
                status_msg += f"   绑定: {'✅ 已绑定' if is_bound else '❌ 未绑定'}\n"

                if is_bound and hasattr(adapter, "binding_manager"):
                    server_name = getattr(adapter, "server_name", None) or getattr(adapter, "_server_name", "")
                    qq2mc = adapter.binding_manager.get_group_flag(server_name, group_id, "qq_to_mc.forward", True)
                    mc_chat = adapter.binding_manager.get_group_flag(server_name, group_id, "mc_to_qq.chat", True)
                    mc_join_quit = adapter.binding_manager.get_group_flag(server_name, group_id, "mc_to_qq.join_quit", True)
                    mc_death = adapter.binding_manager.get_group_flag(server_name, group_id, "mc_to_qq.death", True)
                    mc_qq = adapter.binding_manager.get_group_flag(server_name, group_id, "mc_to_qq.qq_command", True)

                    eff_qq2mc = bool(getattr(self.plugin, "enable_qq_to_mc_forward", False)) and qq2mc
                    eff_chat = bool(getattr(self.plugin, "enable_mc_chat_to_qq_forward", False)) and mc_chat
                    eff_join_quit = bool(getattr(self.plugin, "enable_join_quit_messages", False)) and mc_join_quit
                    eff_death = bool(getattr(self.plugin, "enable_death_messages", True)) and mc_death
                    eff_qq = bool(getattr(self.plugin, "enable_mc_qq_command", True)) and mc_qq

                    status_msg += (
                        f"   本群开关: QQ→MC{'✅' if qq2mc else '❌'} | 聊天{'✅' if mc_chat else '❌'} | "
                        f"进退{'✅' if mc_join_quit else '❌'} | 死亡{'✅' if mc_death else '❌'} | #qq{'✅' if mc_qq else '❌'}\n"
                        f"   生效状态: QQ→MC{'✅' if eff_qq2mc else '❌'} | 聊天{'✅' if eff_chat else '❌'} | "
                        f"进退{'✅' if eff_join_quit else '❌'} | 死亡{'✅' if eff_death else '❌'} | #qq{'✅' if eff_qq else '❌'}\n"
                    )
            
            # 如果未连接，尝试手动启动连接
            if not is_connected:
                try:
                    adapter.websocket_manager.connected = False
                    adapter.websocket_manager.websocket = None
                    adapter.websocket_manager.should_reconnect = True
                    adapter.websocket_manager.total_retries = 0
                    asyncio.create_task(adapter.websocket_manager.start())
                    status_msg += f"   状态: ⏳ 正在尝试重连...\n"
                except Exception as e:
                    status_msg += f"   状态: ❌ 重连失败: {str(e)}\n"
            
        return status_msg

    def _parse_bool_token(self, token: str) -> Optional[bool]:
        t = (token or "").strip().lower()
        truthy = {"on", "true", "1", "yes", "y", "开启", "开", "启用", "启"}
        falsy = {"off", "false", "0", "no", "n", "关闭", "关", "禁用", "停"}
        if t in truthy:
            return True
        if t in falsy:
            return False
        return None

    def _render_group_settings(self, group_id: str) -> str:
        adapters = self.plugin.adapter_router.get_all_adapters()
        bound_adapters = [a for a in adapters if a.is_group_bound(group_id)]
        if not bound_adapters:
            return "❌ 本群未绑定任何Minecraft服务器，请先使用 /mcbind 进行绑定"

        lines = ["本群互通细项（每服务器独立）:"]
        for i, adapter in enumerate(bound_adapters, 1):
            server_name = getattr(adapter, "server_name", None) or getattr(adapter, "_server_name", "")
            if not hasattr(adapter, "binding_manager"):
                continue

            qq2mc = adapter.binding_manager.get_group_flag(server_name, group_id, "qq_to_mc.forward", True)
            mc_chat = adapter.binding_manager.get_group_flag(server_name, group_id, "mc_to_qq.chat", True)
            mc_join_quit = adapter.binding_manager.get_group_flag(server_name, group_id, "mc_to_qq.join_quit", True)
            mc_death = adapter.binding_manager.get_group_flag(server_name, group_id, "mc_to_qq.death", True)
            mc_qq = adapter.binding_manager.get_group_flag(server_name, group_id, "mc_to_qq.qq_command", True)

            lines.append(f"{i}. {adapter.server_name} ({adapter.adapter_id})")
            lines.append(f"   QQ→MC自动转发: {'✅' if qq2mc else '❌'}")
            lines.append(
                f"   MC→QQ: 聊天{'✅' if mc_chat else '❌'} | 进退{'✅' if mc_join_quit else '❌'} | "
                f"死亡{'✅' if mc_death else '❌'} | #qq{'✅' if mc_qq else '❌'}"
            )

        lines.append("用法: /mc设置 <服务器名/适配器ID> <qq2mc|chat|join|death|qqcmd> <on/off>")
        return "\n".join(lines)

    async def handle_settings_command(self, event: AstrMessageEvent):
        """处理mc设置命令：查看/修改本群在某服务器下的转发细项"""
        return await self._decorator_require_admin(self._decorator_require_group(self._handle_settings_logic))(event)

    async def _handle_settings_logic(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        tokens = event.message_str.strip().split()

        # /mc设置 -> 展示本群当前细项
        if len(tokens) == 1:
            return self._render_group_settings(group_id)

        # /mc设置 帮助
        if len(tokens) == 2 and tokens[1] in ("help", "?", "帮助"):
            return (
                "用法:\n"
                "  /mc设置 - 查看本群细项\n"
                "  /mc设置 <服务器名/适配器ID> <qq2mc|chat|join|death|qqcmd> <on/off>\n"
                "示例:\n"
                "  /mc设置 Server chat on\n"
                "  /mc设置 Server qq2mc off\n"
            )

        if len(tokens) < 4:
            return "❓ 参数不足，发送 /mc设置 帮助 查看用法"

        server_name = tokens[1]
        item = (tokens[2] or "").strip().lower()
        value = self._parse_bool_token(tokens[3])
        if value is None:
            return "❓ 开关值请使用 on/off 或 开启/关闭"

        item_to_path = {
            "qq2mc": "qq_to_mc.forward",
            "qq_to_mc": "qq_to_mc.forward",
            "chat": "mc_to_qq.chat",
            "join": "mc_to_qq.join_quit",
            "joinquit": "mc_to_qq.join_quit",
            "join_quit": "mc_to_qq.join_quit",
            "death": "mc_to_qq.death",
            "qqcmd": "mc_to_qq.qq_command",
            "qq_command": "mc_to_qq.qq_command",
        }
        path = item_to_path.get(item)
        if not path:
            return "❓ 未知设置项，可用项：qq2mc/chat/join/death/qqcmd（发送 /mc设置 帮助）"

        try:
            adapter = await self._get_target_adapter(server_name)
        except AdapterNotFoundError as e:
            return str(e)

        if not adapter.is_group_bound(group_id):
            return f"❌ 本群未绑定服务器 {adapter.server_name}，请先使用 /mcbind {adapter.adapter_id}"

        ok = False
        try:
            server_key = getattr(adapter, "server_name", None) or getattr(adapter, "_server_name", "")
            ok = adapter.binding_manager.set_group_flag(server_key, group_id, path, value)
        except Exception as e:
            logger.error(f"设置本群转发细项失败: {e}")
            ok = False

        if not ok:
            return "❌ 设置失败，请查看日志"

        return "✅ 设置已更新\n" + self._render_group_settings(group_id)
    
    async def handle_say_command(self, event: AstrMessageEvent):
        """处理mcsay命令，支持图片"""
        message = event.message_str.replace("mcsay", "", 1).strip()
        images = []
        for item in event.get_messages():
            if item.__class__.__name__ == "Image":
                if hasattr(item, 'url') and item.url:
                    images.append(str(item.url))
        if message == "" and not images:
            return "❓ 请提供要发送的消息内容，例如：/mcsay 大家好"

        sender = event.get_sender_name()
        logger.info(sender)
        adapters = self.plugin.adapter_router.get_all_adapters()
        if not adapters:
            return "❌ 未找到任何Minecraft平台适配器，请确保适配器已正确注册并启用"
        connected_adapters = [adapter for adapter in adapters if await adapter.is_connected()]
        if not connected_adapters:
            return "❌ 所有Minecraft适配器都未连接，请检查连接状态"
        try:
            await self.plugin.adapter_router.broadcast_message(message, sender, images)
        except Exception as e:
            logger.error(f"发送消息到Minecraft服务器时出错: {str(e)}")
            return f"❌ 发送消息失败: {str(e)}"
        return "✅ 消息已发送到所有在线的Minecraft服务器"
    
    def handle_help_command(self, event: AstrMessageEvent):
        """处理mc帮助命令（支持子菜单：qq2mc / mc2qq / admin / 设置）"""
        raw = (event.message_str or "").strip()
        tokens = raw.split(maxsplit=1)
        sub = (tokens[1] if len(tokens) > 1 else "").strip()
        sub_lower = sub.lower()

        # 全局开关状态（注意：群内细项以 /mc设置 为准）
        qq_to_mc_status = "✅ 开启" if getattr(self.plugin, "enable_qq_to_mc_forward", False) else "❌ 关闭"
        mc_chat_status = "✅ 开启" if getattr(self.plugin, "enable_mc_chat_to_qq_forward", False) else "❌ 关闭"
        join_quit_status = "✅ 开启" if getattr(self.plugin, "enable_join_quit_messages", False) else "❌ 关闭"
        death_status = "✅ 开启" if getattr(self.plugin, "enable_death_messages", True) else "❌ 关闭"
        qq_cmd_status = "✅ 开启" if getattr(self.plugin, "enable_mc_qq_command", True) else "❌ 关闭"

        if sub_lower in ("qq2mc", "qq", "qq群", "群", "qq->mc", "qq群->mc", "qq到mc", "qq到mc"):
            return f"""
QQ群 → MC 指令菜单:

🔁 互通状态（全局）:
    QQ→MC自动转发: {qq_to_mc_status}
    说明: 绑定后，QQ群普通消息可自动转发到对应MC服务器（每群/每服细项用 /mc设置）

💬 QQ群指令:
    /mcbind [服务器名] - 绑定当前群与指定服务器（不填为主服务器）
    /mcunbind [服务器名] - 解除绑定
    /mcstatus - 查看连接/绑定/开关状态
    /mc设置 - 查看/配置本群细项开关
    /mcsay <消息> - 向所有已连接的MC服务器发送消息
    /mcreload - 重新加载插件配置（WebUI修改后立即生效）
"""

        if sub_lower in ("mc2qq", "mc", "游戏内", "mc->qq", "mc到qq", "mc->qq群", "mc→qq"):
            return f"""
MC → QQ 指令菜单:

🔁 互通状态（全局）:
    MC聊天→QQ: {mc_chat_status}
    进出游戏→QQ: {join_quit_status}
    死亡消息→QQ: {death_status}
    #qq指令: {qq_cmd_status}
    说明: 绑定后转发到QQ群（每群/每服细项用 /mc设置）

🎮 MC游戏内指令:
    #<内容> - 发起AI对话
    #qq <消息> - 向QQ群发送消息
    #wiki <词条名称> - 查询Minecraft Wiki
"""

        if sub_lower in ("admin", "管理员"):
            return """
管理员指令菜单:

🔧 管理员指令:
    /rcon <指令> - 通过RCON执行Minecraft服务器指令
    /rcon 重启 - 尝试重新连接RCON服务器
    /mc广播设置 [富文本配置] - 设置整点广播富文本内容
    /mc广播开关 - 开启/关闭整点广播
    /mc广播测试 - 测试发送整点广播
    /mc广播清除 - 清除自定义广播内容，恢复默认
    /mc自定义广播 [文本]|[点击命令]|[悬浮文本] - 发送自定义富文本广播
"""

        if sub_lower in ("设置", "config", "开关", "switch", "cfg"):
            return """
互通细项开关（群内/每服务器独立）:

用法:
  /mc设置 - 查看本群细项
  /mc设置 <服务器名/适配器ID> <qq2mc|chat|join|death|qqcmd> <on/off>

示例:
  /mc设置 Server chat on
  /mc设置 Server qq2mc off
"""

        # 默认总览菜单（告诉用户如何拆分打开）
        return f"""
Minecraft 指令菜单（总览）:

📌 子菜单:
    /mc帮助 qq2mc   - QQ群→MC 指令
    /mc帮助 mc2qq   - MC→QQ群 指令
    /mc帮助 admin   - 管理员指令
    /mc帮助 设置    - 互通细项开关

🔁 互通状态（全局）:
    QQ→MC自动转发: {qq_to_mc_status}
    MC聊天→QQ: {mc_chat_status}
    进出游戏→QQ: {join_quit_status}
    死亡消息→QQ: {death_status}
    #qq指令: {qq_cmd_status}

⚠️ 重要提示:
    • 修改插件配置（WebUI）后使用 /mcreload 立即生效
    • 绑定/解绑与细项开关：优先看 /mcstatus 和 /mc设置
    • 修改适配器配置（平台设置）后必须重启AstrBot
"""
    
    async def handle_rcon_command(self, event: AstrMessageEvent):
        """处理rcon命令"""
        return await self._decorator_require_admin(self._handle_rcon_logic)(event)
    
    async def _handle_rcon_logic(self, event: AstrMessageEvent):
        """RCON命令的核心逻辑"""
        command_to_execute = event.message_str.replace("rcon", "", 1).strip()
        try:
            adapter = await self._get_target_adapter()
        except AdapterNotFoundError as e:
            return str(e)

        success, message = await self.plugin.rcon_manager.execute_command(
            command_to_execute, event.get_sender_id(), adapter
        )
        return message
    
    async def handle_broadcast_config_command(self, event: AstrMessageEvent):
        """处理mc广播设置命令"""
        return await self._decorator_require_admin(self._handle_broadcast_config_logic)(event)
    
    async def _handle_broadcast_config_logic(self, event: AstrMessageEvent):
        """广播配置命令的核心逻辑"""
        command_content = event.message_str.replace("mc广播设置", "", 1).strip()
        if not command_content:
            return self.plugin.broadcast_config_manager.get_current_config_display()
        
        tokens = command_content.split(None, 1)
        if len(tokens) < 2:
            return "❌ 参数不足！\n用法：/mc广播设置 <adapter_id> <消息内容>"
        
        adapter_id, msg_content = tokens[0], tokens[1].strip()
        if not adapter_id or not msg_content:
            return "❌ 参数错误！\n用法：/mc广播设置 <adapter_id> <消息内容>"
        
        # 检查适配器是否存在
        adapter = next((a for a in self.plugin.adapter_router.get_all_adapters() if a.adapter_id == adapter_id), None)
        if not adapter:
            return f"❌ 未找到适配器 {adapter_id}，请检查ID是否正确"
        
        success, message = self.plugin.broadcast_config_manager.set_broadcast_content(adapter_id, msg_content)
        if success:
            logger.info(f"适配器 {adapter_id} 整点广播内容已更新")
        return message
    
    async def handle_broadcast_toggle_command(self, event: AstrMessageEvent):
        """处理mc广播开关命令"""
        return await self._decorator_require_admin(self._handle_broadcast_toggle_logic)(event)

    async def _handle_broadcast_toggle_logic(self, event: AstrMessageEvent):
        """广播开关命令的核心逻辑"""
        _, message = self.plugin.broadcast_config_manager.toggle_broadcast()
        return message

    async def handle_broadcast_clear_command(self, event: AstrMessageEvent):
        """处理mc广播清除命令"""
        return await self._decorator_require_admin(self._handle_broadcast_clear_logic)(event)
    
    async def _handle_broadcast_clear_logic(self, event: AstrMessageEvent):
        """广播清除命令的核心逻辑"""
        command_content = event.message_str.replace("mc广播清除", "", 1).strip()
        adapter_id = command_content if command_content else None
        _, message = self.plugin.broadcast_config_manager.clear_custom_content(adapter_id)
        return message

    async def handle_broadcast_test_command(self, event: AstrMessageEvent):
        """处理mc广播测试命令"""
        return await self._decorator_require_admin(self._handle_broadcast_test_logic)(event)
    
    async def _handle_broadcast_test_logic(self, event: AstrMessageEvent):
        """广播测试命令的核心逻辑"""
        command_content = event.message_str.replace("mc广播测试", "", 1).strip()
        adapter_id = command_content if command_content else None
        
        logger.info(f"用户 {event.get_sender_id()} 触发了测试广播")
        await self.plugin.broadcast_scheduler.execute_hourly_broadcast(self.plugin.adapter_router.get_all_adapters())
        return "✅ 已触发测试广播"

    async def handle_custom_broadcast_command(self, event: AstrMessageEvent):
        """处理mc自定义广播命令"""
        return await self._decorator_require_admin(self._handle_custom_broadcast_logic)(event)
    
    async def _handle_custom_broadcast_logic(self, event: AstrMessageEvent):
        """自定义广播命令的核心逻辑"""
        command_content = event.message_str.replace("mc自定义广播", "", 1).strip()
        
        # 解析参数
        parts = command_content.split('|')
        text_content = parts[0].strip() if len(parts) > 0 else ""
        click_value = parts[1].strip() if len(parts) > 1 else ""
        hover_text = parts[2].strip() if len(parts) > 2 else ""

        if not text_content:
            return "❌ 请提供广播的文本内容"

        adapters = self.plugin.adapter_router.get_all_adapters()
        if not adapters:
            return "❌ 未找到任何Minecraft适配器"
        
        try:
            success = await self.plugin.broadcast_sender.send_custom_rich_broadcast(adapters, text_content, click_value, hover_text)
            return "✅ 自定义广播已发送" if success else "❌ 发送自定义广播失败，请查看日志"
        except Exception as e:
            logger.error(f"发送自定义广播时出错: {str(e)}")
            return f"❌ 发送自定义广播时出错: {str(e)}"

    async def handle_player_list_command(self, event: AstrMessageEvent):
        """处理mc玩家列表命令"""
        try:
            adapter = await self._get_target_adapter()
        except AdapterNotFoundError as e:
            return str(e)
        
        if not await adapter.is_connected():
            return "❌ Minecraft适配器未连接，请检查连接状态"
        
        try:
            # 发送获取玩家列表的API请求
            api_request = {
                "api": "get_player_list",
                "data": {}
            }
            
            logger.debug(f"发送获取玩家列表请求: {api_request}")
            success = await adapter.websocket_manager.send_message(api_request)
            
            if not success:
                return "❌ 请求失败，请检查是否为mcdr插件或网络连接"
            
            # 等待响应 (创建一个简单的响应等待机制)
            response = await self._wait_for_api_response(adapter, "get_player_list", timeout=5)
            
            if not response:
                return "❌ 请求超时，请检查是否为mcdr插件或网络连接"
            
            return self._format_player_list_response(response)
            
        except Exception as e:
            logger.error(f"获取玩家列表时出错: {str(e)}")
            return "❌ 请求失败，请检查是否为mcdr插件或网络连接"
    
    async def _wait_for_api_response(self, adapter, api_name: str, timeout: int = 5):
        """等待API响应的辅助方法"""
        import asyncio
        import time
        
        # 设置响应等待器
        adapter.api_response_waiter = None
        start_time = time.time()
        
        # 创建一个临时的消息处理器来捕获API响应
        original_handler = adapter.websocket_manager.message_handler
        response_data = None
        
        async def temp_message_handler(message: str):
            nonlocal response_data
            try:
                data = json.loads(message)
                # 检查是否是我们期待的API响应
                if (data.get("api") == api_name or 
                    (data.get("data", {}).get("players") is not None and api_name == "get_player_list")):
                    response_data = data
                    return
            except:
                pass
            # 如果不是API响应，继续使用原始处理器
            if original_handler:
                await original_handler(message)
        
        # 临时替换消息处理器
        adapter.websocket_manager.set_message_handler(temp_message_handler)
        
        try:
            # 等待响应
            while time.time() - start_time < timeout and response_data is None:
                await asyncio.sleep(0.1)
            
            return response_data
        finally:
            # 恢复原始消息处理器
            adapter.websocket_manager.set_message_handler(original_handler)
    
    def _format_player_list_response(self, response):
        """格式化玩家列表响应"""
        try:
            if response.get("status") != "ok":
                return "❌ 服务器返回错误状态"
            
            data = response.get("data", {})
            players = data.get("players", [])
            count = data.get("count", 0)
            max_players = data.get("max_players", 0)
            
            if count == 0:
                return f"🎮 服务器当前无玩家在线 (0/{max_players})"
            
            result = f"🎮 在线玩家列表 ({count}/{max_players}):\n"
            
            for i, player in enumerate(players, 1):
                nickname = player.get("nickname", "未知")
                is_op = player.get("is_op", False)
                online = player.get("online", True)
                dimension = player.get("dimension")
                coordinate = player.get("coordinate")
                
                status_icon = "👑" if is_op else "👤"
                online_status = "🟢" if online else "🔴"
                
                result += f"{i}. {status_icon} {nickname} {online_status}"
                
                if dimension:
                    result += f" [{dimension}]"
                if coordinate:
                    result += f" ({coordinate})"
                
                result += "\n"
            
            return result.strip()
            
        except Exception as e:
            logger.error(f"格式化玩家列表时出错: {str(e)}")
            return "❌ 解析玩家列表数据时出错" 
