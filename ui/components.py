"""Small reusable UI pieces: styling, severity chips, workflow stepper, bars, number tiles."""
import html

import streamlit as st

from engine.rules import SEVERITY

from .i18n import sev_short, t1

# MINOR is dark enough to read as text on white (contrast about 5:1)
COLOR = dict(ERROR="#d93025", WARNING="#e8710a", MINOR="#8a6700", INFO="#1a73e8", RESOLVED="#188038",
             WAITING="#8e6c00", MUTED="#5f6368")
TINT = dict(ERROR="#fce8e6", WARNING="#feefe3", MINOR="#fef7e0", INFO="#e8f0fe", RESOLVED="#e6f4ea", MUTED="#f1f3f4",
            WAITING="#fef7e0")
ICON = dict(ERROR="🔴", WARNING="🟠", MINOR="🟡", INFO="🔵")
STATUS_COLOR = dict(open="MUTED", in_review="INFO", waiting="WAITING", fixed="RESOLVED", accepted="RESOLVED",
                    not_error="MUTED")

CSS = """
<style>
  /* tighter, document-tool feel */
  .block-container {padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1500px;}
  h1 {font-size: 1.55rem !important; font-weight: 650 !important; padding-bottom: .1rem !important;}
  h2 {font-size: 1.15rem !important; font-weight: 620 !important;}
  h3 {font-size: 1.0rem !important; font-weight: 620 !important;}
  [data-testid="stSidebar"] {background: #f7f8fa; border-right: 1px solid #e3e5e8;}
  [data-testid="stSidebarHeader"] {padding-bottom: .25rem;}
  header[data-testid="stHeader"] {background: rgba(255,255,255,.96);}
  [data-testid="stExpander"] details {border-color: #e3e5e8;}
  [data-testid="stExpander"] summary p {font-size: .93rem;}
  .ldv-sub {color: #5f6368; font-size: .88rem; margin: -.35rem 0 .6rem 0;}
  .ldv-label {color: #5f6368; font-size: .74rem; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
              margin: .2rem 0 .35rem 0;}
  .ldv-chip {display: inline-block; padding: 0 .45rem; border-radius: 4px; font-size: .74rem; font-weight: 600;
             line-height: 1.35rem; white-space: nowrap;}
  .ldv-ws {font-size: .85rem; line-height: 1.35;}
  .ldv-ws b {font-size: .92rem;}
  .ldv-ws .muted {color: #5f6368;}

  /* workflow stepper */
  .ldv-steps {display: flex; gap: 0; margin: .25rem 0 1rem 0; flex-wrap: wrap;}
  .ldv-step {display: flex; align-items: center; font-size: .82rem; color: #80868b; padding-right: .9rem;}
  .ldv-step .dot {width: 1.25rem; height: 1.25rem; border-radius: 50%; border: 1.5px solid #c4c7cc; display: inline-flex;
                  align-items: center; justify-content: center; font-size: .7rem; margin-right: .4rem; background: #fff;}
  .ldv-step.done {color: #188038;} .ldv-step.done .dot {border-color: #188038; background: #188038; color: #fff;}
  .ldv-step.now {color: #202124; font-weight: 600;} .ldv-step.now .dot {border-color: #1a73e8; color: #1a73e8;}
  .ldv-step .bar {width: 1.6rem; height: 1px; background: #c4c7cc; margin-left: .9rem;}
  .ldv-step .extra {color: #5f6368; font-weight: 400; margin-left: .3rem;}

  /* verdict banner */
  .ldv-verdict {border-left: 4px solid; padding: .55rem .9rem; border-radius: 4px; font-weight: 600; font-size: .95rem;
                margin: .2rem 0 .8rem 0;}
  .ldv-verdict small {display: block; font-weight: 400; color: #3c4043; font-size: .82rem; margin-top: .1rem;}

  /* number tiles = buttons in a keyed container */
  div[class*="st-key-tile_"] button {width: 100%; min-height: 4.1rem; justify-content: flex-start; text-align: left;
        background: #fff; border: 1px solid #e3e5e8; border-left-width: 4px; border-radius: 6px; padding: .35rem .7rem;}
  div[class*="st-key-tile_"] button:hover {border-color: #c4c7cc; background: #fafbfc;}
  div[class*="st-key-tile_"] button p {font-size: .78rem; color: #5f6368; margin: 0; line-height: 1.25;}
  div[class*="st-key-tile_"] button p strong {font-size: 1.45rem; color: #202124; font-weight: 650; display: block;
        line-height: 1.6rem;}
  div[class*="st-key-tile_"] button:disabled {opacity: 1; cursor: default;}
  div[class*="st-key-tile_"] button:disabled p strong {color: #80868b;}

  /* horizontal bars */
  .ldv-bars {display: grid; grid-template-columns: 7.5rem 1fr 2.2rem; gap: .35rem .6rem; align-items: center;
             font-size: .84rem;}
  .ldv-track {background: #f1f3f4; border-radius: 3px; height: .6rem; overflow: hidden;}
  .ldv-fill {height: 100%; border-radius: 3px;}
  .ldv-stack {display: flex; height: .7rem; border-radius: 3px; overflow: hidden; background: #f1f3f4; margin: .3rem 0 .4rem 0;}
  .ldv-legend {font-size: .8rem; color: #3c4043;} .ldv-legend span {margin-right: .9rem; white-space: nowrap;}
  .ldv-legend i {display: inline-block; width: .6rem; height: .6rem; border-radius: 2px; margin-right: .3rem;}

  /* document navigator (findings page) */
  div[class*="st-key-docbtn_"] button {width: 100%; justify-content: flex-start; text-align: left; padding: .35rem .6rem;
        border: 1px solid transparent; background: transparent;}
  div[class*="st-key-docbtn_"] button:hover {background: #eef1f4; border-color: transparent;}
  div[class*="st-key-docbtn_"] button[kind="primary"] {background: #e8f0fe; color: #174ea6; border-color: #d2e3fc;}
  div[class*="st-key-docbtn_"] button > div, div[class*="st-key-docbtn_"] button [data-testid="stMarkdownContainer"]
        {width: 100%; justify-content: flex-start; text-align: left;}
  div[class*="st-key-docbtn_"] button p {font-size: .84rem; margin: 0; line-height: 1.3; overflow-wrap: anywhere;
        text-align: left;}
  div.st-key-docnav {position: sticky; top: 3.8rem;}
  div[class*="st-key-fbtn_"] button {width: 100%; justify-content: flex-start; text-align: left; padding: .3rem .55rem;
        border: 1px solid transparent; background: transparent; min-height: 0;}
  div[class*="st-key-fbtn_"] button:hover {background: #eef1f4;}
  div[class*="st-key-fbtn_"] button[kind="primary"] {background: #e8f0fe; color: #174ea6; border-color: #d2e3fc;}
  div[class*="st-key-fbtn_"] button > div, div[class*="st-key-fbtn_"] button [data-testid="stMarkdownContainer"]
        {width: 100%; justify-content: flex-start; text-align: left;}
  div[class*="st-key-fbtn_"] button p {font-size: .83rem; margin: 0; line-height: 1.3; text-align: left;}

  div[class*="st-key-ev_"] button {justify-content: flex-start; text-align: left; padding-left: 0;}
  div[class*="st-key-ev_"] button p {text-align: left; font-size: .84rem;}

  /* icon-only buttons: the label stays for screen readers but is not shown */
  div.st-key-pg_prev button p, div.st-key-pg_next button p, div.st-key-fprev button p, div.st-key-fnext button p,
  div.st-key-fclose button p {position: absolute !important; width: 1px; height: 1px; overflow: hidden;
        clip: rect(0 0 0 0); white-space: nowrap;}

  /* page viewer */
  .ldv-viewer {overflow: auto; background: #e8eaed; border: 1px solid #dadce0; border-radius: 6px; padding: 12px;}
  .ldv-viewer:focus {outline: 2px solid #aecbfa;}
  .ldv-viewer.ldv-pannable .ldv-text {cursor: grab;}
  .ldv-viewer.ldv-panning, .ldv-viewer.ldv-panning * {cursor: grabbing !important; user-select: none;}
  .ldv-zbar {position: sticky; top: 0; left: 0; height: 0; z-index: 6; display: flex; justify-content: flex-end;}
  .ldv-zbar > div {display: flex; margin: -4px -4px 0 0; background: #fff; border: 1px solid #dadce0; border-radius: 6px;
                   box-shadow: 0 1px 3px rgba(0,0,0,.18); height: 30px;}
  .ldv-zbar button {border: 0; background: none; min-width: 30px; padding: 0 6px; font: 500 15px/28px sans-serif;
                    color: #3c4043; cursor: pointer;}
  .ldv-zbar button:hover {background: #f1f3f4;}
  .ldv-zbar .ldv-zpct {font-size: 12px; min-width: 48px; border-left: 1px solid #e3e5e8; border-right: 1px solid #e3e5e8;}
  .ldv-page {position: relative; margin: 0 auto; background: #fff; box-shadow: 0 1px 4px rgba(0,0,0,.2);
             container-type: inline-size;}
  .ldv-page img {width: 100%; height: auto; max-width: none !important; object-fit: fill !important; display: block;
                 user-select: none; -webkit-user-drag: none;}   /* never drawn smaller than its box: boxes must match */
  .ldv-box {position: absolute; border: 2px solid; border-radius: 2px; pointer-events: none; z-index: 1;}
  .ldv-box.ldv-ref {border-style: dashed;}
  .ldv-box.ldv-focus {border-width: 3px; z-index: 3;}
  .ldv-tag {position: absolute; bottom: 100%; left: -2px; color: #fff; font: 600 11px/15px sans-serif; padding: 0 4px;
            border-radius: 2px 2px 0 0; white-space: nowrap;}
  .ldv-hit {position: absolute; background: rgba(251,188,4,.42); pointer-events: none; z-index: 1;}
  .ldv-text {position: absolute; inset: 0; z-index: 2; overflow: hidden; font-size: 1px; line-height: 0;}
  .ldv-text span {position: absolute; color: transparent; white-space: pre; line-height: 1; cursor: text;
                  font-family: Arial, sans-serif;}
  .ldv-text span::selection {background: rgba(26,115,232,.32); color: transparent;}
  .ldv-detail {border: 1px solid #e3e5e8; border-radius: 6px; padding: .7rem .85rem; background: #fff;}
  .ldv-detail .t {font-weight: 620; font-size: .98rem; margin: .35rem 0 .5rem 0; line-height: 1.35;}
  .ldv-kv {display: grid; grid-template-columns: auto 1fr; gap: .15rem .8rem; font-size: .86rem; margin: .2rem 0 .5rem 0;}
  .ldv-kv .k {color: #5f6368;}
  .ldv-kv code {font-size: .84rem;}
  .ldv-val {font-family: ui-monospace, Consolas, monospace; font-size: .86rem; padding: 0 .3rem; border-radius: 3px;}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def chip(text: str, color: str) -> str:
    return (f'<span class="ldv-chip" style="background:{TINT.get(color, TINT["MUTED"])};'
            f'color:{COLOR.get(color, COLOR["MUTED"])}">{esc(text)}</span>')


def sev_chip(sev: str) -> str:
    return chip(sev_short(sev).upper(), sev)


def header(title: str, sub: str = ""):
    st.title(title)
    if sub:
        st.markdown(f'<div class="ldv-sub">{sub}</div>', unsafe_allow_html=True)


def label(text: str):
    st.markdown(f'<div class="ldv-label">{esc(text)}</div>', unsafe_allow_html=True)


def stepper(s: dict | None, c: dict | None = None):
    """Upload → Analyze → Review findings → Resolve → Report, derived from the real state (nothing assumed)."""
    if not s:
        states, extra = ["now", "", "", "", ""], ["", "", "", "", ""]
    else:
        handled = c["done"] if c else 0
        todo = c["actionable"] if c else 0
        reviewed = c and (handled + c["waiting"] + c["in_review"]) > 0
        resolved = todo == 0 or handled == todo
        from engine.review_report import history as made
        n_rep = len(made(s))
        states = ["done", "done", "done" if reviewed or todo == 0 else "now",
                  "done" if resolved else ("now" if reviewed else ""),
                  "done" if n_rep else ("now" if resolved else "")]
        extra = ["", "", "", f"{handled}/{todo}" if todo else "", str(n_rep) if n_rep else ""]
    keys = ["step_upload", "step_analyze", "step_review", "step_resolve", "step_report"]
    parts = []
    for i, (k, stt, ex) in enumerate(zip(keys, states, extra)):
        mark = "✓" if stt == "done" else str(i + 1)
        bar = '<span class="bar"></span>' if i < len(keys) - 1 else ""
        ex = f'<span class="extra">{esc(ex)}</span>' if ex else ""
        parts.append(f'<div class="ldv-step {stt}"><span class="dot">{mark}</span>{esc(t1(k))}{ex}{bar}</div>')
    st.markdown(f'<div class="ldv-steps">{"".join(parts)}</div>', unsafe_allow_html=True)


def stats(items: list[tuple[str, object]]):
    """A row of small label/value pairs."""
    cells = "".join(f'<div><div class="ldv-label">{esc(l)}</div><div style="font-size:1.15rem;font-weight:600">'
                    f'{esc(v)}</div></div>' for l, v in items)
    st.markdown(f'<div style="display:flex;gap:2.5rem;margin:.3rem 0 .6rem 0">{cells}</div>', unsafe_allow_html=True)


def verdict(text: str, color: str, small: str = ""):
    sm = f"<small>{esc(small)}</small>" if small else ""
    st.markdown(f'<div class="ldv-verdict" style="border-color:{COLOR[color]};background:{TINT[color]};'
                f'color:{COLOR[color]}">{esc(text)}{sm}</div>', unsafe_allow_html=True)


def tile(key: str, value, caption: str, color: str = "MUTED", disabled: bool = False) -> bool:
    """A clickable number. Returns True when clicked."""
    with st.container(key=f"tile_{key}"):
        st.markdown(f"<style>div.st-key-tile_{key} button {{border-left-color: {COLOR[color]} !important;}}</style>",
                    unsafe_allow_html=True)
        return st.button(f"**{value}**\n\n{caption}", key=f"btn_{key}", disabled=disabled, width="stretch")


def bars(rows: list[tuple[str, int, str]], total: int):
    """rows = (label, value, colour key)."""
    out = []
    for lab, v, col in rows:
        w = 0 if not total else max(2 if v else 0, round(100 * v / total))
        out.append(f'<div>{esc(lab)}</div><div class="ldv-track"><div class="ldv-fill" '
                   f'style="width:{w}%;background:{COLOR[col]}"></div></div><div style="text-align:right">{v}</div>')
    st.markdown(f'<div class="ldv-bars">{"".join(out)}</div>', unsafe_allow_html=True)


def stack(parts: list[tuple[str, int, str]]):
    total = sum(v for _, v, _ in parts) or 1
    seg = "".join(f'<div style="width:{100 * v / total}%;background:{COLOR[c]}"></div>' for _, v, c in parts if v)
    leg = "".join(f'<span><i style="background:{COLOR[c]}"></i>{esc(l)} {v}</span>' for l, v, c in parts)
    st.markdown(f'<div class="ldv-stack">{seg}</div><div class="ldv-legend">{leg}</div>', unsafe_allow_html=True)


def sev_order(sev: str) -> int:
    return SEVERITY.index(sev) if sev in SEVERITY else 9


def size_txt(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024

