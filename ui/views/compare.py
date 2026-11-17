"""Cross-check: the same information side by side across the documents of the open review.

Only values LDV extracted are shown. A value that is not on a kind of document is 'not applicable', a value that
should be there but was not read is 'not read' — neither is counted as a mismatch. Click a value to open its page.
"""
import pandas as pd
import streamlit as st

from engine.compare import compare

from .. import components as ui
from .. import state
from ..i18n import lang, langs, t, t1

RESULT_ICON = dict(match="✅", mismatch="❌", incomplete="⚠️", single="•", none="—")
BG = dict(odd="#fce8e6", missing="#fef7e0", na="#f8f9fa", nodoc="#f1f3f4")
# text colours telling the values of one row apart: the same value has the same colour in every document
# (red stays for "differs from the other documents")
PALETTE = ["#1a5fb4", "#8e24aa", "#00796b", "#c25e00", "#5d4037", "#c2185b", "#3949ab", "#558b2f"]

TABLE_CSS = """<style>
.ldv-xc {border-collapse: collapse; width: 100%; font-size: 0.86rem; margin: 0.3rem 0 0.4rem 0;}
.ldv-xc th {position: sticky; top: 0; background: #f8f9fa; text-align: left; font-weight: 600; color: #3c4043;
            padding: 6px 8px; border-bottom: 1px solid #dadce0; white-space: nowrap;}
.ldv-xc td {padding: 5px 8px; border-bottom: 1px solid #eceff1; vertical-align: top; line-height: 1.35;}
.ldv-xc td.f {font-weight: 500; color: #202124; white-space: nowrap;}
.ldv-xc td.r {white-space: nowrap;}
.ldv-xc td.r.mismatch {color: #b3261e; font-weight: 600;}
.ldv-xc .v {display: block; word-break: break-word;}
.ldv-xc .doc {color: #80868b; font-size: 0.72rem; margin-left: 4px; white-space: nowrap;}
.ldv-xc .sum {display: block; border-top: 1px dashed #dadce0; margin-top: 2px; padding-top: 1px; font-weight: 600;}
.ldv-xc td.odd {background: #fce8e6;} .ldv-xc td.odd .v {color: #b3261e !important; font-weight: 600;}
.ldv-xc td.missing {background: #fef7e0; color: #5f6368;} .ldv-xc td.na, .ldv-xc td.nodoc {color: #9aa0a6;}
</style>"""


def _name(x: dict) -> str:
    return " / ".join(x[l] for l in langs())


def _cell_text(c: dict) -> str:
    return {"value": c.get("show", ""), "missing": t1("cmp_missing"), "na": "·", "nodoc": t1("cmp_nodoc")}[c["state"]]


def _open(doc: str, page: int | None):
    st.session_state.update(f_doc=doc, v_page=page or 1, f_sel=None)
    state.go("review")


def render():
    s = state.current()
    if not s:
        st.info(t("no_workspace"))
        return
    ui.header(t("cmp_title"), ui.esc(f"{s['shipment']} · " + t("cmp_sub")))
    if not any(d.get("fields") for d in s["docs"]):
        st.info(t("cmp_legacy"))
        return
    c = compare(s)
    cols = [x for x in c["columns"]]
    rows = c["rows"]
    n = {k: sum(r["result"] == k for r in rows) for k in RESULT_ICON}

    ui.stats([(t1("cmp_match"), n["match"]), (t1("cmp_mismatch"), n["mismatch"]),
              (t1("cmp_incomplete"), n["incomplete"]), (t1("cmp_single"), n["single"])])
    only = st.segmented_control(t1("cmp_show"), ["all", "diff"], default="all", key="cmp_only",
                                label_visibility="collapsed",
                                format_func=lambda k: t1("cmp_all") if k == "all" else t1("cmp_diff"))
    shown = [r for r in rows if only != "diff" or r["result"] in ("mismatch", "incomplete")]
    if not shown:
        st.success(t("cmp_no_diff"))
    else:
        st.markdown(TABLE_CSS + table_html(shown, cols), unsafe_allow_html=True)
        st.caption(t("cmp_legend") + " " + t("cmp_colors"))
        source_picker(shown, cols, s)

    lines(c, s)
    if c["not_read"]:
        st.caption(t("cmp_not_read", fields=", ".join(_name(x) for x in c["not_read"])))


def _colors(r: dict, cols: list) -> dict:
    """Colour per value of the row, in the order values first appear. Values the comparison counts as the same
    (8450 = 8450.11.90, 1,065 = 1,065.00) share a colour; no colours when the whole row is one value."""
    from engine.compare import _same
    keys, groups = [], []                          # groups: [representative key, colour index]
    for x in cols:
        cell = r["cells"][x["id"]]
        if cell["state"] != "value":
            continue
        for k in [k for p in cell.get("parts") or [] for k in p["norm"]] + list(cell.get("norm") or []):
            if k in keys:
                continue
            keys.append(k)
            g = next((g for g in groups if g[0] is not None and k is not None and _same([g[0]], [k], r["type"])), None)
            groups.append([k, g[1] if g else len({g[1] for g in groups})])
    if len({g[1] for g in groups}) < 2:
        return {}
    return {k: PALETTE[i % len(PALETTE)] for k, i in groups}


def _span(text: str, color: str | None, extra: str = "") -> str:
    style = f' style="color:{color}"' if color else ""
    return f'<span class="v"{style}>{ui.esc(text)}{extra}</span>'


def _cell_html(r: dict, cell: dict, colors: dict) -> str:
    if cell["state"] != "value":
        return ui.esc(_cell_text(cell))
    parts = cell.get("parts") or []
    if r["type"] == "number" and len(parts) > 1:      # one figure per document, then their total
        out = "".join(_span(p["show"][0] if p["show"] else "", colors.get(p["norm"][0] if p["norm"] else None),
                            f'<span class="doc">{ui.esc(_short(p["doc"]))}</span>') for p in parts)
        tot = colors.get(cell["norm"][0]) if cell.get("norm") else None
        return out + f'<span class="sum"{f" style=\"color:{tot}\"" if tot else ""}>Σ {ui.esc(cell["items"][0])}</span>'
    return "".join(_span(v, colors.get(k)) for v, k in zip(cell.get("items") or [cell.get("show", "")],
                                                        cell.get("norm") or [None]))


def _short(name: str) -> str:
    stem = name.rsplit(".", 1)[0]
    return stem if len(stem) <= 22 else stem[:20] + "…"


def table_html(shown: list, cols: list) -> str:
    head = "".join(f"<th>{ui.esc(_name(x))}" + (f" ({x['n_docs']})" if x["n_docs"] > 1 else "") + "</th>" for x in cols)
    rows = []
    for r in shown:
        colors = _colors(r, cols)
        tds = []
        for x in cols:
            cell = r["cells"][x["id"]]
            cls = "odd" if cell.get("odd") else cell["state"] if cell["state"] != "value" else ""
            tds.append(f'<td class="{cls}">{_cell_html(r, cell, colors)}</td>')
        name = _name(r) + (f" ({r['unit']})" if r["unit"] else "")
        res = f"{RESULT_ICON[r['result']]} {t1('cmp_' + r['result'])}"
        rows.append(f'<tr><td class="f">{ui.esc(name)}</td>{"".join(tds)}'
                    f'<td class="r {r["result"]}">{ui.esc(res)}</td></tr>')
    return (f'<div style="overflow-x:auto"><table class="ldv-xc"><thead><tr><th>{ui.esc(t1("cmp_field"))}</th>{head}'
            f'<th>{ui.esc(t1("cmp_result"))}</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def source_picker(shown: list, cols: list, s: dict):
    """Where a value comes from: pick the field and the document, see the value and open its page."""
    with st.expander(t1("cmp_source"), icon=":material/find_in_page:"):
        a, b = st.columns(2)
        ri = a.selectbox(t1("cmp_field"), range(len(shown)), format_func=lambda i: _name(shown[i]), key="cmp_src_row")
        r = shown[ri]
        opts = [i for i, x in enumerate(cols) if r["cells"][x["id"]]["state"] in ("value", "missing")]
        if not opts:
            st.caption(t("cmp_na_txt"))
            return
        ci = b.selectbox(t1("cmp_doc"), opts, format_func=lambda i: _name(cols[i]), key=f"cmp_src_col_{r['id']}")
        detail(r, cols[ci], s)


def detail(r: dict, col: dict, s: dict):
    cell = r["cells"][col["id"]]
    with st.container(border=True):
        st.markdown(f"**{ui.esc(_name(r))} — {ui.esc(_name(col))}**")
        if cell["state"] == "value":
            if cell.get("odd"):
                st.markdown(ui.chip(t1("cmp_odd"), "ERROR"), unsafe_allow_html=True)
            for i, p in enumerate(cell.get("parts") or [dict(doc=cell["doc"], page=cell.get("page"), show=[cell["show"]])]):
                x, y = st.columns([3, 1])
                x.markdown(f"`{', '.join(p['show'])}`" + (f" {r['unit']}" if r["unit"] else "") +
                           f"  \n<span style='color:#80868b;font-size:0.8rem'>{ui.esc(p['doc'])}"
                           + (f" · {t1('page')} {p['page']}" if p.get("page") else "") + "</span>", unsafe_allow_html=True)
                y.button(t1("cmp_open"), icon=":material/find_in_page:", on_click=_open, args=(p["doc"], p.get("page")),
                         key=f"cmp_go_{r['id']}_{col['id']}_{i}")
        elif cell["state"] == "missing":
            st.write(t("cmp_missing_txt"))
            st.button(t1("cmp_open"), icon=":material/find_in_page:", on_click=_open, args=(cell["doc"], 1),
                      key=f"cmp_go_{r['id']}_{col['id']}")
        elif cell["state"] == "na":
            st.write(t("cmp_na_txt"))
        else:
            st.write(t("cmp_nodoc_txt"))


def lines(c: dict, s: dict):
    if not c["lines"]:
        return
    st.subheader(t("cmp_lines"))
    st.caption(t("cmp_lines_sub"))
    srcs = ["CI", "PL", "SC", "CO"]
    cols = {x["id"]: x for x in c["columns"]}
    qn = {k: f"{t1('cmp_qty')} · {_name(cols[k])}" for k in srcs}
    pn = {k: f"{t1('cmp_price')} · {_name(cols[k])}" for k in ("CI", "SC")}
    data = []
    for r in c["lines"]:
        row = {t1("hs_col_model"): r["model"]}
        for k in srcs:
            row[qn[k]] = f"{r['qty'][k]:,.0f}" if k in r["qty"] else (t1("cmp_missing") if k in r["missing"] else "·")
        for k in pn:
            row[pn[k]] = f"{r['price'][k]:,.2f}" if r["price"].get(k) is not None else "·"
        row[t1("cmp_result")] = f"{RESULT_ICON[r['result']]} {t1('cmp_' + r['result'])}"
        data.append(row)
    df = pd.DataFrame(data)

    def paint(row):
        r = c["lines"][row.name]
        out = [""]
        for k in srcs:
            out.append(f"background-color: {BG['odd']}; color: #b3261e" if r["qty_odd"] and k in r["qty"] else
                       f"background-color: {BG['missing']}" if k in r["missing"] else "")
        for k in pn:
            out.append(f"background-color: {BG['odd']}; color: #b3261e" if r["price_odd"] and k in r["price"] else "")
        out.append("font-weight: 600; color: #b3261e" if r["result"] == "mismatch" else "")
        return out

    ev = st.dataframe(df.style.apply(paint, axis=1), hide_index=True, width="stretch", on_select="rerun",
                      selection_mode="single-cell", key=f"cmp_lines_{lang()}", height=38 + 35 * len(df))
    cells = ev.selection.cells if ev and ev.selection and hasattr(ev.selection, "cells") else []
    if cells:
        ri, cname = cells[0][0], cells[0][1]
        k = next((k for k, v in {**qn, **pn}.items() if v == cname), None)
        r = c["lines"][ri] if ri < len(c["lines"]) else None
        if r and k and r["doc"].get(k):
            st.button(t1("cmp_open_line", doc=r["doc"][k], page=r["page"].get(k) or 1), icon=":material/find_in_page:",
                      on_click=_open, args=(r["doc"][k], r["page"].get(k)), key=f"cmp_line_go_{ri}_{k}")
