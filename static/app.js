// 简单的单页切换与 API 调用逻辑
let currentDocId = null;
let positionMap = {};
const LETTER_COLOR = { R: "R", A: "A", S: "S", I: "I", C: "C" };

function $(id) { return document.getElementById(id); }

function showTab(name) {
  document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  const panel = document.getElementById("tab-" + name);
  if (panel) panel.classList.add("active");
  const tab = document.querySelector(`.tab[data-tab="${name}"]`);
  if (tab) tab.classList.add("active");
  if (name === "list") loadDocuments();
  if (name === "items") { loadDocFilter(); loadItems(); }
  if (name === "employee") loadEmployees();
}

function setMsg(id, text, ok) {
  const el = $(id);
  el.textContent = text || "";
  el.className = "msg " + (text ? (ok ? "ok" : "err") : "");
}

async function api(url, opts) {
  const resp = await fetch(url, opts);
  let data = null;
  try { data = await resp.json(); } catch (e) {}
  if (!resp.ok) {
    const detail = (data && data.detail) ? data.detail : ("HTTP " + resp.status);
    throw new Error(detail);
  }
  return data;
}

// ---------- 设置 ----------
async function loadSettings() {
  const s = await api("/api/settings");
  $("cfg-apikey").value = s.api_key || "";
  $("cfg-baseurl").value = s.base_url || "https://api.deepseek.com";
  $("cfg-model").value = s.model || "deepseek-chat";
}

async function loadMeta() {
  const m = await api("/api/meta");
  positionMap = m.position_map || {};
  itemMeta = {
    departments: m.departments || [],
    positions: m.positions || [],
    position_map: m.position_map || {},
    existing_doc_nos: m.existing_doc_nos || [],
    existing_names: m.existing_names || [],
  };
  const deptSel = $("f-dept");
  deptSel.innerHTML = '<option value="">全部部门</option>' +
    m.departments.map(d => `<option value="${esc(d)}">${esc(d)}</option>`).join("");
  // 工作说明书：所属部门下拉
  $("doc-department").innerHTML = '<option value="">请选择</option>' +
    m.departments.map(d => `<option value="${esc(d)}">${esc(d)}</option>`).join("");
  // 工作说明书：岗位名称、直接上级、直接/间接下级 均受所属部门约束
  $("doc-department").onchange = updatePositionOptionsByDept;
  updatePositionOptionsByDept();
  $("meta-hint").textContent =
    `部门 ${m.departments.length} 个 · 岗位 ${m.positions.length} 个 · ` +
    `文件类型 ${m.file_types.length} 类 · 现有文件 ${m.existing_files.length} 条`;
}

// 根据所属部门过滤岗位相关下拉
function updatePositionOptionsByDept() {
  const dept = $("doc-department").value;
  const positions = dept ? (positionMap[dept] || []) : [];
  const opts = positions.map(p => `<option value="${esc(p)}">${esc(p)}</option>`).join("");
  $("doc-position").innerHTML = '<option value="">请选择</option>' + opts;
  $("doc-supervisor").innerHTML = '<option value="">请选择</option>' + opts;
  $("doc-direct-sub").innerHTML = '<option value="">请选择</option>' + opts;
}

async function saveSettings() {
  try {
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key: $("cfg-apikey").value.trim(),
        base_url: $("cfg-baseurl").value.trim(),
        model: $("cfg-model").value.trim(),
      }),
    });
    setMsg("settings-msg", "已保存", true);
  } catch (e) {
    setMsg("settings-msg", "保存失败：" + e.message, false);
  }
}

async function reimport() {
  try {
    await api("/api/import", { method: "POST" });
    loadMeta();
    setMsg("settings-msg", "三份清单已重新导入", true);
  } catch (e) {
    setMsg("settings-msg", "导入失败：" + e.message, false);
  }
}

// ---------- 编辑器 ----------
function toggleDocType() {
  const t = $("doc-type").value;
  const isReg = t === "管理制度" || t === "店级管理制度";
  const isProc = t === "工作程序";
  const isJD = t === "工作说明书";
  const show = (id, on) => { const el = $(id); if (el) el.style.display = on ? "flex" : "none"; };
  show("wrap-regulation", isReg);
  show("wrap-duty", isProc);
  show("wrap-work", isProc);
  // 工作说明书不需要：目的、范围、相关记录、相关文件
  show("wrap-purpose", !isJD);
  show("wrap-scope", !isJD);
  show("wrap-records", !isJD);
  show("wrap-files", !isJD);
  // 工作说明书：标题与所属部门同一行（各占一列）
  const titleEl = $("wrap-title");
  if (titleEl) titleEl.classList.toggle("full", !isJD);
  show("wrap-dept", isJD);
  // 工作说明书专属字段
  ["wrap-jd", "wrap-qualifications", "wrap-responsibilities",
   "wrap-work-tasks", "wrap-relationships", "wrap-innovation", "wrap-assessment"]
    .forEach(id => show(id, isJD));
}

function collectDoc() {
  const t = $("doc-type").value;
  const isJD = t === "工作说明书";
  // 基本任职资格：四个子项合并为多行文本
  const quals = [];
  if (isJD) {
    const edu = $("qual-edu").value.trim();
    const exp = $("qual-exp").value.trim();
    const lang = $("qual-lang").value.trim();
    const quality = $("qual-quality").value.trim();
    if (edu) quals.push("文化程度：" + edu);
    if (exp) quals.push("工作经验：" + exp);
    if (lang) quals.push("外语水平：" + lang);
    if (quality) quals.push("基本素质：" + quality);
  }
  return {
    doc_type: t,
    doc_no: $("doc-no").value.trim(),
    title: $("doc-title").value.trim(),
    purpose: isJD ? "" : $("doc-purpose").value.trim(),
    scope: isJD ? "" : $("doc-scope").value.trim(),
    regulation: (t === "管理制度" || t === "店级管理制度") ? $("doc-regulation").value.trim() : "",
    duty: t === "工作程序" ? $("doc-duty").value.trim() : "",
    work_requirement: t === "工作程序" ? $("doc-work").value.trim() : "",
    related_records: isJD ? "" : $("doc-records").value.trim(),
    related_files: isJD ? "" : $("doc-files").value.trim(),
    department: isJD ? $("doc-department").value : "",
    position: isJD ? $("doc-position").value : "",
    headcount: isJD ? $("doc-headcount").value.trim() : "",
    direct_supervisor: isJD ? $("doc-supervisor").value : "",
    direct_subordinates: isJD ? $("doc-direct-sub").value.trim() : "",
    qualifications: quals.join("\n"),
    responsibilities: isJD ? $("doc-responsibilities").value.trim() : "",
    work_tasks: isJD ? $("doc-work-tasks").value.trim() : "",
    relationships: isJD ? $("doc-relationships").value.trim() : "",
    innovation: isJD ? $("doc-innovation").value.trim() : "",
    assessment: isJD ? $("doc-assessment").value.trim() : "",
  };
}

function _parseQual(text) {
  const out = { edu: "", exp: "", lang: "", quality: "" };
  if (!text) return out;
  // 去掉行首序号（如 1、 （一） ① 1. 等）后再匹配标签
  const stripPrefix = (line) => line.replace(/^[\s\d一二三四五六七八九十百①②③④⑤⑥⑦⑧⑨⑩、.（）()\[\]【】]+/, "").trim();
  const labels = [
    { key: "edu", names: ["文化程度", "学历", "文化"] },
    { key: "exp", names: ["工作经验", "经验", "从业经验"] },
    { key: "lang", names: ["外语水平", "外语", "语言能力"] },
    { key: "quality", names: ["基本素质", "素质", "职业素养", "素养"] },
  ];
  text.split("\n").forEach(line => {
    const clean = stripPrefix(line);
    for (const lb of labels) {
      for (const name of lb.names) {
        if (clean.startsWith(name)) {
          // 去掉标签名及后面的冒号（全角/半角）
          let val = clean.slice(name.length).replace(/^[：:\s]+/, "");
          out[lb.key] = val;
          break;
        }
      }
    }
  });
  return out;
}

function fillDoc(d) {
  $("doc-id").value = d.id || "";
  $("doc-type").value = d.doc_type || "管理制度";
  $("doc-no").value = d.doc_no || "";
  $("doc-title").value = d.title || "";
  $("doc-purpose").value = d.purpose || "";
  $("doc-scope").value = d.scope || "";
  $("doc-regulation").value = d.regulation || "";
  $("doc-duty").value = d.duty || "";
  $("doc-work").value = d.work_requirement || "";
  $("doc-records").value = d.related_records || "";
  $("doc-files").value = d.related_files || "";
  $("doc-department").value = d.department || "";
  // 先按所属部门刷新岗位下拉，再回填岗位值
  if (d.doc_type === "工作说明书") updatePositionOptionsByDept();
  $("doc-position").value = d.position || "";
  $("doc-headcount").value = d.headcount || "";
  $("doc-supervisor").value = d.direct_supervisor || "";
  $("doc-direct-sub").value = d.direct_subordinates || "";
  const q = _parseQual(d.qualifications || "");
  $("qual-edu").value = q.edu;
  $("qual-exp").value = q.exp;
  $("qual-lang").value = q.lang;
  $("qual-quality").value = q.quality;
  $("doc-responsibilities").value = d.responsibilities || "";
  $("doc-work-tasks").value = d.work_tasks || "";
  $("doc-relationships").value = d.relationships || "";
  $("doc-innovation").value = d.innovation || "";
  $("doc-assessment").value = d.assessment || "";
  toggleDocType();
}

async function saveDoc() {
  const d = collectDoc();
  if (!d.title) { setMsg("editor-msg", "请填写标题", false); return; }
  const isEdit = $("doc-id").value;
  try {
    if (isEdit) {
      const r = await api("/api/documents/" + isEdit, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(d),
      });
      setMsg("editor-msg", "已更新，数字化为 " + (r.item_count || 0) + " 条", true);
    } else {
      const r = await api("/api/documents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(d),
      });
      // 新建保存成功后自动清空表单（含 doc-id），避免下一次保存误覆盖本份
      resetDoc();
      setMsg("editor-msg",
        "已保存（ID：" + r.id + "），数字化为 " + (r.item_count || 0) + " 条，可继续录入下一份文件。",
        true);
    }
  } catch (e) {
    setMsg("editor-msg", "保存失败：" + e.message, false);
  }
}

function resetDoc() {
  $("doc-id").value = "";
  ["doc-no", "doc-title", "doc-purpose", "doc-scope", "doc-regulation",
   "doc-duty", "doc-work", "doc-records", "doc-files",
   "doc-headcount", "doc-direct-sub",
   "qual-edu", "qual-exp", "qual-lang", "qual-quality",
   "doc-responsibilities", "doc-work-tasks", "doc-relationships",
   "doc-innovation", "doc-assessment"].forEach(id => $(id).value = "");
  $("doc-type").value = "管理制度";
  $("doc-department").value = "";
  $("doc-position").value = "";
  $("doc-supervisor").value = "";
  toggleDocType();
  setMsg("editor-msg", "", true);
}

// ---------- Word 上传解析 ----------
async function parseWord() {
  const fileInput = $("word-file");
  const file = fileInput.files[0];
  if (!file) { setMsg("editor-msg", "请先选择 Word 文件（.docx 或 .doc）", false); return; }
  const lname = file.name.toLowerCase();
  if (!lname.endsWith(".docx") && !lname.endsWith(".doc")) {
    setMsg("editor-msg", "仅支持 .docx 和 .doc 格式", false); return;
  }
  const docType = $("doc-type").value;
  const btn = $("btn-parse-word");
  btn.disabled = true;
  btn.textContent = "解析中…";
  setMsg("editor-msg", "正在上传并解析，请稍候…", true);
  try {
    const fd = new FormData();
    fd.append("file", file);
    const resp = await fetch(`/api/parse-word?doc_type=${encodeURIComponent(docType)}`, {
      method: "POST",
      body: fd,
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || ("HTTP " + resp.status));
    const f = data.fields || {};
    // 回填通用字段
    if (f.doc_no) $("doc-no").value = f.doc_no;
    if (f.title) $("doc-title").value = f.title;
    if (f.purpose) $("doc-purpose").value = f.purpose;
    if (f.scope) $("doc-scope").value = f.scope;
    if (f.related_records) $("doc-records").value = f.related_records;
    if (f.related_files) $("doc-files").value = f.related_files;
    if (docType === "管理制度" || docType === "店级管理制度") {
      if (f.regulation) $("doc-regulation").value = f.regulation;
    } else if (docType === "工作程序") {
      if (f.duty) $("doc-duty").value = f.duty;
      if (f.work_requirement) $("doc-work").value = f.work_requirement;
    } else if (docType === "工作说明书") {
      if (f.department) $("doc-department").value = f.department;
      updatePositionOptionsByDept();
      if (f.position) $("doc-position").value = f.position;
      if (f.headcount) $("doc-headcount").value = f.headcount;
      if (f.direct_supervisor) $("doc-supervisor").value = f.direct_supervisor;
      if (f.direct_subordinates) $("doc-direct-sub").value = f.direct_subordinates;
      // 基本任职资格拆回四个子项
      const q = _parseQual(f.qualifications || "");
      $("qual-edu").value = q.edu;
      $("qual-exp").value = q.exp;
      $("qual-lang").value = q.lang;
      $("qual-quality").value = q.quality;
      if (f.responsibilities) $("doc-responsibilities").value = f.responsibilities;
      if (f.work_tasks) $("doc-work-tasks").value = f.work_tasks;
      if (f.relationships) $("doc-relationships").value = f.relationships;
      if (f.innovation) $("doc-innovation").value = f.innovation;
      if (f.assessment) $("doc-assessment").value = f.assessment;
    }
    setMsg("editor-msg", `解析成功（原文 ${data.text_length} 字），请核对后保存`, true);
  } catch (e) {
    setMsg("editor-msg", "解析失败：" + e.message, false);
  } finally {
    btn.disabled = false;
    btn.textContent = "解析并填表";
  }
}

// ---------- 列表 ----------
let _allDocs = [];
let _docSort = { key: "id", asc: false };
let _docPage = 1;
let _docPageSize = 10;

async function loadDocuments() {
  _allDocs = await api("/api/documents");
  // 填充部门下拉
  const depts = [...new Set(_allDocs.map(r => r.cur_dept).filter(Boolean))].sort();
  const deptSel = $("f-list-dept");
  const curVal = deptSel.value;
  deptSel.innerHTML = '<option value="">全部部门</option>' + depts.map(d => `<option value="${esc(d)}">${esc(d)}</option>`).join("");
  deptSel.value = curVal;

  _docPage = 1;
  renderDocList();
}

function renderDocList() {
  const q = ($("f-list-q").value || "").trim().toLowerCase();
  const ft = $("f-list-type").value;
  const fd = $("f-list-dept").value;
  const fg = $("f-list-guest").value;
  const fc = $("f-list-compliance").value;

  let rows = _allDocs.filter(r => {
    if (q) {
      const hay = ((r.doc_no || "") + " " + (r.title || "") + " " +
                   (r.cur_dept || "") + " " + (r.main_position || "") + " " +
                   (r.person_in_charge || "")).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    if (ft && r.doc_type !== ft) return false;
    if (fd && r.cur_dept !== fd) return false;
    if (fg && (r.guest_trip || "") !== fg) return false;
    if (fc && (r.compliance || "") !== fc) return false;
    return true;
  });

  // 排序
  const { key, asc } = _docSort;
  rows.sort((a, b) => {
    let va = a[key] == null ? "" : String(a[key]);
    let vb = b[key] == null ? "" : String(b[key]);
    if (key === "id") { va = Number(a[key] || 0); vb = Number(b[key] || 0); }
    if (va < vb) return asc ? -1 : 1;
    if (va > vb) return asc ? 1 : -1;
    return 0;
  });

  const total = rows.length;
  const totalPages = Math.max(1, Math.ceil(total / _docPageSize));
  if (_docPage > totalPages) _docPage = totalPages;
  const start = (_docPage - 1) * _docPageSize;
  const pageRows = rows.slice(start, start + _docPageSize);

  const tb = $("doc-table");
  if (!total) {
    tb.innerHTML = '<tr><td colspan="11" style="color:#6b7280;text-align:center;padding:20px">暂无符合条件的文件</td></tr>';
    bindDocListActions();
    renderDocPagination(0, 0, 0, 0);
    return;
  }

  tb.innerHTML = pageRows.map(r => `
    <tr>
      <td>${r.id}</td>
      <td>${esc(r.doc_type || "")}</td>
      <td>${esc(r.doc_no || "")}</td>
      <td><a data-id="${r.id}" class="open-doc">${esc(r.title || "(无标题)")}</a></td>
      <td>${esc(r.cur_dept || "")}</td>
      <td>${esc(r.main_position || "")}</td>
      <td>${esc(r.person_in_charge || "")}</td>
      <td>${esc(r.guest_trip || "")}</td>
      <td>${esc(r.compliance || "")}</td>
      <td>${esc(r.created_at || "")}</td>
      <td>
        <a data-id="${r.id}" class="open-doc">查看</a>
        <a data-id="${r.id}" class="edit-doc" style="margin-left:8px">编辑</a>
        <a data-id="${r.id}" class="del-doc" style="margin-left:8px;color:#dc2626">删除</a>
      </td>
    </tr>`).join("");
  bindDocListActions();
  initColResize("doc-list-table");

  // 排序表头样式
  document.querySelectorAll("#doc-list-table th[data-sort]").forEach(th => {
    const k = th.dataset.sort;
    th.style.cursor = "pointer";
    const arrow = _docSort.key === k ? (_docSort.asc ? " ▲" : " ▼") : "";
    if (!th.querySelector(".sort-arrow")) {
      const sp = document.createElement("span");
      sp.className = "sort-arrow";
      th.appendChild(sp);
    }
    th.querySelector(".sort-arrow").textContent = arrow;
  });

  renderDocPagination(total, totalPages, start + 1, Math.min(start + _docPageSize, total));
}

function renderDocPagination(total, totalPages, from, to) {
  const bar = $("doc-pagination");
  if (!bar) return;
  if (!total) { bar.innerHTML = ""; return; }
  let pages = [];
  const cur = _docPage;
  for (let i = 1; i <= totalPages; i++) {
    if (i === 1 || i === totalPages || Math.abs(i - cur) <= 2) pages.push(i);
    else if (pages[pages.length - 1] !== "...") pages.push("...");
  }
  bar.innerHTML = `
    <span class="page-info">共 ${total} 条，第 ${from}-${to} 条</span>
    <select id="doc-page-size" class="page-size">
      <option value="10" ${_docPageSize===10?"selected":""}>10 条/页</option>
      <option value="20" ${_docPageSize===20?"selected":""}>20 条/页</option>
      <option value="50" ${_docPageSize===50?"selected":""}>50 条/页</option>
      <option value="100" ${_docPageSize===100?"selected":""}>100 条/页</option>
    </select>
    <button class="page-btn" ${cur<=1?"disabled":""} data-page="${cur-1}">上一页</button>
    ${pages.map(p => p === "..."
      ? `<span class="page-ellipsis">…</span>`
      : `<button class="page-btn ${p===cur?"active":""}" data-page="${p}">${p}</button>`
    ).join("")}
    <button class="page-btn" ${cur>=totalPages?"disabled":""} data-page="${cur+1}">下一页</button>
  `;
  bar.querySelectorAll(".page-btn[data-page]").forEach(b => {
    b.onclick = () => {
      _docPage = Number(b.dataset.page);
      renderDocList();
    };
  });
  const ps = bar.querySelector("#doc-page-size");
  if (ps) ps.onchange = () => {
    _docPageSize = Number(ps.value);
    _docPage = 1;
    renderDocList();
  };
}

function bindDocListActions() {
  const tb = $("doc-table");
  tb.querySelectorAll(".open-doc").forEach(a =>
    a.onclick = () => openDetail(a.dataset.id));
  tb.querySelectorAll(".edit-doc").forEach(a =>
    a.onclick = async () => {
      const d = await api("/api/documents/" + a.dataset.id);
      fillDoc(d);
      showTab("editor");
    });
  tb.querySelectorAll(".del-doc").forEach(a =>
    a.onclick = async () => {
      if (!confirm("确认删除该文件及其分析结果？")) return;
      await api("/api/documents/" + a.dataset.id, { method: "DELETE" });
      loadDocuments();
    });
}

// 文件列表排序
document.addEventListener("click", (e) => {
  const th = e.target.closest("#doc-list-table th[data-sort]");
  if (!th) return;
  // 避免拖拽触发排序
  if (e.target.classList.contains("col-resizer")) return;
  const key = th.dataset.sort;
  if (_docSort.key === key) {
    _docSort.asc = !_docSort.asc;
  } else {
    _docSort.key = key;
    _docSort.asc = true;
  }
  renderDocList();
});

// 文件列表筛选按钮
document.addEventListener("DOMContentLoaded", () => {
  const btnSearch = $("btn-list-search");
  const btnReset = $("btn-list-reset");
  if (btnSearch) btnSearch.onclick = () => { _docPage = 1; renderDocList(); };
  if (btnReset) btnReset.onclick = () => {
    $("f-list-q").value = "";
    $("f-list-type").value = "";
    $("f-list-dept").value = "";
    $("f-list-guest").value = "";
    $("f-list-compliance").value = "";
    _docPage = 1;
    renderDocList();
  };
  // 回车搜索
  const fq = $("f-list-q");
  if (fq) fq.addEventListener("keydown", (e) => { if (e.key === "Enter") { _docPage = 1; renderDocList(); } });
});

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ---------- 详情 & 结果 ----------
async function openDetail(id) {
  currentDocId = id;
  const d = await api("/api/documents/" + id);
  $("detail-title").textContent = `分析结果：${d.title || d.doc_no || id}`;
  $("doc-preview").innerHTML = `
    <div class="kv">
      <b>文件类型</b><span>${esc(d.doc_type)}</span>
      <b>文件编号</b><span>${esc(d.doc_no)}</span>
      <b>标题</b><span>${esc(d.title)}</span>
      <b>目的</b><span>${esc(d.purpose)}</span>
      <b>范围</b><span>${esc(d.scope)}</span>
      ${d.regulation ? `<b>管理规定</b><span>${nl2br(esc(d.regulation))}</span>` : ""}
      ${d.duty ? `<b>职责</b><span>${nl2br(esc(d.duty))}</span>` : ""}
      ${d.work_requirement ? `<b>工作要求</b><span>${nl2br(esc(d.work_requirement))}</span>` : ""}
      <b>相关记录</b><span>${esc(d.related_records)}</span>
      <b>相关文件</b><span>${esc(d.related_files)}</span>
    </div>`;
  showTab("detail");
  try {
    const r = await api(`/api/documents/${id}/result`);
    renderResult(r);
  } catch (e) { /* 暂无结果 */ }
}

function nl2br(s) {
  return s.replace(/\n/g, "<br>");
}

async function generate() {
  if (!currentDocId) return;
  const btn = $("btn-generate");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>生成中…（可能需数十秒）';
  setMsg("detail-msg", "正在调用大模型分析，请稍候…", true);
  try {
    const r = await api(`/api/documents/${currentDocId}/generate`, { method: "POST" });
    renderResult(r);
    setMsg("detail-msg", "分析完成", true);
  } catch (e) {
    setMsg("detail-msg", "生成失败：" + e.message, false);
  } finally {
    btn.disabled = false;
    btn.innerHTML = "生成分析（RASIC / 接口卡 / 流程图）";
  }
}

function renderResult(r) {
  const area = $("result-area");
  if (!r || (!r.rasic.length && !r.interfaces.length && !r.flowcharts.length)) {
    area.style.display = "none";
    return;
  }
  area.style.display = "block";
  let html = "";

  // RASIC 部门级 / 岗位级
  if (r.rasic.length) {
    html += '<div class="result-block"><h3>RASIC 矩阵</h3>';
    html += legend();
    html += buildMatrix(r.rasic.filter(x => x.level === "department"), "部门级 RASIC");
    const posItems = r.rasic.filter(x => x.level === "position");
    html += buildPositionMatrix(posItems, "岗位级 RASIC（按部门展开岗位）");
    html += "</div>";
  }

  // 接口卡
  if (r.interfaces.length) {
    html += '<div class="result-block"><h3>跨部门接口卡</h3>';
    r.interfaces.forEach((it, i) => {
      html += `<div class="iface">
        <h4>${i + 1}. ${esc(it.name || "接口")}</h4>
        <div class="kv">
          <b>上游部门</b><span>${esc(it.upstream_dept)}</span>
          <b>下游部门</b><span>${esc(it.downstream_dept)}</span>
          <b>输入内容</b><span>${esc(it.input_content)}</span>
          <b>输出内容</b><span>${esc(it.output_content)}</span>
          <b>接口形式</b><span>${esc(it.form)}</span>
          <b>频次</b><span>${esc(it.frequency)}</span>
          <b>相关文件编号</b><span>${esc(parseList(it.related_doc_nos).join("、"))}</span>
          <b>责任岗位</b><span>${esc(parseList(it.responsible_positions).join("、"))}</span>
        </div>
      </div>`;
    });

    // 接口卡汇总表格
    html += '<div class="table-wrap" style="margin-top:16px"><table class="table">';
    html += "<thead><tr>" +
      "<th>序号</th><th>接口名称</th><th>上游部门</th><th>下游部门</th>" +
      "<th>输入内容</th><th>输出内容</th><th>接口形式</th><th>频次</th>" +
      "<th>相关文件编号</th><th>责任岗位</th></tr></thead><tbody>";
    r.interfaces.forEach((it, i) => {
      html += `<tr>
        <td>${i + 1}</td>
        <td>${esc(it.name || "接口")}</td>
        <td>${esc(it.upstream_dept)}</td>
        <td>${esc(it.downstream_dept)}</td>
        <td>${esc(it.input_content)}</td>
        <td>${esc(it.output_content)}</td>
        <td>${esc(it.form)}</td>
        <td>${esc(it.frequency)}</td>
        <td>${esc(parseList(it.related_doc_nos).join("、"))}</td>
        <td>${esc(parseList(it.responsible_positions).join("、"))}</td>
      </tr>`;
    });
    html += "</tbody></table></div>";
    html += "</div>";
  }

  // 流程图
  if (r.flowcharts.length) {
    html += '<div class="result-block"><h3>流程图</h3>';
    r.flowcharts.forEach((f, i) => {
      html += `<div class="flow-wrap"><div id="flow-${i}"></div></div>`;
    });
    html += "</div>";
  }

  area.innerHTML = html;

  // 渲染流程图（泳道图或旧版 Mermaid）
  r.flowcharts.forEach((f, i) => {
    const el = document.getElementById(`flow-${i}`);
    if (f.diagram_type === "swimlane" || (f.source && f.source.trim().startsWith("{"))) {
      try {
        const data = JSON.parse(f.source);
        renderSwimlane(el, data);
      } catch (e) {
        el.innerHTML = `<pre class="flow-raw">${esc(f.source)}</pre>`;
      }
    } else {
      renderMermaid(el, f.source);
    }
  });
}

function legend() {
  return `<div class="legend">R=负责 · A=批准/最终负责 · S=支持 · I=知情 · C=咨询</div>`;
}

function buildMatrix(items, title) {
  if (!items.length) return "";
  const activities = [];
  const roles = [];
  const cell = {};
  items.forEach(x => {
    if (!activities.includes(x.activity)) activities.push(x.activity);
    if (!roles.includes(x.role)) roles.push(x.role);
    cell[x.activity + "||" + x.role] = x.letter;
  });
  let h = `<div class="matrix-wrap"><div style="font-size:13px;color:#374151;margin:6px 0 4px">${title}</div>`;
  h += '<table class="matrix"><thead><tr><th>活动 / 步骤</th>';
  roles.forEach(r => { h += `<th>${esc(r)}</th>`; });
  h += "</tr></thead><tbody>";
  activities.forEach(a => {
    h += `<tr><td class="act">${esc(a)}</td>`;
    roles.forEach(r => {
      const l = cell[a + "||" + r] || "";
      h += `<td>${l ? `<span class="ramp ${l}">${l}</span>` : ""}</td>`;
    });
    h += "</tr>";
  });
  h += "</tbody></table></div>";
  return h;
}

function shortPos(pos, dept) {
  return (pos && dept && pos.startsWith(dept)) ? pos.slice(dept.length) : pos;
}

function buildPositionMatrix(items, title) {
  if (!items.length) return "";
  const activities = [];
  const roles = [];
  const cell = {};
  items.forEach(x => {
    if (!activities.includes(x.activity)) activities.push(x.activity);
    if (!roles.includes(x.role)) roles.push(x.role);
    cell[x.activity + "||" + x.role] = x.letter;
  });

  // 把岗位归入其所属部门（利用部门->岗位映射）
  const deptOf = {};
  const deptOrder = [];
  const deptRoles = {};
  roles.forEach(role => {
    let dept = null;
    for (const d in positionMap) {
      if (positionMap[d].includes(role)) { dept = d; break; }
    }
    if (!dept) dept = "(其他)";
    deptOf[role] = dept;
    if (!deptRoles[dept]) deptRoles[dept] = [];
    deptRoles[dept].push(role);
    if (!deptOrder.includes(dept)) deptOrder.push(dept);
  });

  let h = `<div class="matrix-wrap"><div style="font-size:13px;color:#374151;margin:6px 0 4px">${title}</div>`;
  h += '<table class="matrix"><thead>';
  h += '<tr><th rowspan="2">活动 / 步骤</th>';
  deptOrder.forEach(d => {
    h += `<th colspan="${deptRoles[d].length}">${esc(d)}</th>`;
  });
  h += "</tr><tr>";
  deptOrder.forEach(d => {
    deptRoles[d].forEach(r => { h += `<th>${esc(shortPos(r, d))}</th>`; });
  });
  h += "</tr></thead><tbody>";
  activities.forEach(a => {
    h += `<tr><td class="act">${esc(a)}</td>`;
    deptOrder.forEach(d => {
      deptRoles[d].forEach(r => {
        const l = cell[a + "||" + r] || "";
        h += `<td>${l ? `<span class="ramp ${l}">${l}</span>` : ""}</td>`;
      });
    });
    h += "</tr>";
  });
  h += "</tbody></table></div>";
  return h;
}

async function renderMermaid(el, source) {
  mermaid.initialize({ startOnLoad: false, theme: "default", flowchart: { curve: "basis" } });
  const id = "mmd-" + Math.random().toString(36).slice(2, 8);
  try {
    const { svg } = await mermaid.render(id, source);
    el.innerHTML = svg;
  } catch (e) {
    el.innerHTML = `<div style="color:#dc2626;font-size:12px;margin-bottom:6px">流程图渲染失败，显示原始代码：</div>
      <pre class="flow-raw">${esc(source)}</pre>`;
  }
}

// 泳道图配色：主色、浅色填充、深色文字（一一对应）
const LANE_COLORS = [
  { main: "#059669", light: "#ecfdf5", dark: "#065f46" },
  { main: "#d97706", light: "#fffbeb", dark: "#92400e" },
  { main: "#0891b2", light: "#ecfeff", dark: "#155e75" },
  { main: "#db2777", light: "#fdf2f8", dark: "#9d174d" },
  { main: "#7c3aed", light: "#f5f3ff", dark: "#5b21b6" },
  { main: "#dc2626", light: "#fef2f2", dark: "#991b1b" },
  { main: "#0d9488", light: "#f0fdfa", dark: "#115e59" },
  { main: "#be185d", light: "#fff1f2", dark: "#831843" },
];
const MAIN_COLOR = "#2563eb";

// 用 SVG 渲染泳道图
function renderSwimlane(el, data) {
  const title = data.title || "流程图";
  const mainDept = data.main_dept || "主责部门";
  const steps = data.main_steps || [];
  const collabs = data.collaborations || [];

  // 去重协作部门，保持出现顺序
  const laneDepts = [];
  collabs.forEach(c => { if (!laneDepts.includes(c.to_dept)) laneDepts.push(c.to_dept); });
  const colorMap = {};
  laneDepts.forEach((d, i) => { colorMap[d] = LANE_COLORS[i % LANE_COLORS.length]; });

  // 尺寸
  const LANE_LABEL_W = 160;
  const NODE_W = 132, NODE_H = 70, NODE_GAP = 40;
  const MAIN_LANE_H = 156;
  const SUB_LANE_H = 100;
  const TITLE_H = 88;
  const LEGEND_H = 80;

  const n = steps.length || 1;
  const svgW = Math.max(LANE_LABEL_W + n * NODE_W + (n + 1) * NODE_GAP, 900);
  const svgH = TITLE_H + MAIN_LANE_H + laneDepts.length * SUB_LANE_H + LEGEND_H;

  let s = `<svg viewBox="0 0 ${svgW} ${svgH}" width="100%" style="max-width:${svgW}px;display:block;margin:0 auto;border:1px solid #e2e8f0;border-radius:10px;background:#fff;box-sizing:border-box;">`;
  s += `<defs>
    <marker id="arrMain" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#64748b"/>
    </marker>
    <marker id="arrCoop" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#94a3b8"/>
    </marker>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#0f172a" flood-opacity="0.08"/>
    </filter>
  </defs>`;

  // 标题
  s += `<text x="${svgW/2}" y="42" text-anchor="middle" font-size="22" font-weight="700" fill="#0f172a">${esc(title)}</text>`;
  s += `<text x="${svgW/2}" y="66" text-anchor="middle" font-size="13" fill="#64748b">按部门划分泳道，主流程在${esc(mainDept)}泳道自左向右流转；虚线箭头表示跨部门协作对接</text>`;

  // 泳道背景
  let y = TITLE_H;
  // 主流程泳道
  s += `<rect x="0" y="${y}" width="${svgW}" height="${MAIN_LANE_H}" fill="#eff6ff"/>`;
  s += `<rect x="0" y="${y}" width="6" height="${MAIN_LANE_H}" fill="${MAIN_COLOR}"/>`;
  s += `<text x="${LANE_LABEL_W/2}" y="${y + 78}" text-anchor="middle" dominant-baseline="central" font-size="15" font-weight="700" fill="#0f172a">${esc(mainDept)}</text>`;
  s += `<text x="${LANE_LABEL_W/2}" y="${y + 106}" text-anchor="middle" dominant-baseline="central" font-size="11" fill="#94a3b8">主流程</text>`;
  const mainY = y;
  y += MAIN_LANE_H;

  // 协作部门泳道
  const laneY = {};
  laneDepts.forEach(dept => {
    const c = colorMap[dept];
    s += `<rect x="0" y="${y}" width="${svgW}" height="${SUB_LANE_H}" fill="#ffffff"/>`;
    s += `<rect x="0" y="${y}" width="6" height="${SUB_LANE_H}" fill="${c.main}"/>`;
    s += `<text x="${LANE_LABEL_W/2}" y="${y + SUB_LANE_H/2}" text-anchor="middle" dominant-baseline="central" font-size="15" font-weight="700" fill="${c.main}">${esc(dept)}</text>`;
    s += `<text x="${LANE_LABEL_W/2}" y="${y + SUB_LANE_H/2 + 28}" text-anchor="middle" dominant-baseline="central" font-size="11" fill="#94a3b8">协作部门</text>`;
    laneY[dept] = y;
    y += SUB_LANE_H;
  });

  // 分隔线
  s += `<line x1="0" y1="${TITLE_H}" x2="${svgW}" y2="${TITLE_H}" stroke="#cbd5e1" stroke-width="1"/>`;
  let ly = TITLE_H + MAIN_LANE_H;
  for (let i = 0; i < laneDepts.length; i++) {
    s += `<line x1="0" y1="${ly}" x2="${svgW}" y2="${ly}" stroke="#cbd5e1" stroke-width="1"/>`;
    ly += SUB_LANE_H;
  }
  s += `<line x1="${LANE_LABEL_W}" y1="${TITLE_H}" x2="${LANE_LABEL_W}" y2="${y}" stroke="#cbd5e1" stroke-width="1"/>`;

  // 主流程节点（带阴影）
  const nodeY = mainY + (MAIN_LANE_H - NODE_H) / 2;
  const centers = [];
  steps.forEach((st, i) => {
    const x = LANE_LABEL_W + NODE_GAP + i * (NODE_W + NODE_GAP);
    centers.push(x + NODE_W / 2);
    s += `<rect x="${x}" y="${nodeY}" width="${NODE_W}" height="${NODE_H}" rx="10" fill="#ffffff" stroke="${MAIN_COLOR}" stroke-width="1.5" filter="url(#shadow)"/>`;
    s += `<circle cx="${x + 16}" cy="${nodeY + 16}" r="11" fill="${MAIN_COLOR}"/>`;
    s += `<text x="${x + 16}" y="${nodeY + 16.5}" text-anchor="middle" dominant-baseline="central" font-size="11" font-weight="700" fill="#ffffff">${st.id}</text>`;
    s += `<text x="${x + NODE_W/2}" y="${nodeY + NODE_H/2 + 10}" text-anchor="middle" dominant-baseline="central" font-size="13" font-weight="600" fill="#1e293b">${esc(st.text)}</text>`;
  });

  // 主流程连线
  for (let i = 0; i < centers.length - 1; i++) {
    const x1 = centers[i] + NODE_W / 2;
    const x2 = centers[i + 1] - NODE_W / 2;
    s += `<line x1="${x1}" y1="${nodeY + NODE_H/2}" x2="${x2}" y2="${nodeY + NODE_H/2}" stroke="#64748b" stroke-width="1.5" marker-end="url(#arrMain)"/>`;
  }

  // 协作节点（浅色填充）+ 虚线连线
  const subNodeH = 56;
  collabs.forEach(c => {
    const dept = c.to_dept;
    const c2 = colorMap[dept];
    const stepIdx = steps.findIndex(st => st.id === c.from_step);
    if (stepIdx < 0) return;
    const cx = centers[stepIdx];
    const ly2 = laneY[dept];
    const subY = ly2 + (SUB_LANE_H - subNodeH) / 2;
    const subX = cx - NODE_W / 2;
    s += `<rect x="${subX}" y="${subY}" width="${NODE_W}" height="${subNodeH}" rx="10" fill="${c2.light}" stroke="${c2.main}" stroke-width="1.5"/>`;
    s += `<text x="${cx}" y="${subY + subNodeH/2}" text-anchor="middle" dominant-baseline="central" font-size="13" font-weight="600" fill="${c2.dark}">${esc(c.text)}</text>`;
    // 虚线：主节点底部 -> 协作节点顶部
    s += `<line x1="${cx}" y1="${nodeY + NODE_H}" x2="${cx}" y2="${subY}" stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="5,4" marker-end="url(#arrCoop)"/>`;
  });

  // 图例（动态文字：含部门名与步骤数）
  const legY = y + 30;
  const stepRange = n > 1 ? `步骤 1 → ${n}` : "步骤 1";
  s += `<line x1="${LANE_LABEL_W}" y1="${legY}" x2="${LANE_LABEL_W + 50}" y2="${legY}" stroke="#64748b" stroke-width="1.5" marker-end="url(#arrMain)"/>`;
  s += `<text x="${LANE_LABEL_W + 62}" y="${legY}" dominant-baseline="central" font-size="13" fill="#475569">${esc(mainDept)}内部流程流转（${stepRange}）</text>`;
  s += `<line x1="${LANE_LABEL_W + 320}" y1="${legY}" x2="${LANE_LABEL_W + 370}" y2="${legY}" stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="5,4" marker-end="url(#arrCoop)"/>`;
  s += `<text x="${LANE_LABEL_W + 382}" y="${legY}" dominant-baseline="central" font-size="13" fill="#475569">跨部门协作对接（${esc(mainDept)} → 协作部门）</text>`;

  // 底部说明
  s += `<text x="${svgW/2}" y="${svgH - 18}" text-anchor="middle" font-size="12" fill="#94a3b8">内容依据文件信息重构，仅表达流程结构与协作关系</text>`;

  s += "</svg>";
  el.innerHTML = s;
}

function parseList(v) {
  if (Array.isArray(v)) return v;
  if (!v) return [];
  try {
    const j = JSON.parse(v);
    return Array.isArray(j) ? j : [v];
  } catch (e) { return [v]; }
}

// ---------- 条目查询 ----------
function itemFilters() {
  const p = new URLSearchParams();
  const q = $("q").value.trim();
  const docId = $("f-doc").value;
  const docNo = $("f-docno").value.trim();
  const dept = $("f-dept").value;
  const type = $("f-type").value;
  const pos = $("f-pos").value.trim();
  if (q) p.set("q", q);
  if (docId) p.set("document_id", docId);
  if (docNo) p.set("doc_no", docNo);
  if (dept) p.set("department", dept);
  if (type) p.set("item_type", type);
  if (pos) p.set("position", pos);
  return p;
}

async function loadDocFilter() {
  const rows = await api("/api/documents");
  const sel = $("f-doc");
  const cur = sel.value;
  sel.innerHTML = '<option value="">全部文件</option>' +
    rows.map(d => `<option value="${d.id}">${esc(d.title || d.doc_no || ('#' + d.id))}</option>`).join("");
  sel.value = cur;
}

let _itemPage = 1;
let _itemPageSize = 20;

async function loadItems() {
  const p = itemFilters();
  p.set("limit", "500");
  const r = await api("/api/items?" + p.toString());
  const list = r.items || [];
  const total = list.length;
  $("items-total").textContent = `共 ${r.total || total} 条条目`;

  const totalPages = Math.max(1, Math.ceil(total / _itemPageSize));
  if (_itemPage > totalPages) _itemPage = totalPages;
  const start = (_itemPage - 1) * _itemPageSize;
  const pageList = list.slice(start, start + _itemPageSize);

  const tb = $("items-table");
  if (!total) {
    tb.innerHTML = '<tr><td colspan="11" style="color:#6b7280">暂无条目，请先到「新建 / 编辑文件」录入并保存文件</td></tr>';
  } else {
    tb.innerHTML = pageList.map(it => {
      const fk = (it.frequency || []).concat(it.keywords || []).join("、");
      return `<tr data-id="${it.id}">
        <td><input type="checkbox" class="item-check" value="${it.id}" /></td>
        <td data-field="doc_no">${esc(it.doc_no || "")}</td>
        <td data-field="title">${esc(it.title || "")}</td>
        <td data-field="section">${esc(it.section || "")}</td>
        <td data-field="seq">${esc(it.seq || "")}</td>
        <td class="editable" data-field="item_type" data-type="select-type"><span class="type-tag">${esc(it.item_type || "")}</span></td>
        <td class="item-content" data-field="content">${esc(it.content || "")}</td>
        <td class="editable" data-field="department" data-type="select-dept">${esc(it.cur_dept || "")}</td>
        <td class="editable" data-field="main_position" data-type="select-pos">${esc(it.main_position || "")}</td>
        <td data-field="person_in_charge">${esc(it.person_in_charge || "")}</td>
        <td class="editable" data-field="freq_kw" data-type="text">${esc(fk)}</td>
      </tr>`;
    }).join("");
  }
  const ca = $("items-checkall");
  if (ca) ca.checked = false;
  renderItemStats(r.facets || {});
  renderItemsPagination(total, totalPages, total ? start + 1 : 0, Math.min(start + _itemPageSize, total));
}

function renderItemsPagination(total, totalPages, from, to) {
  const bar = $("items-pagination");
  if (!bar) return;
  if (!total) { bar.innerHTML = ""; return; }
  let pages = [];
  const cur = _itemPage;
  for (let i = 1; i <= totalPages; i++) {
    if (i === 1 || i === totalPages || Math.abs(i - cur) <= 2) pages.push(i);
    else if (pages[pages.length - 1] !== "...") pages.push("...");
  }
  bar.innerHTML = `
    <span class="page-info">共 ${total} 条，第 ${from}-${to} 条</span>
    <select id="items-page-size" class="page-size">
      <option value="20" ${_itemPageSize===20?"selected":""}>20 条/页</option>
      <option value="50" ${_itemPageSize===50?"selected":""}>50 条/页</option>
      <option value="100" ${_itemPageSize===100?"selected":""}>100 条/页</option>
      <option value="200" ${_itemPageSize===200?"selected":""}>200 条/页</option>
    </select>
    <button class="page-btn" ${cur<=1?"disabled":""} data-ipage="${cur-1}">上一页</button>
    ${pages.map(p => p === "..."
      ? `<span class="page-ellipsis">…</span>`
      : `<button class="page-btn ${p===cur?"active":""}" data-ipage="${p}">${p}</button>`
    ).join("")}
    <button class="page-btn" ${cur>=totalPages?"disabled":""} data-ipage="${cur+1}">下一页</button>
  `;
  bar.querySelectorAll(".page-btn[data-ipage]").forEach(b => {
    b.onclick = () => { _itemPage = Number(b.dataset.ipage); loadItems(); };
  });
  const ps = bar.querySelector("#items-page-size");
  if (ps) ps.onchange = () => { _itemPageSize = Number(ps.value); _itemPage = 1; loadItems(); };
}

const ITEM_TYPES = ["工作步骤", "职责", "审批/权限", "注意事项", "时限要求", "表单/记录", "其他/规定"];

function buildSelect(options, current) {
  const opts = ['<option value="">（留空）</option>']
    .concat(options.map(o => `<option value="${esc(o)}"${o === current ? " selected" : ""}>${esc(o)}</option>`));
  return `<select class="cell-edit">${opts.join("")}</select>`;
}

function positionsForDept(dept) {
  return (itemMeta.position_map && itemMeta.position_map[dept]) ? itemMeta.position_map[dept] : itemMeta.positions;
}

async function startCellEdit(td) {
  if (td.querySelector(".cell-edit")) return;
  const field = td.dataset.field;
  const type = td.dataset.type;
  const id = Number(td.parentElement.dataset.id);
  const raw = td.textContent.trim();

  let input;
  if (type === "select-docno") {
    input = buildSelect(itemMeta.existing_doc_nos, raw);
  } else if (type === "select-title") {
    input = buildSelect(itemMeta.existing_names, raw);
  } else if (type === "select-dept") {
    input = buildSelect(itemMeta.departments, raw);
  } else if (type === "select-pos") {
    const deptTd = td.parentElement.querySelector('[data-field="department"]');
    const dept = deptTd ? deptTd.textContent.trim() : "";
    input = buildSelect(positionsForDept(dept), raw);
  } else if (type === "select-type") {
    input = buildSelect(ITEM_TYPES, raw);
  } else if (type === "textarea") {
    input = `<textarea class="cell-edit" rows="3">${esc(raw)}</textarea>`;
  } else {
    input = `<input class="cell-edit" type="text" value="${esc(raw)}" />`;
  }
  td.innerHTML = input;
  const el = td.querySelector(".cell-edit");
  el.focus();
  if (el.select) el.select();

  const finish = async (commit) => {
    if (!commit) { td.textContent = raw; return; }
    const newVal = el.tagName === "SELECT" ? el.value : el.value;
    if (newVal === raw) { td.textContent = raw; return; }
    const payload = {};
    if (field === "freq_kw") {
      const parts = newVal.split(/[、,，]/).map(s => s.trim()).filter(Boolean);
      payload.keywords = parts;
      payload.frequency = [];
    } else {
      payload[field] = newVal;
    }
    try {
      await api(`/api/items/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (field === "item_type") {
        td.innerHTML = `<span class="type-tag">${esc(newVal)}</span>`;
      } else {
        td.textContent = newVal;
      }
    } catch (e) {
      alert("保存失败：" + e.message);
      td.textContent = raw;
    }
  };

  el.addEventListener("blur", () => finish(true));
  if (el.tagName === "SELECT") {
    el.addEventListener("change", () => el.blur());
  } else {
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && type !== "textarea") { e.preventDefault(); el.blur(); }
      if (e.key === "Escape") { finish(false); }
    });
  }
}

function initItemTableInteractions() {
  const tbl = $("items-tbl");
  if (!tbl || tbl.dataset.bound) return;
  tbl.dataset.bound = "1";
  tbl.addEventListener("click", (e) => {
    const td = e.target.closest("td.editable");
    if (td && !e.target.closest(".cell-edit") && !e.target.closest(".item-check")) startCellEdit(td);
  });

  const ths = tbl.querySelectorAll("thead th");
  ths.forEach((th) => {
    const handle = document.createElement("div");
    handle.className = "col-resizer";
    th.appendChild(handle);
    handle.addEventListener("mousedown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const idx = Array.from(th.parentNode.children).indexOf(th);
      const col = tbl.querySelectorAll("colgroup col")[idx];
      if (!col) return;
      const startX = e.pageX;
      const startW = th.offsetWidth;
      const onMove = (ev) => {
        const w = Math.max(40, startW + (ev.pageX - startX));
        col.style.width = w + "px";
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  });
}

function renderItemStats(f) {
  const group = (obj, label) => {
    const chips = Object.entries(obj || {}).slice(0, 10)
      .map(([k, v]) => `<span class="stat-chip">${esc(k)}<i>${v}</i></span>`).join("");
    return `<div class="stat-group"><b>${label}</b><div>${chips || '<span class="hint">无</span>'}</div></div>`;
  };
  $("items-stats").innerHTML =
    group(f.types, "条款类型分布") + group(f.departments, "部门") + group(f.positions, "主责岗位");
}

async function deleteItems() {
  const checked = Array.from(document.querySelectorAll(".item-check:checked"))
    .map(c => Number(c.value));
  if (!checked.length) {
    alert("请先勾选要删除的条目");
    return;
  }
  if (!confirm(`确定删除选中的 ${checked.length} 条条目吗？此操作不可撤销。`)) return;
  try {
    await api("/api/items/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: checked }),
    });
    await loadItems();
  } catch (e) {
    alert("删除失败：" + e.message);
  }
}

function exportItems() {
  window.location.href = "/api/items/export?" + itemFilters().toString();
}

// ==================== 员工工作全景 ====================
let empAll = [];      // 全部员工列表
let empCurrent = "";  // 当前选中的员工
let empCurrentView = "guest_trip";  // 当前视角
let empPanorama = {}; // 已加载的全景数据 {view_type: {narrative, cards, ...}}

async function loadEmployees() {
  try {
    const data = await api("/api/employees");
    empAll = data.employees || [];
    const dl = $("emp-list");
    dl.innerHTML = empAll.map(e =>
      `<option value="${esc(e.name)}">${esc(e.name)}（${e.file_count}份文件）</option>`
    ).join("");
  } catch (e) {
    setMsg("emp-msg", "加载员工列表失败：" + e.message, false);
  }
}

function renderNarrative(nar) {
  // 兼容旧数据：字符串当 overview
  if (typeof nar === "string") nar = { overview: nar };
  const ov = nar.overview || "";
  const ic = nar.internal_collab || "";
  const cc = nar.cross_dept_collab || "";
  const rp = Array.isArray(nar.risk_points) ? nar.risk_points : [];
  const parts = [];
  if (ov) parts.push(`<div class="narr-block narr-overview"><div class="narr-label">工作概述</div><div class="narr-text">${esc(ov)}</div></div>`);
  if (ic) parts.push(`<div class="narr-block narr-internal"><div class="narr-label">本部门内部协作</div><div class="narr-text">${esc(ic)}</div></div>`);
  if (cc) parts.push(`<div class="narr-block narr-cross"><div class="narr-label">跨部门协作</div><div class="narr-text">${esc(cc)}</div></div>`);
  if (rp.length) {
    const items = rp.map(p => `<li>${esc(p)}</li>`).join("");
    parts.push(`<div class="narr-block narr-risk"><div class="narr-label">风险点提示</div><ul class="narr-risk-list">${items}</ul></div>`);
  }
  return parts.join("") || '<div class="narr-block"><div class="narr-text" style="color:#94a3b8">暂无叙述内容</div></div>';
}

async function loadEmployeePanorama() {
  const name = $("emp-search").value.trim();
  if (!name) { setMsg("emp-msg", "请先选择或输入员工姓名", false); return; }
  empCurrent = name;
  setMsg("emp-msg", `正在加载「${name}」的全景数据…`, true);
  try {
    const data = await api(`/api/employees/${encodeURIComponent(name)}/panorama`);
    empPanorama = data.views || {};
    $("emp-result").style.display = "block";
    renderEmpView(empCurrentView);
    setMsg("emp-msg", "", true);
  } catch (e) {
    if (e.message.includes("404")) {
      setMsg("emp-msg", `未找到「${name}」的全景数据，请点击「生成」`, false);
      $("emp-result").style.display = "block";
      $("emp-narrative").style.display = "none";
      $("emp-cards").innerHTML = "";
    } else {
      setMsg("emp-msg", "加载失败：" + e.message, false);
    }
  }
}

function renderEmpView(view) {
  empCurrentView = view;
  document.querySelectorAll(".sub-tab").forEach(t => {
    t.classList.toggle("active", t.dataset.view === view);
  });
  const narr = $("emp-narrative");
  const cards = $("emp-cards");
  const updated = $("emp-updated");
  const genBtn = $("btn-emp-generate");

  // 协作关系视图：不需要生成按钮，展示图谱+列表
  if (view === "collab") {
    narr.style.display = "none";
    genBtn.style.display = "none";
    cards.innerHTML = "";
    updated.textContent = "";
    renderCollaboration();
    return;
  }
  genBtn.style.display = "";

  const v = empPanorama[view];
  if (v && v.narrative) {
    narr.style.display = "block";
    narr.innerHTML = renderNarrative(v.narrative);
    updated.textContent = v.updated_at ? `最后更新：${v.updated_at}` : "";
  } else {
    narr.style.display = "none";
    updated.textContent = "该视角尚未生成";
  }
  cards.innerHTML = "";
  if (v && v.cards && v.cards.length) {
    // 按 group 分组
    const groups = {};
    for (const c of v.cards) {
      const g = c.group || "其他";
      if (!groups[g]) groups[g] = [];
      groups[g].push(c);
    }
    // 统计概览
    const total = v.cards.length;
    const groupCount = Object.keys(groups).length;
    const overview = document.createElement("div");
    overview.className = "pano-overview";
    overview.innerHTML = `<span>共 <b>${groupCount}</b> 个分组、<b>${total}</b> 份文件</span>`;
    cards.appendChild(overview);

    let gi = 0;
    for (const [g, list] of Object.entries(groups)) {
      const gid = "grp-" + view + "-" + gi;
      gi++;
      const div = document.createElement("div");
      div.className = "pano-group";
      div.innerHTML = `
        <div class="pano-group-head" data-gid="${gid}">
          <span class="pano-group-arrow">▶</span>
          <span class="pano-group-title-text">${esc(g)}</span>
          <span class="pano-group-count">${list.length} 份</span>
        </div>
        <div class="pano-group-body" id="${gid}" style="display:none">
          <div class="pano-chips">
            ${list.map((c, i) => `
              <span class="pano-chip" data-gid="${gid}" data-idx="${i}">
                <span class="pano-chip-no">${esc(c.doc_no || "")}</span>
                <span class="pano-chip-name">${esc(c.title || "")}</span>
              </span>
            `).join("")}
          </div>
          <div class="pano-card-detail" id="${gid}-detail"></div>
        </div>
      `;
      cards.appendChild(div);
    }

    // 折叠/展开分组
    cards.querySelectorAll(".pano-group-head").forEach(h => {
      h.onclick = () => {
        const gid = h.dataset.gid;
        const body = document.getElementById(gid);
        const arrow = h.querySelector(".pano-group-arrow");
        const open = body.style.display !== "none";
        body.style.display = open ? "none" : "block";
        arrow.textContent = open ? "▶" : "▼";
      };
    });
    // chip 点击展开详情
    cards.querySelectorAll(".pano-chip").forEach(chip => {
      chip.onclick = () => {
        const gid = chip.dataset.gid;
        const idx = parseInt(chip.dataset.idx);
        const gName = chip.closest(".pano-group").querySelector(".pano-group-title-text").textContent;
        const c = groups[gName][idx];
        const detail = document.getElementById(gid + "-detail");
        // 切换：再次点击同一 chip 则关闭
        if (detail.dataset.activeIdx == idx) {
          detail.innerHTML = "";
          detail.dataset.activeIdx = "";
          chip.classList.remove("active");
          return;
        }
        detail.dataset.activeIdx = idx;
        cards.querySelectorAll(".pano-chip").forEach(c2 => c2.classList.remove("active"));
        chip.classList.add("active");
        detail.innerHTML = `
          <div class="pano-card">
            <div class="pano-card-head">
              <span class="pano-card-title">${esc(c.title || "")}</span>
              <span class="pano-card-docno">${esc(c.doc_no || "")}</span>
            </div>
            ${c.summary ? `<div class="pano-card-summary">${esc(c.summary)}</div>` : ""}
            ${c.key_points && c.key_points.length ?
              `<ul class="pano-card-points">${c.key_points.map(k => `<li>${esc(k)}</li>`).join("")}</ul>` : ""}
          </div>
        `;
      };
    });
  } else if (v) {
    cards.innerHTML = '<div class="hint" style="color:#94a3b8">该视角暂无结构化卡片</div>';
  }
}

async function generateEmpPanorama() {
  if (!empCurrent) { setMsg("emp-msg", "请先选择员工并加载", false); return; }
  const btn = $("btn-emp-generate");
  btn.disabled = true;
  btn.textContent = "生成中…";
  setMsg("emp-msg", `正在生成「${empCurrent}」的${viewLabel(empCurrentView)}全景，请稍候…`, true);
  try {
    const data = await api(
      `/api/employees/${encodeURIComponent(empCurrent)}/panorama?view_type=${empCurrentView}`,
      { method: "POST" }
    );
    empPanorama[empCurrentView] = {
      narrative: data.narrative,
      cards: data.cards,
      source_doc_nos: data.source_doc_nos,
      updated_at: new Date().toLocaleString("zh-CN"),
    };
    renderEmpView(empCurrentView);
    setMsg("emp-msg", "生成成功并已保存", true);
  } catch (e) {
    setMsg("emp-msg", "生成失败：" + e.message, false);
  } finally {
    btn.disabled = false;
    btn.textContent = "生成 / 刷新该视角全景";
  }
}

function viewLabel(v) {
  return { guest_trip: "宾客旅程", compliance: "合规项", internal: "内部管理" }[v] || v;
}

// 表格列宽拖拽
function initColResize(tableId) {
  const table = document.getElementById(tableId);
  if (!table) return;
  const cols = table.querySelectorAll("colgroup col");
  const resizers = table.querySelectorAll(".col-resizer");
  resizers.forEach((resizer, idx) => {
    let startX = 0, startW = 0, col = cols[idx];
    resizer.addEventListener("mousedown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      startX = e.clientX;
      startW = col.offsetWidth;
      const onMove = (ev) => {
        const w = Math.max(60, startW + (ev.clientX - startX));
        col.style.width = w + "px";
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  });
}

// ==================== 员工协作关系图谱 ====================
let collabChart = null;

async function renderCollaboration() {
  if (!empCurrent) return;
  const cards = $("emp-cards");
  cards.innerHTML = `<div class="hint" style="color:#94a3b8">正在分析「${empCurrent}」的协作关系…</div>`;
  try {
    const data = await api(`/api/employees/${encodeURIComponent(empCurrent)}/collaborations`);
    const { center, nodes, edges, collaborators } = data;

    cards.innerHTML = "";

    // --- 图谱区域 ---
    const chartWrap = document.createElement("div");
    chartWrap.className = "collab-section";
    chartWrap.innerHTML = `
      <div class="collab-chart-title">协作关系图谱（绿线=同部门·橙线=跨部门业务衔接·灰线=共同负责文件；粗细=交集强度）</div>
      <div id="collab-chart" style="width:100%;height:420px"></div>
    `;
    cards.appendChild(chartWrap);

    // ECharts 力导向图
    const chartDom = document.getElementById("collab-chart");
    if (collabChart) collabChart.dispose();
    collabChart = echarts.init(chartDom);
    const maxWeight = Math.max(...edges.map(e => e.weight), 1);
    const option = {
      tooltip: {
        formatter: (p) => {
          if (p.dataType === "edge") {
            const e = p.data;
            const typeLabel = e.type === "same_dept" ? "同部门协作" : e.type === "cross_dept" ? "跨部门业务衔接" : "共同负责文件";
            let html = `<b>${e.source}</b> ↔ <b>${e.target}</b><br/>类型：${typeLabel} | 交集强度：${e.weight}`;
            if (e.shared_files && e.shared_files.length) {
              html += `<br/><b>共同文件：</b><br/>` + e.shared_files.map(f => `· ${f.doc_no} ${f.name}`).join("<br/>");
            }
            if (e.cross_items && e.cross_items.length) {
              html += `<br/><b>跨部门业务衔接：</b><br/>` + e.cross_items.slice(0, 8).map(it => `· [${it.doc_no}] ${it.section}: ${it.content}`).join("<br/>");
            }
            return html;
          }
          const d = p.data;
          const pc = d.person_count > 1 ? `（${d.person_count}人）` : "";
          return `<b>${d.name}</b>${pc}<br/>部门：${d.dept || "-"}<br/>交集强度：${d.file_count}`;
        },
      },
      series: [{
        type: "graph",
        layout: "force",
        roam: true,
        draggable: true,
        label: { show: true, position: "right", fontSize: 12 },
        force: { repulsion: 400, edgeLength: [80, 160], gravity: 0.1 },
        lineStyle: { curveness: 0.1 },
        data: nodes.map(n => ({
          name: n.name,
          dept: n.dept || "",
          file_count: n.file_count,
          person_count: n.person_count || 1,
          symbolSize: n.is_center ? 60 : 30 + Math.min(n.file_count * 3, 30) + ((n.person_count || 1) > 1 ? 15 : 0),
          itemStyle: { color: n.is_center ? "#2563eb" : (n.dept === center.dept ? "#059669" : "#f59e0b") },
        })),
        links: edges.map(e => ({
          source: e.source,
          target: e.target,
          weight: e.weight,
          type: e.type,
          shared_files: e.shared_files,
          cross_items: e.cross_items,
          lineStyle: {
            width: 1 + (e.weight / maxWeight) * 6,
            color: e.type === "same_dept" ? "#059669" : e.type === "cross_dept" ? "#f59e0b" : "#94a3b8",
          },
        })),
      }],
    };
    collabChart.setOption(option);

    // --- 协作列表 ---
    const listWrap = document.createElement("div");
    listWrap.className = "collab-section";
    const sameDeptCount = collaborators.filter(c => c.same_dept).length;
    const crossCount = collaborators.filter(c => c.has_cross_dept).length;
    const hasData = collaborators.length > 0;
    listWrap.innerHTML = `
      <div class="collab-chart-title">协作列表（共 ${collaborators.length} 人 · 同部门 ${sameDeptCount} 人 · 跨部门衔接 ${crossCount} 人）</div>
      <div class="collab-table-wrap">
        <table class="collab-table" id="collab-table">
          <colgroup>
            <col style="width:170px">
            <col style="width:110px">
            <col style="width:90px">
            <col>
          </colgroup>
          <thead>
            <tr>
              <th data-col="0">协作员工<span class="col-resizer"></span></th>
              <th data-col="1">部门<span class="col-resizer"></span></th>
              <th data-col="2">交集强度<span class="col-resizer"></span></th>
              <th data-col="3">协作内容<span class="col-resizer"></span></th>
            </tr>
          </thead>
          <tbody>
            ${hasData ? collaborators.map((c, i) => {
              const tags = [];
              if (c.same_dept) tags.push('<span class="tag tag-green">同部门</span>');
              if (c.has_cross_dept) tags.push('<span class="tag tag-orange">跨部门</span>');
              const hintParts = [];
              if (c.shared_file_count) hintParts.push(`${c.shared_file_count} 份共同文件`);
              if (c.cross_dept_count) hintParts.push(`${c.cross_dept_count} 条跨部门衔接`);
              return `
              <tr class="collab-row-head" data-idx="${i}">
                <td>
                  <span class="row-arrow">▶</span>
                  <b>${esc(c.names.join("、"))}</b>${c.names.length > 1 ? ` <span class="tag tag-blue">${c.names.length}人</span>` : ""}${tags.join("")}
                </td>
                <td>${esc(c.dept || "-")}</td>
                <td><b style="color:#2563eb">${c.shared_count}</b></td>
                <td class="collab-files-cell">
                  <span class="collab-fold-hint">点击展开查看 ${hintParts.join("、")}</span>
                </td>
              </tr>
              <tr class="collab-row-detail" id="collab-detail-${i}" style="display:none">
                <td colspan="4" style="padding:10px 14px 14px 36px;background:#fafbfc">
                  ${c.shared_files.length ? `
                    <div class="collab-detail-section">
                      <div class="collab-detail-label">共同负责文件（${c.shared_files.length}）</div>
                      <div>${c.shared_files.map(f => `<span class="pano-chip" style="margin:2px 4px 2px 0">
                        <span class="pano-chip-no">${esc(f.doc_no)}</span>
                        <span class="pano-chip-name">${esc(f.name)}</span>
                      </span>`).join("")}</div>
                    </div>
                  ` : ""}
                  ${c.cross_items && c.cross_items.length ? `
                    <div class="collab-detail-section">
                      <div class="collab-detail-label">跨部门业务衔接（${c.cross_items.length} 条）</div>
                      <ul class="collab-cross-list">
                        ${c.cross_items.map(it => `<li><b>[${esc(it.doc_no)}]</b> ${esc(it.section)}：${esc(it.content)}</li>`).join("")}
                      </ul>
                    </div>
                  ` : ""}
                </td>
              </tr>
            `;
            }).join("") : `<tr><td colspan="4" style="text-align:center;color:#94a3b8;padding:20px">暂无协作关系</td></tr>`}
          </tbody>
        </table>
      </div>
    `;
    cards.appendChild(listWrap);

    // 行折叠/展开
    listWrap.querySelectorAll(".collab-row-head").forEach(row => {
      row.onclick = () => {
        const idx = row.dataset.idx;
        const detail = document.getElementById("collab-detail-" + idx);
        const arrow = row.querySelector(".row-arrow");
        const open = detail.style.display !== "none";
        detail.style.display = open ? "none" : "table-row";
        arrow.textContent = open ? "▶" : "▼";
      };
    });

    // 列宽拖拽
    initColResize("collab-table");

    setMsg("emp-msg", "", true);
  } catch (e) {
    cards.innerHTML = `<div class="hint" style="color:#dc2626">加载协作关系失败：${esc(e.message)}</div>`;
  }
}

// ---------- 事件绑定 ----------
document.addEventListener("DOMContentLoaded", () => {
  loadSettings();
  loadMeta();
  loadDocuments();

  document.querySelectorAll(".tab").forEach(t =>
    t.onclick = () => showTab(t.dataset.tab));

  $("btn-save-settings").onclick = saveSettings;
  $("btn-reimport").onclick = reimport;
  $("btn-save").onclick = saveDoc;
  $("btn-reset").onclick = resetDoc;
  $("doc-type").onchange = toggleDocType;
  $("btn-parse-word").onclick = parseWord;
  $("btn-generate").onclick = generate;
  $("btn-back").onclick = () => showTab("list");
  $("btn-search").onclick = () => { _itemPage = 1; loadItems(); };
  $("btn-export").onclick = exportItems;
  $("btn-delete-items").onclick = deleteItems;
  $("items-checkall").onclick = (e) => {
    document.querySelectorAll(".item-check").forEach(c => c.checked = e.target.checked);
  };
  initItemTableInteractions();

  // 员工全景
  $("btn-emp-load").onclick = loadEmployeePanorama;
  $("btn-emp-generate").onclick = generateEmpPanorama;
  document.querySelectorAll(".sub-tab").forEach(t =>
    t.onclick = () => renderEmpView(t.dataset.view));
});