"""Import a Word (.docx) document into a drafting view as editable Revit text notes.

The document is read straight from its XML, so Word does not need to be installed.
Bold, italic, underline, bullets, numbered and lettered lists and indent levels carry
over. Numbers and bullets typed into the text with a tab and a hanging indent (1.<tab>,
A.<tab>, a symbol bullet<tab>) become Revit list items so wrapped lines align under the
text; labels Revit lists can't show (4A., 1.1, (a)) are placed as a label note beside
the text note at Word's hanging indent. Headings start a new text note and are set bold. Tables become a grid of detail
lines with one text note per cell, sized from Word's column widths; merged cells span.
Pictures, shapes, headers and footers are skipped. Text wraps to a column width and
flows into new columns, like a general notes sheet.
"""
import os
import re
import zipfile
import xml.etree.ElementTree as ET

from pyrevit import DB
from System.Collections.Generic import List

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TWIPS_PER_INDENT = 720
TWIPS_PER_LIST_STEP = 360
TWIPS_PER_FOOT = 1440 * 12
WORD_CELL_MARGIN = 108
CELL_PAD_V = 0.03 / 12
TYPED_NUMBER = re.compile(r"^\s*(\d{1,3}|[A-Za-z])[.)]\t")
TYPED_BULLET = re.compile(r"^\s*[^\w\s]\t", re.UNICODE)
TYPED_PREFIX = re.compile(r"^\s*(\(?[0-9A-Za-z]{1,4}(?:\.[0-9A-Za-z]{1,3})*[.)]?)\t")
ALIGNMENTS = {"center": "Center", "right": "Right", "end": "Right"}
LIST_TYPES = {
    "bullet": "Bullet",
    "decimal": "ArabicNumbers",
    "decimalZero": "ArabicNumbers",
    "lowerLetter": "LowerCaseLetters",
    "upperLetter": "UpperCaseLetters",
    "lowerRoman": "LowerCaseLetters",
    "upperRoman": "UpperCaseLetters",
}


class Paragraph(object):
    """One Word paragraph: runs of (text, bold, italic, underline), plus list and heading info."""

    def __init__(self):
        self.runs = []
        self.heading = False
        self.list_key = None
        self.list_type = None
        self.level = 0
        self.left = 0
        self.first_page = 1
        self.last_page = 1
        self.typed_number = None
        self.prefix = None
        self.hang = 0
        self.align = None

    @property
    def text(self):
        return u"".join(r[0] for r in self.runs)


class Hanging(object):
    """A paragraph with a typed label Revit lists can't reproduce (such as 4A.), placed as a
    label note and a text note beside it so wrapped lines align like Word's hanging indent."""

    def __init__(self, para):
        self.para = para


class Skipped(object):
    """A paragraph outside the chosen pages. It is not placed, but still counts toward list numbering."""

    def __init__(self, para):
        self.para = para


class _Pager(object):
    """Page counter while reading. With rendered=True it follows the page breaks Word saved
    from its last layout; otherwise it counts manual page breaks and new-page section breaks."""

    def __init__(self, rendered):
        self.rendered = rendered
        self.page = 1
        self.started = False


class Cell(object):
    """One table cell: its paragraphs, the grid columns it spans, and its vertical merge
    state: None, 'restart' (top of a merged block) or 'continue' (covered by the cell above)."""

    def __init__(self, paras, start, span, vmerge, align="Left"):
        self.paras = paras
        self.start = start
        self.span = span
        self.vmerge = vmerge
        self.align = align


class Table(object):
    """A Word table: grid column widths in twips, rows of Cells, the (first, last) page of each
    row, Word's indent in twips, and the paragraph just before it (the note it belongs to)."""

    def __init__(self, widths, rows, row_pages, indent=0, after=None, margin=WORD_CELL_MARGIN):
        self.widths = widths
        self.rows = rows
        self.row_pages = row_pages
        self.indent = indent
        self.after = after
        self.margin = margin


def _val(el, tag):
    if el is None:
        return None
    child = el.find(W + tag)
    return None if child is None else child.get(W + "val")


def _left(ppr):
    ind = None if ppr is None else ppr.find(W + "ind")
    if ind is None:
        return None
    try:
        return int(float(ind.get(W + "left") or ind.get(W + "start") or 0))
    except ValueError:
        return None


def _hanging(ppr):
    ind = None if ppr is None else ppr.find(W + "ind")
    if ind is None:
        return None
    try:
        return int(float(ind.get(W + "hanging") or 0)) - int(float(ind.get(W + "firstLine") or 0))
    except ValueError:
        return None


def _strip(runs, count):
    out = []
    for text, b, i, u in runs:
        cut = min(count, len(text))
        count -= cut
        if text[cut:]:
            out.append((text[cut:], b, i, u))
    return out


def _on(rpr, tag):
    if rpr is None:
        return None
    el = rpr.find(W + tag)
    if el is None:
        return None
    v = el.get(W + "val")
    if tag == "u":
        return v not in ("none", None) if v is not None else True
    return v not in ("0", "false", "off")


class _Styles(object):
    def __init__(self, root):
        self.by_id = {}
        if root is None:
            return
        for s in root.findall(W + "style"):
            self.by_id[s.get(W + "styleId")] = s

    def _chain(self, style_id):
        seen = set()
        while style_id and style_id not in seen and style_id in self.by_id:
            seen.add(style_id)
            s = self.by_id[style_id]
            yield s
            style_id = _val(s, "basedOn")

    def is_heading(self, style_id):
        for s in self._chain(style_id):
            name = (_val(s, "name") or "").lower()
            if name.startswith("heading") or name in ("title", "subtitle"):
                return True
            ppr = s.find(W + "pPr")
            if ppr is not None and ppr.find(W + "outlineLvl") is not None:
                return True
        return False

    def num_pr(self, style_id):
        for s in self._chain(style_id):
            ppr = s.find(W + "pPr")
            npr = None if ppr is None else ppr.find(W + "numPr")
            if npr is not None:
                return npr
        return None

    def left(self, style_id):
        for s in self._chain(style_id):
            v = _left(s.find(W + "pPr"))
            if v is not None:
                return v
        return None

    def table_margins(self, style_id):
        """The tblCellMar element of a table style (or one it's based on), or None."""
        for s in self._chain(style_id):
            m = s.find(W + "tblPr/" + W + "tblCellMar")
            if m is not None:
                return m
        return None

    def jc(self, style_id):
        """Word paragraph alignment (left, center, right, both...) from the style chain, or None."""
        for s in self._chain(style_id):
            v = _val(s.find(W + "pPr"), "jc")
            if v is not None:
                return v
        return None

    def hanging(self, style_id):
        for s in self._chain(style_id):
            v = _hanging(s.find(W + "pPr"))
            if v is not None:
                return v
        return None

    def run_flag(self, style_id, tag):
        for s in self._chain(style_id):
            v = _on(s.find(W + "rPr"), tag)
            if v is not None:
                return v
        return False


class _Numbering(object):
    def __init__(self, root):
        self.abstract = {}
        self.num = {}
        if root is None:
            return
        for a in root.findall(W + "abstractNum"):
            levels = {}
            for lvl in a.findall(W + "lvl"):
                levels[int(lvl.get(W + "ilvl"))] = (_val(lvl, "numFmt") or "decimal", _left(lvl.find(W + "pPr")))
            self.abstract[a.get(W + "abstractNumId")] = levels
        for n in root.findall(W + "num"):
            self.num[n.get(W + "numId")] = _val(n, "abstractNumId")

    def level(self, num_id, level):
        """(number format, left indent in twips or None) of a list level."""
        return self.abstract.get(self.num.get(num_id), {}).get(level, ("decimal", None))


def _read(z, name):
    try:
        return ET.fromstring(z.read(name))
    except KeyError:
        return None


def _paragraph(p, styles, numbering, pager=None):
    out = Paragraph()
    ppr = p.find(W + "pPr")
    style_id = _val(ppr, "pStyle")
    out.heading = styles.is_heading(style_id)
    jc = _val(ppr, "jc") or styles.jc(style_id)
    if jc is not None:
        out.align = ALIGNMENTS.get(jc, "Left")
    npr = ppr.find(W + "numPr") if ppr is not None else None
    if npr is None:
        npr = styles.num_pr(style_id)
    if npr is not None:
        num_id = _val(npr, "numId")
        ilvl = int(_val(npr, "ilvl") or 0)
        if num_id and num_id != "0":
            fmt, list_left = numbering.level(num_id, ilvl)
            if fmt in LIST_TYPES:
                out.list_type = LIST_TYPES[fmt]
                out.list_key = (num_id, ilvl)
            out.level = ilvl
            out.left = list_left or 0
    left = _left(ppr)
    if left is None:
        left = styles.left(style_id)
    if left is not None:
        out.left = left
    if out.list_type is None:
        out.level = max(0, int(round(out.left / float(TWIPS_PER_INDENT))))
    if pager is not None and not pager.rendered and pager.started and _on(ppr, "pageBreakBefore"):
        pager.page += 1
    if pager is not None:
        out.first_page = pager.page
    has_text = False
    for r in p.iter(W + "r"):
        rpr = r.find(W + "rPr")
        flags = []
        for tag in ("b", "i", "u"):
            v = _on(rpr, tag)
            flags.append(styles.run_flag(style_id, tag) if v is None else v)
        text = []
        for child in r:
            page_break = (child.tag == W + "br" and child.get(W + "type") == "page")
            if pager is not None and ((pager.rendered and child.tag == W + "lastRenderedPageBreak")
                                      or (not pager.rendered and page_break)):
                pager.page += 1
                if not has_text:
                    out.first_page = pager.page
            if child.tag == W + "t":
                text.append(child.text or u"")
                has_text = has_text or bool((child.text or u"").strip())
            elif child.tag == W + "tab":
                text.append(u"\t")
            elif child.tag in (W + "br", W + "cr") and not page_break:
                text.append(u" ")
        if text:
            out.runs.append((u"".join(text), flags[0], flags[1], flags[2]))
    if out.list_type is None and not out.heading:
        hanging = _hanging(ppr)
        if hanging is None:
            hanging = styles.hanging(style_id) or 0
        number, bullet, prefix = (TYPED_NUMBER.match(out.text), TYPED_BULLET.match(out.text),
                                  TYPED_PREFIX.match(out.text))
        if number:
            token = number.group(1)
            if token.isdigit():
                out.list_type, out.typed_number = "ArabicNumbers", int(token)
            elif token.isupper():
                out.list_type, out.typed_number = "UpperCaseLetters", ord(token) - ord("A") + 1
            else:
                out.list_type, out.typed_number = "LowerCaseLetters", ord(token) - ord("a") + 1
            out.runs = _strip(out.runs, len(number.group(0)))
            out.level = max(0, int(round((out.left - hanging) / float(TWIPS_PER_INDENT))))
        elif bullet:
            out.list_type = "Bullet"
            out.runs = _strip(out.runs, len(bullet.group(0)))
            out.level = max(0, int(round((out.left - hanging) / float(TWIPS_PER_INDENT))))
        elif prefix and hanging > 0:
            out.prefix = prefix.group(1)
            out.hang = hanging
            out.runs = _strip(out.runs, len(prefix.group(0)))
            out.level = 0
    if pager is not None:
        out.last_page = pager.page
        pager.started = True
        sect = ppr.find(W + "sectPr") if ppr is not None else None
        if not pager.rendered and sect is not None and _val(sect, "type") not in ("continuous",):
            pager.page += 1
    return out


def _int(el, attr, default):
    try:
        return int(float(el.get(W + attr)))
    except (TypeError, ValueError, AttributeError):
        return default


def _cell_paras(tc, styles, numbering, pager):
    paras = []
    for el in tc:
        if el.tag == W + "p":
            para = _paragraph(el, styles, numbering, pager)
            para.heading = False
            if para.text.strip():
                paras.append(para)
        elif el.tag == W + "tbl":
            for tr in el.iter(W + "tr"):
                row = Paragraph()
                row.runs.append((u"\t".join(
                    u" ".join(_paragraph(p, styles, numbering, pager).text.strip() for p in c.iter(W + "p")).strip()
                    for c in tr.findall(W + "tc")), False, False, False))
                if row.text.strip():
                    paras.append(row)
    return paras


def _table(tbl, styles, numbering, pager):
    tblpr = tbl.find(W + "tblPr")
    tblind = tblpr.find(W + "tblInd") if tblpr is not None else None
    indent = _int(tblind, "w", 0) if tblind is not None and tblind.get(W + "type") in (None, "dxa") else 0
    table_jc = styles.jc(_val(tbl.find(W + "tblPr"), "tblStyle"))
    margin = WORD_CELL_MARGIN
    for source in (styles.table_margins(_val(tblpr, "tblStyle")),
                   tblpr.find(W + "tblCellMar") if tblpr is not None else None):
        if source is not None:
            sides = [_int(source.find(W + tag), "w", None) for tag in ("left", "start", "right", "end")]
            sides = [v for v in sides if v is not None]
            if sides:
                margin = max(sides)
    table_align = ALIGNMENTS.get(table_jc, "Left")
    grid = tbl.find(W + "tblGrid")
    widths = [_int(g, "w", 0) for g in grid.findall(W + "gridCol")] if grid is not None else []
    rows = []
    row_pages = []
    cell_widths = {}
    for tr in tbl.findall(W + "tr"):
        row_start = pager.page
        trpr = tr.find(W + "trPr")
        col = _int(trpr.find(W + "gridBefore"), "val", 0) if trpr is not None else 0
        cells = []
        for tc in tr.findall(W + "tc"):
            tcpr = tc.find(W + "tcPr")
            span = max(1, _int(tcpr.find(W + "gridSpan"), "val", 1)) if tcpr is not None else 1
            tcw = tcpr.find(W + "tcW") if tcpr is not None else None
            if span == 1 and tcw is not None and tcw.get(W + "type") in (None, "dxa"):
                cell_widths[col] = max(cell_widths.get(col, 0), _int(tcw, "w", 0))
            vm = tcpr.find(W + "vMerge") if tcpr is not None else None
            vmerge = None if vm is None else ("restart" if vm.get(W + "val") == "restart" else "continue")
            paras = _cell_paras(tc, styles, numbering, pager)
            align = next((p.align for p in paras if p.align), table_align)
            cells.append(Cell(paras, col, span, vmerge, align))
            col += span
        rows.append(cells)
        firsts = [p.first_page for c in cells for p in c.paras]
        row_pages.append((min(firsts) if firsts else row_start, pager.page))
    ncols = max([c.start + c.span for r in rows for c in r] + [len(widths), 1])
    widths += [0] * (ncols - len(widths))
    grid_known = [w for w in widths if w > 0]
    grid_even = len(set(grid_known)) <= 1
    cells_uneven = len(set(w for w in cell_widths.values() if w > 0)) > 1
    if not grid_known or (grid_even and cells_uneven):
        for col, w in cell_widths.items():
            if w > 0:
                widths[col] = w
    known = [w for w in widths if w > 0]
    fill = sum(known) / len(known) if known else 1440
    widths = [w if w > 0 else fill for w in widths] + [fill] * (ncols - len(widths))
    return Table(widths, rows, row_pages, indent, None, margin)


def read_docx(path):
    """Return the document body in order as Paragraph and Table objects, each tagged with
    the pages it falls on. Raises IOError or zipfile.BadZipfile when the file is not a
    readable .docx."""
    z = zipfile.ZipFile(path)
    try:
        body = _read(z, "word/document.xml").find(W + "body")
        styles = _Styles(_read(z, "word/styles.xml"))
        numbering = _Numbering(_read(z, "word/numbering.xml"))
    finally:
        z.close()
    pager = _Pager(any(True for _ in body.iter(W + "lastRenderedPageBreak")))
    items = []
    last = None
    for el in body:
        if el.tag == W + "p":
            para = _paragraph(el, styles, numbering, pager)
            if not para.text.strip():
                para.runs = []
            else:
                last = para
            items.append(para)
        elif el.tag == W + "tbl":
            table = _table(el, styles, numbering, pager)
            table.after = last
            items.append(table)
    paras = [p for p in items if isinstance(p, Paragraph)]
    base = [p.left for p in paras if p.list_key and p.level == 0]
    if base:
        for p in paras:
            if p.list_key and p.level == 0:
                p.level = max(0, int(round((p.left - min(base)) / float(TWIPS_PER_LIST_STEP))))
    return items


def has_layout_pages(path):
    """True when the file holds the page breaks Word saved from its last layout."""
    z = zipfile.ZipFile(path)
    try:
        return b"lastRenderedPageBreak" in z.read("word/document.xml")
    finally:
        z.close()


def page_count(items):
    """Number of the last page any item falls on."""
    last = 1
    for it in items:
        last = max(last, it.row_pages[-1][1] if isinstance(it, Table) and it.row_pages else
                   getattr(it, "last_page", 1))
    return last


def parse_pages(text, last):
    """Turn '1-3, 5' into a set of page numbers from 1 to `last`. Blank means every page.
    Raises ValueError with a message for the user when the text can't be read."""
    text = (text or "").strip()
    if not text:
        return set(range(1, last + 1))
    pages = set()
    for part in re.split(r"[,;]", text):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)\s*(?:-\s*(\d+))?$", part)
        if not m:
            raise ValueError("'{}' is not a page or a range like 2-4.".format(part))
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a < 1 or b < a:
            raise ValueError("'{}' is not a valid page range.".format(part))
        pages.update(range(a, min(b, last) + 1))
    if not pages:
        raise ValueError("None of those pages exist; the document has {} pages.".format(last))
    return pages


def select_pages(items, pages):
    """Keep the paragraphs and table rows that touch any page in `pages`. Paragraphs left out
    come back as Skipped, so list numbering still counts them."""
    out = []
    for it in items:
        if isinstance(it, Table):
            keep = [i for i, (a, b) in enumerate(it.row_pages) if any(n in pages for n in range(a, b + 1))]
            if not keep:
                continue
            rows = [it.rows[i] for i in keep]
            for cell in rows[0]:
                if cell.vmerge == "continue":
                    cell.vmerge = None
            out.append(Table(it.widths, rows, [it.row_pages[i] for i in keep], it.indent, it.after, it.margin))
        elif any(n in pages for n in range(it.first_page, it.last_page + 1)):
            out.append(it)
        else:
            out.append(Skipped(it))
    return out


def sections(items):
    """Group items into blocks: each heading starts a new text note, and each table, or
    paragraph left out by a page range, is a block of its own. Empty paragraphs stay inside
    a text note as blank lines; at the start or end of a note they are dropped."""
    groups = []
    for it in items:
        if isinstance(it, (Table, Skipped)):
            groups.append(it)
        elif not it.runs:
            if groups and isinstance(groups[-1], list):
                groups[-1].append(it)
        elif it.prefix:
            groups.append(Hanging(it))
        elif it.heading or not groups or not isinstance(groups[-1], list):
            groups.append([it])
        else:
            groups[-1].append(it)
    return [g for g in (_fold(_trim(g)) if isinstance(g, list) else g for g in groups) if g != []]


def _fold(paras):
    """Turn each empty paragraph into a line break at the end of the paragraph before it, and
    make sure every top-level numbered paragraph has one blank line before it, whether Word
    used an empty paragraph or paragraph spacing there. Revit restarts a numbered list after
    an empty paragraph and then refuses a start number on the next item, but a line break
    inside a paragraph keeps the list going."""
    out = []
    for p in paras:
        if not p.runs:
            if out:
                out[-1] = _with_break(out[-1])
            continue
        if out and p.list_type and p.list_type != "Bullet" and p.level == 0:
            out[-1] = _with_break(out[-1])
        out.append(p)
    return out


def _with_break(p):
    if p.text.endswith(u"\u000b"):
        return p
    copy = Paragraph()
    copy.__dict__.update(p.__dict__)
    text, b, i, u = copy.runs[-1]
    copy.runs = copy.runs[:-1] + [(text + u"\u000b", b, i, u)]
    return copy


def _trim(paras):
    out = []
    for p in paras:
        if p.runs or (out and out[-1].runs):
            out.append(p)
    while out and not out[-1].runs:
        out.pop()
    return out


def _count(counters, p):
    """Advance the list counter for list paragraph `p` and return its number."""
    number = counters.get(p.list_key, 0) + 1
    counters[p.list_key] = number
    for key in [k for k in counters if k[0] == p.list_key[0] and k[1] > p.list_key[1]]:
        del counters[key]
    return number


def _make_note(doc, view, origin, width, type_id, paras, counters, align="Left"):
    text = u"\r".join(p.text for p in paras)
    options = DB.TextNoteOptions(type_id)
    options.HorizontalAlignment = getattr(DB.HorizontalTextAlignment, align)
    note = DB.TextNote.Create(doc, view.Id, origin, width, text, options)
    ft = note.GetFormattedText()
    pos = 0
    last = {}
    for p in paras:
        length = len(p.text)
        if length:
            start = pos
            for run_text, bold, italic, underline in p.runs:
                n = len(run_text)
                if n:
                    rng = DB.TextRange(start, n)
                    if bold or p.heading:
                        ft.SetBoldStatus(rng, True)
                    if italic:
                        ft.SetItalicStatus(rng, True)
                    if underline:
                        ft.SetUnderlineStatus(rng, True)
                start += n
            prange = DB.TextRange(pos, length)
            level = min(p.level, ft.GetMaximumIndentLevel())
            if level:
                ft.SetIndentLevel(prange, level)
            if p.list_type:
                ft.SetListType(prange, getattr(DB.ListType, p.list_type))
                if p.list_key is None:
                    key = ("typed", p.list_type)
                    number = p.typed_number or 1
                else:
                    key = p.list_key
                    number = _count(counters, p)
                follows = last.get(p.level) in ((key, number - 1), (key, None))
                if p.list_type != "Bullet" and number > 1 and not follows:
                    try:
                        ft.SetListStartNumber(prange, min(number, ft.GetMaximumListStartNumber()))
                    except Exception:
                        pass
                last[p.level] = (key, number if p.list_key is None else None)
                for lvl in [k for k in last if k > p.level]:
                    del last[lvl]
            else:
                last.clear()
        else:
            last.clear()
        pos += length + 1
    note.SetFormattedText(ft)
    return note


def _height(doc, view, note):
    doc.Regenerate()
    bb = note.get_BoundingBox(view)
    return bb.Max.Y - bb.Min.Y


def _segment(doc, view, a, b, lines):
    if a.DistanceTo(b) > doc.Application.ShortCurveTolerance:
        lines.append(doc.Create.NewDetailCurve(view, DB.Line.CreateBound(a, b)))


def _build_table(doc, view, table, type_id, x0, y0, max_width):
    """Draw `table` with its top-left corner at (x0, y0): one text note per cell inside a
    grid of detail lines. Column widths follow Word, scaled down to fit `max_width` (paper
    feet). Returns (notes, lines, height in model feet)."""
    scale = view.Scale
    paper = [w / float(TWIPS_PER_FOOT) for w in table.widths]
    fit = min(1.0, max_width / sum(paper))
    xs = [x0]
    for w in paper:
        xs.append(xs[-1] + w * fit * scale)
    margin = table.margin / float(TWIPS_PER_FOOT)
    pad_v = CELL_PAD_V * scale
    offset_param = doc.GetElement(type_id).get_Parameter(DB.BuiltInParameter.LEADER_OFFSET_SHEET)
    offset = offset_param.AsDouble() if offset_param is not None else 0.0
    notes, lines, tops = [], [], [y0]
    for row in table.rows:
        top, bottom = tops[-1], tops[-1] - 2 * pad_v - 0.1 * scale / 12
        for cell in row:
            if cell.vmerge == "continue" or not cell.paras:
                continue
            width = (xs[cell.start + cell.span] - xs[cell.start]) / scale - 2 * margin
            left, right = xs[cell.start] + margin * scale, xs[cell.start + cell.span] - margin * scale
            anchor = {"Center": (left + right) / 2.0, "Right": right}.get(cell.align, left)
            note = _make_note(doc, view, DB.XYZ(anchor, top - pad_v, 0),
                              max(width, 0.05 / 12), type_id, cell.paras, {}, cell.align)
            notes.append(note)
            text_height = _height(doc, view, note) - 2 * offset * scale
            bottom = min(bottom, top - pad_v - text_height - pad_v)
        tops.append(bottom)
    for i, row in enumerate(table.rows):
        top, bottom = tops[i], tops[i + 1]
        for cell in row:
            _segment(doc, view, DB.XYZ(xs[cell.start], top, 0), DB.XYZ(xs[cell.start], bottom, 0), lines)
            if cell.vmerge != "continue":
                _segment(doc, view, DB.XYZ(xs[cell.start], top, 0),
                         DB.XYZ(xs[cell.start + cell.span], top, 0), lines)
        if row:
            right = row[-1].start + row[-1].span
            _segment(doc, view, DB.XYZ(xs[right], top, 0), DB.XYZ(xs[right], bottom, 0), lines)
    if table.rows:
        last = table.rows[-1]
        if last:
            _segment(doc, view, DB.XYZ(xs[last[0].start], tops[-1], 0),
                     DB.XYZ(xs[last[-1].start + last[-1].span], tops[-1], 0), lines)
    return notes, lines, y0 - tops[-1]


def _hanging_note(doc, view, para, type_id, x0, y0, col_width):
    """Place `para`'s typed label and its text as two notes, the text starting at Word's
    hanging indent. Returns ([label note, text note], height in model feet)."""
    scale = view.Scale
    label_x = max(0, para.left - para.hang) / float(TWIPS_PER_FOOT)
    text_x = para.left / float(TWIPS_PER_FOOT)
    first = para.runs[0] if para.runs else (u"", False, False, False)
    label = Paragraph()
    label.runs.append((para.prefix, first[1], first[2], first[3]))
    body = Paragraph()
    body.runs = list(para.runs)
    notes = [_make_note(doc, view, DB.XYZ(x0 + label_x * scale, y0, 0), max(text_x - label_x, 0.1 / 12),
                        type_id, [label], {}),
             _make_note(doc, view, DB.XYZ(x0 + text_x * scale, y0, 0), max(col_width - text_x, 0.5 / 12),
                        type_id, [body], {})]
    return notes, max(_height(doc, view, n) for n in notes)


def _table_indent(table, tab):
    """Paper indent (feet) for a table Word indents: line it up with where the text of the
    note before it starts in Revit (one Tab Size per list level after the number, or Word's
    hanging indent for a typed label like 4A.). A table Word doesn't indent stays at 0."""
    if table.indent <= 0:
        return 0.0
    p = table.after
    if p is not None and p.list_type:
        return (p.level + 1) * tab
    if p is not None and p.prefix:
        return p.left / float(TWIPS_PER_FOOT)
    if p is not None and p.level:
        return p.level * tab
    return table.indent / float(TWIPS_PER_FOOT)


def place(doc, view, items, type_id, col_width, col_height, gap):
    """Create the notes and tables in `view`, top-left at the origin, flowing into columns.
    Widths and heights are paper sizes in feet; `gap` is the space between blocks. A text
    section taller than the room left in a column is split into notes that fill each column
    and continue at the top of the next. Must run inside a transaction.
    Returns (text notes, detail lines, number of tables)."""
    scale = view.Scale
    col_w, col_h, gap_m = col_width * scale, col_height * scale, gap * scale
    offset_param = doc.GetElement(type_id).get_Parameter(DB.BuiltInParameter.LEADER_OFFSET_SHEET)
    frame = 2 * (offset_param.AsDouble() if offset_param is not None else 0.0) * scale
    tab_param = doc.GetElement(type_id).get_Parameter(DB.BuiltInParameter.TEXT_TAB_SIZE)
    tab = tab_param.AsDouble() if tab_param is not None else 0.5 / 12
    state = {"x": 0.0, "y": 0.0, "used": 0.0}
    notes, lines = [], []
    tables = 0
    counters = {}

    def room():
        return col_h - state["used"] if state["used"] else col_h

    def put(elements, h, framed, space_after):
        """Stack a placed block: move it to a new column if it doesn't fit, then advance."""
        visible = h - frame if framed else h
        if state["used"] and state["used"] + visible > col_h:
            DB.ElementTransformUtils.MoveElements(doc, List[DB.ElementId]([e.Id for e in elements]),
                                                  DB.XYZ(col_w + gap_m, -state["y"], 0))
            state["x"] += col_w + gap_m
            state["y"], state["used"] = 0.0, 0.0
        state["y"] -= visible + space_after
        state["used"] += visible + space_after

    def origin():
        return DB.XYZ(state["x"], state["y"], 0)

    def text_height(para):
        if not para.runs:
            para = Paragraph()
            para.runs.append((u"X", False, False, False))
        probe = _make_note(doc, view, origin(), col_width, type_id, [para], {})
        h = _height(doc, view, probe) - frame
        doc.Delete(probe.Id)
        return h

    for group in sections(items):
        if isinstance(group, Skipped):
            if group.para.list_key:
                _count(counters, group.para)
            continue
        if isinstance(group, Hanging):
            h_notes, h = _hanging_note(doc, view, group.para, type_id, state["x"], state["y"], col_width)
            notes.extend(h_notes)
            put(h_notes, h, True, gap_m)
            continue
        if isinstance(group, Table):
            indent = _table_indent(group, tab)
            t_notes, t_lines, h = _build_table(doc, view, group, type_id, state["x"] + indent * scale,
                                               state["y"], col_width - indent)
            notes.extend(t_notes)
            lines.extend(t_lines)
            tables += 1
            put(t_notes + t_lines, h, False, gap_m)
            continue
        saved = dict(counters)
        note = _make_note(doc, view, origin(), col_width, type_id, group, counters)
        h = _height(doc, view, note)
        if h - frame <= room() or h - frame <= col_h:
            notes.append(note)
            put([note], h, True, gap_m)
            continue
        doc.Delete(note.Id)
        counters.clear()
        counters.update(saved)
        heights = [text_height(p) for p in group]
        rest = list(zip(group, heights))
        while rest:
            space, chunk, total = room(), [], 0.0
            while rest and (not chunk or total + rest[0][1] <= space):
                p, ph = rest.pop(0)
                chunk.append(p)
                total += ph
            chunk = _trim(chunk)
            while rest and not rest[0][0].runs:
                rest.pop(0)
            if not chunk:
                continue
            note = _make_note(doc, view, origin(), col_width, type_id, chunk, counters)
            notes.append(note)
            put([note], _height(doc, view, note), True, gap_m if not rest else 0.0)
            if rest:
                state["x"] += col_w + gap_m
                state["y"], state["used"] = 0.0, 0.0
    return notes, lines, tables


def refresh_pages(path):
    """Have Word lay out a temporary copy of `path` and save it, so its page breaks match
    Word's current layout. The original file is never opened by Word. Returns the path of
    the refreshed copy, or None when Word isn't installed or the refresh fails. If Word
    hands back an instance that already has documents open (the user's own session), it
    is left completely alone and None is returned."""
    import shutil
    import tempfile
    import System
    from System.Reflection import BindingFlags

    def com(obj, name, flags, *args):
        return obj.GetType().InvokeMember(name, flags, None, obj, System.Array[System.Object](list(args)))

    word_type = System.Type.GetTypeFromProgID("Word.Application")
    if word_type is None:
        return None
    folder = tempfile.mkdtemp(prefix="word_notes_")
    source = os.path.join(folder, "source.docx")
    target = os.path.join(folder, "paged.docx")
    shutil.copyfile(path, source)
    word = None
    try:
        word = System.Activator.CreateInstance(word_type)
        documents = com(word, "Documents", BindingFlags.GetProperty)
        if com(documents, "Count", BindingFlags.GetProperty) != 0:
            word = None
            return None
        com(word, "DisplayAlerts", BindingFlags.SetProperty, 0)
        document = com(documents, "Open", BindingFlags.InvokeMethod, source, False, True, False)
        try:
            com(document, "Repaginate", BindingFlags.InvokeMethod)
            com(document, "SaveAs2", BindingFlags.InvokeMethod, target, 16)
        finally:
            com(document, "Close", BindingFlags.InvokeMethod, False)
        return target if os.path.exists(target) else None
    except Exception:
        return None
    finally:
        if word is not None:
            try:
                documents = com(word, "Documents", BindingFlags.GetProperty)
                if com(documents, "Count", BindingFlags.GetProperty) == 0:
                    com(word, "Quit", BindingFlags.InvokeMethod, False)
            except Exception:
                pass


def load(path):
    """Read `path` for importing, laying it out through Word first when Word is available.
    Returns (items, how), where how says where the page numbers came from. Raises IOError
    or zipfile.BadZipfile when the file can't be read."""
    paged = refresh_pages(path)
    try:
        items = read_docx(paged or path)
    finally:
        if paged:
            remove_refreshed(paged)
    if paged:
        how = "Page numbers from Word's layout."
    elif has_layout_pages(path):
        how = "Page numbers from when the file was last saved in Word."
    else:
        how = "Word wasn't available, so only manual page breaks are counted."
    return items, how


def page_previews(items):
    """{page number: the start of the first paragraph or table that begins on that page}."""
    previews = {}
    for it in items:
        if isinstance(it, Table):
            for (first, _), row in zip(it.row_pages, it.rows):
                text = u" | ".join(u" ".join(p.text for p in c.paras).strip() for c in row if c.paras)
                previews.setdefault(first, u"Table: " + text)
        elif it.runs:
            label = it.prefix or (u"{}.".format(it.typed_number) if it.typed_number and it.list_type == "ArabicNumbers"
                                  else u"\u2022" if it.list_type == "Bullet" else u"")
            previews.setdefault(it.first_page, (label + u" " + it.text).strip())
    last = page_count(items)
    return dict((n, previews.get(n, u"(continued from page {})".format(n - 1))) for n in range(1, last + 1))


def format_pages(pages):
    """Write a set of page numbers the way a user would type it, e.g. '1-3, 5'."""
    out, run = [], []
    for n in sorted(pages):
        if run and n == run[-1] + 1:
            run.append(n)
            continue
        if run:
            out.append(str(run[0]) if len(run) == 1 else "{}-{}".format(run[0], run[-1]))
        run = [n]
    if run:
        out.append(str(run[0]) if len(run) == 1 else "{}-{}".format(run[0], run[-1]))
    return ", ".join(out)


def remove_refreshed(paged):
    """Delete the temporary folder refresh_pages made, retrying while Word lets go of it."""
    import shutil
    import time
    folder = os.path.dirname(paged)
    for _ in range(20):
        shutil.rmtree(folder, ignore_errors=True)
        if not os.path.exists(folder):
            return True
        time.sleep(0.25)
    return False


def view_name(path):
    return re.sub(r"[\\:{}\[\]|;<>?`~]", "-", os.path.splitext(os.path.basename(path))[0])


def drafting_view(doc, name, scale):
    """Return the drafting view called `name` with its text notes and detail lines removed,
    or a new one. Must run inside a transaction."""
    for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewDrafting):
        if not v.IsTemplate and v.Name == name:
            old = list(DB.FilteredElementCollector(doc, v.Id).OfClass(DB.TextNote).ToElementIds())
            old += [e.Id for e in DB.FilteredElementCollector(doc, v.Id).OfClass(DB.CurveElement)
                    if isinstance(e, DB.DetailCurve)]
            if old:
                doc.Delete(List[DB.ElementId](old))
            return v
    vft = next(t for t in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
               if t.ViewFamily == DB.ViewFamily.Drafting)
    v = DB.ViewDrafting.Create(doc, vft.Id)
    v.Name = name
    v.Scale = scale
    return v
