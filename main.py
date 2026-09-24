"""FastAPI 应用：文档录入、LLM 生成 RASIC/接口卡/流程图、SQLite 存取。"""
import csv
import json
import os
from contextlib import asynccontextmanager
from io import StringIO
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import items
import llm


@asynccontextmanager
async def lifespan(app):
    db.ensure_startup()
    _cleanup_gen_py()
    yield


def _cleanup_gen_py():
    """清理 pywin32 的 gen_py COM 缓存，避免缓存损坏导致 Word 解析失败。"""
    import shutil
    import tempfile
    candidates = [
        Path(tempfile.gettempdir()) / "gen_py",
    ]
    try:
        import win32com
        candidates.append(Path(win32com.__file__).parent / "gen_py")
    except Exception:
        pass
    for p in candidates:
        try:
            if p.exists() and p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass


app = FastAPI(title="酒店管理制度文件分析系统", lifespan=lifespan)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

VALID_LETTERS = {"R", "A", "S", "I", "C"}
LETTER_MAP = {
    "R": "R", "A": "A", "S": "S", "I": "I", "C": "C",
    "负责": "R", "执行": "R", "批准": "A", "问责": "A", "最终负责": "A",
    "支持": "S", "知情": "I", "咨询": "C",
}


# ---------- 请求模型 ----------
class SettingsIn(BaseModel):
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"


class DocumentIn(BaseModel):
    doc_type: str
    doc_no: str = ""
    title: str = ""
    purpose: str = ""
    scope: str = ""
    regulation: str = ""
    duty: str = ""
    work_requirement: str = ""
    related_records: str = ""
    related_files: str = ""
    department: str = ""
    position: str = ""
    headcount: str = ""
    direct_supervisor: str = ""
    direct_subordinates: str = ""
    indirect_subordinates: str = ""
    qualifications: str = ""
    responsibilities: str = ""
    work_tasks: str = ""
    relationships: str = ""
    innovation: str = ""
    assessment: str = ""
    raw_text: str = ""
    raw_filename: str = ""


class ItemsDeleteIn(BaseModel):
    ids: list[int]


# ---------- 工具 ----------
def get_settings() -> dict:
    conn = db.get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    s = {r["key"]: r["value"] for r in rows}
    return {
        "api_key": s.get("api_key", ""),
        "base_url": s.get("base_url", "https://api.deepseek.com"),
        "model": s.get("model", "deepseek-chat"),
    }


def normalize_letter(v):
    letter = str(v).strip().upper()
    if letter in LETTER_MAP:
        return LETTER_MAP[letter]
    if letter in VALID_LETTERS:
        return letter
    return None


def normalize_role(name, departments, positions, level):
    n = str(name).strip()
    if not n:
        return n
    if level == "department":
        if n in departments:
            return n
        for d in departments:
            if d in n or n in d:
                return d
        return n
    # level == "position"：岗位名优先精确匹配，其次模糊匹配；不降级为部门
    if n in positions:
        return n
    for p in positions:
        if n in p or p in n:
            return p
    return n


def _load_names():
    conn = db.get_conn()
    departments = [r["department"] for r in conn.execute(
        "SELECT DISTINCT department FROM positions ORDER BY id")]
    positions = [r["position"] for r in conn.execute(
        "SELECT position FROM positions ORDER BY id")]
    conn.close()
    return departments, positions


def store_result(document_id, result):
    departments, positions = _load_names()
    conn = db.get_conn()
    # 清空旧结果
    conn.execute("DELETE FROM rasic_matrix WHERE document_id=?", (document_id,))
    conn.execute("DELETE FROM interface_cards WHERE document_id=?", (document_id,))
    conn.execute("DELETE FROM flowcharts WHERE document_id=?", (document_id,))

    for level, key in (("department", "rasic_department"),
                       ("position", "rasic_position")):
        for row in result.get(key) or []:
            activity = str(row.get("activity", "")).strip()
            roles = row.get("roles") or {}
            for role, letter in roles.items():
                l = normalize_letter(letter)
                if not activity or not l:
                    continue
                r = normalize_role(role, departments, positions, level)
                conn.execute(
                    "INSERT INTO rasic_matrix(document_id,level,activity,role,letter)"
                    " VALUES(?,?,?,?,?)",
                    (document_id, level, activity, r, l),
                )

    for it in result.get("interfaces") or []:
        conn.execute(
            "INSERT INTO interface_cards(document_id,name,upstream_dept,"
            "downstream_dept,input_content,output_content,form,frequency,"
            "related_doc_nos,responsible_positions) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                document_id,
                str(it.get("name", "")).strip(),
                str(it.get("upstream_dept", "")).strip(),
                str(it.get("downstream_dept", "")).strip(),
                str(it.get("input_content", "")).strip(),
                str(it.get("output_content", "")).strip(),
                str(it.get("form", "")).strip(),
                str(it.get("frequency", "")).strip(),
                in_json(it.get("related_doc_nos")),
                in_json(it.get("responsible_positions")),
            ),
        )

    fc = result.get("flowchart")
    if fc:
        conn.execute(
            "INSERT INTO flowcharts(document_id,diagram_type,source)"
            " VALUES(?,?,?)",
            (document_id, "swimlane", json.dumps(fc, ensure_ascii=False)),
        )

    conn.commit()
    conn.close()


def in_json(v):
    import json
    if v is None:
        return "[]"
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


def out_json(v):
    import json
    if not v:
        return []
    try:
        return json.loads(v)
    except Exception:
        return [v]


# ---------- 静态页面 ----------
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


# ---------- 配置 ----------
@app.get("/api/settings")
def read_settings():
    return get_settings()


@app.post("/api/settings")
def write_settings(s: SettingsIn):
    conn = db.get_conn()
    for k, v in s.dict().items():
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (k, v),
        )
    conn.commit()
    conn.close()
    return {"ok": True}


# ---------- 元数据 ----------
@app.get("/api/meta")
def meta():
    conn = db.get_conn()
    pos_rows = [r for r in conn.execute(
        "SELECT department, position FROM positions ORDER BY id")]
    departments = []
    positions = []
    position_map = {}
    for r in pos_rows:
        d = r["department"]
        p = r["position"]
        if d not in position_map:
            position_map[d] = []
            departments.append(d)
        position_map[d].append(p)
        positions.append(p)
    file_types = [r["name"] for r in conn.execute(
        "SELECT name FROM file_types ORDER BY id")]
    existing = [dict(r) for r in conn.execute(
        "SELECT doc_no, name, doc_type, cur_dept, main_position FROM existing_files ORDER BY id")]
    conn.close()
    return {
        "departments": departments,
        "file_types": file_types,
        "positions": positions,
        "position_map": position_map,
        "existing_files": existing,
        "existing_doc_nos": [r["doc_no"] for r in existing if r.get("doc_no")],
        "existing_names": [r["name"] for r in existing if r.get("name")],
    }


@app.post("/api/import")
def reimport():
    try:
        db.import_lists()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- 文档 CRUD ----------
@app.post("/api/documents")
def create_document(d: DocumentIn):
    if d.doc_type not in ("管理制度", "店级管理制度", "工作程序", "工作说明书"):
        raise HTTPException(status_code=400, detail="文件类型只支持：管理制度 / 店级管理制度 / 工作程序 / 工作说明书")
    conn = db.get_conn()
    # 重复校验：doc_no 已存在则拒绝
    if d.doc_no:
        dup = conn.execute("SELECT id, title FROM documents WHERE doc_no=? LIMIT 1", (d.doc_no,)).fetchone()
        if dup:
            conn.close()
            raise HTTPException(status_code=400, detail=f"文件编号「{d.doc_no}」已存在（ID:{dup['id']}，标题：{dup['title']}），请勿重复录入")
    cur = conn.execute(
        "INSERT INTO documents(doc_type,doc_no,title,purpose,scope,regulation,"
        "duty,work_requirement,related_records,related_files,department,position,"
        "headcount,direct_supervisor,direct_subordinates,indirect_subordinates,"
        "qualifications,responsibilities,work_tasks,relationships,innovation,assessment,raw_text,raw_filename)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (d.doc_type, d.doc_no, d.title, d.purpose, d.scope, d.regulation,
         d.duty, d.work_requirement, d.related_records, d.related_files,
         d.department, d.position, d.headcount, d.direct_supervisor,
         d.direct_subordinates, d.indirect_subordinates, d.qualifications,
         d.responsibilities, d.work_tasks, d.relationships, d.innovation,
         d.assessment, d.raw_text, d.raw_filename),
    )
    conn.commit()
    doc_id = cur.lastrowid
    conn.close()
    item_count = items.split_and_store(doc_id)
    return {"id": doc_id, "item_count": item_count}


@app.get("/api/documents")
def list_documents():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT d.id, d.doc_type, d.doc_no, d.title, d.created_at, d.updated_at, "
        "CASE WHEN d.raw_filename IS NOT NULL AND d.raw_filename != '' THEN 1 ELSE 0 END AS has_raw, "
        "e.cur_dept, e.main_position, e.person_in_charge, e.filter_result, "
        "e.relevance, e.guest_trip, e.compliance, e.reason "
        "FROM documents d LEFT JOIN existing_files e ON d.doc_no = e.doc_no "
        "ORDER BY d.id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: int):
    conn = db.get_conn()
    row = conn.execute(
        "SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")
    return dict(row)


@app.get("/api/documents/{doc_id}/raw")
def get_document_raw(doc_id: int):
    """获取文档导入的原始文本，用于对比查看。"""
    conn = db.get_conn()
    row = conn.execute(
        "SELECT raw_text FROM documents WHERE id=?", (doc_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"raw_text": row["raw_text"] or ""}


@app.get("/api/documents/{doc_id}/download")
def download_document_raw(doc_id: int):
    """下载文档导入的原始 Word 文件。"""
    conn = db.get_conn()
    row = conn.execute(
        "SELECT raw_filename, doc_no, title FROM documents WHERE id=?", (doc_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")
    stored = row["raw_filename"]
    if not stored:
        raise HTTPException(status_code=404, detail="该文档未保存原始文件")
    uploads_dir = Path(__file__).resolve().parent / "uploads"
    fpath = uploads_dir / stored
    if not fpath.exists():
        raise HTTPException(status_code=404, detail="原始文件已丢失")
    # 下载时用"编号_标题"作为文件名，更直观
    ext = Path(stored).suffix
    dl_name = f"{row['doc_no'] or row['id']}_{row['title'] or 'document'}{ext}"
    return FileResponse(str(fpath), filename=dl_name,
                        media_type="application/octet-stream")


@app.get("/api/documents/{doc_id}/open")
def open_document_raw(doc_id: int):
    """直接用系统默认程序（Word）打开原始文件。"""
    import sys
    conn = db.get_conn()
    row = conn.execute(
        "SELECT raw_filename FROM documents WHERE id=?", (doc_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")
    stored = row["raw_filename"]
    if not stored:
        raise HTTPException(status_code=404, detail="该文档未保存原始文件")
    uploads_dir = Path(__file__).resolve().parent / "uploads"
    fpath = uploads_dir / stored
    if not fpath.exists():
        raise HTTPException(status_code=404, detail="原始文件已丢失")
    try:
        # 清理 Word 残留的锁文件（~$ 开头），否则 Word 会打开后又关闭
        lock_file = fpath.parent / f"~${fpath.name}"
        if lock_file.exists():
            try:
                lock_file.unlink()
            except OSError:
                pass
        if sys.platform.startswith("win"):
            # 用 ctypes 直接调用 ShellExecuteW，确保 Word 进程独立于服务器
            import ctypes
            SW_SHOWNORMAL = 1
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "open", str(fpath), None, None, SW_SHOWNORMAL)
            # 返回值 <= 32 表示失败
            if ret <= 32:
                raise OSError(f"ShellExecuteW 失败，错误码：{ret}")
        elif sys.platform == "darwin":
            import os
            os.system(f'open "{fpath}"')
        else:
            import os
            os.system(f'xdg-open "{fpath}"')
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"打开失败：{e}")


@app.put("/api/documents/{doc_id}")
def update_document(doc_id: int, d: DocumentIn):
    conn = db.get_conn()
    # 重复校验：doc_no 已被其他文档占用则拒绝
    if d.doc_no:
        dup = conn.execute("SELECT id, title FROM documents WHERE doc_no=? AND id!=? LIMIT 1",
                           (d.doc_no, doc_id)).fetchone()
        if dup:
            conn.close()
            raise HTTPException(status_code=400, detail=f"文件编号「{d.doc_no}」已被 ID:{dup['id']}（{dup['title']}）占用，请勿重复")
    cur = conn.execute(
        "UPDATE documents SET doc_type=?,doc_no=?,title=?,purpose=?,scope=?,"
        "regulation=?,duty=?,work_requirement=?,related_records=?,"
        "related_files=?,department=?,position=?,headcount=?,direct_supervisor=?,"
        "direct_subordinates=?,indirect_subordinates=?,qualifications=?,"
        "responsibilities=?,work_tasks=?,relationships=?,innovation=?,assessment=?,"
        "raw_text=?,raw_filename=?,updated_at=datetime('now','localtime') WHERE id=?",
        (d.doc_type, d.doc_no, d.title, d.purpose, d.scope, d.regulation,
         d.duty, d.work_requirement, d.related_records, d.related_files,
         d.department, d.position, d.headcount, d.direct_supervisor,
         d.direct_subordinates, d.indirect_subordinates, d.qualifications,
         d.responsibilities, d.work_tasks, d.relationships, d.innovation,
         d.assessment, d.raw_text, d.raw_filename, doc_id),
    )
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="文档不存在")
    item_count = items.split_and_store(doc_id)
    return {"ok": True, "item_count": item_count}


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: int):
    conn = db.get_conn()
    conn.execute("DELETE FROM rasic_matrix WHERE document_id=?", (doc_id,))
    conn.execute("DELETE FROM interface_cards WHERE document_id=?", (doc_id,))
    conn.execute("DELETE FROM flowcharts WHERE document_id=?", (doc_id,))
    conn.execute("DELETE FROM document_items WHERE document_id=?", (doc_id,))
    conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ---------- Word 文档上传解析 ----------
def _extract_word_text_via_com(file_path: str) -> str:
    """用 Word COM 打开文档并另存为纯文本（含自动编号序号），返回纯文本。"""
    import pythoncom
    import time
    from win32com.client import dynamic
    pythoncom.CoInitialize()
    # 用 dynamic.Dispatch（纯晚期绑定），完全绕开 gen_py 缓存，避免缓存损坏报错
    word = dynamic.Dispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = False
    txt_path = str(Path(file_path).with_suffix(".txt"))
    doc = None
    try:
        doc = word.Documents.Open(file_path)
        # 7 = wdFormatUnicodeText，另存为文本时 Word 会把自动编号序号写入
        doc.SaveAs2(txt_path, FileFormat=7)
        doc.Close(False)
        doc = None
    finally:
        try:
            word.Quit()
        except Exception:
            pass
        word = None
        pythoncom.CoUninitialize()
        # 等待 Word 完全退出并释放文件句柄
        time.sleep(0.5)
    with open(txt_path, "rb") as f:
        raw = f.read()
    Path(txt_path).unlink(missing_ok=True)
    # 中文 Windows 下 Word 存为 GBK，尝试多种编码解码
    for enc in ("utf-8-sig", "utf-8", "gbk", "utf-16", "utf-16-le"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, ValueError):
            continue
    else:
        text = raw.decode("gbk", errors="ignore")
    # Word 用 \r 作段落分隔，\x07 是表格单元格/行标记
    text = text.replace("\r", "\n").replace("\x07", "")
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    return "\n".join(lines)


def _extract_word_text(filename: str, content: bytes) -> str:
    """提取 Word 文档全文（含自动编号序号）。统一走 Word COM，确保序号完整。"""
    ext = Path(filename).suffix.lower()
    if ext not in (".doc", ".docx"):
        raise ValueError(f"不支持的文件格式：{ext}")
    import tempfile
    import time
    suffix = ext if ext in (".doc", ".docx") else ".docx"
    # 用 mkstemp + 手动关闭，避免 NamedTemporaryFile 在 Windows 上的句柄占用问题
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    try:
        return _extract_word_text_via_com(tmp_path)
    finally:
        # 重试删除临时文件，等待 Word 释放句柄
        for _ in range(5):
            try:
                Path(tmp_path).unlink(missing_ok=True)
                break
            except OSError:
                time.sleep(0.5)



@app.post("/api/parse-word")
async def parse_word(doc_type: str = "管理制度", file: UploadFile = File(...)):
    if doc_type not in ("管理制度", "店级管理制度", "工作程序", "工作说明书"):
        raise HTTPException(status_code=400, detail="文件类型只支持：管理制度 / 店级管理制度 / 工作程序 / 工作说明书")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        text = _extract_word_text(file.filename or "", raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Word 解析失败：{e}")
    if not text.strip():
        raise HTTPException(status_code=400, detail="文档内容为空")
    settings = get_settings()
    prompt = llm.build_word_parse_prompt(doc_type, text)
    try:
        raw_resp = llm.call_llm(settings, prompt, system=llm.WORD_PARSE_SYSTEM)
        fields = llm.parse_json(raw_resp)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"大模型解析失败：{e}")
    fields["doc_type"] = doc_type
    # 从文件名拆分文件编号和标题，优先于 LLM 结果
    fn_doc_no, fn_title = _split_filename(file.filename or "")
    if fn_doc_no:
        fields["doc_no"] = fn_doc_no
    if fn_title:
        fields["title"] = fn_title

    # 保存原始 Word 文件到 uploads 目录
    uploads_dir = Path(__file__).resolve().parent / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    orig_name = Path(file.filename or "document.docx").name
    safe_no = fn_doc_no or f"doc_{int(__import__('time').time())}"
    stored_name = f"{safe_no}_{orig_name}"
    stored_path = uploads_dir / stored_name
    stored_path.write_bytes(raw)

    return {"ok": True, "fields": fields, "text_length": len(text),
            "raw_text": text, "raw_filename": stored_name}


def _split_filename(filename: str):
    """从文件名拆分文件编号（前部字母数字段）和标题（后部文字）。
    例：MTFD-CW-B-005合同管理制度.doc -> (MTFD-CW-B-005, 合同管理制度)"""
    import re
    name = Path(filename).stem  # 去掉扩展名
    # 匹配前部连续的字母、数字、连字符、下划线、点作为编号
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9\-._]*)", name)
    doc_no = m.group(1).strip("-._") if m else ""
    title = name[m.end():].strip() if m else name.strip()
    return doc_no, title


# ---------- 结果读取 ----------
@app.get("/api/documents/{doc_id}/result")
def get_result(doc_id: int):
    conn = db.get_conn()
    rasic = conn.execute(
        "SELECT level, activity, role, letter FROM rasic_matrix "
        "WHERE document_id=? ORDER BY id", (doc_id,)).fetchall()
    interfaces = conn.execute(
        "SELECT * FROM interface_cards WHERE document_id=? ORDER BY id",
        (doc_id,)).fetchall()
    flows = conn.execute(
        "SELECT * FROM flowcharts WHERE document_id=? ORDER BY id",
        (doc_id,)).fetchall()
    conn.close()
    return {
        "rasic": [dict(r) for r in rasic],
        "interfaces": [dict(r) for r in interfaces],
        "flowcharts": [dict(r) for r in flows],
    }


# ---------- 生成 ----------
@app.post("/api/documents/{doc_id}/generate")
def generate(doc_id: int):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")
    doc = dict(row)
    try:
        settings = get_settings()
        user_prompt = llm.build_user_prompt(doc)
        raw = llm.call_llm(settings, user_prompt)
        result = llm.parse_json(raw)
        store_result(doc_id, result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return get_result(doc_id)


# ---------- 条目化 ----------
@app.post("/api/documents/{doc_id}/split")
def split_document(doc_id: int):
    try:
        n = items.split_and_store(doc_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "item_count": n}


@app.get("/api/documents/{doc_id}/items")
def get_document_items(doc_id: int):
    return items.query_items(document_id=doc_id, limit=10000)


@app.get("/api/items")
def search_items(q: str = None, department: str = None, position: str = None,
                 item_type: str = None, document_id: int = None,
                 doc_no: str = None, limit: int = 500):
    rows = items.query_items(keyword=q, department=department, position=position,
                             item_type=item_type, document_id=document_id,
                             doc_no=doc_no, limit=limit)
    return {"items": rows, "total": len(rows), "facets": items.facet_items()}


@app.get("/api/items/stats")
def items_stats():
    return items.facet_items()


@app.put("/api/items/{item_id}")
def update_item_endpoint(item_id: int, body: dict):
    ok = items.update_item(item_id, body)
    if not ok:
        raise HTTPException(status_code=400, detail="没有可更新的字段")
    return {"ok": True}


@app.get("/api/items/export")
def export_items(q: str = None, department: str = None, position: str = None,
                 item_type: str = None, document_id: int = None,
                 doc_no: str = None):
    rows = items.query_items(keyword=q, department=department, position=position,
                             item_type=item_type, document_id=document_id,
                             doc_no=doc_no, limit=100000)
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["文件编号", "文件类型", "标题", "章节", "序号", "层级", "条款类型",
                     "条目原文", "部门", "主责岗位", "负责人", "时限/频次", "关键词"])
    for r in rows:
        writer.writerow([
            r.get("doc_no", ""), r.get("doc_type", ""), r.get("title", ""),
            r.get("section", ""), r.get("seq", ""), r.get("level", ""),
            r.get("item_type", ""), r.get("content", ""),
            r.get("cur_dept", ""), r.get("main_position", ""),
            r.get("person_in_charge", ""),
            "、".join(r.get("frequency", [])), "、".join(r.get("keywords", [])),
        ])
    data = buf.getvalue()
    headers = {"Content-Disposition": 'attachment; filename="items.csv"'}
    return Response(content="\ufeff" + data, media_type="text/csv; charset=utf-8", headers=headers)


@app.post("/api/items/delete")
def delete_items(body: ItemsDeleteIn):
    ids = list(dict.fromkeys([i for i in body.ids if isinstance(i, int)]))
    if not ids:
        raise HTTPException(status_code=400, detail="未选择要删除的条目")
    placeholders = ",".join("?" * len(ids))
    conn = db.get_conn()
    cur = conn.execute(
        f"UPDATE document_items SET deleted=1 WHERE id IN ({placeholders}) AND deleted=0",
        ids,
    )
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": deleted}


# ==================== 员工工作全景 ====================

def _collect_employee_files(person: str, view_type: str) -> list:
    """收集某员工在指定视角下的文件及其内容摘要。"""
    conn = db.get_conn()
    like = f"%{person}%"
    # 先取出该员工负责的所有文件
    ef_rows = conn.execute(
        "SELECT doc_no, name, doc_type, cur_dept, main_position, "
        "guest_trip, compliance FROM existing_files "
        "WHERE person_in_charge LIKE ? ORDER BY doc_no",
        (like,),
    ).fetchall()

    files = []
    for ef in ef_rows:
        ef = dict(ef)
        # 视角筛选
        gt = ef.get("guest_trip") or ""
        cp = ef.get("compliance") or ""
        if view_type == "guest_trip" and not gt:
            continue
        if view_type == "compliance" and not cp:
            continue
        if view_type == "internal" and (gt or cp):
            continue  # 内部管理 = 既无旅程也无合规

        # 收集文件内容：优先 document_items，其次 documents 字段
        doc = conn.execute(
            "SELECT * FROM documents WHERE doc_no=? ORDER BY id DESC LIMIT 1",
            (ef["doc_no"],),
        ).fetchone()
        content_parts = []
        if doc:
            doc = dict(doc)
            doc_id = doc["id"]
            items_rows = conn.execute(
                "SELECT section, seq, content FROM document_items "
                "WHERE document_id=? AND deleted=0 ORDER BY sort_order LIMIT 80",
                (doc_id,),
            ).fetchall()
            if items_rows:
                for it in items_rows:
                    prefix = f"[{it['section']}]" if it["section"] else ""
                    seq = f"{it['seq']}" if it["seq"] else ""
                    content_parts.append(f"{prefix}{seq} {it['content']}")
            else:
                for fld in ("purpose", "scope", "regulation", "duty",
                            "work_requirement", "responsibilities", "work_tasks"):
                    v = doc.get(fld) or ""
                    if v.strip():
                        content_parts.append(v.strip())
        ef["content"] = "\n".join(content_parts)[:3000]
        files.append(ef)
    conn.close()
    return files


@app.get("/api/employees")
def list_employees():
    """返回所有负责人（拆分到个人）及其负责文件数。"""
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT person_in_charge FROM existing_files "
        "WHERE person_in_charge IS NOT NULL AND person_in_charge != ''"
    ).fetchall()
    conn.close()
    from collections import Counter
    cnt = Counter()
    for r in rows:
        pic = r["person_in_charge"]
        if not pic:
            continue
        for p in pic.replace("、", ",").replace("，", ",").split(","):
            p = p.strip()
            if p and p != "#N/A":
                cnt[p] += 1
    return {
        "employees": [
            {"name": name, "file_count": c}
            for name, c in cnt.most_common()
        ]
    }


@app.get("/api/employees/{person}/panorama")
def get_employee_panorama(person: str):
    """获取某员工已保存的全景分析（三个视角）。"""
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT view_type, narrative, cards, source_doc_nos, updated_at "
        "FROM employee_panoramas WHERE person_name=?",
        (person,),
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        nar = r["narrative"]
        # 兼容旧数据：narrative 可能是字符串（旧版）或 JSON 字符串（新版）
        if isinstance(nar, str):
            try:
                parsed = json.loads(nar)
                if isinstance(parsed, dict):
                    nar = parsed
                else:
                    nar = {"overview": nar}
            except (json.JSONDecodeError, TypeError):
                nar = {"overview": nar}
        result[r["view_type"]] = {
            "narrative": nar,
            "cards": json.loads(r["cards"]) if r["cards"] else [],
            "source_doc_nos": json.loads(r["source_doc_nos"]) if r["source_doc_nos"] else [],
            "updated_at": r["updated_at"],
        }
    return {"person": person, "views": result}


@app.post("/api/employees/{person}/panorama")
def generate_employee_panorama(person: str, view_type: str = "internal"):
    """生成并保存某员工指定视角的全景分析。"""
    if view_type not in ("guest_trip", "compliance", "internal"):
        raise HTTPException(status_code=400, detail="view_type 只支持：guest_trip / compliance / internal")
    files = _collect_employee_files(person, view_type)
    if not files:
        raise HTTPException(status_code=404, detail=f"未找到「{person}」在该视角下的相关文件")
    try:
        settings = get_settings()
        prompt = llm.build_employee_panorama_prompt(person, view_type, files)
        raw = llm.call_llm(settings, prompt, system=llm.EMP_PANORAMA_SYSTEM)
        result = llm.parse_json(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    narrative = result.get("narrative", {})
    cards = result.get("cards", [])
    doc_nos = [f["doc_no"] for f in files]

    conn = db.get_conn()
    conn.execute(
        "INSERT INTO employee_panoramas(person_name, view_type, narrative, cards, "
        "source_doc_nos, updated_at) VALUES(?,?,?,?,?,datetime('now','localtime')) "
        "ON CONFLICT(person_name, view_type) DO UPDATE SET "
        "narrative=excluded.narrative, cards=excluded.cards, "
        "source_doc_nos=excluded.source_doc_nos, updated_at=excluded.updated_at",
        (person, view_type, json.dumps(narrative, ensure_ascii=False),
         json.dumps(cards, ensure_ascii=False),
         json.dumps(doc_nos, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()
    return {
        "person": person,
        "view_type": view_type,
        "narrative": narrative,
        "cards": cards,
        "source_doc_nos": doc_nos,
    }


@app.get("/api/employees/{person}/collaborations")
def get_employee_collaborations(person: str):
    """分析某员工与其他员工的业务交集关系。

    两种协作类型：
    - shared_file: 共同负责同一文件（同部门标记为 same_dept）
    - cross_dept: 该员工负责的文件中，document_items 提到的其他部门 → 关联该部门负责人

    返回：
    - center: 中心员工信息
    - nodes: 节点列表
    - edges: 连线列表（type: shared_file / cross_dept）
    - collaborators: 协作列表
    """
    import json as _json
    from collections import defaultdict

    conn = db.get_conn()
    like = f"%{person}%"

    # 该员工负责的所有文件
    my_files = conn.execute(
        "SELECT doc_no, name, cur_dept, main_position FROM existing_files "
        "WHERE person_in_charge LIKE ? ORDER BY doc_no",
        (like,),
    ).fetchall()
    my_doc_nos = {r["doc_no"] for r in my_files}
    if not my_doc_nos:
        conn.close()
        raise HTTPException(status_code=404, detail=f"未找到「{person}」负责的文件")

    # 中心员工的部门
    my_dept_row = conn.execute(
        "SELECT cur_dept FROM existing_files WHERE person_in_charge LIKE ? LIMIT 1",
        (like,),
    ).fetchone()
    my_dept = my_dept_row["cur_dept"] if my_dept_row else ""

    # ====== 类型1：共同负责文件 ======
    placeholders = ",".join("?" * len(my_doc_nos))
    related = conn.execute(
        f"SELECT doc_no, name, cur_dept, person_in_charge FROM existing_files "
        f"WHERE doc_no IN ({placeholders})",
        list(my_doc_nos),
    ).fetchall()
    shared = defaultdict(list)  # other_name -> [shared_files]
    dept_of_person = {}
    for r in related:
        pic = r["person_in_charge"] or ""
        for p in pic.replace("、", ",").replace("，", ",").split(","):
            p = p.strip()
            if not p or p == "#N/A" or p == person:
                continue
            shared[p].append({"doc_no": r["doc_no"], "name": r["name"]})
            if p not in dept_of_person and r["cur_dept"]:
                dept_of_person[p] = r["cur_dept"]

    # ====== 类型2：跨部门业务衔接（document_items） ======
    # 查该员工负责文件的所有条目，提取 departments
    item_rows = conn.execute(
        f"SELECT d.doc_no, e.name AS doc_name, e.cur_dept, di.section, di.content, di.departments "
        f"FROM document_items di "
        f"JOIN documents d ON di.document_id = d.id "
        f"JOIN existing_files e ON d.doc_no = e.doc_no "
        f"WHERE d.doc_no IN ({placeholders}) "
        f"AND di.departments IS NOT NULL AND di.departments != '' AND di.departments != '[]'",
        list(my_doc_nos),
    ).fetchall()

    # 按跨部门分组，收集条目详情
    cross_dept_items = defaultdict(list)  # dept -> [item details]
    for r in item_rows:
        try:
            depts = _json.loads(r["departments"]) if isinstance(r["departments"], str) else r["departments"]
        except Exception:
            depts = [r["departments"]]
        if not isinstance(depts, list):
            depts = [depts]
        for dept in depts:
            dept = str(dept).strip()
            if not dept or dept == my_dept:
                continue
            cross_dept_items[dept].append({
                "doc_no": r["doc_no"],
                "doc_name": r["doc_name"],
                "section": r["section"],
                "content": (r["content"] or "")[:120],
            })

    # 把跨部门映射到具体的人：取该部门出现频率最高的 1~2 个负责人作为代表
    dept_person_freq = defaultdict(lambda: defaultdict(int))  # dept -> person -> count
    all_ef = conn.execute(
        "SELECT cur_dept, person_in_charge FROM existing_files "
        "WHERE cur_dept IS NOT NULL AND cur_dept != '' "
        "AND person_in_charge IS NOT NULL AND person_in_charge != ''"
    ).fetchall()
    for r in all_ef:
        dept = r["cur_dept"]
        for p in (r["person_in_charge"] or "").replace("、", ",").replace("，", ",").split(","):
            p = p.strip()
            if p and p != "#N/A":
                dept_person_freq[dept][p] += 1

    # cross_dept 协作：other_name -> {weight, cross_items, dept}
    cross = {}
    for dept, items in cross_dept_items.items():
        persons = dept_person_freq.get(dept, {})
        if not persons:
            continue
        # 取频率最高的前 2 人作为该部门代表
        top_persons = sorted(persons.items(), key=lambda x: -x[1])[:2]
        for p_name, _ in top_persons:
            if p_name == person:
                continue
            if p_name not in cross:
                cross[p_name] = {"weight": 0, "cross_items": [], "dept": dept}
            cross[p_name]["weight"] += len(items)
            cross[p_name]["cross_items"].extend(items)
            dept_of_person[p_name] = dept

    conn.close()

    # ====== 合并两种协作关系 ======
    all_others = set(shared.keys()) | set(cross.keys())

    # 按「共同文件集合 + 跨部门条目集合」分组，相同的合并为一组
    # 签名：(frozenset(共同文件doc_no), frozenset(跨部门条目doc_no+section))
    groups = {}  # signature -> {names, dept, shared_files, cross_items, same_dept, has_cross}
    for other in all_others:
        sf = shared.get(other, [])
        cd = cross.get(other, {})
        sf_key = frozenset(f["doc_no"] for f in sf)
        cd_key = frozenset((it["doc_no"], it["section"], it["content"]) for it in cd.get("cross_items", []))
        sig = (sf_key, cd_key)
        if sig not in groups:
            groups[sig] = {
                "names": [],
                "dept": dept_of_person.get(other, ""),
                "shared_files": sf,
                "cross_items": cd.get("cross_items", []),
                "same_dept": bool(my_dept and dept_of_person.get(other) == my_dept),
                "has_cross_dept": bool(cd),
            }
        groups[sig]["names"].append(other)

    # ====== 构建节点/连线/列表 ======
    nodes = [{"name": person, "dept": my_dept, "file_count": len(my_doc_nos), "is_center": True}]
    edges = []
    collaborators = []

    for sig, g in groups.items():
        names = g["names"]
        # 节点名：单人直接显示，多人用顿号连接
        node_name = "、".join(names) if len(names) > 1 else names[0]
        sf = g["shared_files"]
        ci = g["cross_items"]
        weight = len(sf) + len(ci)

        nodes.append({
            "name": node_name,
            "dept": g["dept"],
            "file_count": weight,
            "is_center": False,
            "person_count": len(names),
        })

        if g["same_dept"]:
            edge_type = "same_dept"
        elif g["has_cross_dept"]:
            edge_type = "cross_dept"
        else:
            edge_type = "shared_file"

        edges.append({
            "source": person,
            "target": node_name,
            "weight": weight,
            "type": edge_type,
            "shared_files": sf,
            "cross_items": ci,
        })

        collaborators.append({
            "names": names,
            "name": node_name,
            "dept": g["dept"],
            "shared_count": weight,
            "shared_file_count": len(sf),
            "cross_dept_count": len(ci),
            "shared_files": sf,
            "cross_items": ci,
            "same_dept": g["same_dept"],
            "has_cross_dept": g["has_cross_dept"],
        })

    collaborators.sort(key=lambda x: (-x["shared_count"], x["name"]))

    return {
        "person": person,
        "center": {"name": person, "dept": my_dept, "file_count": len(my_doc_nos)},
        "nodes": nodes,
        "edges": edges,
        "collaborators": collaborators,
    }


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")