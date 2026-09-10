"""DeepSeek（兼容 OpenAI 接口）客户端与提示词构建。"""
import json
import re

import httpx

from db import get_conn

RASIC_LEGEND = {
    "R": "负责执行 Responsible",
    "A": "最终负责/批准 Accountable",
    "S": "支持 Support",
    "I": "知情 Informed",
    "C": "咨询 Consulted",
}

SYSTEM_PROMPT = """你是一名酒店管理文件的流程与职责分析专家。
你的任务：根据给定的管理文件内容，结合【部门岗位清单】【文件类型清单】【现有文件清单】，拆解并输出结构化分析结果。

RASIC 矩阵字母含义（必须严格区分，绝不可混淆）：
- R (Responsible) 负责执行：实际动手完成这项工作的人/岗位/部门。每项活动必须至少有一个 R。
- A (Accountable) 最终负责/批准：对结果负最终责任、有审批签字权的人，通常是比执行者更高一级的管理者（如部门经理、总办/总经理）。A 是“拍板、问责”的人，不是亲手干活的人；每项活动有且仅有一个 A。
- S (Support) 支持：提供资源、数据或辅助配合的部门/岗位。
- I (Informed) 知情：工作完成或进行中需被知会结果/进展，但不参与执行。
- C (Consulted) 咨询：决策或执行前需征求其意见的部门/岗位。

判断要点（务必遵守）：
1. “谁动手做”→ R；“谁审批签字、最终负责”→ A。二者必须区分，绝不能把执行者标成 A。
2. 示例：活动“审核原始凭证与电脑报表”，执行审核的财务部岗位 = R，审阅签字的财务部经理（或总办）= A；被检查/提供凭证的餐饮、前厅等一线部门 = S 或 C；仅需知晓结果的部门 = I。
3. 绝不允许某一列全是 A，也不允许整张矩阵只有 A 和 I 而缺失 R/S/C。
4. 涉及钱款、免单/打折、招投标、重大决策等事项，A 通常为总办（总经理）或部门负责人；日常例行操作，A 为该部门负责人。
5. 跨部门协作的衔接点，上下游部门分别用 R/S/C/I 体现，不要一律写成 I。

必须严格输出如下 JSON 结构（不要输出任何 JSON 之外的文字，不要用 Markdown 代码块包裹）：

{
  "rasic_department": [
    {"activity": "活动/步骤描述", "roles": {"部门名": "R或A或S或I或C"}}
  ],
  "rasic_position": [
    {"activity": "活动/步骤描述", "roles": {"岗位名": "R或A或S或I或C"}}
  ],
  "interfaces": [
    {
      "name": "接口名称",
      "upstream_dept": "上游部门",
      "downstream_dept": "下游部门",
      "input_content": "上游提供给下游的内容",
      "output_content": "下游输出的结果内容",
      "form": "接口形式：文件/会议/系统/邮件/口头等",
      "frequency": "频次：每日/每周/每月/每季度/按需等",
      "related_doc_nos": ["相关现有文件编号"],
      "responsible_positions": ["接口涉及的责任岗位"]
    }
  ],
  "flowchart": {
    "title": "流程标题（如：销售部日常工作流程）",
    "main_dept": "主责部门（R 角色所在部门）",
    "main_steps": [
      { "id": 1, "text": "步骤1描述" },
      { "id": 2, "text": "步骤2描述" }
    ],
    "collaborations": [
      { "from_step": 1, "to_dept": "协作部门名", "text": "该部门在步骤1提供的协作内容" }
    ]
  }
}

约束：
1. activity 从文件正文（管理制度/店级管理制度取“管理规定”、工作程序取“工作要求”与“职责”）逐条拆解，通常 5~15 条。
2. rasic_department 的 roles 键只能使用给出的【部门】名称；rasic_position 的 roles 键只能使用给出的【岗位】名称（含部门前缀，如“财务部经理”）。岗位级必须是部门级的向下分解：activity 与部门级保持逐条一致，并把每个部门承担的 R/A/S/I/C 落到该部门内的具体岗位（例如部门级“财务部=R”，岗位级则对应“财务部会计=R、财务部经理=A”；A 落到经理/主管/总监等管理岗位，R 落到具体经办岗位）。
3. 每个 activity 中同级别角色有且仅有一个 A、至少有一个 R，可有多个 S/I/C。
4. interfaces 聚焦跨部门协作的衔接点；若文件内容未体现跨部门，则结合现有文件清单合理推断。
5. flowchart 生成泳道图结构化数据（不是 Mermaid 代码）：
   - main_dept 填主责部门（即承担 R 角色最多的部门）。
   - main_steps 列出该部门的主流程步骤，id 从 1 开始连续编号，text 为步骤简要描述（8~15 字）。
   - collaborations 列出跨部门协作：from_step 对应 main_steps 中的步骤 id，to_dept 为协作部门（必须来自给出的【部门】清单），text 为该协作部门在此步骤提供的内容。
   - 若某步骤无跨部门协作，不加入 collaborations。
   - 协作部门在 collaborations 中只出现一次（取最主要的协作内容）。
   - 若整个流程无跨部门协作，collaborations 为空数组。
"""


def _collect_context():
    conn = get_conn()
    positions = conn.execute(
        "SELECT department, position FROM positions ORDER BY id"
    ).fetchall()
    file_types = conn.execute("SELECT name FROM file_types ORDER BY id").fetchall()
    existing = conn.execute(
        "SELECT doc_no, name, doc_type, cur_dept FROM existing_files ORDER BY id"
    ).fetchall()
    conn.close()

    dept_lines = []
    seen_dept = []
    for p in positions:
        if p["department"] not in seen_dept:
            seen_dept.append(p["department"])
    dept_lines = seen_dept

    pos_lines = [f"{p['department']} - {p['position']}" for p in positions]
    type_lines = [f["name"] for f in file_types]
    file_lines = [
        f"{f['doc_no']} | {f['name']} | {f['doc_type']} | {f['cur_dept']}"
        for f in existing
    ]
    return {
        "departments": dept_lines,
        "positions": pos_lines,
        "file_types": type_lines,
        "existing_files": file_lines,
    }


def build_user_prompt(doc: dict) -> str:
    ctx = _collect_context()
    parts = []
    parts.append("【部门清单】")
    parts.append("\n".join(ctx["departments"]))
    parts.append("\n【岗位清单】（部门 - 岗位）")
    parts.append("\n".join(ctx["positions"]))
    parts.append("\n【文件类型清单】")
    parts.append("\n".join(ctx["file_types"]))
    parts.append("\n【现有文件清单】（文件编号 | 文件名称 | 文件类型 | 现所属部门）")
    parts.append("\n".join(ctx["existing_files"]))

    parts.append("\n【待分析文件】")
    parts.append(f"文件类型：{doc.get('doc_type', '')}")
    parts.append(f"文件编号：{doc.get('doc_no', '')}")
    parts.append(f"标题：{doc.get('title', '')}")
    parts.append(f"目的：{doc.get('purpose', '')}")
    parts.append(f"范围：{doc.get('scope', '')}")
    if doc.get("regulation"):
        parts.append(f"管理规定：{doc['regulation']}")
    if doc.get("duty"):
        parts.append(f"职责：{doc['duty']}")
    if doc.get("work_requirement"):
        parts.append(f"工作要求：{doc['work_requirement']}")
    parts.append(f"相关记录：{doc.get('related_records', '')}")
    parts.append(f"相关文件：{doc.get('related_files', '')}")

    parts.append("\n请严格按上述 JSON 结构输出分析结果。")
    return "\n".join(parts)


def parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("模型返回内容不是有效 JSON")
    return json.loads(text[start : end + 1])


def call_llm(settings: dict, user_prompt: str, system: str = SYSTEM_PROMPT) -> str:
    base_url = (settings.get("base_url") or "https://api.deepseek.com").rstrip("/")
    model = settings.get("model") or "deepseek-chat"
    api_key = settings.get("api_key") or ""
    if not api_key:
        raise ValueError("尚未配置 API Key，请先在“系统设置”中填写")

    url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=180.0) as client:
        resp = client.post(url, json=payload, headers=headers)
    if resp.status_code != 200:
        detail = resp.text[:500]
        raise ValueError(f"LLM 接口返回 {resp.status_code}：{detail}")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise ValueError("LLM 返回结构异常：" + resp.text[:500])


# ==================== Word 文档解析 ====================

WORD_PARSE_SYSTEM = """你是一名酒店管理文件的结构化解析专家。
你的任务：从用户上传的 Word 文档正文中，按文件类型提取对应字段，输出 JSON。

三种文件类型及字段：
1. 管理制度/店级管理制度：doc_no(文件编号), title(标题), purpose(目的), scope(范围), regulation(管理规定), related_records(相关记录), related_files(相关文件)
2. 工作程序：doc_no(文件编号), title(标题), purpose(目的), scope(范围), duty(职责), work_requirement(工作要求), related_records(相关记录), related_files(相关文件)
3. 工作说明书：doc_no(文件编号), title(标题), department(所属部门), position(岗位名称), headcount(岗位定员), direct_supervisor(直接上级), direct_subordinates(直接下级), qualifications(基本任职资格), responsibilities(岗位职责), work_tasks(工作任务), relationships(与其它部门或部位的关系), innovation(创新空间), assessment(考核标准)

要求：
- 严格从原文中提取，不要编造；原文没有的字段留空字符串。
- 【重要】完整保留原文中的所有序号和编号，包括：中文序号（一、二、三、……）、阿拉伯数字（1、2、3、……）、带括号序号（（一）（二）、(1)(2)、①②）、多级编号（1.1、1.2.3）。序号是内容的一部分，不得删除。岗位职责、工作任务等列表型字段尤其要保留每条的序号。
- 保留原文的换行结构，多段落字段用换行（\\n）分隔。
- 工作说明书的基本任职资格必须严格按以下四行格式输出（每行一项，不要合并）：
  文化程度：xxx
  工作经验：xxx
  外语水平：xxx
  基本素质：xxx
- 直接下级有多个时用顿号或逗号分隔。

只输出 JSON，不要输出 JSON 之外的任何文字。"""


def build_word_parse_prompt(doc_type: str, text: str) -> str:
    return (
        f"文件类型：{doc_type}\n\n"
        f"【文档正文】\n{text}\n\n"
        f"请按上述字段要求输出 JSON。"
    )


# ==================== 员工工作全景分析 ====================

EMP_PANORAMA_SYSTEM = """你是一名酒店管理顾问，擅长基于制度文件对某位员工的工作职责进行全景式梳理。
你的任务：根据给定员工负责的文件清单及内容，从指定视角输出该员工的工作全景描述。

视角说明：
- guest_trip（宾客旅程视角）：按宾客旅程阶段归类，展示该员工在宾客从预订到离店各环节中的参与与职责。
- compliance（合规项视角）：按合规类别归类，展示该员工需遵守的各项合规要求及对应职责。
- internal（内部管理视角）：归类不直接面向宾客、也不属于特定合规条线的内部管理事务（如人事、行政、培训、质检、会议、印章、收发文等）。

输出 JSON 结构（严格遵守，不要输出 JSON 之外的文字）：
{
  "narrative": {
    "overview": "一段 100~200 字的概述，概括该员工在本视角下的核心职责与工作范围。",
    "internal_collab": "该员工与本部门内部其他员工需要配合处理的工作内容（100~200 字），说明配合对象、配合事项与衔接方式。",
    "cross_dept_collab": "该员工与其他部门员工需要配合处理的工作内容（100~200 字），说明对接部门、对接岗位、配合事项与衔接方式。",
    "risk_points": "该员工在当前工作内容中可能存在的风险点（3~6 条，每条不超过 40 字），从操作风险、合规风险、沟通风险、遗漏风险等角度提炼，必须基于文件内容，不要编造。"
  },
  "cards": [
    {
      "group": "所属分组名称（旅程阶段名 / 合规类别名 / 内部管理类别名）",
      "title": "文件名称",
      "doc_no": "文件编号",
      "summary": "该文件在本视角下的核心内容摘要（1~2 句）",
      "key_points": ["该员工在此文件中承担的关键职责或要点1", "要点2"]
    }
  ]
}

要求：
- narrative 各段落必须基于给定文件内容，不要编造文件中没有的信息。
- internal_collab 与 cross_dept_collab 需明确区分：本部门内部的配合写入 internal_collab，跨部门的配合写入 cross_dept_collab。
- risk_points 必须是具体、可执行的风险提示，避免空泛表述。
- cards 按 group 分组排列，同一 group 的卡片放在一起。
- key_points 每条不超过 30 字，提炼该员工在该文件中的具体职责。
- 若某文件在当前视角下无相关内容，可不放入 cards。"""


# 旅程阶段排序（用于 guest_trip 视角）
JOURNEY_STAGES = [
    "1.预定", "2.到店", "3.入住", "4.餐饮相关全部",
    "6.专项接待餐", "8.在店", "9.离店", "10.回访",
]

# 合规类别排序
COMPLIANCE_CATS = [
    "2.消防安全", "3.食品卫生安全", "6.安全生产综合管理",
    "7.燃气与电气安全", "9.治安管理与公安对接", "10.个人信息保护",
    "11.财务与资金管控", "12.内控合规", "13.劳动用工安全",
    "17.文旅星级标准运营合规", "18.综合应急管理",
]

VIEW_LABELS = {
    "guest_trip": "宾客旅程视角",
    "compliance": "合规项视角",
    "internal": "内部管理视角",
}


def build_employee_panorama_prompt(person: str, view_type: str, files: list) -> str:
    """构建员工全景分析的 user prompt。

    files: list of dict, each with:
      doc_no, name, doc_type, cur_dept, main_position,
      guest_trip, compliance, content (文件正文或条目摘要)
    """
    lines = []
    lines.append(f"员工姓名：{person}")
    lines.append(f"分析视角：{VIEW_LABELS.get(view_type, view_type)}")
    lines.append("")
    lines.append("【该员工负责的文件清单及内容】")
    for i, f in enumerate(files, 1):
        lines.append(f"--- 文件 {i} ---")
        lines.append(f"编号：{f.get('doc_no','')}")
        lines.append(f"名称：{f.get('name','')}")
        lines.append(f"类型：{f.get('doc_type','')}")
        lines.append(f"部门：{f.get('cur_dept','')}")
        lines.append(f"主责岗位：{f.get('main_position','')}")
        if f.get("guest_trip"):
            lines.append(f"宾客旅程：{f['guest_trip']}")
        if f.get("compliance"):
            lines.append(f"合规类别：{f['compliance']}")
        content = f.get("content", "")
        if content:
            lines.append(f"内容摘要：{content}")
        lines.append("")

    if view_type == "guest_trip":
        lines.append("请按宾客旅程阶段（预订→到店→入住→餐饮→在店→离店→回访）对文件分组，"
                      "生成该员工在宾客旅程各环节中的工作全景。")
    elif view_type == "compliance":
        lines.append("请按合规类别对文件分组，生成该员工需遵守的各项合规要求全景。")
    else:
        lines.append("请按内部管理职能（如人事、行政、培训、质检、会议、印章、收发文等）对文件分组，"
                      "生成该员工的内部管理工作全景。")

    lines.append("请严格按 JSON 结构输出。")
    return "\n".join(lines)