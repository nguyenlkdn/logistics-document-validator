"""Excel shipment documents (.xlsx / .xlsm): commercial invoice, packing list and sales contract sheets.

A supplier may send the invoice / packing list / contract as one workbook instead of PDFs. Each VISIBLE sheet's print
area is drawn as a PDF page (cell texts at their cell positions, merged cells, borders), so the review viewer,
highlights and evidence pictures work as for a PDF. Values are read from the CELLS (label cell -> value cell, table
header -> column), not from the drawn text: a number stored in a cell is the number, whatever its display format.

Every value keeps the place it is drawn at (Field.line / start / end), like a value read from a PDF.
Hidden sheets (working sheets, lookup tables) are not documents and are not read.
"""
import re
from datetime import date, datetime
from pathlib import Path

import pymupdf

from .pdftext import Line, Span

FS = 8.0                     # drawing font size (pt); the page is a picture of the sheet, not a copy of its fonts
PAD = 2.0
SEP = "   "                  # between cells on one text line (wide gap, as in PDF text lines)
CJK = re.compile(r"[⺀-鿿＀-￯]")


def _col_pt(ws, letter):
    cd = ws.column_dimensions.get(letter)
    if cd is not None and cd.hidden:
        return 0.0
    w = cd.width if cd is not None and cd.width else (ws.sheet_format.defaultColWidth or 8.43)
    return (w * 7 + 5) * 0.75


def _row_pt(ws, r):
    rd = ws.row_dimensions.get(r)
    if rd is not None and rd.hidden:
        return 0.0
    h = rd.height if rd is not None and rd.height else (ws.sheet_format.defaultRowHeight or 15)
    return float(h)


def display(v, fmt: str = "General") -> str:
    """The text Excel shows for a cell value (enough of the number formats used on shipping documents)."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        v = v.date()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, bool):
        return str(v).upper()
    if isinstance(v, (int, float)):
        fmt = (fmt or "General").split(";")[0]
        m = re.search(r"0\.(0+)", fmt)
        dec = len(m[1]) if m else None
        if dec is None:
            if float(v).is_integer():
                s = f"{int(v):,}" if "#,##" in fmt else str(int(v))
            else:
                s = f"{v:,.6f}".rstrip("0").rstrip(".") if "#,##" in fmt else repr(round(v, 6)).rstrip("0").rstrip(".")
            return s
        return f"{v:,.{dec}f}" if "#,##" in fmt or "," in fmt else f"{v:.{dec}f}"
    return str(v).replace("\xa0", " ").replace("　", " ")


class Cell:
    __slots__ = ("sheet", "row", "col", "value", "text", "line", "start", "end", "page")

    def __init__(self, sheet, row, col, value, text):
        self.sheet, self.row, self.col, self.value, self.text = sheet, row, col, value, text
        self.line = self.start = self.end = None
        self.page = None

    def __repr__(self):
        return f"Cell({self.sheet}!{self.col}{self.row}={self.text!r})"


class Sheet:
    """The cells of one visible sheet inside its print area, in reading order."""

    def __init__(self, ws, page: int):
        from openpyxl.utils import column_index_from_string, get_column_letter
        self.title, self.page = ws.title, page
        area = None
        if ws.print_area:
            pa = ws.print_area if isinstance(ws.print_area, str) else ws.print_area[0]
            pa = pa.split(",")[0].split("!")[-1].replace("$", "")
            m = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", pa)
            if m:
                area = (int(m[2]), column_index_from_string(m[1]), int(m[4]), column_index_from_string(m[3]))
        if area is None:
            area = (ws.min_row, ws.min_column, ws.max_row, ws.max_column)
        self.r0, self.c0, self.r1, self.c1 = area
        self.colx, x = {}, PAD * 6
        for c in range(self.c0, self.c1 + 2):
            self.colx[c] = x
            if c <= self.c1:
                x += _col_pt(ws, get_column_letter(c))
        self.rowy, y = {}, PAD * 6
        for r in range(self.r0, self.r1 + 2):
            self.rowy[r] = y
            if r <= self.r1:
                y += _row_pt(ws, r)
        self.width, self.height = x + PAD * 6, y + PAD * 6
        self.merged = {}                       # top-left (row, col) -> (r1, c1); other cells of a merge are covered
        self.covered = set()
        for rng in ws.merged_cells.ranges:
            self.merged[(rng.min_row, rng.min_col)] = (rng.max_row, rng.max_col)
            for r in range(rng.min_row, rng.max_row + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    if (r, c) != (rng.min_row, rng.min_col):
                        self.covered.add((r, c))
        self.cells, self.at, self.style = [], {}, {}
        for row in ws.iter_rows(min_row=self.r0, max_row=self.r1, min_col=self.c0, max_col=self.c1):
            for c in row:
                if (c.row, c.column) in self.covered or c.value in (None, ""):
                    continue
                if _row_pt(ws, c.row) == 0 or _col_pt(ws, get_column_letter(c.column)) == 0:
                    continue
                t = display(c.value, c.number_format).strip("\n")
                if not t.strip():
                    continue
                cell = Cell(self.title, c.row, c.column, c.value, t)
                cell.page = page
                self.cells.append(cell)
                self.at[(c.row, c.column)] = cell
                self.style[id(cell)] = (c.alignment.horizontal, c.alignment.vertical, bool(c.alignment.wrap_text),
                                        bool(c.font and c.font.b))
        self.borders = []
        for row in ws.iter_rows(min_row=self.r0, max_row=self.r1, min_col=self.c0, max_col=self.c1):
            for c in row:
                b = c.border
                if b is None:
                    continue
                x0, y0, x1, y1 = self.colx[c.column], self.rowy[c.row], self.colx[c.column + 1], self.rowy[c.row + 1]
                for side, seg in (("top", (x0, y0, x1, y0)), ("bottom", (x0, y1, x1, y1)),
                                  ("left", (x0, y0, x0, y1)), ("right", (x1, y0, x1, y1))):
                    s = getattr(b, side)
                    if s is not None and s.style:
                        self.borders.append(seg)

    def rect(self, cell):
        r1, c1 = self.merged.get((cell.row, cell.col), (cell.row, cell.col))
        return self.colx[cell.col], self.rowy[cell.row], self.colx[c1 + 1], self.rowy[r1 + 1]

    def right(self, cell, max_cols=12):
        """The next filled cell to the right on the same row (the value after a label)."""
        for c in range(cell.col + 1, min(cell.col + max_cols, self.c1) + 1):
            x = self.at.get((cell.row, c))
            if x is not None:
                return x
        return None

    def row(self, r):
        return [c for c in self.cells if c.row == r]

    def find(self, rx, flags=re.I):
        rx = re.compile(rx, flags)
        return [c for c in self.cells if rx.search(c.text)]

    def text(self):
        return "\n".join(c.text for c in self.cells)


def _wrap(text, width, fs, font):
    out = []
    for para in text.split("\n"):
        words, cur = para.split(" "), ""
        for w in words:
            t = (cur + " " + w) if cur else w
            if cur and pymupdf.get_text_length(t, fontname=font, fontsize=fs) > width:
                out.append(cur)
                cur = w
            else:
                cur = t
        out.append(cur)
    return out


def draw(sheets: list, out: Path) -> list:
    """Draw the sheets as PDF pages; give every cell its text Line / offsets. Returns the Lines (reading order)."""
    pdf = pymupdf.open()
    lines = []
    for sh in sheets:
        page = pdf.new_page(width=sh.width, height=sh.height)
        for seg in sh.borders:
            page.draw_line(seg[:2], seg[2:], color=(0.55, 0.55, 0.55), width=0.4)
        frags = []                                     # (y, x0, text, font, fs, cell, line index in cell)
        for cell in sh.cells:
            x0, y0, x1, y1 = sh.rect(cell)
            h_al, v_al, wrap, bold = sh.style[id(cell)]
            font = "china-s" if CJK.search(cell.text) else ("hebo" if bold else "helv")
            is_num = isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool)
            avail = x1 - x0 - 2 * PAD
            if not wrap and not is_num and h_al in (None, "general", "left"):
                # an unwrapped text runs on over empty cells to its right (as Excel shows it)
                c, x_end = (sh.merged.get((cell.row, cell.col), (cell.row, cell.col))[1]) + 1, x1
                while c <= sh.c1 and (cell.row, c) not in sh.at and (cell.row, c) not in sh.covered:
                    x_end = sh.colx[c + 1]
                    c += 1
                avail = x_end - x0 - 2 * PAD
            texts = _wrap(cell.text, avail, FS, font) if wrap else cell.text.split("\n")
            fs = FS
            for t in texts:
                w = pymupdf.get_text_length(t, fontname=font, fontsize=fs)
                if w > avail > 0:
                    fs = max(3.0, min(fs, FS * avail / max(w, 1)))
            lh = fs * 1.2
            block = lh * len(texts)
            if v_al == "top":
                ty = y0 + PAD
            elif v_al == "center":
                ty = (y0 + y1 - block) / 2
            else:
                ty = max(y0 + PAD, y1 - PAD - block)
            for k, t in enumerate(texts):
                if not t.strip():
                    continue
                w = pymupdf.get_text_length(t, fontname=font, fontsize=fs)
                if h_al in ("center", "centerContinuous"):
                    tx = (x0 + x1 - w) / 2
                elif h_al == "right" or (h_al in (None, "general") and is_num):
                    tx = x1 - PAD - w
                else:
                    tx = x0 + PAD
                base = ty + lh * k + fs
                page.insert_text((tx, base), t, fontname=font, fontsize=fs)
                frags.append((round(base - fs * 0.35, 1), tx, t, font, fs, cell, k, w))
        frags.sort(key=lambda f: (f[0], f[1]))
        page_lines = []
        for f in frags:                                # one text line per baseline (cells side by side)
            if page_lines and abs(page_lines[-1][0] - f[0]) <= 1.5:
                page_lines[-1][1].append(f)
            else:
                page_lines.append((f[0], [f]))
        for y, fr in page_lines:
            fr.sort(key=lambda f: f[1])
            ln = Line(sh.page, y)
            text, offs = "", []
            for f in fr:
                if text:
                    text += SEP
                bbox = (f[1], y - f[4] * 0.65, f[1] + f[7], y + f[4] * 0.45)
                sp = Span(f[2], bbox, f[3], f[4], 0, 0, (f[1], y))
                ln.spans.append(sp)
                offs.append((len(text), len(text) + len(f[2]), sp))
                cell = f[5]
                if f[6] == 0 or cell.line is None:
                    cell.line, cell.start, cell.end = ln, len(text), len(text) + len(f[2])
                text += f[2]
            ln._text, ln._offs = text, offs
            lines.append(ln)
    pdf.set_metadata({"title": out.stem, "producer": "LDV (drawn from Excel)"})
    pdf.save(out)
    pdf.close()
    return lines


# --------------------------------------------------------------------------------------------- sheet roles

def sheet_role(sh: Sheet) -> str | None:
    t = sh.text().upper()
    head = " ".join(c.text.upper() for c in sh.cells[:12])
    if "SALES CONTRACT" in head or re.search(r"THE SELLER\s*:", t) and re.search(r"THE BUYER\s*:", t):
        return "SC"
    if re.search(r"INVOICE NO", t) and re.search(r"N\.\s*W\.|G\.\s*W\.|MEASUREMENT", t):
        return "PL"
    if re.search(r"INVOICE NO", t) and re.search(r"UNIT PRICE|AMOUNT", t):
        return "INV"
    if "PACKING LIST" in t:
        return "PL"
    if "COMMERCIAL INVOICE" in t:
        return "INV"
    return None


def split(path: Path, outdir: Path) -> list:
    """The workbook as documents: [(kind 'CI' | 'SC', pdf path, [Sheet], lines)]. CI = invoice + packing list."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    groups = {"CI": [], "SC": []}
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        sh = Sheet(ws, 0)
        role = sheet_role(sh)
        if role in ("INV", "PL"):
            groups["CI"].append((role, ws))
        elif role == "SC":
            groups["SC"].append((role, ws))
    out = []
    if groups["CI"]:                               # invoice page first, then the packing list: one document
        items = sorted(groups["CI"], key=lambda x: x[0] != "INV")
        sheets = [Sheet(ws, i) for i, (_, ws) in enumerate(items)]
        for sh, (role, _) in zip(sheets, items):
            sh.role = role
        pdf = outdir / f"{path.stem} [Invoice+PL].pdf"
        out.append(("CI", pdf, sheets, draw(sheets, pdf)))
    for n, (role, ws) in enumerate(groups["SC"], 1):  # every contract sheet is a contract of its own
        sh = Sheet(ws, 0)
        sh.role = role
        pdf = outdir / f"{path.stem} [Contract{'' if n == 1 else ' ' + str(n)}].pdf"
        out.append(("SC", pdf, [sh], draw([sh], pdf)))
    return out


# --------------------------------------------------------------------------------------------- reading the cells

_MODEL_CELL = re.compile(r"^[A-Z][A-Za-z0-9]*-[A-Za-z0-9\-]+(?:\([A-Za-z0-9]+\)[A-Za-z0-9]*)?(?:-[A-Za-z0-9]+)*$")
_CONTAINER = re.compile(r"\b([A-Z]{4}\d{7})\b")
_CNTR_TYPE = re.compile(r"\b(\d{2})\s*'?\s*(HQ|HC|GP|DC|RF|OT|FR)\b", re.I)


def _f(cell, value=None, a=0, b=None, raw=None):
    """A Field for the cell (or for the characters a:b of its text)."""
    from .extract import Field
    b = len(cell.text) if b is None else b
    t = cell.text[a:b]
    if cell.line is None:                          # not drawn: no place
        return Field(t if value is None else value, raw or t, Line(cell.page, 0.0), 0, 0)
    first = cell.line.text[cell.start:cell.end]    # only the first text line of a cell has offsets
    if b > len(first):
        a, b = 0, len(first)
    return Field(t if value is None else value, raw if raw is not None else t, cell.line, cell.start + a, cell.start + b)


def _number(cell):
    v = cell.value
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _date_of(cell):
    from .util import parse_date
    v = cell.value
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return parse_date(str(v))


def _label(sh, rx):
    """(label cell, value cell) for the first label cell matching rx, or (None, None). The value may be written in
    the label cell itself ('Country of origin: China'): then (label cell, ('same', offset))."""
    for c in sh.find(rx):
        m = re.search("(?:" + rx + r")\s*[:：]?\s*(.*)$", c.text, re.I)
        if m and m.group(m.re.groups).strip():
            return c, ("same", m.start(m.re.groups))
        v = sh.right(c)
        if v is not None:
            return c, v
    return None, None


def _value(sh, rx, conv=None):
    lab, v = _label(sh, rx)
    if lab is None:
        return None
    if isinstance(v, tuple):
        k = v[1]
        t = lab.text[k:].strip()
        return _f(lab, conv(t) if conv else t, k, k + len(t))
    return _f(v, conv(v) if conv else None)


def _header(sh, need: dict):
    """The table header row: (row, {name: column}) for the first row that has every name of need (rx per name)."""
    for r in sorted({c.row for c in sh.cells}):
        cells = sh.row(r)
        cols = {}
        for name, rx in need.items():
            hit = next((c for c in cells if re.search(rx, c.text.replace("\n", " "), re.I)), None)
            if hit:
                cols[name] = hit.col
        if all(k in cols for k in need):
            return r, cols
    return None, {}


def _model_col(sh, r_head, cols_exclude):
    """The column holding models under the header: a 'MODEL NO' heading, else the column with most model texts."""
    for c in sh.cells:
        if c.row > r_head and re.match(r"\s*MODEL\s*NO", c.text, re.I):
            return c.col, c.row
    counts = {}
    for c in sh.cells:
        if c.row > r_head and c.col not in cols_exclude and _MODEL_CELL.match(c.text.strip()):
            counts[c.col] = counts.get(c.col, 0) + 1
    return (max(counts, key=counts.get), r_head) if counts else (None, r_head)


def _items(sh, qty_col, model_col, start_row, extra: dict):
    """Goods rows: a model in the model column and a number in the quantity column."""
    from .extract import PO_RE
    rows = []
    for r in sorted({c.row for c in sh.cells if c.row > start_row}):
        mc, qc = sh.at.get((r, model_col)), sh.at.get((r, qty_col))
        if mc is None or qc is None or _number(qc) is None or not _MODEL_CELL.match(mc.text.strip()):
            continue
        it = dict(model=mc.text.strip(), model_f=_f(mc), qty=_f(qc, _number(qc)), row=r)
        for k, col in extra.items():
            c = sh.at.get((r, col))
            it[k] = _f(c, _number(c)) if c is not None and _number(c) is not None else None
        po = next((re.search(PO_RE, c.text) for c in sh.row(r) if re.search(PO_RE, c.text)), None)
        it["po"] = po[0] if po else None
        rows.append(it)
    return rows


def _goods_heading(sh, r_head, model_row):
    """The goods description printed between the table header and the model rows ('ACME FAN AND ACME HEATER')."""
    for c in sorted(sh.cells, key=lambda c: (c.row, c.col)):
        if r_head < c.row <= model_row and len(c.text) > 8 and re.search(r"[A-Za-z]{3}", c.text) \
                and not re.match(r"\s*(MODEL|CONTAINER|N/?M\b|PR NO)", c.text, re.I) \
                and not re.match(r"\s*(FOB|CIF|CFR|CIP|CPT|EXW|FCA|DAP|DDP)\b", c.text):
            return c
    return None


def _incoterm(sh, r_head):
    """('CIF PORT A' Field, port Field, term) from the price-column heading, or (None, None, None)."""
    from .extract import Field
    for c in sorted(sh.cells, key=lambda c: (c.row, c.col)):
        m = re.match(r"\s*(FOB|CIF|CFR|CIP|CPT|EXW|FCA|DAP|DDP)\s+([A-Z][A-Za-z ]*?[A-Za-z])(?=\s*,|\s*$)", c.text)
        if m and c.row >= (r_head or 0):
            return (Field(f"{m[1]} {m[2].upper()}", c.text.strip(), c.line, c.start + m.start(), c.start + m.end()),
                    _f(c, m[2], m.start(2), m.end(2)), m[1])
    return None, None, None


def _company(sh):
    """The company printed at the top of the sheet (the issuer)."""
    for c in sorted(sh.cells, key=lambda c: (c.row, c.col))[:4]:
        if re.search(r"\b(CO\.?|LTD\.?|LIMITED|PTE|CORP(ORATION)?|INC\.?|COMPANY)\b", c.text, re.I):
            return _f(c, c.text.strip())
    return None


def _amount_words(sh):
    c = next(iter(sh.find(r"^\s*SAY\b")), None)
    return _f(c, c.text.strip()) if c else None


def _charges(sh, r_head, amount_col):
    """Charges billed on their own row (CIF: freight, insurance): part of the total amount, not goods."""
    out = []
    for c in sh.cells:
        if c.row > r_head and re.fullmatch(r"\s*(?:Ocean\s+)?(Freight|Insurance)(?:\s+Premium)?\s*", c.text, re.I):
            a = sh.at.get((c.row, amount_col))
            if a is not None and _number(a) is not None:
                out.append(dict(name=c.text.strip().lower(), label=_f(c), amount=_f(a, _number(a))))
    return out


def _currency(sh, r_head):
    cur = next((c for c in sh.cells if c.row >= (r_head or 0) - 1 and re.fullmatch(r"\s*(USD|EUR|JPY|VND)\s*", c.text)),
               None) or next((c for c in sh.cells if re.search(r"\bUSD\b|U\.S\. DOLLARS", c.text)), None)
    if cur is None:
        return None
    m = re.search(r"USD|EUR|JPY|VND|U\.S\. DOLLARS", cur.text)
    return _f(cur, "USD" if m[0].startswith("U") else m[0], m.start(), m.end())


def _port(f):
    if f is not None:
        f.value = re.split(r"\s*,", f.value)[0].strip()
    return f


def read_ci(d, sheets):
    """Invoice + packing-list sheets of one workbook into the fields the PDF invoice reader fills."""
    from .extract import Field, PO_RE, item_id
    from .util import num
    inv = next((s for s in sheets if s.role == "INV"), None)
    pl = next((s for s in sheets if s.role == "PL"), None)
    absent = []
    pos = set()
    for sh in sheets:
        for c in sh.cells:
            pos.update(re.findall(PO_RE, c.text))
    first = d.lines[0] if d.lines else Line(0, 0.0)
    if pos:
        d.f["pos"] = Field(sorted(pos), "", first, 0, 0)
    d.lists["fob"] = []
    if inv is not None:
        d.f["invoice_no"] = _value(inv, r"^\s*Invoice\s*No\.?")
        d.f["invoice_date"] = _value(inv, r"^\s*(?:Inv(?:oice)?\.?\s*)?Date", conv=_date_of)
        d.f["pod"] = _port(_value(inv, r"^\s*PORT OF (?:DISCHARGE|DESTINATION)"))
        d.lists["pod"] = [d.f["pod"]] if d.f["pod"] else []
        d.f["payment"] = _value(inv, r"^\s*Terms? of Payment")
        d.f["consignee"] = _value(inv, r"^\s*Messrs")
        d.f["shipper"] = _company(inv)
        d.f["origin"] = _value(inv, r"^\s*COUNTRY OF ORIGIN")
        r_head, cols = _header(inv, dict(qty=r"Quantity", price=r"Unit\s*Price", amount=r"^\s*Amount"))
        if r_head:
            mcol, mrow = _model_col(inv, r_head, set(cols.values()))
            if mcol:
                for it in _items(inv, cols["qty"], mcol, mrow, dict(price=cols["price"], amount=cols["amount"])):
                    it["desc"] = None
                    d.items.append(it)
            g = _goods_heading(inv, r_head, mrow if mcol else r_head + 3)
            if g:
                d.f["goods"] = _f(g, g.text.strip())
                d.f["goods_full"] = d.f["goods"]
            inc, port, term = _incoterm(inv, r_head)
            if inc:
                d.f["incoterm"] = inc
                if term == "FOB":
                    d.lists["fob"] = [port]
                    d.f["pol"] = port
            d.lists["charges"] = _charges(inv, r_head, cols["amount"])
            for c in inv.cells:
                if c.row > r_head and re.match(r"\s*(TOTAL AMOUNT|TOTAL)\s*[:：]?\s*$", c.text, re.I):
                    a = inv.at.get((c.row, cols["amount"])) or next(
                        (x for x in inv.row(c.row) if x.col > c.col and _number(x) is not None), None)
                    if a is not None and _number(a) is not None:
                        d.f["total_amount"] = _f(a, _number(a))
                    q = inv.at.get((c.row, cols["qty"]))
                    if q is not None and _number(q) is not None:
                        d.f["total_qty"] = _f(q, _number(q))
            d.f["currency"] = _currency(inv, r_head)
            d.lists["currency"] = [d.f["currency"]] if d.f["currency"] else []
            qh = inv.at.get((r_head, cols["qty"]))
            u = re.search(r"\b(SETS?|PCS|PIECES?|UNITS?)\b", qh.text.upper()) if qh is not None else None
            if u:                                     # 'Quantity (SETS)': the unit of every quantity below
                d.f["qty_unit"] = _f(qh, u[1], u.start(), u.end())
        d.f["amount_words"] = _amount_words(inv)
        if not d.f.get("total_qty"):
            absent.append("total_qty")                # the invoice prints line quantities only
    if pl is not None:
        d.pl_page = pl.page                           # the packing list is its own sheet (page)
        r_head, cols = _header(pl, dict(qty=r"Quantity.*(SET|PCS|UNIT)", ctn=r"Quantity.*(CTN|CARTON)|^\s*CTNS",
                                        nw=r"N\.\s*W", gw=r"G\.\s*W", cbm=r"Measurement|CBM|M3"))
        if r_head:
            mcol, mrow = _model_col(pl, r_head, set(cols.values()))
            cntr = None
            if mcol:
                for it in _items(pl, cols["qty"], mcol, mrow, dict(ctn=cols["ctn"], nw=cols["nw"], gw=cols["gw"],
                                                                  cbm=cols["cbm"])):
                    for c in pl.row(it["row"]):                # '1.ABCD1234567/40HQ': the container this row starts
                        m = _CONTAINER.search(c.text)
                        if m and c.col != mcol:
                            cntr = dict(no=_f(c, m[1], m.start(1), m.end(1)), type=_CNTR_TYPE.search(c.text),
                                        cell=c)
                            d.lists.setdefault("pl_containers", []).append(cntr)
                    ctn = it["ctn"]
                    d.pl_items.append(dict(model=it["model"], model_f=it["model_f"], qty=it["qty"],
                                           ctn=ctn.value if ctn else None, ctn_f=ctn, nw=it["nw"], gw=it["gw"],
                                           cbm=it["cbm"], desc=None, rng=None, po=it["po"], no=None,
                                           container=cntr["no"].value if cntr else None))
            for c in pl.cells:
                if c.row > r_head and re.match(r"\s*(TOTAL|TTL)\s*[:：]?\s*$", c.text, re.I):
                    for k in ("qty", "ctn", "nw", "gw", "cbm"):
                        x = pl.at.get((c.row, cols[k]))
                        d.f[f"pl_total_{k}"] = _f(x, _number(x)) if x is not None and _number(x) is not None else None
            g = _goods_heading(pl, r_head, mrow if mcol else r_head + 3)
            if g:
                d.f["pl_goods_full"] = _f(g, g.text.strip())
            w = next(iter(pl.find(r"TOTAL PACKED IN")), None)
            if w is not None:
                m = re.search(r"IN\s+(.+?)\s*\(\s*([\d,]+)\s*\)\s*(CARTONS?|CTNS?|PACKAGES?|PALLETS?)", w.text, re.I)
                if m:
                    d.f["pl_ctn_words"] = _f(w, m[1].upper(), m.start(1), m.end(1))
                    d.f["pl_ctn_words_fig"] = _f(w, num(m[2]), m.start(2), m.end(2))
            cs = d.lists.get("pl_containers", [])
            if cs:
                d.f["containers"] = _f(cs[0]["cell"], len(cs))       # the count of the container rows
                nos = ", ".join(dict.fromkeys(c["no"].value for c in cs))
                d.f["cntr_nos"] = Field(nos, nos, cs[0]["no"].line, cs[0]["no"].start, cs[0]["no"].end)
                types = {}
                for c in cs:
                    if c["type"]:
                        t = f"{c['type'][1]}{c['type'][2].upper()}"
                        types[t] = types.get(t, 0) + 1
                if types:
                    v = ",".join(f"{n}x{t}" for t, n in types.items())
                    d.lists["cntr_types"] = [Field(v, v, cs[0]["no"].line, cs[0]["no"].start, cs[0]["no"].end)]
        d.f["pl_consignee"] = _value(pl, r"^\s*Messrs")
        d.f["pl_shipper"] = _company(pl)
        pl_pos = sorted({x for c in pl.cells for x in re.findall(PO_RE, c.text)})
        if pl_pos:
            d.f["pl_pos"] = Field(pl_pos, "", pl.cells[0].line, 0, 0)
        cs = d.lists.get("pl_containers", [])
        if cs:                                        # the packing list's own container count (its container rows)
            d.f["pl_containers"] = _f(cs[0]["cell"], len(cs))
            d.f["pl_cntr_nos"] = d.f.get("cntr_nos")
        # header fields the packing-list sheet does not print at all: 'not printed' (cross-check), not 'not read'
        pt = pl.text()
        for k, rx in (("pl_vessel", r"VESSEL|SHIPPED BY|\bM/?V\b"), ("pl_incoterm", r"\b(?:FOB|CIF|CFR|CIP|CPT|EXW|FCA|DAP|DDP)\b"),
                      ("pl_freight", r"\bFREIGHT\b"), ("pl_origin", r"\bORIGIN\b|MADE IN"),
                      ("pl_payment", r"PAYMENT"), ("pl_pos", PO_RE), ("pl_shipper", r"\b(?:LTD|LIMITED|PTE|INC|CORP)")):
            if not d.f.get(k) and not re.search(rx, pt, re.I):
                absent.append(k)
        d.f["pl_pod"] = _port(_value(pl, r"^\s*PORT OF (?:DISCHARGE|DESTINATION)"))
        d.f["pl_invoice_no"] = _value(pl, r"^\s*Invoice\s*No\.?")
        d.f["pl_date"] = _value(pl, r"^\s*Date", conv=_date_of)
        d.f["pl_goods_full"] = d.f.get("pl_goods_full")
    d.lists["headers"] = [dict(no=x, date=y) for x, y in ((d.f.get("invoice_no"), d.f.get("invoice_date")),
                                                           (d.f.get("pl_invoice_no"), d.f.get("pl_date"))) if x and y]
    # what this layout does not print at all: 'not on this document' (not 'not read')
    whole = "\n".join(sh.text() for sh in sheets)
    for k, rx in (("vessel", r"VESSEL|SHIPPED BY|\bM/?V\b"), ("sailing", r"SAILING|ON BOARD|\bETD\b"),
                  ("freight", r"FREIGHT\s+(COLLECT|PREPAID)"), ("eta", r"\bETA\b"),
                  ("pol", r"PORT OF LOADING|\bFOB\b|\bFROM\s*:"), ("pl_pol", r"PORT OF LOADING|\bFROM\s*:"),
                  ("pl_sailing", r"SAILING|\bETD\b"), ("containers", r"CONTAINER|\b\d{2}\s*'?\s*(HQ|HC|GP)\b")):
        if not d.f.get(k) and not re.search(rx, whole, re.I):
            absent.append(k)
    if not pos:
        absent.append("pos")
    if absent:
        d.f["absent"] = Field(", ".join(absent), "", first, 0, 0)
    d.item_ids = [item_id(d.lines, it) for it in d.items]
    d.pl_item_ids = [item_id(d.lines, it) for it in d.pl_items]


def read_sc(d, sheets):
    """One sales-contract sheet into the fields the PDF contract reader fills."""
    from .extract import Field, PO_RE
    sh = sheets[0]
    first = d.lines[0] if d.lines else Line(0, 0.0)
    lab, v = _label(sh, r"^\s*No\.?")
    if lab is not None and v is not None and not isinstance(v, tuple):
        nos = [v] + [c for c in sh.cells if c.col == v.col and v.row < c.row <= v.row + 3
                     and re.fullmatch(PO_RE, c.text.strip())]
        raw = ",".join(c.text.strip() for c in nos)
        d.f["sc_no"] = _f(v, raw)
        d.f["pos"] = Field(sorted(set(re.findall(PO_RE, raw))), "", v.line, v.start, v.end)
    buyer = sh.find(r"The Buyer")
    d.f["sc_date"] = None
    for c in sorted(sh.cells, key=lambda c: (c.row, c.col)):   # the contract date: a date cell above the buyer
        if c.row <= (buyer[0].row if buyer else 20) and (
                isinstance(c.value, (datetime, date)) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", c.text.strip())):
            d.f["sc_date"] = _f(c, _date_of(c))
            break
    d.f["seller"] = _value(sh, r"^\s*The Seller")
    d.f["buyer"] = _value(sh, r"^\s*The Buyer")
    d.f["origin"] = None
    for c in sh.find(r"COUNTRY OF ORIGIN"):
        m = re.search(r"COUNTRY OF ORIGIN\s*[:：]?\s*([A-Za-z][A-Za-z ]*?[A-Za-z])\s*$", c.text, re.I)
        if m:
            d.f["origin"] = _f(c, m[1], m.start(1), m.end(1))
        elif sh.right(c):
            d.f["origin"] = _f(sh.right(c))
        break
    r_head, cols = _header(sh, dict(no=r"^\s*NO\.?\s*$", qty=r"QTY|Quantity", price=r"U/?\s*PRICE|Unit Price",
                                    amount=r"AMOUNT"))
    d.lists["fob"] = []
    sc_absent = []
    if r_head:
        mcol, mrow = _model_col(sh, r_head, set(cols.values()))
        if mcol:
            for it in _items(sh, cols["qty"], mcol, r_head, dict(price=cols["price"], amount=cols["amount"])):
                noc = sh.at.get((it["row"], cols["no"]))
                it["no"] = _f(noc, int(_number(noc))) if noc is not None and _number(noc) is not None else None
                d.items.append(it)
        g = _goods_heading(sh, r_head, r_head + 3)
        if g:
            d.f["goods_full"] = _f(g, g.text.strip())
            d.f["goods"] = d.f["goods_full"]
        inc, port, term = _incoterm(sh, r_head)
        if inc:
            d.f["incoterm"] = inc
            if term == "FOB":
                d.lists["fob"] = [port]
                d.f["fob_port"] = port
            else:                                     # CIF / CFR …: the contract names the destination, no loading port
                sc_absent.append("fob_port")
        d.lists["charges"] = _charges(sh, r_head, cols["amount"])
        for c in sh.cells:
            if c.row > r_head and re.match(r"\s*TOTAL\s*[:：]?\s*$", c.text, re.I):
                q, a = sh.at.get((c.row, cols["qty"])), sh.at.get((c.row, cols["amount"]))
                d.f["total_qty"] = _f(q, _number(q)) if q is not None and _number(q) is not None else None
                d.f["total_amount"] = _f(a, _number(a)) if a is not None and _number(a) is not None else None
                break
        d.f["currency"] = _currency(sh, r_head)
        d.lists["currency"] = [d.f["currency"]] if d.f["currency"] else []
    d.f["amount_words"] = _amount_words(sh)
    d.f["shipment_by"] = None
    absent = sc_absent
    for c in sh.find(r"^\s*SHIPMENT\s*$"):
        for x in sh.row(c.row):
            if x.col > c.col and (isinstance(x.value, (datetime, date)) or _date_of(x)):
                d.f["shipment_by"] = _f(x, _date_of(x))
                break
        if d.f["shipment_by"] is None and not [x for x in sh.row(c.row) if x.col > c.col and not re.fullmatch(r"\s*By\s*", x.text, re.I)]:
            d.f["blank:shipment_by"] = _f(c, c.text.strip())   # the term is printed with nothing after it
            absent.append("shipment_by")
        break
    for c in sh.find(r"^\s*PAYMENT\s*$"):
        v = sh.right(c)
        if v is not None:
            d.f["payment"] = _f(v, v.text.strip())
        break
    docs, on = [], None
    for c in sorted(sh.cells, key=lambda c: (c.row, c.col)):
        if re.search(r"DOCUMENTS REQUIRED", c.text, re.I):
            on = c.row
            continue
        if on and re.match(r"\s*\d+\.\d", c.text):
            docs.append(c.text.strip())
        elif on and c.row > on and re.fullmatch(r"\s*\d+\s*", c.text):
            break
    d.f["docs_required"] = Field(" | ".join(docs), "", first, 0, 0)
    if absent:
        d.f["absent"] = Field(", ".join(absent), "", first, 0, 0)
