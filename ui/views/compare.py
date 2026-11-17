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
        field_col = t1("cmp_field")
        col_names = [f"{_name(x)}" + (f" ({x['n_docs']})" if x["n_docs"] > 1 else "") for x in cols]
        res_col = t1("cmp_result")
        data = [{field_col: _name(r) + (f" ({r['unit']})" if r["unit"] else ""),
                 **{cn: _cell_text(r["cells"][x["id"]]) for cn, x in zip(col_names, cols)},
                 res_col: f"{RESULT_ICON[r['result']]} {t1('cmp_' + r['result'])}"} for r in shown]
        df = pd.DataFrame(data)

        def paint(row):
            r = shown[row.name]
            out = [""]
            for x in cols:
                cell = r["cells"][x["id"]]
                key = "odd" if cell.get("odd") else cell["state"] if cell["state"] != "value" else None
                out.append(f"background-color: {BG[key]}; color: {'#b3261e' if key == 'odd' else '#80868b' if key in ('na', 'nodoc') else ''}"
                           if key else "")
            out.append("font-weight: 600; color: #b3261e" if r["result"] == "mismatch" else "")
            return out

        ev = st.dataframe(df.style.apply(paint, axis=1), hide_index=True, width="stretch", on_select="rerun",
                          selection_mode="single-cell", key=f"cmp_tbl_{only}_{lang()}",
                          height=38 + 35 * len(df),
                          column_config={field_col: st.column_config.TextColumn(width="medium"),
                                         res_col: st.column_config.TextColumn(width="medium")})
        st.caption(t("cmp_legend"))
        cells = ev.selection.cells if ev and ev.selection and hasattr(ev.selection, "cells") else []
        if cells:
            ri, cname = cells[0][0], cells[0][1]
            if cname in col_names and ri < len(shown):
                detail(shown[ri], cols[col_names.index(cname)], s)

    lines(c, s)
    if c["not_read"]:
        st.caption(t("cmp_not_read", fields=", ".join(_name(x) for x in c["not_read"])))


def detail(r: dict, col: dict, s: dict):
    cell = r["cells"][col["id"]]
    with st.container(border=True):
        st.markdown(f"**{ui.esc(_name(r))} — {ui.esc(_name(col))}**")
        if cell["state"] == "value":
            docs = cell.get("docs") or [cell["doc"]]
            st.markdown(f"`{cell['show']}`" + (f" {r['unit']}" if r["unit"] else ""))
            st.caption(" · ".join(docs) + (f" · {t1('page')} {cell['page']}" if cell.get("page") else ""))
            if cell.get("odd"):
                st.markdown(ui.chip(t1("cmp_odd"), "ERROR"), unsafe_allow_html=True)
            st.button(t1("cmp_open"), icon=":material/find_in_page:", on_click=_open, args=(cell["doc"], cell.get("page")),
                      key=f"cmp_go_{r['id']}_{col['id']}")
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
