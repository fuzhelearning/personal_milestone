"""wbs_generate 中文 prompt。"""

from __future__ import annotations

from app.models import Goal

SYSTEM_PROMPT = """你是个人目标规划助手。只输出一个 JSON 对象，不要 Markdown 围栏，不要解释。

必须包含 milestones 与 day_assignments（可选 assumptions / risks）。禁止 minutes、story_points、hours 等工时字段。

形状（tasks 必须是对象数组，禁止字符串；task_codes 只能引用任务 code，不能引用里程碑 code）：
{
  "milestones": [
    {
      "code": "1.0",
      "title": "阶段名",
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "tasks": [
        {
          "code": "1.1",
          "title": "任务名",
          "start_date": "YYYY-MM-DD",
          "end_date": "YYYY-MM-DD",
          "description": ""
        }
      ]
    }
  ],
  "day_assignments": [
    {"date": "YYYY-MM-DD", "task_codes": ["1.1"]}
  ]
}

硬规则：
- 每个里程碑至少 1 个 task 对象（含 code/title/start_date/end_date）。
- 所有 code 全局唯一；里程碑与任务 code 不可混用。
- 任务日期必须落在所属里程碑窗内，且不超过计划起止日。
- 计划开始到结束的每一天都必须有且仅有一条 day_assignments；每天 task_codes 长度必须为 1。
- 日安排的 date 必须落在被引用任务的 start_date~end_date 内。
"""


def build_user_prompt(goal: Goal) -> str:
    note = goal.note or ""
    start = goal.plan_start_date.isoformat()
    end = goal.plan_end_date.isoformat()
    days = (goal.plan_end_date - goal.plan_start_date).days + 1
    return (
        f"目标名称：{goal.title}\n"
        f"计划开始：{start}\n"
        f"计划结束：{end}\n"
        f"共 {days} 天（含起止），day_assignments 必须恰好 {days} 条。\n"
        f"用户备注：\n{note}\n\n"
        "请只输出符合系统约定形状的 JSON。"
        "milestones[].tasks 必须是对象数组（含 code/title/start_date/end_date），不能是字符串。"
        "day_assignments[].task_codes 只能填任务 code。"
        "每天恰好一件任务。不要解释。"
    )


def build_retry_user_suffix(error_zh: str) -> str:
    return (
        "\n\n上次输出不合格，请按错误修正后重新只输出 JSON，不要解释。\n"
        "再次强调：tasks 是对象数组，例如 "
        '{"code":"1.1","title":"任务","start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD"}；'
        "不要写成 [\"任务名\"]。task_codes 必须是任务 code，不要填里程碑 code。\n"
        f"错误说明：{error_zh}"
    )


def goal_request_meta(goal: Goal) -> dict:
    return {
        "title": goal.title,
        "plan_start_date": goal.plan_start_date.isoformat(),
        "plan_end_date": goal.plan_end_date.isoformat(),
        "note": goal.note,
    }
