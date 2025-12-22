import re
from dataclasses import dataclass
from typing import Callable, Match, Optional, Pattern, Sequence, Union


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
