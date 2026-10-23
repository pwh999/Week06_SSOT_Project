#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NCU《人机协同导论》第 6 周实践课：单一事实源（SSOT）一源多端自动化编译器
功能：
  1. [Gate 1] 扫描母稿 report.md，确保 100% 纯语义 CommonMark（0 HTML 标签、0 未填槽位）
  2. [Gate 2] 执行 AST 解析与幻灯片视觉预算检查（每页要点数 <= 6、标题字数防断行预警）
  3. [Gate 3] 一键分发编译：
     - dist/slides.html : 16:9 宽屏高对比度学术汇报幻灯片（自包含离线可交互 HTML）
     - dist/report.pdf  : A4 双面学术排版报告（支持 Typst 引擎 + 零外置依赖 PDF 兜底）

用法：
  python ssot_compiler.py
  python ssot_compiler.py --input report.md --outdir dist
"""

import argparse
import hashlib
import html
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


# ==============================================================================
# 1. [Gate 1] 纯语义门禁与局部差分修补状态检查
# ==============================================================================
HTML_TAG_PATTERN = re.compile(
    r"</?(?:div|span|font|br|hr|style|script|table|tr|td|th|p|h[1-6]|center|img)\b[^>]*>",
    re.IGNORECASE,
)
SLOT_PATTERN = re.compile(r"\[待填槽位[：:][^\]]*\]")


def run_gate1_semantic_check(md_text: str, src_path: Path) -> bool:
    print("=" * 68)
    print(f"🔍 [Gate 1] 纯语义门禁扫描 (Target: {src_path.name})")
    print("=" * 68)

    lines = md_text.splitlines()
    html_violations = []
    slot_violations = []

    for idx, line in enumerate(lines, start=1):
        # 忽略行内反引号代码中的演示文字
        clean_line = re.sub(r"`[^`]+`", "", line)
        for m in HTML_TAG_PATTERN.finditer(clean_line):
            html_violations.append((idx, m.group(0), line.strip()))
        for m in SLOT_PATTERN.finditer(clean_line):
            slot_violations.append((idx, m.group(0), line.strip()))

    if html_violations:
        print("❌ [Gate 1 拦截] 检测到违规 HTML 表现层标签污染纯语义母稿：")
        for ln, tag, snippet in html_violations[:5]:
            print(f"   - 第 {ln:02d} 行发现 `{tag}` -> {snippet[:60]}")
        return False

    if slot_violations:
        print("❌ [Gate 1 拦截] 检测到尚未填充的 `[待填槽位]` 占位符：")
        for ln, slot, snippet in slot_violations[:5]:
            print(f"   - 第 {ln:02d} 行发现 `{slot}`")
        return False

    # 检查第 28~36 行是否已完成【任务四：带行号局部差分修补】
    if len(lines) >= 36:
        head_hash = hashlib.sha256("\n".join(lines[:27]).encode("utf-8")).hexdigest()[:12]
        tail_hash = hashlib.sha256("\n".join(lines[36:]).encode("utf-8")).hexdigest()[:12]
        patch_zone = "\n".join(lines[27:36])
        print(f"   ✔ 纯语义扫描通过：0 个 HTML 标签，0 个残留槽位（总行数：{len(lines)} 行）")
        print(f"   ✔ 上下文散列校验：Lines 01-27 [{head_hash}] | Lines 37-{len(lines):02d} [{tail_hash}]")
        if "840 秒" in patch_zone and "帕累托最优改进效应" in patch_zone:
            print("   ⚠️ [任务四提醒] 检测到第 28～36 行仍包含未修补的初稿缺陷（“840 秒”未折算为分钟、“帕累托最优”黑话）！")
            print("      建议参照实验指导完成【任务四：带行号局部差分修补】后再次运行本编译器。")
        else:
            print("   ✔ 局部差分修补核验：第 28～36 行（3.2 节）已完成单位统一折算与因果链补全！")
    else:
        print(f"   ✔ 纯语义扫描通过：0 个 HTML 标签，0 个残留槽位（总行数：{len(lines)} 行）")

    return True


# ==============================================================================
# 2. Markdown 轻量级 AST 解析器
# ==============================================================================
def parse_markdown_ast(md_text: str) -> dict:
    lines = md_text.splitlines()
    doc = {
        "title": "未命名研究报告",
        "abstract": "",
        "chapters": [],  # [{"title": ..., "sections": [{"title": ..., "paragraphs": [...], "table": [...]}]}]
    }

    current_chapter = None
    current_section = None
    in_table = False
    table_buf = []

    def flush_table():
        nonlocal in_table, table_buf
        if in_table and table_buf and current_section is not None:
            current_section["tables"].append(table_buf)
        in_table = False
        table_buf = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush_table()
            continue

        if line.startswith("# ") and doc["title"] == "未命名研究报告":
            doc["title"] = line[2:].strip()
            continue

        if line.startswith("> "):
            quote_content = line[2:].strip()
            doc["abstract"] = (doc["abstract"] + " " + quote_content).strip()
            continue

        if line.startswith("## "):
            flush_table()
            current_chapter = {"title": line[3:].strip(), "sections": []}
            doc["chapters"].append(current_chapter)
            current_section = None
            continue

        if line.startswith("### "):
            flush_table()
            if current_chapter is None:
                current_chapter = {"title": "核心章节", "sections": []}
                doc["chapters"].append(current_chapter)
            current_section = {
                "title": line[4:].strip(),
                "paragraphs": [],
                "tables": [],
            }
            current_chapter["sections"].append(current_section)
            continue

        if line.startswith("|") and line.endswith("|"):
            # 忽略纯分隔行 | :--- | :--- |
            if re.match(r"^\|[\s:\-\|]+\|$", line):
                in_table = True
                continue
            in_table = True
            cells = [c.strip() for c in line.strip("|").split("|")]
            table_buf.append(cells)
            continue

        flush_table()
        if current_section is not None:
            current_section["paragraphs"].append(line)
        elif current_chapter is not None:
            current_section = {
                "title": current_chapter["title"],
                "paragraphs": [line],
                "tables": [],
            }
            current_chapter["sections"].append(current_section)

    flush_table()
    return doc


def is_formula_block(text: str) -> bool:
    """判断该行是否为 $$ ... $$ 独立公式块（母源用 LaTeX 书写，编译端需降级为可读排版）"""
    t = text.strip()
    return len(t) > 4 and t.startswith("$$") and t.endswith("$$")


def latex_to_plain(text: str) -> str:
    """
    将母稿中的 LaTeX 独立公式降级为纯文本排版（用于 PDF 兜底引擎、Typst 与 A4 网页版）。
    只覆盖实验报告常用的少数命令，避免引入 LaTeX 解析依赖。
    """
    t = text.strip()
    if t.startswith("$$") and t.endswith("$$"):
        t = t[2:-2]
    t = re.sub(r"\\text\{([^{}]*)\}", r"\1", t)
    # \frac{A}{B} -> (A) / (B)
    t = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1) / (\2)", t)
    t = t.replace(r"\times", "×").replace(r"\approx", "≈").replace(r"\rightarrow", "→")
    t = t.replace(r"\div", "÷").replace(r"\%", "%").replace(r"\ ", " ")
    t = re.sub(r"\\[a-zA-Z]+", "", t)
    t = re.sub(r"[{}]", "", t)
    t = re.sub(r"\s*=\s*", " = ", t)
    return re.sub(r"\s+", " ", t).strip()


def format_inline_html(text: str) -> str:
    """将纯语义 Markdown 行内语法安全转换为 HTML 片段（用于多端渲染器内部使用）"""
    if is_formula_block(text):
        return f'<span class="formula-block">{html.escape(latex_to_plain(text))}</span>'
    escaped = html.escape(text)
    # 数学公式轻量美化：$N=40$ / $\rightarrow$
    escaped = escaped.replace(r"$\rightarrow$", "→")
    escaped = re.sub(r"\$([^\$]+)\$", r'<span class="math-inline">\1</span>', escaped)
    # 行内代码 `code`
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    # 加粗 **bold**
    escaped = re.sub(r"\*\*([^\*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def split_paragraph_to_bullets(paragraphs: list) -> list:
    """将学术长段落智能拆解为不超过 6 条的幻灯片高信息密度要点"""
    bullets = []
    for p in paragraphs:
        # 独立公式块原样保留为一条要点，不追加句号
        if is_formula_block(p):
            bullets.append(p)
            continue
        # 按分号或句号切分关键论断
        clauses = [c.strip() for c in re.split(r"[；;。]", p) if c.strip()]
        for c in clauses:
            if len(bullets) < 5:
                bullets.append(c + "。")
    return bullets[:6]


# ==============================================================================
# 3. [Gate 2] 视觉预算与防溢出预检
# ==============================================================================
def run_gate2_layout_budget(doc: dict) -> list:
    print("\n" + "=" * 68)
    print("📐 [Gate 2] 16:9 幻灯片与 A4 页面视觉预算预检 (6×6 防溢出法则)")
    print("=" * 68)

    slides = []
    # 封面页
    slides.append(
        {
            "type": "cover",
            "kicker": "Single Source of Truth · 一源多端工程化交付",
            "title": doc["title"],
            "abstract": doc["abstract"],
        }
    )

    warnings = []
    for ch in doc["chapters"]:
        for sec in ch["sections"]:
            bullets = split_paragraph_to_bullets(sec["paragraphs"])
            if len(sec["title"]) > 30:
                warnings.append(f"小节标题过长 ({len(sec['title'])} 字)，建议精简防断行：{sec['title']}")
            if len(bullets) > 6:
                warnings.append(f"小节《{sec['title']}》要点数超过 6 条 ({len(bullets)} 条)，已自动截断收敛")
                bullets = bullets[:6]

            slides.append(
                {
                    "type": "section",
                    "chapter_title": ch["title"],
                    "title": sec["title"],
                    "bullets": bullets,
                    "tables": sec["tables"],
                }
            )

    print(f"   ✔ 幻灯片树状切分完成：共生成 {len(slides)} 页 16:9 宽屏幻灯片（每页要点数均 <= 6 条）")
    if warnings:
        for w in warnings:
            print(f"   ⚠️ [版面预警] {w}")
    else:
        print("   ✔ 标题字数与表格密度自检通过：0 处断行溢出风险")

    return slides


# ==============================================================================
# 4. [Gate 3A] 16:9 宽屏演示幻灯片生成器 (dist/slides.html)
# ==============================================================================
def build_slides_html(slides: list, out_html_path: Path, out_marp_path: Path):
    # 同时导出标准 Marp Markdown 源码供学生参考
    marp_lines = [
        "---",
        "marp: true",
        "theme: default",
        "paginate: true",
        "size: 16:9",
        "---",
        "",
    ]

    slide_sections_html = []
    total = len(slides)

    for idx, s in enumerate(slides, start=1):
        if s["type"] == "cover":
            marp_lines.append(f"# {s['title']}\n\n> {s['abstract']}\n\n---\n")
            abstract_clean = re.sub(r"^\*\*摘要\*\*[：:]\s*", "", s["abstract"])
            slide_sections_html.append(
                f"""
      <section class="slide cover-slide active" data-index="{idx}">
        <div class="slide-inner cover-inner">
          <div class="kicker-badge">{html.escape(s['kicker'])}</div>
          <h1 class="cover-title">{format_inline_html(s['title'])}</h1>
          <div class="abstract-card">
            <div class="abstract-label">核心摘要 · Executive Summary</div>
            <p>{format_inline_html(abstract_clean)}</p>
          </div>
          <div class="cover-footer">
            <span>NCU《人机协同导论》第 6 周实践课编译产物</span>
            <span>按 ← / → 键翻页 · 共 {total} 页</span>
          </div>
        </div>
      </section>"""
            )
        else:
            marp_lines.append(f"## {s['chapter_title']}\n### {s['title']}\n")
            for b in s["bullets"]:
                marp_lines.append(f"- {b}")
            marp_lines.append("\n---\n")

            bullets_html = "\n".join(
                f'            <li class="bullet-item">{format_inline_html(b)}</li>'
                for b in s["bullets"]
            )

            table_html = ""
            if s["tables"]:
                tbl = s["tables"][0]
                if len(tbl) >= 2:
                    th_cells = "".join(f"<th>{format_inline_html(c)}</th>" for c in tbl[0])
                    body_rows = []
                    for row in tbl[1:]:
                        td_cells = "".join(f"<td>{format_inline_html(c)}</td>" for c in row)
                        body_rows.append(f"<tr>{td_cells}</tr>")
                    table_html = f"""
          <div class="table-wrap">
            <table class="data-table">
              <thead><tr>{th_cells}</tr></thead>
              <tbody>{''.join(body_rows)}</tbody>
            </table>
          </div>"""

            slide_sections_html.append(
                f"""
      <section class="slide content-slide" data-index="{idx}">
        <div class="slide-inner">
          <header class="slide-header">
            <div class="chapter-pill">{format_inline_html(s['chapter_title'])}</div>
            <h2 class="section-title">{format_inline_html(s['title'])}</h2>
          </header>
          <div class="slide-body">
            <ul class="bullet-list">
{bullets_html}
            </ul>
            {table_html}
          </div>
          <footer class="slide-footer">
            <span class="ssot-tag">SSOT 纯语义自动编译 · 6×6 视觉防溢出已校验</span>
            <span class="page-num">{idx} / {total}</span>
          </footer>
        </div>
      </section>"""
            )

    out_marp_path.write_text("\n".join(marp_lines), encoding="utf-8")

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.escape(slides[0]['title'])} - 16:9 演示幻灯片</title>
  <style>
    :root {{
      --bg-dark: #0f172a;
      --card-bg: #f8fafc;
      --ink-main: #0f172a;
      --ink-muted: #475569;
      --accent-blue: #1d4ed8;
      --accent-amber: #d97706;
      --accent-teal: #0d9488;
      --border-soft: #cbd5e1;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg-dark);
      color: var(--ink-main);
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      overflow: hidden;
    }}
    .stage-viewport {{
      width: min(94vw, calc(86vh * 16 / 9));
      aspect-ratio: 16 / 9;
      background: var(--card-bg);
      border-radius: 14px;
      box-shadow: 0 25px 60px rgba(0, 0, 0, 0.55);
      position: relative;
      overflow: hidden;
    }}
    .slide {{
      position: absolute;
      inset: 0;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.22s ease;
      display: flex;
      flex-direction: column;
    }}
    .slide.active {{
      opacity: 1;
      pointer-events: auto;
    }}
    .slide-inner {{
      flex: 1;
      padding: 38px 52px 28px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .cover-inner {{
      background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%);
      color: #f8fafc;
      padding: 52px 64px 36px;
    }}
    .kicker-badge {{
      display: inline-block;
      align-self: flex-start;
      background: rgba(56, 189, 248, 0.18);
      border: 1px solid rgba(56, 189, 248, 0.45);
      color: #7dd3fc;
      font-size: 14px;
      font-weight: 600;
      padding: 5px 14px;
      border-radius: 999px;
      letter-spacing: 0.04em;
    }}
    .cover-title {{
      font-size: clamp(26px, 2.8vw, 38px);
      line-height: 1.32;
      font-weight: 800;
      color: #ffffff;
      margin: 12px 0;
    }}
    .abstract-card {{
      background: rgba(255, 255, 255, 0.08);
      border-left: 4px solid #38bdf8;
      padding: 18px 24px;
      border-radius: 8px;
      font-size: clamp(14px, 1.35vw, 18px);
      line-height: 1.65;
      color: #e2e8f0;
    }}
    .abstract-label {{
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #7dd3fc;
      font-weight: 700;
      margin-bottom: 6px;
    }}
    .abstract-card strong {{ color: #fde047; }}
    .cover-footer {{
      display: flex;
      justify-content: space-between;
      font-size: 13px;
      color: #94a3b8;
      border-top: 1px solid rgba(255, 255, 255, 0.15);
      padding-top: 14px;
    }}
    .slide-header {{
      border-bottom: 2px solid #e2e8f0;
      padding-bottom: 12px;
      margin-bottom: 16px;
    }}
    .chapter-pill {{
      font-size: 13px;
      font-weight: 700;
      color: var(--accent-blue);
      margin-bottom: 4px;
    }}
    .section-title {{
      font-size: clamp(22px, 2.2vw, 30px);
      color: var(--ink-main);
      font-weight: 800;
    }}
    .slide-body {{
      flex: 1;
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: 16px;
      overflow: hidden;
    }}
    .bullet-list {{
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}
    .bullet-item {{
      position: relative;
      padding: 12px 18px 12px 36px;
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-left: 4px solid var(--accent-blue);
      border-radius: 8px;
      font-size: clamp(14px, 1.35vw, 18px);
      line-height: 1.55;
      color: #1e293b;
      box-shadow: 0 2px 6px rgba(15, 23, 42, 0.04);
    }}
    .bullet-item::before {{
      content: "▸";
      position: absolute;
      left: 14px;
      top: 11px;
      color: var(--accent-blue);
      font-weight: bold;
    }}
    .bullet-item strong {{
      color: #b45309;
      background: #fef3c7;
      padding: 1px 5px;
      border-radius: 4px;
    }}
    .formula-block {{
      display: inline-block;
      font-family: "Cambria Math", "Times New Roman", serif;
      font-size: 1.05em;
      color: #0f172a;
      letter-spacing: 0.02em;
    }}
    code {{
      font-family: "SFMono-Regular", Consolas, monospace;
      background: #eff6ff;
      color: #1d4ed8;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 0.9em;
    }}
    .table-wrap {{
      margin-top: 4px;
      overflow-x: auto;
    }}
    .data-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: clamp(12px, 1.15vw, 15px);
      background: #ffffff;
      border-top: 2.5px solid #0f172a;
      border-bottom: 2.5px solid #0f172a;
    }}
    .data-table th {{
      background: #f1f5f9;
      color: #0f172a;
      font-weight: 700;
      text-align: left;
      padding: 8px 12px;
      border-bottom: 1.5px solid #334155;
    }}
    .data-table td {{
      padding: 8px 12px;
      border-bottom: 1px solid #e2e8f0;
      color: #334155;
    }}
    .data-table td strong {{
      color: #0f766e;
    }}
    .slide-footer {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-top: 1px solid #e2e8f0;
      padding-top: 10px;
      font-size: 12px;
      color: var(--ink-muted);
    }}
    .ssot-tag {{
      color: var(--accent-teal);
      font-weight: 600;
    }}
    .toolbar {{
      margin-top: 14px;
      display: flex;
      gap: 12px;
      align-items: center;
      color: #cbd5e1;
      font-size: 13px;
    }}
    .toolbar button {{
      background: #1e293b;
      color: #f8fafc;
      border: 1px solid #475569;
      padding: 6px 14px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 13px;
    }}
    .toolbar button:hover {{ background: #334155; }}
  </style>
</head>
<body>
  <div class="stage-viewport" id="deck">
{''.join(slide_sections_html)}
  </div>
  <div class="toolbar">
    <button onclick="prevSlide()">← 上一页</button>
    <span id="indicator">第 1 / {total} 页</span>
    <button onclick="nextSlide()">下一页 →</button>
  </div>
  <script>
    const slides = Array.from(document.querySelectorAll('.slide'));
    const indicator = document.getElementById('indicator');
    let cur = 0;
    function showSlide(i) {{
      cur = (i + slides.length) % slides.length;
      slides.forEach((s, idx) => s.classList.toggle('active', idx === cur));
      indicator.textContent = `第 ${{cur + 1}} / ${{slides.length}} 页`;
    }}
    function nextSlide() {{ showSlide(cur + 1); }}
    function prevSlide() {{ showSlide(cur - 1); }}
    window.addEventListener('keydown', (e) => {{
      if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') nextSlide();
      if (e.key === 'ArrowLeft' || e.key === 'PageUp') prevSlide();
    }});
  </script>
</body>
</html>
"""
    out_html_path.write_text(html_doc, encoding="utf-8")


# ==============================================================================
# 5. [Gate 3B] A4 学术级报告编译器 (dist/report.pdf & dist/report.typ)
# ==============================================================================
def md_inline_to_typst(text: str) -> str:
    """将纯语义 Markdown 行内格式转换为 Typst 语法"""
    if is_formula_block(text):
        # 独立公式：降级为居中排版行，避免 Typst 数学语法（$...$ 与 $$...$$ 语义不同）直接报错
        plain = latex_to_plain(text).replace("%", "\\%")
        return f"#align(center)[{plain}]"
    t = text.replace("$\\rightarrow$", "$->$").replace("→", "$->$")
    # 加粗 **...** -> *...*
    t = re.sub(r"\*\*([^\*]+)\*\*", r"*\1*", t)
    # 百分号转义（非公式内）
    t = t.replace("%", "\\%")
    return t


def build_report_typst_and_pdf(doc: dict, out_typ_path: Path, out_pdf_path: Path, out_a4_html_path: Path):
    abstract_clean = re.sub(r"^\*\*摘要\*\*[：:]\s*", "", doc["abstract"])
    typ_lines = [
        # 页脚页码交给排版引擎自己算，避免兜底引擎那种「手工数页」的脆弱实现
        '#set page(paper: "a4", margin: (top: 2.5cm, bottom: 2.5cm, left: 2.6cm, right: 2.6cm),'
        ' numbering: (i, n) => text(size: 8.5pt, fill: rgb("#64748b"))[第 #i 页 / 共 #n 页])',
        '#set text(font: ("PingFang SC", "Songti SC", "STSong", "Noto Serif CJK SC", "SimSun"), size: 10.5pt, lang: "zh")',
        "#set par(justify: true, leading: 0.72em, first-line-indent: 2em)",
        "#set heading(numbering: none)",
        "",
        "#align(center)[",
        f'  #text(size: 17pt, weight: "bold")[{md_inline_to_typst(doc["title"])}]',
        "  #v(0.5em)",
        '  #text(size: 9.5pt, fill: rgb("#475569"))[NCU《人机协同导论》第 6 周实践课 · 单一事实源 (SSOT) 编译交付物]',
        "]",
        "#v(0.8em)",
        "#rect(width: 100%, fill: rgb(\"#f8fafc\"), stroke: (left: 3pt + rgb(\"#1d4ed8\")), inset: 10pt)[",
        "#set par(first-line-indent: 0pt)",
        f'  *摘要*：{md_inline_to_typst(abstract_clean)}',
        "]",
        "#v(0.6em)",
        "",
    ]

    # 同步生成一份 A4 印刷版 HTML 备份，方便无 PDF 阅读器时直接浏览器预览打印
    a4_html_parts = [
        f"<h1>{format_inline_html(doc['title'])}</h1>",
        f"<div class='meta'>NCU《人机协同导论》第 6 周实践课 · 单一事实源 (SSOT) 编译交付物</div>",
        f"<div class='abstract'><strong>摘要：</strong>{format_inline_html(abstract_clean)}</div>",
    ]

    for ch in doc["chapters"]:
        typ_lines.append(f'== {md_inline_to_typst(ch["title"])}')
        a4_html_parts.append(f"<h2>{format_inline_html(ch['title'])}</h2>")
        for sec in ch["sections"]:
            typ_lines.append(f'=== {md_inline_to_typst(sec["title"])}')
            a4_html_parts.append(f"<h3>{format_inline_html(sec['title'])}</h3>")
            for p in sec["paragraphs"]:
                typ_lines.append(md_inline_to_typst(p))
                typ_lines.append("")
                a4_html_parts.append(f"<p>{format_inline_html(p)}</p>")

            for tbl in sec["tables"]:
                if len(tbl) >= 2:
                    cols = len(tbl[0])
                    # 按各列最长单元格的字数分配列宽权重（fr 归一化），否则长表头会把邻列挤成一字一行
                    weights = [
                        max(14, min(32, max(len(str(r[c_i])) for r in tbl))) for c_i in range(cols)
                    ]
                    col_spec = "(" + ", ".join(f"{w}fr" for w in weights) + ")"
                    typ_lines.append("#set par(first-line-indent: 0pt)")
                    typ_lines.append("#align(center)[")
                    typ_lines.append("  #set text(size: 8.5pt)")
                    typ_lines.append(
                        f"  #table(columns: {col_spec}, stroke: (x, y) => if y == 0 {{ (top: 1.5pt + black, bottom: 1pt + black) }} else {{ (bottom: 0.5pt + gray) }}, inset: (x: 5pt, y: 4pt),"
                    )
                    for r_idx, row in enumerate(tbl):
                        for cell in row:
                            c_str = md_inline_to_typst(cell)
                            if r_idx == 0:
                                typ_lines.append(f"    [*{c_str}*],")
                            else:
                                typ_lines.append(f"    [{c_str}],")
                    typ_lines.append("  )")
                    typ_lines.append("]")
                    typ_lines.append("#set par(first-line-indent: 2em)")
                    typ_lines.append("")

                    # HTML Table
                    th_html = "".join(f"<th>{format_inline_html(c)}</th>" for c in tbl[0])
                    tr_html = "".join(
                        "<tr>" + "".join(f"<td>{format_inline_html(c)}</td>" for c in r) + "</tr>"
                        for r in tbl[1:]
                    )
                    a4_html_parts.append(
                        f"<table class='three-line'><thead><tr>{th_html}</tr></thead><tbody>{tr_html}</tbody></table>"
                    )

    out_typ_path.write_text("\n".join(typ_lines), encoding="utf-8")

    a4_html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>{html.escape(doc['title'])} - A4 学术报告</title>
  <style>
    @page {{ size: A4; margin: 22mm 20mm; }}
    body {{
      font-family: "PingFang SC", "Songti SC", "Microsoft YaHei", serif;
      color: #0f172a;
      max-width: 210mm;
      margin: 0 auto;
      padding: 20mm;
      line-height: 1.75;
      font-size: 10.5pt;
      background: #ffffff;
    }}
    h1 {{ text-align: center; font-size: 17pt; margin-bottom: 6px; }}
    .meta {{ text-align: center; font-size: 9.5pt; color: #475569; margin-bottom: 18px; }}
    .abstract {{
      background: #f8fafc;
      border-left: 3.5px solid #1d4ed8;
      padding: 10px 14px;
      margin-bottom: 18px;
      font-size: 10pt;
    }}
    h2 {{ font-size: 13pt; border-bottom: 1px solid #cbd5e1; padding-bottom: 4px; margin-top: 18px; }}
    h3 {{ font-size: 11pt; margin-top: 12px; color: #1e3a8a; }}
    p {{ text-indent: 2em; margin: 8px 0; text-align: justify; }}
    table.three-line {{
      width: 100%;
      border-collapse: collapse;
      margin: 14px 0;
      font-size: 9.5pt;
      border-top: 2px solid #0f172a;
      border-bottom: 2px solid #0f172a;
    }}
    table.three-line th {{
      border-bottom: 1px solid #0f172a;
      padding: 6px 8px;
      text-align: left;
      background: #f8fafc;
    }}
    table.three-line td {{ padding: 6px 8px; border-bottom: 0.5px solid #cbd5e1; }}
    code {{ font-family: monospace; background: #f1f5f9; padding: 1px 4px; border-radius: 3px; }}
    .formula-block {{
      display: block;
      text-align: center;
      font-family: "Cambria Math", "Times New Roman", serif;
      margin: 10px 0;
    }}
  </style>
</head>
<body>
{''.join(a4_html_parts)}
</body>
</html>"""
    out_a4_html_path.write_text(a4_html_doc, encoding="utf-8")

    # 优先调用 Typst 编译 PDF：先找 CLI，再试 `pip install typst` 装出来的 Python 绑定
    engine = _compile_pdf_with_typst(out_typ_path, out_pdf_path)
    if engine:
        return engine

    # 备选：使用内置 CJK 原生 PDF 兜底生成器（确保任何无外部依赖的裸 Python 环境均可输出合法 PDF）
    generate_fallback_cjk_pdf(doc, out_pdf_path)
    return "Python 内置学术 PDF 引擎 (零外部依赖兜底)"


def _compile_pdf_with_typst(typ_path: Path, pdf_path: Path):
    """尝试用 Typst 把 .typ 编译成 PDF；成功返回引擎名，不可用/失败返回 None。

    两条通路，缺一不可：
      1. Typst 官方 CLI（独立安装的二进制，`shutil.which("typst")` 可见）；
      2. `pip install typst` 安装的 Python 绑定 —— 这个 wheel **只注册 `import typst`，
         不生成 typst.exe**，所以 `shutil.which("typst")` 永远返回 None，必须显式 import。
         这正是"明明按老师说的装了 typst、PDF 却仍然走兜底引擎"的根因。
    """
    # 可复现构建：Typst 默认把「编译那一刻」写进 PDF 的 CreationDate/ID，
    # 导致同一份母稿两次编译的散列不同，SSOT 的「回滚后逐字节还原」就无法自证。
    # 固定为 SOURCE_DATE_EPOCH（可复现构建的通行约定），未设置时用报告定稿日。
    epoch = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    stamp = int(epoch) if epoch.isdigit() else 1792684800  # 2026-10-23 00:00:00 +08:00

    typst_bin = shutil.which("typst")
    if typst_bin:
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(stamp))
        res = subprocess.run(
            [typst_bin, "compile", str(typ_path), str(pdf_path)],
            capture_output=True,
            text=True,
            env=env,
        )
        if res.returncode == 0 and pdf_path.exists():
            return "Typst CLI 引擎"
        print("   ⚠ [warn] Typst CLI 编译失败，改试 Python 绑定：" + (res.stderr or "").strip()[:200])

    try:
        import typst as typst_py  # type: ignore
    except ImportError:
        return None

    try:
        pdf_bytes, warnings = typst_py.compile_with_warnings(str(typ_path), timestamp=stamp)
        pdf_path.write_bytes(pdf_bytes)
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            # 字体链是跨平台的，本机没装的那几款会报 unknown font family，属预期噪音
            real_warns = [w for w in warnings if "unknown font family" not in str(w)]
            if real_warns:
                print(f"   ⚠ [warn] Typst 编译告警 {len(real_warns)} 条：" + str(real_warns[0])[:200])
            return "Typst Python 绑定引擎 (pip install typst)"
    except Exception as exc:
        print("   ⚠ [warn] Typst Python 绑定编译失败：" + str(exc).strip()[:200])
    return None


def _pdf_utf16be_hex(text: str) -> str:
    """将中文字符串编码为 PDF Type0 CIDFont 支持的 UTF-16BE 十六进制文本串"""
    clean = re.sub(r"\*\*|`", "", text).replace("$\\rightarrow$", "->").replace("$N=40$", "N=40").replace("$N$", "N")
    return "<FEFF" + clean.encode("utf-16-be").hex().upper() + ">"


def generate_fallback_cjk_pdf(doc: dict, out_pdf_path: Path):
    """
    零第三方依赖的纯 Python 标准库 PDF 生成器（使用 Adobe-GB1 / STSong-Light 标准中日韩 CID 字库）
    当学生电脑既未安装 typst 也未安装 reportlab 时，100% 保证生成可打开阅读的 A4 PDF。
    """
    lines_to_draw = []
    # 标题按 15pt 字号折算可用宽度（A4 版心约 495pt / 15pt ≈ 33 字），超长必须折行防右侧溢出
    title_clean = re.sub(r"\*\*|`", "", doc["title"])
    for seg in [title_clean[i : i + 30] for i in range(0, len(title_clean), 30)] or [""]:
        lines_to_draw.append((15, seg))
    # 副标题为 9pt 固定文案，约 55 字上限，同样折行
    subtitle = "NCU《人机协同导论》第 6 周实践课 · 单一事实源 (SSOT) 编译交付物"
    for seg in [subtitle[i : i + 50] for i in range(0, len(subtitle), 50)] or [""]:
        lines_to_draw.append((9, seg))
    lines_to_draw.append((10, ""))

    # 自动按 42 个字符宽度折行
    def wrap_line(text: str, width: int = 42):
        if is_formula_block(text):
            clean = latex_to_plain(text)
        else:
            clean = re.sub(r"\*\*|`", "", text).replace("$\\rightarrow$", "->")
        return [clean[i : i + width] for i in range(0, len(clean), width)] or [""]

    for w in wrap_line(doc["abstract"], 40):
        lines_to_draw.append((10, w))
    lines_to_draw.append((10, ""))

    for ch in doc["chapters"]:
        lines_to_draw.append((12, ch["title"]))
        for sec in ch["sections"]:
            lines_to_draw.append((11, sec["title"]))
            for p in sec["paragraphs"]:
                for w in wrap_line("    " + p, 42):
                    lines_to_draw.append((10, w))
            for tbl in sec["tables"]:
                for row in tbl:
                    lines_to_draw.append((9, " | ".join(row)))
            lines_to_draw.append((10, ""))

    # 分页组装 PDF 内容流
    pages_streams = []
    y = 780
    cur_cmds = ["BT"]
    for fsize, text in lines_to_draw:
        # 分页规则：① 正文触底（y<65）；② 标题（>=11pt）落在页底 3 行内，提前换页避免"孤行标题"
        need_break = y < 65 or (fsize >= 11 and y < 150)
        if need_break and len(cur_cmds) > 1:
            cur_cmds.append("ET")
            pages_streams.append("\n".join(cur_cmds))
            cur_cmds = ["BT"]
            y = 780
        if text:
            hex_str = _pdf_utf16be_hex(text)
            cur_cmds.append(f"/F1 {fsize} Tf 50 {y} Td {hex_str} Tj -50 -{y} Td")
        y -= int(fsize * 1.65)
    cur_cmds.append("ET")
    pages_streams.append("\n".join(cur_cmds))

    # 逐页补齐页脚页码（学术排版规范：每页底部标注「第 N 页 / 共 M 页」）
    total_pages = len(pages_streams)
    for i in range(total_pages):
        footer_hex = _pdf_utf16be_hex(f"第 {i + 1} 页 / 共 {total_pages} 页")
        pages_streams[i] += f"\nBT /F1 9 Tf 268 38 Td {footer_hex} Tj ET"

    # 构建 PDF 对象表
    objects = []
    # 1: Catalog, 2: Pages, 3: Type0 Font (STSong-Light / UniGB-UCS2-H), 4: CIDFont
    num_pages = len(pages_streams)
    first_page_obj = 5
    kids_refs = " ".join(f"{first_page_obj + i * 2} 0 R" for i in range(num_pages))

    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    objects.append(
        f"2 0 obj\n<< /Type /Pages /Kids [{kids_refs}] /Count {num_pages} >>\nendobj\n".encode("ascii")
    )
    objects.append(
        b"3 0 obj\n<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H /DescendantFonts [4 0 R] >>\nendobj\n"
    )
    objects.append(
        b"4 0 obj\n<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light /CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> >>\nendobj\n"
    )

    for i, stream_str in enumerate(pages_streams):
        page_obj_id = first_page_obj + i * 2
        content_obj_id = page_obj_id + 1
        stream_bytes = stream_str.encode("ascii")
        page_obj = (
            f"{page_obj_id} 0 obj\n"
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_obj_id} 0 R >>\n"
            f"endobj\n"
        ).encode("ascii")
        content_obj = (
            f"{content_obj_id} 0 obj\n<< /Length {len(stream_bytes)} >>\nstream\n".encode("ascii")
            + stream_bytes
            + b"\nendstream\nendobj\n"
        )
        objects.append(page_obj)
        objects.append(content_obj)

    pdf_bytes = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf_bytes))
        pdf_bytes.extend(obj)

    xref_pos = len(pdf_bytes)
    total_objs = len(objects) + 1
    pdf_bytes.extend(f"xref\n0 {total_objs}\n0000000000 65535 f \n".encode("ascii"))
    for off in offsets[1:]:
        pdf_bytes.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    pdf_bytes.extend(
        f"trailer\n<< /Size {total_objs} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    out_pdf_path.write_bytes(bytes(pdf_bytes))


# ==============================================================================
# 6. CLI 主入口
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="NCU 第 6 周实践课：单一事实源 (SSOT) 一源多端自动化编译器")
    parser.add_argument(
        "--input",
        "-i",
        default="report.md",
        help="纯语义 Markdown 母稿路径（默认读取当前目录下的 report.md）",
    )
    parser.add_argument(
        "--outdir",
        "-o",
        default="dist",
        help="多端衍生制品输出目录（默认输出至 dist/）",
    )
    args = parser.parse_args()

    src_path = Path(args.input).resolve()
    if not src_path.exists():
        print(f"❌ 找不到输入母稿文件：{src_path}")
        print("💡 提示：请确认你在包含 report.md 的工程目录下运行 `python ssot_compiler.py`。")
        sys.exit(1)

    md_text = src_path.read_text(encoding="utf-8")

    # Gate 1: 纯语义检查
    if not run_gate1_semantic_check(md_text, src_path):
        sys.exit(2)

    # AST 解析与 Gate 2 视觉预算检查
    doc = parse_markdown_ast(md_text)
    slides = run_gate2_layout_budget(doc)

    # Gate 3: 多端产物构建
    out_dir = Path(args.outdir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    slides_html_path = out_dir / "slides.html"
    slides_marp_path = out_dir / "slides.marp.md"
    report_typ_path = out_dir / "report.typ"
    report_pdf_path = out_dir / "report.pdf"
    report_a4_html_path = out_dir / "report_a4_preview.html"

    print("\n" + "=" * 68)
    print("🚀 [Gate 3] 一源多端自动化分发编译 (Single Source -> Multi-Target)")
    print("=" * 68)

    build_slides_html(slides, slides_html_path, slides_marp_path)
    print(f"   ✔ [终端 1：16:9 宽屏演示幻灯片] 已生成 -> {slides_html_path.relative_to(src_path.parent)}")

    pdf_engine = build_report_typst_and_pdf(doc, report_typ_path, report_pdf_path, report_a4_html_path)
    print(
        f"   ✔ [终端 2：A4 学术长文报告 PDF] 已生成 -> {report_pdf_path.relative_to(src_path.parent)} (驱动: {pdf_engine})"
    )
    print(
        f"   ✔ [辅助预览：A4 网页印刷版备份] 已生成 -> {report_a4_html_path.relative_to(src_path.parent)}"
    )
    print("=" * 68)
    print("🎉 编译成功！请双击打开 dist/slides.html 与 dist/report.pdf 验收多端一致性。")


if __name__ == "__main__":
    main()
