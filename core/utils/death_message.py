import re
import random
from dataclasses import dataclass
from typing import Callable, Match, Optional, Pattern, Sequence, Union, Any, Mapping


_COLOR_CODE_RE = re.compile(r"§.")
_SPACE_RE = re.compile(r"\s+")


Repl = Union[str, Callable[[Match[str]], str]]


@dataclass(frozen=True)
class DeathMessageRule:
    pattern: Pattern[str]
    repl: Repl


def _clean(text: str) -> str:
    t = (text or "").replace("\u00a0", " ")
    t = _COLOR_CODE_RE.sub("", t)
    t = _SPACE_RE.sub(" ", t).strip()
    return t


def _repl_fall(match: Match[str]) -> str:
    name = (match.groupdict().get("name") or "").strip()
    if name:
        return f"{name} 从高处坠落"
    return "从高处坠落"


def _repl_slain(match: Match[str]) -> str:
    name = (match.groupdict().get("name") or "").strip()
    killer = (match.groupdict().get("killer") or "").strip()
    item = (match.groupdict().get("item") or "").strip()
    if name and killer:
        if item:
            return f"{name} 被 {killer} 用 {item} 杀死"
        return f"{name} 被 {killer} 杀死"
    return (match.group(0) or "").strip()


def _repl_shot(match: Match[str]) -> str:
    name = (match.groupdict().get("name") or "").strip()
    killer = (match.groupdict().get("killer") or "").strip()
    item = (match.groupdict().get("item") or "").strip()
    if name and killer:
        if item:
            return f"{name} 被 {killer} 用 {item} 射杀"
        return f"{name} 被 {killer} 射杀"
    return (match.group(0) or "").strip()


# 说明：
# - 优先覆盖常见/高频死因
# - 规则尽量同时匹配英文原文与中文本地化（以便不同语言服务端也能归一化）
_RULES: Sequence[DeathMessageRule] = (
    # 坠落类（Java 常见）
    DeathMessageRule(re.compile(r"^(?P<name>.+?) fell from a high place(?: .+)?$", re.IGNORECASE), _repl_fall),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) hit the ground too hard(?: .+)?$", re.IGNORECASE), _repl_fall),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) fell off a ladder$", re.IGNORECASE), _repl_fall),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) fell off some vines$", re.IGNORECASE), _repl_fall),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) fell off some weeping vines$", re.IGNORECASE), _repl_fall),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) fell off some twisting vines$", re.IGNORECASE), _repl_fall),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) fell off scaffolding$", re.IGNORECASE), _repl_fall),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) fell while climbing$", re.IGNORECASE), _repl_fall),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) fell out of the world$", re.IGNORECASE), r"\g<name> 掉出了世界"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) fell into the void$", re.IGNORECASE), r"\g<name> 掉进了虚空"),

    # 中文本地化（Java 中文）
    DeathMessageRule(re.compile(r"^(?P<name>.+?) 落地过猛$"), _repl_fall),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) 从高处坠落$"), _repl_fall),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) 从梯子上摔下了$"), _repl_fall),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) 从藤蔓上摔下了$"), _repl_fall),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) 从脚手架上摔下了$"), _repl_fall),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) 掉出了这个世界$"), r"\g<name> 掉出了世界"),

    # 溺水/岩浆/火焰
    DeathMessageRule(re.compile(r"^(?P<name>.+?) drowned$", re.IGNORECASE), r"\g<name> 溺水"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) 淹死了$"), r"\g<name> 溺水"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) tried to swim in lava(?: .+)?$", re.IGNORECASE), r"\g<name> 试图在熔岩里游泳"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) went up in flames(?: .+)?$", re.IGNORECASE), r"\g<name> 被烧死了"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) burned to death(?: .+)?$", re.IGNORECASE), r"\g<name> 被烧死了"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) was burnt to a crisp(?: .+)?$", re.IGNORECASE), r"\g<name> 被烧死了"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) 烧死了$"), r"\g<name> 被烧死了"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) walked into a cactus$", re.IGNORECASE), r"\g<name> 扎进了仙人掌"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) was pricked to death$", re.IGNORECASE), r"\g<name> 被刺死了"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) starved to death$", re.IGNORECASE), r"\g<name> 饿死了"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) 饿死了$"), r"\g<name> 饿死了"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) suffocated in a wall$", re.IGNORECASE), r"\g<name> 在墙里窒息"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) 在墙里窒息了$"), r"\g<name> 在墙里窒息"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) was struck by lightning$", re.IGNORECASE), r"\g<name> 被雷劈死了"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) was squashed by a falling anvil$", re.IGNORECASE), r"\g<name> 被铁砧砸死"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) was squashed by a falling block$", re.IGNORECASE), r"\g<name> 被坠落方块砸死"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) was impaled on a stalagmite$", re.IGNORECASE), r"\g<name> 被钟乳石刺穿"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) was impaled by (?P<killer>.+?)$", re.IGNORECASE), r"\g<name> 被 \g<killer> 刺穿"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) was roasted in dragon breath$", re.IGNORECASE), r"\g<name> 被龙息烤焦了"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) died from dehydration$", re.IGNORECASE), r"\g<name> 脱水而死"),

    # 被杀死/被射杀（保留凶手信息）
    # 覆盖：was slain by X / was slain by X using Y / 以及尾部追加描述（如 while trying to ...）
    DeathMessageRule(
        re.compile(
            r"^(?P<name>.+?) was slain by (?P<killer>.+?)(?: using (?P<item>.+?))?(?: .+)?$",
            re.IGNORECASE,
        ),
        _repl_slain,
    ),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) 被 (?P<killer>.+?) 杀死了$"), _repl_slain),
    DeathMessageRule(
        re.compile(
            r"^(?P<name>.+?) was shot by (?P<killer>.+?)(?: using (?P<item>.+?))?(?: .+)?$",
            re.IGNORECASE,
        ),
        _repl_shot,
    ),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) 被 (?P<killer>.+?) 射杀了$"), _repl_shot),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) was killed by magic$", re.IGNORECASE), r"\g<name> 被魔法杀死"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) was killed by (?P<killer>.+?) using magic$", re.IGNORECASE),
                     r"\g<name> 被 \g<killer> 用魔法杀死"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) was killed$", re.IGNORECASE), r"\g<name> 被杀死"),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) was killed by (?P<killer>.+?)(?: .+)?$", re.IGNORECASE), r"\g<name> 被 \g<killer> 杀死"),

    # 爆炸
    DeathMessageRule(re.compile(r"^(?P<name>.+?) blew up$", re.IGNORECASE), r"\g<name> 爆炸而死"),
    DeathMessageRule(
        re.compile(
            r"^(?P<name>.+?) was blown up by (?P<killer>.+?)(?: using (?P<item>.+?))?(?: .+)?$",
            re.IGNORECASE,
        ),
        lambda m: (
            f"{m.group('name').strip()} 被 {m.group('killer').strip()} 用 {m.group('item').strip()} 炸死"
            if (m.groupdict().get("name") and m.groupdict().get("killer") and m.groupdict().get("item"))
            else f"{m.group('name').strip()} 被 {m.group('killer').strip()} 炸死"
            if (m.groupdict().get("name") and m.groupdict().get("killer"))
            else (m.group(0) or "").strip()
        ),
    ),
    DeathMessageRule(re.compile(r"^(?P<name>.+?) 被 (?P<killer>.+?) 炸死了$"), r"\g<name> 被 \g<killer> 炸死"),
)


def normalize_death_message(message: str, default_player_name: Optional[str] = None) -> str:
    """
    归一化死亡消息，输出更简洁的中文文本。
    - 不保证覆盖所有死亡消息类型；优先处理常见/高频类型
    - 未匹配时返回清洗后的原文（去颜色码、折叠空白）
    """
    msg = _clean(message)
    if not msg:
        return f"{default_player_name} 死了" if default_player_name else ""

    for rule in _RULES:
        m = rule.pattern.match(msg)
        if not m:
            continue
        repl = rule.repl
        out = repl(m) if callable(repl) else m.expand(repl)
        out = _clean(out)
        return out or msg

    return msg


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for v in value:
            if v is None:
                continue
            s = _clean(str(v))
            if s:
                out.append(s)
        return out
    s = _clean(str(value))
    return [s] if s else []

def _t(official: str, *variants: str) -> tuple[str, ...]:
    return (official, *variants)


# 说明：
# - 以 death.md 中列出的 key 为范围做“尽量完整”的模板覆盖
# - 模板使用 `{0} {1} {2}` 对应 args[0..]（通常是 死者/击杀者/物品）
# - 少量 key（如 onMoon/potato）在原版语言文件中可能没有中文，此处保留 death.md 给出的英文
_DEATH_TEMPLATES: dict[str, tuple[str, ...]] = {
    # 暴力行为 / 常见击杀
    "death.attack.player": _t("{0} 被 {1} 杀死了"),
    "death.attack.player.item": _t("{0} 被 {1} 用 {2} 杀死了"),
    "death.attack.mob": _t("{0} 被 {1} 杀死了"),
    "death.attack.mob.item": _t("{0} 被 {1} 用 {2} 杀死了"),

    "death.attack.arrow": _t("{0} 被 {1} 射杀了"),
    "death.attack.arrow.item": _t("{0} 被 {1} 用 {2} 射杀了"),

    "death.attack.trident": _t("{0} 被 {1} 刺穿了"),
    "death.attack.trident.item": _t("{0} 被 {1} 用 {2} 刺穿了"),

    "death.attack.spear": _t("{0} 被 {1} 用矛刺死了"),
    "death.attack.spear.item": _t("{0} 被 {1} 用 {2} 刺死了"),

    "death.attack.thrown": _t("{0} 被 {1} 砸死了"),
    "death.attack.thrown.item": _t("{0} 被 {1} 用 {2} 砸死了"),

    "death.attack.fireball": _t("{0} 被 {1} 的火球烧死了"),
    "death.attack.fireball.item": _t("{0} 被 {1} 用 {2} 发射的火球烧死了"),

    "death.attack.witherSkull": _t("{0} 被 {1} 的凋灵之首杀死了"),
    "death.attack.witherSkull.item": _t("{0} 被 {1} 用 {2} 发射的凋灵之首杀死了"),

    "death.attack.indirectMagic": _t("{0} 被 {1} 用魔法杀死了"),
    "death.attack.indirectMagic.item": _t("{0} 被 {1} 用 {2} 施放的魔法杀死了"),

    "death.attack.sonic_boom": _t("{0} 被音波尖啸抹除了"),
    "death.attack.sonic_boom.player": _t("{0} 被 {1} 的音波尖啸抹除了"),
    "death.attack.sonic_boom.item": _t("{0} 被 {1} 用 {2} 的音波尖啸抹除了"),

    "death.attack.mace_smash": _t("{0} 被 {1} 的重锤猛击了"),
    "death.attack.mace_smash.item": _t("{0} 被 {1} 用 {2} 猛击了"),

    # 荆棘/反伤
    "death.attack.thorns": _t("{0} 在试图伤害 {1} 时被反弹伤害杀死了"),
    "death.attack.thorns.item": _t("{0} 在试图伤害 {1} 时被 {2} 上的荆棘反弹伤害杀死了"),

    # 蜇刺
    "death.attack.sting": _t("{0} 被蜇死了"),
    "death.attack.sting.player": _t("{0} 被 {1} 蜇死了"),
    "death.attack.sting.item": _t("{0} 被 {1} 用 {2} 蜇死了"),

    # 龙息（注：该伤害类型主要用于 /damage）
    "death.attack.dragonBreath": _t("{0} 在龙息中烤焦了"),
    "death.attack.dragonBreath.player": _t("{0} 在与 {1} 战斗时在龙息中烤焦了"),

    # 负面效果 / 环境
    "death.attack.inFire": _t("{0} 浴火焚身"),
    "death.attack.inFire.player": _t("{0} 在与 {1} 战斗时浴火焚身"),

    "death.attack.onFire": _t("{0} 被烧死了"),
    "death.attack.onFire.player": _t("{0} 在与 {1} 战斗时被烧死了"),
    "death.attack.onFire.item": _t("{0} 被 {1} 用 {2} 烧死了"),

    "death.attack.lava": _t(
        "{0} 试图在熔岩里游泳",
        "{0} 被熔化了。",
        "{0} 被烧成了灰。",
        "{0} 试图在熔岩中游泳。",
        "{0} 喜欢在岩浆中玩耍。",
    ),
    "death.attack.lava.player": _t("{0} 在试图逃离 {1} 时试图在熔岩里游泳"),

    "death.attack.hotFloor": _t("{0} 发现地板是熔岩块"),
    "death.attack.hotFloor.player": _t("{0} 在试图逃离 {1} 时发现地板是熔岩块"),

    "death.attack.inWall": _t("{0} 在墙里窒息了"),
    "death.attack.inWall.player": _t("{0} 在与 {1} 战斗时在墙里窒息了"),

    "death.attack.drown": _t(
        "{0} 淹死了",
        "{0} 忘了呼吸。",
        "{0} 与鱼同眠。",
        "{0} 溺死了。",
        "{0} 试图饮尽湖水。",
        "{0} 发现了亚特兰蒂斯。",
        "{0} 忘了带毛巾。",
    ),
    "death.attack.drown.player": _t("{0} 在试图逃离 {1} 时淹死了"),

    "death.attack.dryout": _t("{0} 脱水而死"),
    "death.attack.dryout.player": _t("{0} 在试图逃离 {1} 时脱水而死"),

    "death.attack.freeze": _t("{0} 冻死了"),
    "death.attack.freeze.player": _t("{0} 在试图逃离 {1} 时冻死了"),

    "death.attack.cramming": _t("{0} 被挤死了"),
    "death.attack.cramming.player": _t("{0} 在试图逃离 {1} 时被挤死了"),

    "death.attack.cactus": _t("{0} 被戳死了"),
    "death.attack.cactus.player": _t("{0} 在试图逃离 {1} 时走进了仙人掌"),

    "death.attack.sweetBerryBush": _t("{0} 被甜浆果丛刺死了"),
    "death.attack.sweetBerryBush.player": _t("{0} 在试图逃离 {1} 时被甜浆果丛刺死了"),

    "death.attack.lightningBolt": _t("{0} 被闪电击中"),
    "death.attack.lightningBolt.player": _t("{0} 在与 {1} 战斗时被闪电击中"),

    "death.attack.magic": _t("{0} 被魔法杀死了"),
    "death.attack.magic.player": _t("{0} 被 {1} 用魔法杀死了"),

    "death.attack.wither": _t("{0} 凋零了"),
    "death.attack.wither.player": _t("{0} 在与 {1} 战斗时凋零了"),

    "death.attack.starve": _t("{0} 饿死了"),
    # 该 key 主要通过 /damage 产生，语义不稳定；保持官方主句式即可
    "death.attack.starve.player": _t("{0} 饿死了"),

    # 世界边界/虚空
    "death.attack.outsideBorder": _t("{0} 离开了这个世界的边界"),
    "death.attack.outsideBorder.player": _t("{0} 在试图逃离 {1} 时离开了这个世界的边界"),

    "death.attack.outOfWorld": _t("{0} 掉出了这个世界"),
    "death.attack.outOfWorld.player": _t("{0} 在试图逃离 {1} 时掉出了这个世界"),

    # 意外事故
    "death.attack.fall": _t(
        "{0} 落地过猛",
        "{0} 摔死了。",
        "{0} 没有反弹。",
        "{0} 发明了重力。",
        "{0} 领悟了“抛出窗外”的意思。",
        "{0} 自由……自由落体了。",
        "{0} 认为自己会飞。",
        "{0} 留下了一个大坑。",
        "{0} 坠机了。",
    ),
    "death.attack.fall.player": _t("{0} 在试图逃离 {1} 时落地过猛"),

    "death.attack.stalagmite": _t("{0} 被滴水石锥刺穿了"),
    "death.attack.stalagmite.player": _t("{0} 在试图逃离 {1} 时被滴水石锥刺穿了"),

    "death.attack.anvil": _t("{0} 被铁砧压扁了"),
    "death.attack.anvil.player": _t("{0} 在与 {1} 战斗时被铁砧压扁了"),

    "death.attack.fallingStalactite": _t("{0} 被掉落的滴水石锥刺穿了"),
    "death.attack.fallingStalactite.player": _t("{0} 在与 {1} 战斗时被掉落的滴水石锥刺穿了"),

    "death.attack.fallingBlock": _t("{0} 被正在坠落的方块压扁了"),
    "death.attack.fallingBlock.player": _t("{0} 在与 {1} 战斗时被正在坠落的方块压扁了"),

    "death.attack.flyIntoWall": _t("{0} 体验了动能", "{0} 感受到了动能"),
    "death.attack.flyIntoWall.player": _t("{0} 在试图逃离 {1} 时体验了动能", "{0} 在试图逃离 {1} 时感受到了动能"),

    # 爆炸
    "death.attack.explosion": _t("{0} 爆炸了"),
    "death.attack.explosion.player": _t("{0} 被 {1} 炸死了"),
    "death.attack.explosion.player.item": _t("{0} 被 {1} 用 {2} 炸死了"),

    "death.attack.badRespawnPoint.message": _t("{0} 被[有意为之的游戏设计]杀死了"),

    # 杂项
    "death.attack.generic": _t("{0} 死了"),
    "death.attack.generic.player": _t("{0} 被 {1} 杀死了"),

    "death.attack.genericKill": _t("{0} 被杀死了"),
    "death.attack.genericKill.player": _t("{0} 被 {1} 杀死了"),

    "death.attack.even_more_magic": _t("{0} 被更强大的魔法杀死了"),

    # 烟花
    "death.attack.fireworks": _t("{0} 随着烟花一同爆炸了"),
    "death.attack.fireworks.player": _t("{0} 随着 {1} 的烟花一同爆炸了"),
    "death.attack.fireworks.item": _t("{0} 随着 {1} 用 {2} 放的烟花一同爆炸了"),

    # 摔落扩展（高处/梯子/藤蔓等）
    "death.fell.accident.generic": _t("{0} 从高处摔了下来"),
    "death.fell.accident.ladder": _t("{0} 从梯子上摔了下来"),
    "death.fell.accident.scaffolding": _t("{0} 从脚手架上摔了下来"),
    "death.fell.accident.vines": _t("{0} 从藤蔓上摔了下来"),
    "death.fell.accident.weeping_vines": _t("{0} 从垂泪藤上摔了下来"),
    "death.fell.accident.twisting_vines": _t("{0} 从缠怨藤上摔了下来"),
    "death.fell.accident.other_climbable": _t("{0} 攀爬时不慎摔落"),
    "death.fell.accident.water": _t("{0} 从水中掉了下来"),

    # 摔落相关的复合消息（官方文本较长，此处尽量贴近原版句式）
    "death.fell.killer": _t("{0} 注定要摔死"),
    "death.fell.assist": _t("{0} 注定要摔死（{1} 也帮了一把）"),
    "death.fell.assist.item": _t("{0} 注定要摔死（{1} 用 {2} 也帮了一把）"),
    "death.fell.finish": _t("{0} 摔得粉身碎骨，{1} 完成了最后一击"),
    "death.fell.finish.item": _t("{0} 摔得粉身碎骨，{1} 用 {2} 完成了最后一击"),

    # 这些为特殊版本/彩蛋类死亡消息（death.md 提供英文原文）
    "death.attack.nightmare": _t("{0} was too soft for this world"),
    "death.attack.nightmare.player": _t("{0} was too soft for this world ({1} helped)"),

    "death.attack.onMoon": _t("{0} experienced the dark side of the moon"),
    # death.md 注：语言文件无对应文本，这里保留一个可读兜底
    "death.attack.onMoon.player": _t("{0} experienced the dark side of the moon ({1} helped)"),

    "death.midas.turned_into_gold": _t("{0} was turned into gold"),

    "death.attack.potato_heat": _t("{0} held the hot potato for too long."),
    "death.attack.potato_heat.player": _t("{0} held the hot potato for too long. ({1} helped)"),
    "death.attack.potato_magic": _t("{0} was killed by a bad-tempered potato"),
    "death.attack.potato_magic.player": _t("{0} was killed by a bad-tempered potato ({1} helped)"),
}


def _pick_template(templates: Sequence[str], style: str) -> str:
    """根据风格在模板列表中选择输出文本。templates[0] 约定为官方版本。"""
    if not templates:
        return ""

    normalized = (style or "official").strip().lower()
    if normalized in {"official", "off", "0", "false", "关闭", "关", "官方"}:
        return templates[0]

    # fun: 尽量用彩蛋（若无彩蛋则回退官方）
    if normalized in {"fun", "meme", "彩蛋"}:
        if len(templates) <= 1:
            return templates[0]
        return random.choice(list(templates[1:]))

    # mix/random: 官方为主，少量彩蛋；无彩蛋则官方
    if normalized in {"mix", "random", "rand", "shuffle", "mixed", "随机"}:
        if len(templates) <= 1:
            return templates[0]
        # 80% 官方，20% 彩蛋
        if random.random() < 0.2:
            return random.choice(list(templates[1:]))
        return templates[0]

    return templates[0]


def _safe_format(template: str, args: list[str], default_player_name: Optional[str]) -> str:
    if not template:
        return ""

    safe_args = list(args)
    if not safe_args and default_player_name:
        safe_args = [default_player_name]

    # pad，避免 IndexError
    safe_args.extend([""] * 6)

    try:
        return template.format(*safe_args)
    except Exception:
        return template


def _format_killed(args: list[str], verb: str = "杀死") -> str:
    if len(args) >= 3 and args[0] and args[1] and args[2]:
        return f"{args[0]} 被 {args[1]} 用 {args[2]} {verb}"
    if len(args) >= 2 and args[0] and args[1]:
        return f"{args[0]} 被 {args[1]} {verb}"
    return ""


def format_death(
    death: Mapping[str, Any],
    default_player_name: Optional[str] = None,
    *,
    style: str = "official",
) -> str:
    """
    通过 QueQiao 的结构化死亡数据（death.key/args/text）格式化死亡消息。

    - 优先用 key/args（与服务端语言无关，稳定）
    - 若 key 未覆盖则回退到 death.text，并使用 normalize_death_message 做归一化
    """
    if not isinstance(death, Mapping):
        return ""

    key = _clean(str(death.get("key") or ""))
    args = _as_text_list(death.get("args"))
    text = _clean(str(death.get("text") or ""))

    if not key:
        if text:
            return normalize_death_message(text, default_player_name=default_player_name)
        return f"{default_player_name} 死了" if default_player_name else ""

    templates = _DEATH_TEMPLATES.get(key)
    if templates:
        template = _pick_template(templates, style)
        out = _safe_format(template, args, default_player_name)
        out = _clean(out)
        if out:
            return out

    # 兜底：尽量使用 text（可能是英文/中文），并做归一化
    if text:
        return normalize_death_message(text, default_player_name=default_player_name)

    name = args[0] if args else (default_player_name or "")
    return f"{name} 死了" if name else ""
