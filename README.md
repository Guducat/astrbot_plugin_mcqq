# astrbot_plugin_mcqq (Guducat Fork v2.0.0)

基于 [鹊桥模组 (Queqiao)](https://www.curseforge.com/minecraft/mc-mods/queqiao) 的 Minecraft 平台适配器插件：在 AstrBot 内实现 **QQ 群 ↔ Minecraft 服务器** 的消息互通，并提供 RCON、整点广播等管理能力。

本分支：**Guducat Fork v2.0.0**，以当前代码为准；适配 **AstrBot v4.10**，并已在 **NeoForge 1.21.1** 实际部署测试。

> 上游/参考：kterna / Akiyo-dayo 的 `astrbot_plugin_mcqq`。

## 功能概览（以当前实现为准）

- **QQ → MC（默认开启）**：绑定群后，QQ群普通消息会自动转发到对应 MC 服务器（无需唤醒词）。
  - 支持文字 + 图片（图片转发可选 `clean/cicode/raw` 三种模式，见配置）。
  - 支持按「**每群/每服务器**」细粒度开关（`/mc设置`）。
- **MC → QQ（可选项较多）**
  - 玩家 **进服/退服** 通知（默认开启，可全局关闭/按群按服关闭）。
  - 玩家 **死亡** 消息（默认开启，可全局关闭/按群按服关闭）。
  - **MC 普通聊天 → QQ** 自动转发（默认关闭，避免刷屏；开启后默认不转发以唤醒词开头的消息）。
  - **`<唤醒词>qq <消息>`**：游戏内主动转发到绑定 QQ 群（默认开启，可全局关闭/按群按服关闭）。
- **多服务器互通（MC ↔ MC）**：若配置了多个 Minecraft 适配器，聊天/进退/死亡会自动转发到其它在线服务器（由 AstrBot 中转）。
- **管理能力**
  - `/mcsay`：向所有在线 MC 服务器广播（支持图片）。
  - `/rcon`：通过 RCON 执行指令（**仅主适配器**）。
  - `/mc广播*`：整点广播开关、配置、测试、清除、自定义富文本广播。
  - `/mcreload`：重载插件配置（仅 `_conf_schema.json` 中的插件配置；平台适配器配置需重启）。

## 安装与前置

- **AstrBot**：v4.10（或兼容版本）。
- **QQ 平台**：当前实现仅对 `aiocqhttp` / `aiocqhttp_platform` 的群消息做「QQ→MC 自动转发」监听。
- **Minecraft 服务器**：
  - 使用鹊桥模组（Fabric/Forge/NeoForge 等），或
  - 使用鹊桥的 MCDR 移植版（`/mc玩家列表` 仅该方案可用）。

安装方式：将本插件放入 AstrBot 的插件目录（或通过插件市场安装），重启 AstrBot。

## 快速开始（推荐流程）

1. **配置 Minecraft 平台适配器**
   - AstrBot → 平台适配器 → 新增「Minecraft服务器适配器」。
   - 关键字段：
     - `adapter_id`：适配器唯一 ID（多服时用于区分）。
     - `ws_url`：鹊桥 WebSocket 地址（示例：`ws://127.0.0.1:8080/minecraft/ws`）。
     - `server_name`：服务器名（**必须与鹊桥配置中的 server_name 一致**，否则绑定/转发可能找不到群）。
     - `Authorization`：鹊桥配置了 token 时填写（代码会以 `Bearer <token>` 形式发送）。
     - `qq_platform_id`：可选；当自动识别 QQ 平台失败时，手动填 QQ 平台的 adapter_id。
   - 其余字段（重连/假人过滤/RCON）见下文「配置说明」。

2. **配置 Minecraft 唤醒词**
   - AstrBot → 平台配置 → 唤醒词：为 Minecraft 平台配置一个不与原版 `/` 冲突的前缀（推荐 `#`）。
   - 兼容：即使未配置，仍会默认识别 `#` 作为唤醒词。

3. **配置插件开关（WebUI 插件配置）**
   - 修改后使用 `/mcreload` 让插件配置立即生效。

4. **在 QQ 群绑定服务器**
   - 在目标 QQ 群发送：`/mcbind [服务器名或适配器ID]`
   - 不带参数默认绑定到「主适配器」（通常是第一个找到的 Minecraft 适配器）。

## 配置说明

### 1) 插件配置（WebUI / `_conf_schema.json`）

这些配置由插件读取；修改后使用 `/mcreload` 重载：

- `enable_qq_to_mc_forward`（默认 `true`）：是否开启 QQ 群消息自动转发到 MC
- `qq_forward_message_color`（默认 `#00BFFF`）：QQ→MC 转发文本颜色
- `qq_image_forward_mode`（默认 `clean`）：QQ→MC 图片转发模式
  - `clean`：清洗为“发送了图片/（含图片）”，不附带图片组件（最兼容）
  - `cicode`：把图片 URL 转为 `[[CICode,url=...,name=Image]]`
  - `raw`：保留图片 URL 组件（最接近旧逻辑）
- `enable_join_quit_messages`（默认 `true`）：是否转发 MC 进服/退服到 QQ
- `enable_death_messages`（默认 `true`）：是否转发 MC 死亡到 QQ
- `death_message_style`（默认 `official`）：死亡消息风格
  - `official`：只输出官方句式
  - `mix`：官方为主 + 少量彩蛋
  - `fun`：尽量使用彩蛋（无彩蛋则官方）
  - `random` / `随机`：在可用模板中全随机（含官方）
- `enable_mc_chat_to_qq_forward`（默认 `false`）：是否转发 MC 普通聊天到 QQ
- `enable_mc_qq_command`（默认 `true`）：是否允许 MC 侧使用 `<唤醒词>qq` 转发到 QQ
- `debug_mode`（默认 `false`）：更详细日志（排查转发链路用）

### 2) Minecraft 平台适配器配置（平台设置）

这些是「平台适配器」的配置；**修改后通常需要重启 AstrBot** 才能完全生效：

- `adapter_id`：适配器唯一 ID
- `ws_url` / `server_name` / `Authorization`：鹊桥连接信息（务必一致）
- `qq_platform_id`：手动指定 QQ 平台 adapter_id（建议留空自动识别；识别失败再填）
- 重连：`reconnect_interval` / `max_reconnect_retries`
- 假人过滤：`filter_bots` / `bot_prefix` / `bot_suffix`
- RCON（主适配器生效）：`rcon_enabled` / `rcon_host` / `rcon_port` / `rcon_password`

### 3) 绑定后的细粒度开关（每群/每服务器）

使用 `/mc设置` 在「某个 QQ 群」里为「某个服务器」单独开关：

- `qq2mc`：该群 → 该服 的 QQ→MC 自动转发
- `chat` / `join` / `death` / `qqcmd`：该服 → 该群 的 MC→QQ 聊天/进退/死亡/#qq

## 命令列表（以当前实现为准）

### QQ 群命令

多数命令为群聊使用；标注「管理员」的命令需要 AstrBot 管理员权限：

- `/mcbind [服务器名/适配器ID]`（管理员）：绑定当前群到指定服务器（不填为主适配器）
- `/mcunbind [服务器名/适配器ID]`（管理员）：解绑
- `/mcstatus`：查看所有适配器连接状态 + 本群绑定/开关（未连接会触发一次尝试重连）
- `/mc设置`（管理员）：查看/修改本群在某服务器下的细项开关（见上文）
- `/mcsay <消息>`：向所有在线 MC 服务器广播（支持图片）
- `/mcreload`：重载插件配置（WebUI 插件配置修改后用）
- `/mc帮助 [qq2mc|mc2qq|admin|设置]`：分菜单帮助
- `/mc玩家列表`：请求玩家列表（仅 MCDR 版鹊桥可用）

管理员相关：

- `/rcon <指令>`（管理员）：通过 RCON 执行 MC 指令（仅主适配器）
- `/rcon 重启`（管理员）：重连 RCON
- `/mc广播设置 <adapter_id> <配置>`（管理员）：设置某个适配器的整点广播内容（不带参数则显示当前配置）
  - 简单：直接写文本
  - 富文本：`文本,颜色,粗体(true/false),点击命令,悬浮文本|下一个组件`（支持 `{{time}}` 占位）
- `/mc广播开关`（管理员）：开启/关闭整点广播
- `/mc广播清除 [adapter_id]`（管理员）：清除指定适配器（或全部）的自定义广播内容
- `/mc广播测试`（管理员）：立即执行一次整点广播（含 Wiki 内容）
- `/mc自定义广播 文本|点击命令|悬浮文本`（管理员）：向所有在线服务器发送自定义富文本广播

### Minecraft 游戏内（聊天）命令

需要以「唤醒词」开头（推荐 `#`）：

- `<唤醒词>qq <消息>`：转发到绑定 QQ 群（受 `enable_mc_qq_command` 与 `/mc设置 qqcmd` 控制）
- `<唤醒词>wiki [关键词]`：查询中文 Minecraft Wiki；不带关键词会返回随机知识
- `<唤醒词>路标 查看/增加/编辑/删除 ...`：路标管理（详见游戏内帮助输出）
- `<唤醒词>命令指南`：向玩家私聊发送一段指南内容（用于服务器内查看）
- `<唤醒词><AstrBot 指令>`：执行 AstrBot 指令/触发对话（如 `#help`、`#你好`）

## 常见问题（FAQ）

### 1) QQ→MC 没有转发

- 确认插件配置 `enable_qq_to_mc_forward=true`
- 确认 QQ 平台为 `aiocqhttp` / `aiocqhttp_platform`
- 确认当前群已 `/mcbind` 且 `/mc设置 <server> qq2mc on`
- 若只发图片不生效：检查 `qq_image_forward_mode`（推荐先用 `clean`）

### 2) MC→QQ 没有转发（进退/死亡/#qq/聊天）

- 确认群已绑定：`/mcstatus`
- 确认细项开关：`/mc设置`（对应 `chat/join/death/qqcmd`）
- 确认全局开关：WebUI 插件配置（`enable_join_quit_messages / enable_death_messages / enable_mc_chat_to_qq_forward / enable_mc_qq_command`）
- 若提示找不到 QQ 平台：在 Minecraft 适配器配置里填写 `qq_platform_id`

### 3) `/mcreload` 之后仍“不生效”

- `/mcreload` 只针对插件配置（WebUI 插件配置）重载
- 修改 `ws_url/server_name/Authorization/qq_platform_id` 等平台适配器配置后：请 **重启 AstrBot**

## 已知限制

- AstrBot 平台适配器的配置变更通常需要重启；热重载插件/适配器在不同 AstrBot 版本上行为不完全一致。
- `/mc玩家列表` 依赖 MCDR 版鹊桥的 API，原版鹊桥不支持该请求。

## 许可证

MIT License

## 备注
Docs by ChatGPT5.2
