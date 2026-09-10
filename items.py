"""纯规则方式的文档条目化：拆分正文为「一条一行」+ 规则抽取元数据。

不依赖大模型。拆分依据编号/换行；元数据依据基础数据（岗位清单）做
字符串匹配 + 正则/词典规则，零成本、秒级完成。
"""
import hashlib
import json
import re

from db import get_conn

# 各章节字段（按文档结构的展示顺序）
SECTION_FIELDS = [
    ("目的", "purpose"),
    ("范围", "scope"),
    ("管理规定", "regulation"),
    ("职责", "duty"),
    ("工作要求", "work_requirement"),
    ("相关记录", "related_records"),
    ("相关文件", "related_files"),
    ("基本任职资格", "qualifications"),
    ("岗位职责", "responsibilities"),
    ("工作任务", "work_tasks"),
    ("与其它部门或部位的关系", "relationships"),
    ("创新空间", "innovation"),
    ("考核标准", "assessment"),
]

# —— 条款类型词典 ——
APPROVAL = ["审批", "批准", "授权", "权限", "审定", "核准", "签批", "审批人", "签报"]
DUTY = ["负责", "职责", "应负责", "承担", "任职", "分管", "主持", "归口管理"]
FORBID = ["严禁", "不得", "禁止", "注意", "切勿", "杜绝", "必须", "务必", "一律"]
TIME_WORDS = ["每日", "每天", "当日", "当天", "次日", "每月", "每年", "每周", "年度",
              "季度", "半年度", "按时", "及时", "限时", "期限", "时限", "定时", "定期"]
RECORD = ["记录", "台账", "登记表", "报表", "表格", "单据", "凭证", "清单", "表单",
          "登记簿", "交接表", "统计表"]
ACTION_VERBS = ["审核", "核对", "复核", "检查", "巡查", "巡检", "抽查", "提交", "上报",
                "报送", "打印", "填写", "录入", "登记", "通知", "知会", "送交", "领取",
                "归档", "存档", "收集", "整理", "汇总", "出具", "签发", "签字", "确认",
                "追讨", "清点", "交接", "比对", "盘点", "验收", "发放", "收缴", "保管",
                "借用", "注销", "复核", "结转", "对账"]

# —— 时限/频次正则 ——
FREQ_PATTERNS = [
    r"每(日|天|周|月|季度|年|半月)",
    r"(当|次|翌|隔|本|明)(日|天|周|月|班)",
    r"\d+\s*(工作日|天|日|小时|时|分钟|分|个工作日)(内|前|之内|以前)?",
    r"(下班|上班|当班|交班|接班|交接班|班前|班后)",
    r"每月\s*\d+\s*日前",
    r"\d{1,2}[:：]\d{2}",
]

# —— 编号识别（返回 (seq, level, 去掉编号后的文字) 或 None）——
def _match_numbering(s):
    s = s.strip()
    # 1) 多级数字编号：1.1 / 1.1.1
    m = re.match(r"^(\d+(?:\.\d+)+)\s*(?:[、.．)）])?", s)
    if m and (m.end() == len(s) or not s[m.end()].isdigit()):
        seq = m.group(1)
        return seq, seq.count(".") + 1, s[m.end():].strip()
    # 2) 单级数字编号：1、 / 1. / 1） / 1．
    m = re.match(r"^(\d+)\s*[、.．)）]", s)
    if m and (m.end() == len(s) or not s[m.end()].isdigit()):
        return m.group(1), 1, s[m.end():].strip()
    # 3) 括号数字：(1) （1）
    m = re.match(r"^[\(（]\s*(\d+)\s*[\)）]", s)
    if m:
        return m.group(1), 2, s[m.end():].strip()
    # 4) 中文一级：一、
    m = re.match(r"^([一二三四五六七八九十]+)\s*[、.]", s)
    if m:
        return m.group(1), 1, s[m.end():].strip()
    # 5) 中文括号：（一）
    m = re.match(r"^[（(]\s*([一二三四五六七八九十]+)\s*[）)]", s)
    if m:
        return m.group(1), 2, s[m.end():].strip()
    # 6) 圈号：①
    m = re.match(r"^([①②③④⑤⑥⑦⑧⑨⑩])", s)
    if m:
        return m.group(1), 2, s[m.end():].strip()
    return None


def split_section(text):
    """把某一章节正文拆成条目列表。[{seq, level, content, parent_local_idx}]"""
    result = []
    stack = []          # [(level, local_idx)]
    current = None
    for raw in (text or "").split("\n"):
        s = raw.strip()
        if not s:
            continue
        m = _match_numbering(s)
        if m:
            seq, level, rest = m
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else None
            item = {"seq": seq, "level": level, "content": rest,
                    "parent_local_idx": parent}
            result.append(item)
            stack.append((level, len(result) - 1))
            current = item
        else:
            # 无编号行：只有上一条是有编号条目时，才作为续行合并；
            # 否则（上一条也是无编号，或为首行）另起一条。
            if current is not None and current["seq"] is not None and current["content"]:
                current["content"] += "\n" + s
            else:
                item = {"seq": None, "level": 1, "content": s,
                        "parent_local_idx": None}
                result.append(item)
                current = item
    return result


def _dedupe(lst):
    seen = set()
    out = []
    for x in lst:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def load_base():
    conn = get_conn()
    rows = [r for r in conn.execute(
        "SELECT department, position FROM positions ORDER BY id")]
    conn.close()
    departments = []
    positions = []
    pos_dept = {}
    for r in rows:
        d, p = r["department"], r["position"]
        if d not in departments:
            departments.append(d)
        positions.append(p)
        pos_dept[p] = d
    return departments, positions, pos_dept


def classify(c):
    if any(w in c for w in APPROVAL):
        return "审批/权限"
    if any(w in c for w in DUTY):
        return "职责"
    if any(w in c for w in FORBID):
        return "注意事项"
    if any(w in c for w in TIME_WORDS):
        return "时限要求"
    if any(w in c for w in ACTION_VERBS):
        return "工作步骤"
    if any(w in c for w in RECORD):
        return "表单/记录"
    return "其他/规定"


def enrich(item, departments, positions, pos_dept):
    c = item["content"]
    found_pos = [p for p in positions if p in c]
    found_dept = [d for d in departments if d in c]
    dept_set = set(found_dept)
    for p in found_pos:
        dept_set.add(pos_dept.get(p))
    item["positions"] = found_pos
    item["departments"] = [d for d in departments if d in dept_set]

    freqs = []
    for pat in FREQ_PATTERNS:
        for mm in re.finditer(pat, c):
            freqs.append(mm.group(0))
    item["frequency"] = _dedupe(freqs)

    item["item_type"] = classify(c)

    kws = []
    for w in ACTION_VERBS:
        if w in c:
            kws.append(w)
    for w in RECORD:
        if w in c:
            kws.append(w)
    kws += freqs
    item["keywords"] = _dedupe(kws)[:8]


def _content_hash(section, content):
    """条目内容指纹：章节 + 正文，用于判断是否为同一条。"""
    return hashlib.md5(f"{section}\n{content}".encode("utf-8")).hexdigest()


def split_and_store(document_id):
    """增量拆分 + 元数据 + 落库，返回本次条目总数。

    对齐规则（按 (section, sort_order) 定位）：
    - 已存在且内容未变 → 跳过，保留手工修改的推断字段；
    - 已存在但内容变了 → 只更新正文与指纹，保留推断字段；
    - 该位置被用户软删除 → 不再复活（跳过）；
    - 新位置 → 插入；
    - 库中存在但新正文已无此位置 → 软删除（deleted=1）。
    """
    conn = get_conn()
    doc = conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    if not doc:
        conn.close()
        return 0
    doc = dict(doc)
    departments, positions, pos_dept = load_base()

    # 取部门与主责岗位：工作说明书取自文档自身的所属部门/岗位名称；
    # 其他类型按文件编号去《现有文件清单》匹配。
    if doc.get("doc_type") == "工作说明书":
        item_dept = doc.get("department") or ""
        item_pos = doc.get("position") or ""
    else:
        doc_no = doc.get("doc_no") or ""
        ef = None
        if doc_no:
            ef = conn.execute(
                "SELECT cur_dept, main_position FROM existing_files WHERE doc_no=? LIMIT 1",
                (doc_no,),
            ).fetchone()
        item_dept = ef["cur_dept"] if ef else ""
        item_pos = ef["main_position"] if ef else ""

    items = []
    for section, field in SECTION_FIELDS:
        text = (doc.get(field) or "").strip()
        if not text:
            continue
        base = len(items)
        for it in split_section(text):
            it["section"] = section
            if it["parent_local_idx"] is not None:
                it["parent_idx"] = base + it["parent_local_idx"]
            else:
                it["parent_idx"] = None
            enrich(it, departments, positions, pos_dept)
            items.append(it)

    # 取出现有条目（含已删除），按 (section, sort_order) 建索引
    existing = {}
    for r in conn.execute(
        "SELECT id, section, sort_order, content_hash, deleted FROM document_items "
        "WHERE document_id=?", (document_id,)):
        existing[(r["section"], r["sort_order"])] = dict(r)

    matched_ids = set()
    id_by_idx = {}
    for idx, it in enumerate(items):
        key = (it["section"], idx)
        cur_hash = _content_hash(it["section"], it["content"])
        old = existing.get(key)
        if old:
            if old["deleted"]:
                # 用户已删除，不再复活
                continue
            matched_ids.add(old["id"])
            if old["content_hash"] == cur_hash:
                # 内容未变，完全保留（含手工修改）
                id_by_idx[idx] = old["id"]
                continue
            # 内容变了：只更新正文与指纹，保留推断字段
            conn.execute(
                "UPDATE document_items SET content=?, content_hash=? WHERE id=?",
                (it["content"], cur_hash, old["id"]),
            )
            id_by_idx[idx] = old["id"]
        else:
            # 新条目
            cur = conn.execute(
                "INSERT INTO document_items(document_id,section,seq,level,parent_id,"
                "sort_order,content,item_type,departments,positions,frequency,keywords,"
                "department,main_position,content_hash)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (document_id, it["section"], it["seq"], it["level"], None, idx,
                 it["content"], it["item_type"],
                 json.dumps(it["departments"], ensure_ascii=False),
                 json.dumps(it["positions"], ensure_ascii=False),
                 json.dumps(it["frequency"], ensure_ascii=False),
                 json.dumps(it["keywords"], ensure_ascii=False),
                 item_dept, item_pos, cur_hash),
            )
            id_by_idx[idx] = cur.lastrowid
            matched_ids.add(cur.lastrowid)

    # 库中未被匹配到的非删除条目 → 软删除
    for r in existing.values():
        if r["id"] not in matched_ids and not r["deleted"]:
            conn.execute("UPDATE document_items SET deleted=1 WHERE id=?", (r["id"],))

    conn.commit()
    conn.close()
    return len(items)


def _unjson(v):
    try:
        return json.loads(v) if v else []
    except Exception:
        return []


def item_to_dict(r):
    d = dict(r)
    d["departments"] = _unjson(d.get("departments"))
    d["positions"] = _unjson(d.get("positions"))
    d["frequency"] = _unjson(d.get("frequency"))
    d["keywords"] = _unjson(d.get("keywords"))
    return d


def query_items(keyword=None, department=None, position=None, item_type=None,
                document_id=None, doc_no=None, limit=500):
    conn = get_conn()
    sql = ("SELECT i.*, d.doc_no, d.title, d.doc_type, "
           "COALESCE(NULLIF(i.department,''), e.cur_dept) AS cur_dept, "
           "COALESCE(NULLIF(i.main_position,''), e.main_position) AS main_position, "
           "e.person_in_charge AS person_in_charge "
           "FROM document_items i "
           "LEFT JOIN documents d ON i.document_id=d.id "
           "LEFT JOIN existing_files e ON d.doc_no=e.doc_no "
           "WHERE i.deleted=0")
    params = []
    if keyword:
        sql += " AND (i.content LIKE ? OR i.keywords LIKE ?)"
        like = f"%{keyword}%"
        params += [like, like]
    if department:
        sql += " AND COALESCE(NULLIF(i.department,''), e.cur_dept) = ?"
        params.append(department)
    if position:
        sql += " AND COALESCE(NULLIF(i.main_position,''), e.main_position) = ?"
        params.append(position)
    if item_type:
        sql += " AND i.item_type = ?"
        params.append(item_type)
    if document_id:
        sql += " AND i.document_id = ?"
        params.append(document_id)
    if doc_no:
        sql += " AND d.doc_no = ?"
        params.append(doc_no)
    sql += " ORDER BY i.document_id DESC, i.sort_order ASC LIMIT ?"
    params.append(limit)
    rows = [item_to_dict(r) for r in conn.execute(sql, params)]
    conn.close()
    return rows


def update_item(item_id, fields):
    """仅允许更新「推断类」字段：item_type、department、main_position、frequency、keywords。
    抓取类字段（section/seq/content）与文档级字段（doc_no/title）不允许在此修改。"""
    conn = get_conn()
    allowed = {"item_type", "department", "main_position", "frequency", "keywords"}
    sets, vals = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k in ("frequency", "keywords") and not isinstance(v, str):
            v = json.dumps(v, ensure_ascii=False)
        sets.append(f"{k}=?")
        vals.append(v)
    if not sets:
        conn.close()
        return False
    vals.append(item_id)
    conn.execute(f"UPDATE document_items SET {', '.join(sets)} WHERE id=? AND deleted=0",
                 vals)
    conn.commit()
    conn.close()
    return True


def facet_items():
    """全量条目的统计：按类型、按部门、按主责岗位。"""
    conn = get_conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT i.item_type, "
        "COALESCE(NULLIF(i.department,''), e.cur_dept) AS cur_dept, "
        "COALESCE(NULLIF(i.main_position,''), e.main_position) AS main_position "
        "FROM document_items i "
        "LEFT JOIN documents d ON i.document_id=d.id "
        "LEFT JOIN existing_files e ON d.doc_no=e.doc_no "
        "WHERE i.deleted=0")]
    conn.close()
    types, depts, poss = {}, {}, {}
    for r in rows:
        t = r["item_type"]
        types[t] = types.get(t, 0) + 1
        if r["cur_dept"]:
            depts[r["cur_dept"]] = depts.get(r["cur_dept"], 0) + 1
        if r["main_position"]:
            poss[r["main_position"]] = poss.get(r["main_position"], 0) + 1
    return {
        "types": dict(sorted(types.items(), key=lambda x: -x[1])),
        "departments": dict(sorted(depts.items(), key=lambda x: -x[1])),
        "positions": dict(sorted(poss.items(), key=lambda x: -x[1])),
    }