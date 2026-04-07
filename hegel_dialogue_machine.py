from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict


@dataclass
class HegelStage:
    name: str
    thesis: str
    antithesis: str
    contradiction_hint: str
    aufhebung: str
    next_stage: str
    plan_steps: List[str]
    keywords: List[str]


STAGES: List[HegelStage] = [
    HegelStage(
        name="存在论-定在与质",
        thesis="你先把问题当作一个确定事实（定在）。",
        antithesis="一旦细看，事实依赖其性质与边界（质），并非孤立。",
        contradiction_hint="你把“它是什么”与“它如何保持自己”割裂了。",
        aufhebung="把问题转为“边界管理”：保留核心质，调整可变条件。",
        next_stage="有限性与应当",
        plan_steps=[
            "写下当前状态与目标状态，区分不可丢失的核心质与可调整项。",
            "定义边界：超过什么阈值，事情就不再是它自己。",
            "先做一项低风险调整，验证是否仍保持核心质。",
        ],
        keywords=["我是谁", "定位", "边界", "失控", "定义不清"],
    ),
    HegelStage(
        name="存在论-有限与无限",
        thesis="你感到被限制（有限）。",
        antithesis="你又不断追求超越（应当/无限）。",
        contradiction_hint="把限制看成纯障碍，而非发展条件。",
        aufhebung="把限制转化为台阶：每次突破都在新的有限中继续展开。",
        next_stage="一与多",
        plan_steps=[
            "列出当前三条限制，逐条写出它们对应能训练出的能力。",
            "将长期目标拆成三段可完成的有限目标（7天/30天/90天）。",
            "每完成一段就重定义下一段，形成“有限-超越-再有限”的循环。",
        ],
        keywords=["瓶颈", "卡住", "上限", "无限", "想突破"],
    ),
    HegelStage(
        name="存在论-一与多",
        thesis="你希望统一一个目标（一）。",
        antithesis="现实里出现多个冲突角色/任务（多）。",
        contradiction_hint="把多样性当成对统一性的破坏。",
        aufhebung="建立层级统一：多任务服务同一核心意图。",
        next_stage="量与尺度",
        plan_steps=[
            "写一句核心意图（例如：长期健康、稳定成长、关系修复）。",
            "把所有任务映射到核心意图：支持/中性/冲突。",
            "删除1个冲突任务，强化1个支持任务，保留1个中性任务。",
        ],
        keywords=["时间管理", "多任务", "选择困难", "冲突", "平衡"],
    ),
    HegelStage(
        name="量-质-尺度",
        thesis="你在做数量变化（投入更多时间/钱/精力）。",
        antithesis="超过阈值会触发性质变化（关系恶化、身心崩溃等）。",
        contradiction_hint="把量变当作永远安全，不承认临界点。",
        aufhebung="建立个人尺度：在临界点前主动换挡。",
        next_stage="本质与现象",
        plan_steps=[
            "定义3个量化指标（例如睡眠时长、沟通频次、学习时长）。",
            "为每个指标设置“健康区间/预警区间/危险区间”。",
            "进入预警区间时立即执行替代动作，不等到危险区间。",
        ],
        keywords=["过度", "拖延", "爆发", "节奏", "临界点", "量变质变"],
    ),
    HegelStage(
        name="本质与现象",
        thesis="你看到的是现象（情绪、冲突、结果）。",
        antithesis="背后有结构性根据（关系模式、资源配置、认知框架）。",
        contradiction_hint="要么只盯表面，要么空谈本质。",
        aufhebung="用“现象-根据”双栏法，把可见问题追溯到可改结构。",
        next_stage="根据与条件",
        plan_steps=[
            "记录一周内重复出现的三个现象。",
            "为每个现象写出至少两个可能根据（内部/外部各一个）。",
            "只改一个可控根据，观察7天反馈。",
        ],
        keywords=["总是这样", "反复", "根本原因", "看不懂自己"],
    ),
    HegelStage(
        name="根据与条件到实存",
        thesis="你有内在动机和理由（根据）。",
        antithesis="没有外在条件，理由无法落地。",
        contradiction_hint="把“我想做”与“我能做”分离。",
        aufhebung="把目标改写为“根据+条件+触发器”的执行单元。",
        next_stage="现实",
        plan_steps=[
            "一句话写目标根据：我为什么必须做这件事。",
            "列出必要条件（时间、地点、资源、同伴、提醒）。",
            "设置触发器：何时何地，一出现就执行第一个动作。",
        ],
        keywords=["执行力", "坚持不住", "行动不了", "计划落空"],
    ),
    HegelStage(
        name="现实中的偶然与必然",
        thesis="你遇到的很多是偶然事件。",
        antithesis="长期走势由必然结构决定。",
        contradiction_hint="把失败全归偶然，或把偶然全忽略。",
        aufhebung="把偶然事件纳入结构复盘，提炼必然改进项。",
        next_stage="概念与判断",
        plan_steps=[
            "复盘最近一次失败：列偶然因素3条。",
            "再写出能重复作用的结构因素3条（习惯、规则、流程）。",
            "下次只优先修复1条结构因素，验证是否降低失败概率。",
        ],
        keywords=["运气", "总倒霉", "为什么总失败", "不可控"],
    ),
    HegelStage(
        name="概念-判断-推论",
        thesis="你有一个概念性自我叙事（我是怎样的人/这事是什么）。",
        antithesis="你的判断与事实证据不一致。",
        contradiction_hint="用未经检验的概念直接指导行动。",
        aufhebung="从断言转向推论：每个判断都要有可验证根据。",
        next_stage="真与善统一",
        plan_steps=[
            "写下你当前的核心判断一句话。",
            "列3条支持证据与3条反证据。",
            "据此改写为条件化判断，并配一个可检验行动。",
        ],
        keywords=["我就是", "我不行", "他就是", "判断", "证据"],
    ),
    HegelStage(
        name="真与善的统一（认识到实践）",
        thesis="你知道正确道理（真）。",
        antithesis="你做不出对应行动（善的实现失败）。",
        contradiction_hint="把认知升级误当行为升级。",
        aufhebung="把“知道”转成“可重复实践回路”。",
        next_stage="新的实践循环",
        plan_steps=[
            "把道理改写成最小行动（5-15分钟可完成）。",
            "连续执行7天并记录结果，不评价人格只评价流程。",
            "第8天根据数据升级或降级难度，进入下一轮扬弃。",
        ],
        keywords=["知道但做不到", "懂很多", "改变不了", "自律"],
    ),
]


def detect_stage(user_question: str) -> HegelStage:
    text = user_question.lower()
    best = STAGES[0]
    best_score = -1
    for stage in STAGES:
        score = 0
        for kw in stage.keywords:
            if kw in user_question or kw.lower() in text:
                score += 1
        if score > best_score:
            best_score = score
            best = stage
    return best


def generate_response(user_question: str) -> Dict[str, object]:
    stage = detect_stage(user_question)
    return {
        "问题": user_question,
        "当前环节": stage.name,
        "正题": stage.thesis,
        "反题": stage.antithesis,
        "矛盾诊断": stage.contradiction_hint,
        "扬弃方向": stage.aufhebung,
        "下一环节": stage.next_stage,
        "扬弃行动计划": stage.plan_steps,
    }


def format_response(data: Dict[str, object]) -> str:
    lines = [
        f"你的问题：{data['问题']}",
        "",
        f"【所处逻辑环节】{data['当前环节']}",
        f"- 正题：{data['正题']}",
        f"- 反题：{data['反题']}",
        f"- 主要矛盾：{data['矛盾诊断']}",
        "",
        f"【扬弃】{data['扬弃方向']}",
        f"【下一步】{data['下一环节']}",
        "",
        "【具体步骤】",
    ]
    for idx, step in enumerate(data["扬弃行动计划"], start=1):
        lines.append(f"{idx}. {step}")
    lines.append("")
    lines.append("提示：执行3-7天后，把结果反馈回来，我可以继续做下一轮辩证扬弃。")
    return "\n".join(lines)


def main() -> None:
    print("黑格尔逻辑学对话机（可落地版）")
    print("输入你的生活问题，按回车；输入 exit 退出。")
    while True:
        try:
            question = input("\n你：").strip()
        except EOFError:
            print("\n已退出。")
            break
        if question.lower() in {"exit", "quit"}:
            print("已退出。")
            break
        if not question:
            print("请输入具体问题，例如：我知道要学习但总是拖延。")
            continue
        result = generate_response(question)
        print("\nAI：")
        print(format_response(result))


if __name__ == "__main__":
    main()
