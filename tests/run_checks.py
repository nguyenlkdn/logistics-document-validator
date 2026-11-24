"""Check runner tests (LDV 2.3, P1): every check leaves a record, nothing passes without its inputs.

  python tests/run_checks.py            # exit code 1 on any failure
  python tests/run_checks.py --local    # also T1 / T2 / T4 on the local test sets in tests/baseline (not committed)

T1-T18 as listed in docs/P1_DESIGN.md §7 and the P1 brief. The package below is invented (ACME, AB-X10, PORT A …),
built in memory: no real document is needed and none may ever be copied into this file.
"""
import copy
import os
import sys
import tempfile
import traceback
from contextlib import contextmanager
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["LDV_DATA_DIR"] = tempfile.mkdtemp(prefix="ldv_checks_data_")
import logging                                                  # noqa: E402

logging.getLogger("ldv.checks").setLevel(logging.CRITICAL)      # T3 / T18 raise on purpose
from engine import checks, master, rules                        # noqa: E402
from engine.checks import REGISTRY, CheckStatus, verdict        # noqa: E402
from engine.extract import Doc, Field                           # noqa: E402
from engine.pdftext import Line, Span                           # noqa: E402
from engine.rules import Finding, validate_checks               # noqa: E402

FAILS = []


def test(name):
    def deco(fn):
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as e:                                   # noqa: BLE001 — report every failure, keep going
            FAILS.append(name)
            print(f"FAIL  {name}: {e}")
            traceback.print_exc(limit=3)
        return fn
    return deco


# ----------------------------------------------------------------------------------------------- invented package
def _line(text, y=0.0, page=0):
    return Line(page, y, [Span(text, (40, y, 40 + 5 * len(text), y + 8), "helv", 8, 0, 0, (40, y))])


def F(v, raw=None):
    raw = raw if raw is not None else (v if isinstance(v, str) else str(v))
    return Field(v, raw, _line(raw), 0, len(raw))


def mk(kind, name, texts, f, items=(), pl_items=(), lists=None):
    d = Doc(Path(name), kind, [_line(t, 12.0 * i) for i, t in enumerate(texts)], 595, True)
    d.f.update(f)
    d.items, d.pl_items, d.lists = list(items), list(pl_items), dict(lists or {})
    return d


INV, PO, MODEL = "ACME0001", "PR123456789012", "AB-X10(W1)VN"
D_INV, D_SAIL = date(2026, 11, 1), date(2026, 11, 10)


def package(inv=INV, model=MODEL, qty=100.0, ctn=100, gw=1000.0, nw=900.0, cbm=5.0, amount=1000.0, name="acme"):
    ci = mk("CI", f"{name}_ci.pdf", [
        "< COMMERCIAL INVOICE >", f"INVOICE NO. {inv}   DATE : 01/11/2026", f"P/O NO.{PO}",
        f"TTL :   {ctn} CARTON(S)   {qty:.0f} SET(S)   IN USD {amount:,.2f}", "< COMMERCIAL INVOICE / ATTACHMENT >",
        f"TTL :   {ctn} CARTON(S)   {qty:.0f} SET(S)   IN USD {amount:,.2f}", "< PACKING LIST >",
        f"INVOICE NO. {inv}   DATE : 01/11/2026", f"CARTON 1-{ctn}   {qty:.0f} SET(S)   {nw}   {gw}   {cbm}",
        f"TTL:   {ctn} CARTON(S)   {qty:.0f} SET(S)   {nw}   {gw}   {cbm}", "SHIPPING MARK & NO.", model,
        "FREIGHT COLLECT"],
        dict(invoice_no=F(inv), invoice_date=F(D_INV, "01/11/2026"), sailing=F(D_SAIL, "10/11/2026"),
             vessel=F(("ACME STAR", "001N"), "ACME STAR V.001N"), pol=F("PORT A"), pod=F("PORT B"), containers=F(1, "1"),
             goods=F("RICE COOKER"), pos=F([PO], PO), total_amount=F(amount, f"{amount:,.2f}"), total_qty=F(qty, f"{qty:.0f}"),
             pl_total_qty=F(qty, f"{qty:.0f}"), pl_total_nw=F(nw), pl_total_gw=F(gw), pl_total_cbm=F(cbm),
             pl_total_ctn=F(float(ctn), str(ctn)), origin=F("THAILAND"), payment=F("T/T 30 DAYS"),
             consignee=F("BUYER CO., LTD."), shipper=F("ACME CO., LTD."), currency=F("USD"),
             goods_full=F('"ACME" BRAND RICE COOKER'), incoterm=F("FOB PORT A"), freight=F("COLLECT"),
             **{f"pl_{k}": v for k, v in dict(consignee=F("BUYER CO., LTD."), shipper=F("ACME CO., LTD."),
                                               vessel=F(("ACME STAR", "001N"), "ACME STAR V.001N"), pol=F("PORT A"),
                                               pod=F("PORT B"), sailing=F(D_SAIL, "10/11/2026"), payment=F("T/T 30 DAYS"),
                                               origin=F("THAILAND"), goods_full=F('"ACME" BRAND RICE COOKER'),
                                               pos=F([PO], PO), containers=F(1, "1"), incoterm=F("FOB PORT A"),
                                               freight=F("COLLECT")).items()}),
        items=[dict(model=model, qty=F(qty, f"{qty:.0f}"), price=F(amount / qty, f"{amount / qty:.2f}"),
                    amount=F(amount, f"{amount:,.2f}"), po=PO, desc=F("RICE COOKER 1.0L"), no=1)],
        pl_items=[dict(model=model, ctn=ctn, ctn_f=F(ctn, f"CARTON 1-{ctn}"), desc=F("RICE COOKER 1.0L"), rng=(1, ctn),
                       qty=F(qty, f"{qty:.0f}"), nw=F(nw), gw=F(gw), cbm=F(cbm), po=PO, no=1)],
        lists=dict(fob=[F("PORT A")], currency=[F("USD")], marks_models=[F(model)], pl_marks_models=[F(model)],
                   ci_ttls=[dict(ctn=F(float(ctn), str(ctn)), qty=F(qty), amount=F(amount))] * 2,
                   pl_ttls=[dict(ctn=F(float(ctn), str(ctn)), qty=F(qty), nw=F(nw), gw=F(gw), cbm=F(cbm))] * 2,
                   headers=[dict(no=F(inv), date=F(D_INV, "01/11/2026"))] * 2, cover_pos=[F([PO], PO)],
                   cntr_types=[F("1x40HQ")], pod=[F("PORT B")]))
    sc = mk("SC", f"{name}_sc.pdf", ["Sales Contract", f"No. : {PO}/1", "FOB PORT A", "7. DOCUMENTS REQUIRED",
                                     "7.4. Certificate of origin (Form D)"],
            dict(sc_no=F(f"{PO}/1"), pos=F([PO], PO), sc_date=F(date(2026, 10, 30), "30/10/2026"),
                 shipment_by=F(date(2026, 11, 20), "20-NOV-2026"), payment=F("By T/T 30 DAYS"),
                 total_amount=F(amount), total_qty=F(qty), docs_required=F("7.4. Certificate of origin (Form D)"),
                 seller=F("ACME CO., LTD."), buyer=F("BUYER CO., LTD."), origin=F("Thailand"),
                 goods_full=F('"ACME" BRAND RICE COOKER'), incoterm=F("FOB PORT A"), fob_port=F("PORT A"), currency=F("USD")),
            items=[dict(no=F(1, "1"), model=model, qty=F(qty), price=F(amount / qty), amount=F(amount))],
            lists=dict(fob=[F("PORT A")], currency=[F("USD")]))
    bl = mk("BL", f"{name}_bl.pdf", ["[ Shipper ]", "ACMU1234567/ SEAL1/ 40HC", "SHIPPING MARK & NO.", model,
                                     f"{ctn} CARTONS  ({qty:.0f} SETS)", "ONE (1) CONTAINER(S) ONLY", "FREIGHT COLLECT"],
            dict(bl_no=F("ACMEBL000001"), vessel=F(("ACME STAR", "001N"), "ACME STAR/ 001N"), pol=F("PORT A"),
                 pod=F("PORT B"), containers=F(1, "1"), gw=F(gw), cbm=F(cbm), ctn=F(float(ctn), str(ctn)),
                 invoice_no=F(inv), hs=F("8516"), cntr_summary=F("1X40'HC"), cntr_words=F("ONE"), cntr_words_n=F(1, "1"),
                 goods=F("RICE COOKER"), bl_qty=F(qty), bl_unit=F("SETS"), bl_qty_ctn=F(float(ctn), str(ctn)),
                 bl_qty_phrase=F(f"{ctn} CARTONS  ({qty:.0f} SETS)"), final_dest=F("CAT LAI"), delivery=F("CAT LAI"),
                 shipper=F("ACME CO., LTD."), consignee=F("BUYER CO., LTD."), dest_country=F("VIETNAM"),
                 goods_full=F('"ACME" BRAND RICE COOKER'), freight=F("COLLECT"), origin=F("THAILAND")),
            lists=dict(cntr=[F(("ACMU1234567", "40HC"), "40HC")], invoice_nos=[F(inv)], marks_models=[F(model)],
                       pod=[F("PORT B")]))
    co = mk("CO", f"{name}_co.pdf", ["FORM D", "CERTIFICATE OF ORIGIN", "Page : 1 of 1", model],
            dict(departure=F(D_SAIL, "10/11/2026"), vessel=F(("ACME STAR", "001N"), "ACME STAR V.001N"), pod=F("PORT B"),
                 total_ctn=F(float(ctn), str(ctn)), total_ctn_words=F("ONE HUNDRED"), total_value=F(amount),
                 total_qty=F(qty), exporter=F("ACME CO., LTD."), consignee=F("BUYER CO., LTD."), origin=F("THAILAND"),
                 import_country=F("VIETNAM"), currency=F("USD")),
            items=[dict(no=1, hs="8516.60.10", hs_f=F("8516.60.10"), qty=F(qty), inv_ref=inv, inv_date=F(D_INV, "01/11/2026"),
                        pkg_words="ONE HUNDRED", pkg_fig=F(float(ctn), str(ctn)), per_ctn=1, model=model,
                        goods=F("RICE COOKER"), goods_full=F('"ACME" BRAND RICE COOKER'), inv_ref_f=F(inv))],
            lists=dict(invoices=[dict(no=F(inv), date=F(D_INV, "01/11/2026"))], origin=[F("THAILAND")],
                       import_country=[F("VIETNAM")], pages=[dict(n=1, of=1, f=F("Page : 1 of 1"))], currency=[F("USD")],
                       marks_models=[F(model)]))
    return [ci, sc, bl, co]


def setup_master():
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Mã NPL/SP", "Mã HS"])
    ws.append([MODEL, "8516.60.10"])
    ws.append(["CD-Y20(W1)VN", "8516.60.10"])
    p = Path(os.environ["LDV_DATA_DIR"]) / "master_test.xlsx"
    wb.save(p)
    master.import_xlsx(p)


def by_id(results, cid, group=None):
    return [r for r in results if r.check_id == cid and (group is None or r.group_id == group)]


def status(results, cid, group=None):
    rs = by_id(results, cid, group)
    assert rs, f"{cid}: no record"
    return {r.status for r in rs}


def run(docs):
    fs, res = validate_checks(docs)
    return fs, res


def pv(res):
    return verdict([r.to_dict() for r in res], [])


setup_master()
BASE_FS, BASE_RES = run(package())


@test("T0 the invented package is GREEN: no finding, every core check PASS or NOT_APPLICABLE")
def _():
    bad = [(r.check_id, r.status, r.reason, r.detail) for r in BASE_RES if r.core and r.status not in ("PASS", "NOT_APPLICABLE")]
    assert not BASE_FS, [f.key for f in BASE_FS]
    assert not bad, bad
    nr = [(r.check_id, r.reason, r.detail.get("missing")) for r in BASE_RES if r.status == "NOT_RUN"]
    assert not nr, nr
    v = verdict([r.to_dict() for r in BASE_RES], [dict(no=i, severity=f.severity) for i, f in enumerate(BASE_FS, 1)])
    assert v["state"] == "GREEN", v


# ----------------------------------------------------------------------------------------------- T1 / T4 / T10 helpers
def closure_errors(res, docs):
    errs = [(r.check_id, r.group_id, r.doc, r.reason) for r in res if r.reason in ("not_reported", "internal_error")]
    keys = [(r.check_id, r.group_id, r.doc) for r in res]
    dup = {k for k in keys if keys.count(k) > 1}
    return errs + [("duplicate", *k) for k in dup]


def undeclared(res):
    out = []
    for r in res:
        needs = REGISTRY[r.check_id].needs
        for x in r.inputs:
            key = "master" if x["name"] == "master" else f"{x['kind']}.{x['name']}"
            base = key.split("[")[0]
            if not any(n in (key, base, f"*.{x['name']}", f"*.{x['name'].split('[')[0]}") for n in needs):
                out.append((r.check_id, key))
    return sorted(set(out))


@test("T1 registry closure: one record per applicable check and group, no not_reported / internal_error")
def _():
    assert not closure_errors(BASE_RES, package()), closure_errors(BASE_RES, package())
    ids = {r.check_id for r in BASE_RES}
    assert ids == set(REGISTRY) - {"DOC_PAIRING"} | {"DOC_PAIRING"}, set(REGISTRY) - ids   # every check id has a record
    assert len(REGISTRY) == 107, len(REGISTRY)      # 2.11: MASTER_NAME, MASTER_UNIT; 2.7: + CO_ITEM_VALUE, CO_CRITERION (Form E); 2.8: CNTR_VS_PL, SC_CHARGES; 2.9: the P/O numbers of a contract


@test("T4 declared vs used inputs: every input a check read is declared in CheckDef.needs")
def _():
    assert not undeclared(BASE_RES), undeclared(BASE_RES)


@test("T4b every finding is produced through a registered check, and its key is declared there")
def _():
    docs = package(qty=100.0)
    docs[3].f["total_qty"] = F(99.0, "99")                       # Form D total wrong
    docs[2].f["gw"] = F(999.0, "999.0")                          # B/L G.W. wrong
    fs, res = run(docs)
    assert fs, "expected findings"
    for f in fs:
        assert f.check in REGISTRY, (f.key, f.check)
        keys = REGISTRY[f.check].keys
        assert not keys or f.key in keys, (f.check, f.key)
    linked = {i for r in res for i in r.finding_indexes}
    assert linked == set(range(1, len(fs) + 1)), (linked, len(fs))


# ----------------------------------------------------------------------------------------------- T2 blank-out sweep
@contextmanager
def removed(docs, inp):
    """Take one input away (as if the reader had not found it), restore it afterwards."""
    d = next((x for x in docs if x.name == inp["doc"]), None)
    name = inp["name"]
    saved = []
    if name == "master":
        old = master.load
        master.load = lambda: None
        try:
            yield True
        finally:
            master.load = old
        return
    if d is None:
        yield False
        return
    if name in ("items", "pl_items", "cargo_blocks", "packages"):
        saved.append(("attr", name, getattr(d, name)))
        setattr(d, name, [])
    elif name.startswith("lists."):
        k = name[6:]
        saved.append(("list", k, d.lists.get(k)))
        d.lists[k] = []
    elif name.startswith("Σ"):
        k = name[1:]
        src = {"qty": "total_qty", "amount": "total_amount", "pl_qty": "pl_total_qty"}.get(k, f"pl_total_{k}")
        saved.append(("f", src, d.f.get(src)))
        d.f.pop(src, None)
        attr = "items" if k in ("qty", "amount") else "pl_items"
        saved.append(("attr", attr, getattr(d, attr)))
        setattr(d, attr, [])
        if k == "qty":
            saved.append(("f", "pl_total_qty", d.f.get("pl_total_qty")))
            d.f.pop("pl_total_qty", None)
    elif "[" in name:
        attr, key = name.split("[")[0], name.split("[")[1].rstrip("]")
        rows = getattr(d, attr)
        saved.append(("rows", attr, [dict(r) if isinstance(r, dict) else copy.copy(r) for r in rows]))
        new = []
        for r in rows:                                          # dict rows (items) or dataclasses (CargoBlock, Package)
            r = dict(r) if isinstance(r, dict) else copy.copy(r)
            if isinstance(r, dict):
                r[key] = None
            else:
                setattr(r, key, None)
            new.append(r)
        setattr(d, attr, new)
    elif name in d.f:
        saved.append(("f", name, d.f.get(name)))
        d.f.pop(name)
    else:
        yield False                                            # derived input (e.g. the invoice's unit word)
        return
    try:
        yield True
    finally:
        for kind, k, v in reversed(saved):
            if kind == "attr":
                setattr(d, k, v)
            elif kind == "list":
                if v is None:
                    d.lists.pop(k, None)
                else:
                    d.lists[k] = v
            elif kind == "rows":
                setattr(d, k, v)
            elif v is not None:
                d.f[k] = v


def blank_out(docs, label=""):
    """Every input a passing / failing check read is removed in turn: that check must not PASS and must not vanish."""
    _, res = run(docs)
    problems, n = [], 0
    for r in res:
        if r.status not in (CheckStatus.PASS, CheckStatus.FAIL, CheckStatus.REVIEW_REQUIRED):
            continue
        if REGISTRY[r.check_id].kind == "scan":
            continue                                           # a scan looks at all text; it has no required input
        for inp in [x for x in r.inputs if x["status"] == "READ"]:
            with removed(docs, inp) as ok:
                if not ok:
                    continue
                n += 1
                _, res2 = run(docs)
                again = [x for x in res2 if (x.check_id, x.group_id, x.doc) == (r.check_id, r.group_id, r.doc)]
                if not again:
                    problems.append((label, r.check_id, r.group_id, inp["name"], "vanished"))
                elif again[0].status == CheckStatus.PASS:
                    # allowed only when the check really used another source instead (a fallback it records)
                    before = {(x["doc"], x["name"]) for x in r.inputs}
                    after = {(x["doc"], x["name"]) for x in again[0].inputs}
                    gone = (inp["doc"], inp["name"]) not in after
                    if not (gone and after - before):
                        problems.append((label, r.check_id, r.group_id, inp["kind"] + "." + inp["name"], "PASS without input"))
    return problems, n


@test("T2 blank-out sweep: removing any read input of a check never leaves it PASS, and it never disappears")
def _():
    problems, n = blank_out(package(), "invented")
    assert n > 100, n
    assert not problems, problems[:20]


# ----------------------------------------------------------------------------------------------- T3 / T18 exceptions
@contextmanager
def raising(name):
    old = getattr(rules, name)

    def boom(*a, **k):
        raise KeyError("invented failure")
    boom.__name__ = name                                       # the runner knows a rule by its function name
    setattr(rules, name, boom)
    try:
        yield
    finally:
        setattr(rules, name, old)


@test("T3 exception isolation: a failing rule gives NOT_RUN(internal_error) for its checks, the rest is unchanged")
def _():
    docs = package()
    docs[0].f["vessel"] = F(("OTHER STAR", "001N"), "OTHER STAR V.001N")       # a VESSEL finding that will be lost
    fs0, res0 = run(docs)
    with raising("r_vessel"):
        fs1, res1 = run(docs)
    assert status(res1, "VESSEL.ci") == {"NOT_RUN"} and by_id(res1, "VESSEL.ci")[0].reason == "internal_error"
    assert by_id(res1, "VESSEL.co")[0].reason == "internal_error"
    assert by_id(res1, "VESSEL.ci")[0].detail == dict(rule="r_vessel", error="KeyError")   # no message text
    assert [f.key for f in fs1] == [f.key for f in fs0 if f.key != "VESSEL"]
    others0 = {(r.check_id, r.group_id, r.doc): r.status for r in res0 if not r.check_id.startswith("VESSEL")}
    others1 = {(r.check_id, r.group_id, r.doc): r.status for r in res1 if not r.check_id.startswith("VESSEL")}
    assert others0 == others1


@test("T3b BaseException is not swallowed (KeyboardInterrupt goes through)")
def _():
    old = rules.r_vessel

    def stop(*a, **k):
        raise KeyboardInterrupt
    rules.r_vessel = stop
    try:
        run(package())
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("KeyboardInterrupt was swallowed")
    finally:
        rules.r_vessel = old


@test("T18 a core rule raising an exception: NOT_RUN(internal_error), the verdict cannot be GREEN")
def _():
    with raising("r_line_math"):
        fs, res = run(package())
    r = by_id(res, "TOTAL_QTY.ci")[0]
    assert r.status == "NOT_RUN" and r.reason == "internal_error" and r.core
    assert pv(res)["state"] != "GREEN", pv(res)
    assert pv(res)["internal_errors"] >= 1


# ----------------------------------------------------------------------------------------------- T5 - T8, T15, T16
@test("T5 empty lists: no P/O on the invoice / no lines on both sides -> NOT_RUN, never PASS")
def _():
    docs = package()
    docs[0].f["pos"] = F([], "")                                # today the contract P/O then shows as "extra" (WARNING)
    _, res = run(docs)
    r = by_id(res, "SC_PO_COVERAGE")[0]
    assert r.status != "PASS", r.status
    assert any(x["name"] == "pos" and x["status"] == "NOT_FOUND" for x in r.inputs), r.inputs
    docs[1].f["pos"] = F([], "")                                # nothing on either side: not "all P/O covered"
    _, res = run(docs)
    r = by_id(res, "SC_PO_COVERAGE")[0]
    assert r.status == "NOT_RUN" and r.reason == "field_not_found", (r.status, r.reason)
    docs = package()
    docs[0].items, docs[1].items = [], []
    _, res = run(docs)
    r = by_id(res, "SC_VS_CI")[0]
    assert r.status == "NOT_RUN" and r.reason == "items_not_read", (r.status, r.reason)


@test("T6 Form D applicability comes from the documents: required / not required / unknown")
def _():
    ci, sc, bl, co = package()
    _, res = run([ci, sc, bl])                                  # contract lists Form D, none in the package
    r = by_id(res, "DEPARTURE_DATE")[0]
    assert (r.status, r.reason) == ("NOT_RUN", "document_missing"), (r.status, r.reason)
    ci, sc, bl, co = package()
    sc.f["docs_required"] = F("7.1. Bill of Lading | 7.2. Commercial invoice")
    _, res = run([ci, sc, bl])                                  # contract lists its documents, no Form D among them
    r = by_id(res, "DEPARTURE_DATE")[0]
    assert r.status == "NOT_APPLICABLE" and r.detail.get("evidence") == "sc_docs_without_formd", (r.status, r.detail)
    ci, sc, bl, co = package()
    _, res = run([ci, bl])                                      # nothing says whether a contract / Form D is needed
    for cid in ("DEPARTURE_DATE", "SC_VS_CI"):
        r = by_id(res, cid)[0]
        assert (r.status, r.reason) == ("NOT_RUN", "requirement_unknown"), (cid, r.status, r.reason)


@test("T15 unknown requirement is NOT_RUN(requirement_unknown), never NOT_APPLICABLE; an F.O.C invoice needs none (owner rule)")
def _():
    ci, sc, bl, co = package()
    _, res = run([ci, bl])                                      # nothing says whether a contract / Form D is needed
    sc_co = [r for r in res if set(REGISTRY[r.check_id].kinds) & {"SC", "CO"}]
    assert sc_co and all(r.status == "NOT_RUN" and r.reason == "requirement_unknown" for r in sc_co), \
        {(r.check_id, r.status, r.reason) for r in sc_co if r.reason != "requirement_unknown"}
    assert pv(res)["state"] == "AMBER"
    ci.lines.append(_line("F.O.C   NO COMMERCIAL VALUE", 999))   # owner rule 2026-11-19
    _, res = run([ci, bl])
    sc_co = [r for r in res if set(REGISTRY[r.check_id].kinds) & {"SC", "CO"}]
    assert sc_co and all(r.status == "NOT_APPLICABLE" and r.detail.get("evidence") == "foc_invoice" for r in sc_co), \
        {(r.check_id, r.status, r.reason) for r in sc_co}


@test("2A one wrong B/L cargo block is reported once (the block), the B/L total check follows it")
def _():
    a, b = package(inv="ACME0001", name="a"), package(inv="ACME0002", name="b", model="CD-Y20(W1)VN")
    bl = a[2]
    bl.lists["invoice_nos"] = [F("ACME0001"), F("ACME0002")]
    for k, v in (("gw", 2000.0), ("cbm", 10.0), ("ctn", 200.0)):
        bl.f[k] = F(v)
    from engine.extract import CargoBlock
    bl.cargo_blocks = [CargoBlock(F(100.0), F(103.0), F("PCS"), None, None, F("ACME0001")),
                       CargoBlock(F(100.0), F(100.0), F("PCS"), None, None, F("ACME0002"))]
    bl.f["bl_qty"], bl.f["bl_qty_ctn"] = F(203.0), F(200.0)
    fs, res = run([a[0], a[1], b[0], b[1], bl, a[3], b[3]])
    keys = [f.key for f in fs]
    assert keys.count("BL_BLOCK") == 1 and "BL_QTY" not in keys and "BL_DESC_QTY" not in keys, keys
    r = by_id(res, "BL_CARGO_QTY", "shipment")[0]
    assert (r.status, r.reason) == ("NOT_RUN", "blocked_by") and r.detail.get("by") == "BL_CARGO_BLOCK", (r.status, r.detail)
    assert status(res, "BL_CARGO_BLOCK", "shipment") == {"FAIL"}


@test("T6b Form D naming an invoice of another group: that group needs it (document_missing)")
def _():
    a, b = package(inv="ACME0001", name="a"), package(inv="ACME0002", name="b", model="CD-Y20(W1)VN")
    co = a[3]
    co.lists["invoices"] = [dict(no=F("ACME0001"), date=F(D_INV)), dict(no=F("ACME0002"), date=F(D_INV))]
    docs = [a[0], a[1], b[0], b[1], a[2], co]
    a[2].lists["invoice_nos"] = [F("ACME0001"), F("ACME0002")]
    _, res = run(docs)
    g2 = [r for r in res if r.group_id == "inv2" and r.check_id == "DEPARTURE_DATE"]
    g1 = [r for r in res if r.group_id == "inv1" and r.check_id == "DEPARTURE_DATE"]
    assert g1 and g2, (g1, g2)
    paired = g1[0] if g1[0].status != "NOT_RUN" else g2[0]
    other = g2[0] if paired is g1[0] else g1[0]
    assert (other.status, other.reason) == ("NOT_RUN", "document_missing"), (other.status, other.reason, other.detail)


@test("T7 layout trace: no totals row printed -> NOT_APPLICABLE; printed twice but read once -> NOT_RUN")
def _():
    docs = package()
    ci = docs[0]
    ci.lists["ci_ttls"] = ci.lists["ci_ttls"][:1]               # the invoice prints two TTL rows, one was read
    _, res = run(docs)
    r = by_id(res, "CI_COVER_TOTAL")[0]
    assert r.status == "NOT_RUN", (r.status, r.reason)
    docs = package()
    ci = docs[0]
    ci.lists["ci_ttls"] = ci.lists["ci_ttls"][:1]
    ci.lines = [l for l in ci.lines if not l.text.startswith("TTL")]
    _, res = run(docs)
    r = by_id(res, "CI_COVER_TOTAL")[0]
    assert r.status == "NOT_APPLICABLE" and r.detail.get("evidence") == "not_printed", (r.status, r.detail)


@test("T8 several invoices: B/L cartons NOT_RUN naming the invoice whose cartons were not read; G.W./CBM still PASS")
def _():
    a, b = package(inv="ACME0001", name="a"), package(inv="ACME0002", name="b", model="CD-Y20(W1)VN")
    bl = a[2]
    bl.lists["invoice_nos"] = [F("ACME0001"), F("ACME0002")]
    for k, v in (("gw", 2000.0), ("cbm", 10.0), ("ctn", 200.0)):
        bl.f[k] = F(v)
    bl.f["bl_qty"], bl.f["bl_qty_ctn"] = F(200.0), F(200.0)
    b[0].f.pop("pl_total_ctn")
    b[0].pl_items = [dict(p, ctn=None, rng=None) for p in b[0].pl_items]
    fs, res = run([a[0], a[1], b[0], b[1], bl, a[3], b[3]])
    r = by_id(res, "BL_VS_PL.ctn", "shipment")[0]
    assert r.status == "NOT_RUN", (r.status, r.reason)
    assert any(m["doc"] == "b_ci.pdf" for m in r.detail["missing"]), r.detail
    assert status(res, "BL_VS_PL.gw", "shipment") == {"PASS"} and status(res, "BL_VS_PL.cbm", "shipment") == {"PASS"}
    assert not by_id(res, "BL_VS_PL.ctn", "inv1"), "per-invoice record in a multi-invoice package"


@test("T16 two invoices with the same number keep separate check groups")
def _():
    a, b = package(inv="ACME0001", name="a"), package(inv="ACME0001", name="b", model="CD-Y20(W1)VN")
    _, res = run([a[0], a[1], b[0], b[1], a[2], a[3], b[3]])
    g = {r.group_id for r in res}
    assert {"inv1", "inv2", "shipment"} <= g, g
    l1 = {r.group_label for r in res if r.group_id == "inv1"}
    l2 = {r.group_label for r in res if r.group_id == "inv2"}
    assert l1 == l2 == {"ACME0001"}
    docs1 = {d for r in res if r.group_id == "inv1" for d in r.input_documents}
    docs2 = {d for r in res if r.group_id == "inv2" for d in r.input_documents}
    assert "a_ci.pdf" in docs1 and "a_ci.pdf" not in docs2 and "b_ci.pdf" in docs2


# ----------------------------------------------------------------------------------------------- T9 / T11 / T13 / T14 / T17
def rec(cid, st, core=True, findings=(), detail=None, reason=None):
    return dict(id=cid, status=st, core=core, findings=list(findings), detail=detail or {}, reason=reason)


@test("T9 verdict table")
def _():
    E, W = dict(no=1, severity="ERROR", sig="e"), dict(no=1, severity="WARNING", sig="w")
    cases = [
        ([rec("A", "PASS")], [], "GREEN"),
        ([rec("A", "PASS"), rec("B", "NOT_APPLICABLE")], [], "GREEN"),
        ([rec("A", "NOT_RUN", reason="field_not_found")], [], "AMBER"),
        ([rec("A", "NOT_RUN", reason="master_data_missing")], [], "AMBER"),
        ([rec("A", "REVIEW_REQUIRED", findings=[1])], [W], "AMBER"),
        ([rec("A", "FAIL", findings=[1])], [E], "RED"),
        ([rec("A", "PASS"), rec("X", "NOT_RUN", core=False, reason="field_not_found")], [], "GREEN"),
        ([rec("A", "FAIL", findings=[1]), rec("B", "NOT_RUN", reason="field_not_found")], [E], "RED"),
    ]
    for chk, fs, want in cases:
        v = verdict(chk, fs)
        assert v["state"] == want, (chk, v)
    v = verdict([rec("A", "PASS"), rec("X", "NOT_RUN", core=False, reason="field_not_found")], [])
    assert v["noncore_not_run"] == 1                            # visible even though GREEN
    v = verdict([rec("A", "NOT_RUN", reason="master_data_missing"), rec("B", "NOT_RUN", reason="field_not_found")], [])
    assert v["categories"] == {"master_data": 1, "reading": 1}, v


@test("T13 an open ERROR from a non-core check makes the package RED")
def _():
    v = verdict([rec("A", "PASS"), rec("X", "FAIL", core=False, findings=[1])], [dict(no=1, severity="ERROR", sig="e")])
    assert v["state"] == "RED", v
    docs = package()
    docs[0].f["vessel"] = F(("OTHER STAR", "001N"), "OTHER STAR V.001N")     # VESSEL.ci is not core
    fs, res = run(docs)
    assert not REGISTRY["VESSEL.ci"].id in checks.core_ids()
    v = verdict([r.to_dict() for r in res], [dict(no=i, severity=f.severity) for i, f in enumerate(fs, 1)])
    assert v["state"] == "RED", v


@test("T14 a core check with only a WARNING (no open error) makes the package AMBER")
def _():
    docs = package()
    docs[2].f["consignee"] = F("SOMEONE ELSE CO., LTD.")          # PARTY_NAME is a WARNING, PARTY.consignee is core
    fs, res = run(docs)
    assert {f.severity for f in fs} == {"WARNING"}, [(f.key, f.severity) for f in fs]
    assert status(res, "PARTY.consignee") == {"REVIEW_REQUIRED"}
    v = verdict([r.to_dict() for r in res], [dict(no=i, severity=f.severity) for i, f in enumerate(fs, 1)])
    assert v["state"] == "AMBER", v


@test("T11 severity mapping: ERROR -> FAIL, WARNING -> REVIEW_REQUIRED, MINOR / INFO -> PASS")
def _():
    from engine.checks import Group, Run, begin
    docs = package()
    with Run(docs) as r:
        r.set_group(Group("inv1", "invoice", "x", docs))
        for cid, sev in (("VESSEL.ci", "ERROR"), ("VESSEL.co", "WARNING"), ("CO_NUMBERING", "MINOR"), ("SC_DOCS", "INFO")):
            doc = docs[3] if cid == "CO_NUMBERING" else docs[1] if cid == "SC_DOCS" else None
            ck = begin(cid, [], doc)
            ck.compared()
            ck.add(Finding("X", sev, [docs[0]]))
            ck.end()
        got = {x.check_id: x.status for x in r.results if x.check_id in ("VESSEL.ci", "VESSEL.co", "CO_NUMBERING", "SC_DOCS")}
    assert got == {"VESSEL.ci": "FAIL", "VESSEL.co": "REVIEW_REQUIRED", "CO_NUMBERING": "PASS", "SC_DOCS": "PASS"}, got


@test("T17 reviewer accepts an ERROR: the stored result stays FAIL, the decision is logged apart, the verdict follows")
def _():
    from engine.history import History
    docs = package()
    docs[3].f["total_qty"] = F(99.0, "99")
    fs, res = run(docs)
    stored = [r.to_dict() for r in res]
    findings = [dict(no=i, severity=f.severity, sig=f"sig{i}") for i, f in enumerate(fs, 1)]
    before = copy.deepcopy(stored)
    assert verdict(stored, findings)["state"] == "RED"
    h = History(Path(tempfile.mkdtemp()) / "history.db")
    for f in findings:
        assert h.set_mark("ACME0001", f["sig"], "accepted", "agreed with the supplier", who="Reviewer A")
    marks = h.marks("ACME0001")
    s = dict(schema=2, checks=stored, findings=findings)
    v = checks.effective(s, marks)
    assert v["state"] == "GREEN" and v["reviewer_closed"] == len(findings), v
    assert stored == before, "the stored automated results were changed"
    assert any(r["status"] == "FAIL" for r in stored)
    log = h.log("ACME0001", findings[0]["sig"])
    assert log and log[0]["who"] == "Reviewer A" and log[0]["status"] == "accepted" and log[0]["ts"], log


@test("T17b sign-off: plain approval refused unless GREEN; exception needs a reason")
def _():
    from engine.history import History
    import sqlite3
    h = History(Path(tempfile.mkdtemp()) / "history.db")
    with sqlite3.connect(h.path) as db:
        db.execute("INSERT INTO checks (id, ts, shipment, revision) VALUES (1, '2026-11-01T00:00:00', 'ACME0001', 1)")
    for v in ("AMBER", "RED"):
        try:
            h.sign(1, "approved", "", who="Reviewer A", verdict=v)
        except ValueError:
            pass
        else:
            raise AssertionError(f"approved on {v}")
    try:
        h.sign(1, "approved_exception", "", who="Reviewer A", verdict="AMBER")
    except ValueError:
        pass
    else:
        raise AssertionError("exception without a reason")
    h.sign(1, "approved_exception", "core check not run: checked by hand", who="Reviewer A", verdict="AMBER")
    h.sign(1, "approved", "", who="Reviewer A", verdict="GREEN")
    so = h.signoffs(1)
    assert [x["result"] for x in so] == ["approved", "approved_exception"] and all(x["who"] and x["ts"] for x in so)


# ----------------------------------------------------------------------------------------------- T10 sessions
def _one_pdf(tmp: Path) -> Path:
    import pymupdf
    p = tmp / "acme_invoice.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    for i, t in enumerate(["< COMMERCIAL INVOICE >", f"INVOICE NO. {INV}   DATE : 01/11/2026",
                           "1. P/O NO.PR123456789012", f"{MODEL}", "100 SET(S)   10.00   1,000.00",
                           "TTL :   100 CARTON(S)   100 SET(S)   IN USD 1,000.00"]):
        page.insert_text((40, 40 + 13 * i), t, fontsize=8, fontname="helv")
    doc.save(p)
    return p


@test("T10 sessions: schema 2 round trip; an old schema-1 review opens (legacy); the 2.2.3 loader reads schema 2")
def _():
    import json
    import subprocess
    from engine import check, session
    tmp = Path(tempfile.mkdtemp())
    res = check([_one_pdf(tmp)], out_root=tmp / "out")
    s = session.load(res.out_dir)
    assert s["schema"] == 2 and s["checks"] and s["verdict"]["state"] in ("RED", "AMBER", "GREEN")
    assert all("check" in f for f in s["findings"])
    old = json.loads((res.out_dir / "review.json").read_text())
    for k in ("checks", "verdict"):
        old.pop(k)
    old["schema"] = 1
    for f in old["findings"]:
        f.pop("check", None)
    (res.out_dir / "review.json").write_text(json.dumps(old))
    s1 = session.load(res.out_dir)
    assert s1["schema"] == 1 and checks.effective(s1, {}) is None
    from engine.review_report import outcome
    assert outcome(s1, {})[0].startswith("auto_")               # legacy verdict for an old review
    (res.out_dir / "review.json").write_text(json.dumps(session.build(res), ensure_ascii=False))
    try:                                                        # the loader of the 2.2.3 release on the new file
        src = subprocess.run(["git", "show", "9013811:engine/session.py"], cwd=ROOT, capture_output=True, text=True,
                             check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        print("      (2.2.3 loader check skipped: git history not available)")
        return
    ns = {"__name__": "session_223"}
    exec(compile(src.replace("from .report import plain", "from engine.report import plain")
                 .replace("from .extract import Field", "from engine.extract import Field"), "session_223", "exec"), ns)
    s223 = ns["load"](res.out_dir)
    assert isinstance(s223["findings"], list) and s223["docs"] and s223["schema"] == 2
    assert s223["checks"] == s["checks"] or len(s223["checks"]) == len(s["checks"])   # extra keys passed through
    assert len(s223["findings"]) == len(s["findings"])


@test("Form D item table wrong as a whole (CO_ITEMS): item-by-item pairing checks blocked, header, totals and box-10 / HS / marks still checked")
def _():
    docs = package()
    co = docs[3]
    co.items = [dict(co.items[0], model="AB-X10(W1)VN-XX", qty=F(90.0, "90"))]     # one item, wrong model and quantity
    docs[0].items.append(dict(docs[0].items[0], model="CD-Y20(W1)VN"))            # the invoice has two lines
    co.f["departure"] = F(date(2026, 11, 5), "05/11/2026")                         # a header error stays reported
    fs, res = run(docs)
    keys = {f.key for f in fs}
    assert "CO_ITEMS" in keys and "DEPARTURE_DATE" in keys, keys
    assert not keys & {"CO_QTY", "CO_MODEL", "CO_INVOICE_NO", "CO_INVOICE_DATE", "CO_PKG_COUNT", "CO_MARKS_MODEL"}, keys
    for cid in ("CO_QTY", "CO_MODEL", "CO_PKG", "CO_GOODS_DESC"):
        r = by_id(res, cid)[0]
        assert (r.status, r.reason, r.detail.get("by")) == ("NOT_RUN", "blocked_by", "CO_ITEMS"), (cid, r.status, r.detail)
    for cid in ("CO_HS", "CO_INVOICE_NO", "CO_INVOICE_DATE", "CO_NUMBERING"):        # need no line pairing: they run
        assert all(r.reason != "blocked_by" for r in by_id(res, cid)), (cid, [(r.status, r.detail) for r in by_id(res, cid)])
    assert status(res, "CO_ITEMS") == {"FAIL"}
    f = next(x for x in fs if x.key == "CO_ITEMS")
    assert "missing on Form D: AB-X10(W1)VN, CD-Y20(W1)VN" in f.text("en"), f.text("en")
    assert "not on the invoice: AB-X10(W1)VN-XX" in f.text("en"), f.text("en")
    assert f.current == "1: AB-X10(W1)VN-XX 90" and f.suggested.startswith("2: AB-X10(W1)VN 100, CD-Y20(W1)VN"), (f.current, f.suggested)


@test("Form D TOTAL lines: words and figure both wrong -> one finding over the phrase; one part wrong -> that part")
def _():
    def total_line(words, fig, unit):
        ln = _line(f"TOTAL : {words} ({fig}) {unit}***")
        i = ln.text.index(words)
        j = ln.text.index(f"({fig})") + 1
        return Field(words, words, ln, i, i + len(words)), Field(float(fig), fig, ln, j, j + len(fig))
    docs = package()                                            # invoice / packing list: 100 sets in 100 cartons
    co = docs[3]
    co.f["total_ctn_words"], co.f["total_ctn"] = total_line("NINETY FIVE", "95", "CARTON")
    w, q = total_line("NINETY FIVE", "95", "SET")
    co.f["total_qty"], co.lists["total_qty_words"] = q, [w]
    fs, _res = run(docs)
    tot = sorted((f.params["label"], f.current, f.suggested) for f in fs if f.key == "CO_TOTAL")
    assert tot == [("@ctn_phrase", "NINETY FIVE (95)", "ONE HUNDRED (100)"),
                   ("@total_qty_phrase", "NINETY FIVE (95)", "ONE HUNDRED (100)")], tot
    assert not [f for f in fs if f.key == "WORDS_VS_FIGURES"]
    co.f["total_ctn_words"], co.f["total_ctn"] = total_line("ONE HUNDRED", "95", "CARTON")      # only the figure
    fs, _res = run(docs)
    assert ("@ctn", "95", "100") in {(f.params["label"], f.current, f.suggested) for f in fs if f.key == "CO_TOTAL"}


@test("Form D total value over two lines: words and figure both wrong -> one finding, both lines boxed, Form D style")
def _():
    docs = package()                                            # invoice amount 1,000.00
    co = docs[3]
    l1, l2 = _line("TOTAL : NINE HUNDRED", 1), _line("POINT FIVE ZERO (900.50) USD***", 2)
    k = l2.text.index("900.50")
    co.f["total_value"] = Field(900.5, "900.50", l2, k, k + 6)
    co.lists["total_value_words"] = [Field("NINE HUNDRED", "NINE HUNDRED", l1, 8, 20),
                                     Field("POINT FIVE ZERO", "POINT FIVE ZERO", l2, 0, 15)]
    fs, _res = run(docs)
    f = next(x for x in fs if x.key == "CO_TOTAL" and x.params.get("label") == "@total_value_phrase")
    assert (f.current, f.suggested) == ("NINE HUNDRED POINT FIVE ZERO (900.50)", "ONE THOUSAND POINT ZERO ZERO (1000.00)"), \
        (f.current, f.suggested)
    assert len([l for l in f.locs if l.role == "wrong"]) == 2


@test("a '#n' tag does not sit on printed text when a free place exists")
def _():
    from engine.evidence import tag_places
    box = (100, 100, 180, 112, 1)
    above = (98, 88, 160, 99)                      # the line above the box, under the default 'above' place
    right = (182, 100, 260, 112)                   # text right after the box
    assert tag_places([box], words=[above, right]) not in (["above"], ["right"]), tag_places([box], words=[above, right])
    assert tag_places([box]) == ["above"]          # no text around: the usual place


@test("Form D model error: the invoice reference box is on the invoice's model, not on its quantity")
def _():
    from engine.rules_net import _line_model
    l = _line("    AB-X10(W1)VN   12 PCS   5.00    60.00", 3)
    k = l.text.index("12")
    a = dict(model="AB-X10(W1)VN", qty=Field(12.0, "12", l, k, k + 2))
    f = _line_model(a)
    assert f is not None and l.text[f.start:f.end] == "AB-X10(W1)VN", f
    l2 = _line("    AB-X10 (W1)VN   12 PCS", 4)
    f2 = _line_model(dict(model="AB-X10(W1)VN", qty=Field(12.0, "12", l2, l2.text.index("12"), l2.text.index("12") + 2)))
    assert f2 is not None and l2.text[f2.start:f2.end] == "AB-X10 (W1)VN", f2


@test("B/L shipping marks listing none of the invoice models: one ERROR over the block, per-model warnings withdrawn")
def _():
    docs = package()
    bl = docs[2]
    l = _line("ZZ-900(Q1)VN", 7)
    l2 = _line("YY-120(Q2)VN", 8)
    bl.lists["marks_models"] = [Field("ZZ-900(Q1)VN", "ZZ-900(Q1)VN", l, 0, 12), Field("YY-120(Q2)VN", "YY-120(Q2)VN", l2, 0, 12)]
    fs, res = run(docs)
    none = [f for f in fs if f.key == "MARKS_NONE"]
    assert len(none) == 1 and none[0].severity == "ERROR", [(f.key, f.severity) for f in fs]
    assert len([x for x in none[0].locs if x.role == "wrong"]) == 1        # one box around the block
    assert not [f for f in fs if f.key in ("BL_MARKS_MODEL", "MARKS_MISSING") and f.docs[0] is bl]
    assert any((r.status, r.reason) == ("NOT_RUN", "blocked_by") for r in by_id(res, "BL_MARKS_MODEL", "inv1")), by_id(res, "BL_MARKS_MODEL", "inv1")


@test("B/L marks with the invoice model plus an extra one stay a WARNING (not MARKS_NONE)")
def _():
    docs = package()
    bl = docs[2]
    ci = docs[0]
    m = ci.items[0]["model"]
    l = _line(m, 7); l2 = _line("ZZ-900(Q1)VN", 8)
    bl.lists["marks_models"] = [Field(m, m, l, 0, len(m)), Field("ZZ-900(Q1)VN", "ZZ-900(Q1)VN", l2, 0, 12)]
    fs, _res = run(docs)
    assert not [f for f in fs if f.key == "MARKS_NONE"]
    assert [f.severity for f in fs if f.key == "BL_MARKS_MODEL"] == ["WARNING"], [(f.key, f.severity) for f in fs]


@test("Form D item table wrong (CO_ITEMS): box-10 invoice no. is still checked on every item; a wrong one is reported")
def _():
    docs = package()
    co, ci = docs[3], docs[0]
    extra = dict(co.items[0]); extra["no"] = len(co.items) + 1; extra["inv_ref"] = "ACME9999"; extra["inv_ref_f"] = None
    co.items.append(extra)
    fs, res = run(docs)
    keys = [f.key for f in fs]
    assert "CO_ITEMS" in keys and "CO_INVOICE_NO" in keys, keys
    r = by_id(res, "CO_INVOICE_NO", "inv1")[0]
    assert r.status == "FAIL", (r.status, r.reason)


@test("Not in the HS list: a model on any document (one ERROR), an HS code of the C/O or B/L; look-alikes are typos")
def _():
    key = lambda fs, *ks: [(f.key, f.severity, f.current, sorted(d.kind for d in f.docs)) for f in fs if f.key in ks]
    docs = package()
    ci, sc, bl, co = docs
    for d in (ci, sc, co):
        for it in d.items + d.pl_items:
            it["model"] = "ZZ-777(Q)"
    for d in (bl, co):
        d.lists["marks_models"] = [F("ZZ-777(Q)")]
    co.items[0]["hs"], bl.f["hs"] = "9999.10.10", F("9999")
    bl.lists.pop("hs_codes", None)
    fs, res = run(docs)
    assert key(fs, "HS_MASTER_MISSING") == [("HS_MASTER_MISSING", "ERROR", "ZZ-777(Q)", ["BL", "CI", "CO", "SC"])], key(fs, "HS_MASTER_MISSING")
    assert sorted(x[2] for x in key(fs, "HS_NOT_IN_MASTER")) == ["9999", "9999.10.10"]
    assert status(res, "HS_MASTER") == status(res, "CO_HS") == status(res, "BL_HS") == {"FAIL"}
    assert not closure_errors(res, docs) and not undeclared(res), undeclared(res)
    docs = package()                                              # only the B/L marks show another model
    docs[2].lists["marks_models"] = [F(MODEL), F("ZZ-777(Q)")]
    assert key(run(docs)[0], "HS_MASTER_MISSING") == [("HS_MASTER_MISSING", "ERROR", "ZZ-777(Q)", ["BL"])]
    docs[2].lists["marks_models"] = [F(MODEL[:-1] + "X")]         # one letter off: a typo, reported as one
    assert not key(run(docs)[0], "HS_MASTER_MISSING")
    assert master.lists_hs("8516") and master.lists_hs("8516.60") and not master.lists_hs("85") and not master.lists_hs("8517")
    assert not key(BASE_FS, "HS_MASTER_MISSING", "HS_NOT_IN_MASTER")


@test("HS master missing: the reason names every model to add")
def _():
    from engine.checks import reason_text
    r = dict(status="NOT_RUN", reason="master_data_missing", detail=dict(what="model", models=["AB-X10(W1)VN", "CD-Y20(Q2)VN"]))
    assert "AB-X10(W1)VN, CD-Y20(Q2)VN" in reason_text(r, "en") and "AB-X10(W1)VN" in reason_text(r, "vi")
    assert "city list" in reason_text(dict(status="NOT_RUN", reason="master_data_missing", detail=dict(what="city_list")), "en")


# ----------------------------------------------------------------------------------------------- P5 plausibility gate
def gated(docs):
    from engine.plausibility import mark
    for d in docs:
        mark(d)
    fs, res = run(docs)
    return fs, res, verdict([r.to_dict() for r in res],
                            [dict(no=i, severity=f.severity, suspect=f.suspect, sig=f"s{i}") for i, f in enumerate(fs, 1)])


@test("T19 S1: a total cut out of a larger number is SUSPECT: its ERROR is kept, marked, the package AMBER (not RED)")
def _():
    docs = package()
    ci = docs[0]
    ln = _line("TTL:   100 CARTON(S)   357.00 SET(S)")
    k = ln.text.index("00 SET")                                  # the reader took '00' from '357.00'
    ci.f["total_qty"] = Field(0.0, "00", ln, k, k + 2)
    fs, res, v = gated(docs)
    f = next(x for x in fs if x.key == "TOTAL_QTY")
    assert f.severity == "ERROR" and f.suspect == "S1", (f.severity, f.suspect)
    r = by_id(res, "TOTAL_QTY.ci")[0]
    assert (r.status, r.reason) == ("REVIEW_REQUIRED", "suspect_reading"), (r.status, r.reason)
    assert v["state"] == "AMBER" and v["open_errors"] == 0, v


@test("T20 S2: goods lines not read -> line sums SUSPECT: no confirmed ERROR from them")
def _():
    docs = package()
    ci = docs[0]
    ci.lists["unparsed"] = [_line("SPARE PART   7 PCS   0.70")]
    ci.pl_items[0]["qty"] = F(93.0, "93")                         # the lines that were read add up to less
    fs, res, v = gated(docs)
    lined = [x for x in fs if x.key in ("CI_PL_QTY", "LINES", "PL_LINE", "PL_TOTAL")]
    assert lined and all(x.suspect == "S2" for x in lined), [(x.key, x.suspect) for x in lined]
    assert v["state"] == "AMBER", v


@test("T21 S3: a role label inside a company name is SUSPECT")
def _():
    docs = package()
    docs[0].f["shipper"] = F("CONSIGNEE BUYER CO., LTD.")
    fs, res, v = gated(docs)
    r = by_id(res, "PL_HEADER.shipper")[0]
    # the other documents agree with the packing list, so no PL_HEADER finding: NOT_RUN, still 'may be misread'
    assert r.status in ("REVIEW_REQUIRED", "NOT_RUN") and r.reason == "suspect_reading", (r.status, r.reason)
    assert v["state"] == "AMBER", v
    assert docs[1].f["buyer"].status == "READ"                   # 'BUYER CO., LTD.' is a name, not a label


@test("T22 an error with no SUSPECT input stays a confirmed ERROR next to a SUSPECT one: RED")
def _():
    docs = package()
    docs[0].f["shipper"] = F("CONSIGNEE BUYER CO., LTD.")       # SUSPECT
    docs[3].f["departure"] = F(date(2026, 11, 5), "05/11/2026")   # real: Form D date differs, nothing misread
    fs, res, v = gated(docs)
    dep = next(x for x in fs if x.key == "DEPARTURE_DATE")
    assert not dep.suspect and status(res, "DEPARTURE_DATE") == {"FAIL"}
    assert v["state"] == "RED" and v["open_errors"] == 1, v


@test("T23 closing a SUSPECT finding does not make the check PASS (it did not run on a sound value)")
def _():
    docs = package()
    docs[0].f["shipper"] = F("CONSIGNEE BUYER CO., LTD.")
    fs, res, _v = gated(docs)
    stored = [r.to_dict() for r in res]
    findings = [dict(no=i, severity=f.severity, suspect=f.suspect, sig=f"s{i}") for i, f in enumerate(fs, 1)]
    v = verdict(stored, findings, is_open=lambda f: False)          # the reviewer closed everything
    assert v["state"] == "AMBER" and v["core_not_run"] >= 1, v


@test("T24 no SUSPECT on the invented package (no false alarm), and GREEN stays GREEN")
def _():
    docs = package()
    fs, res, v = gated(docs)
    from engine.extract import Field as _F
    from engine.plausibility import _fields
    assert not [f for d in docs for f in _fields([d.f, d.lists, d.items, d.pl_items]) if f.status == "SUSPECT"]
    assert v["state"] == "GREEN", v


# ----------------------------------------------------------------------------------------------- local sets (not committed)
def local_sets():
    sys.path.insert(0, str(ROOT / "tests"))
    import run_baseline as rb
    return rb.test_sets(), rb.BASE


if "--local" in sys.argv:
    invented = os.environ["LDV_DATA_DIR"]                   # importing run_baseline sets its own
    sets, base = local_sets()
    from run_baseline import load_set as rb_load
    os.environ["LDV_DATA_DIR"] = tempfile.mkdtemp(prefix="ldv_checks_local_")
    if (base / "master_hs.xlsx").exists():
        master.import_xlsx(base / "master_hs.xlsx")
    for z in sets:
        with tempfile.TemporaryDirectory() as t:
            docs = rb_load(z, Path(t))

            @test(f"T1/T4 local set {z.name[:40]}")
            def _():
                _, res = run(docs)
                assert not closure_errors(res, docs), closure_errors(res, docs)
                assert not undeclared(res), undeclared(res)

            @test(f"T24 no SUSPECT on local set {z.name[:40]}")
            def _():
                from engine.plausibility import _fields
                sus = [(d.name, f.why, f.raw) for d in docs for f in _fields([d.f, d.lists, d.items, d.pl_items])
                       if f.status == "SUSPECT"] + [(d.name, "S2", d.suspect_lines) for d in docs if d.suspect_lines]
                assert not sus, sus[:5]

            @test(f"T2 blank-out local set {z.name[:40]}")
            def _():
                problems, n = blank_out(docs, z.name)
                print(f"      {n} inputs removed")
                assert not problems, problems[:20]
    os.environ["LDV_DATA_DIR"] = invented                      # the tests below use the invented master list again
    master._cache["key"] = master._cache["added_key"] = None

# ------------------------------------------------------------------- P/O numbers of a sales contract (PO T01 - T10)
def _po(n):
    return f"PR{n:012d}"


def _sc_with(pos, name="po_sc.pdf"):
    s = package()[1]
    raw = ", ".join(p.strip() for p in pos if p and p.strip()) or "X"
    s.path = Path(name)
    s.f["sc_no"] = F(raw)
    s.lists["po_refs"] = [F(p) for p in pos]
    return s


def _po_findings(*scs):
    out = []
    rules.r_sc_po_numbers(list(scs), out)
    assert all(f.severity == "WARNING" for f in out)
    return [(f.key, f.docs[0].name, f.params.get("po") or f.params["n"]) for f in out]


DUP, CNT = "SC_DUPLICATE_PO_NUMBER", "SC_PO_COUNT_EXCEEDED"
for tid, pos, want in (
        ("T01 one P/O", [_po(1)], []),
        ("T02 three different P/Os", [_po(1), _po(2), _po(3)], []),
        ("T03 four different P/Os", [_po(1), _po(2), _po(3), _po(4)], [(CNT, 4)]),
        ("T04 a repeated P/O", [_po(1), _po(2), _po(1)], [(DUP, _po(1))]),
        ("T05 three different, one repeated: duplicate only", [_po(1), _po(2), _po(3), _po(2)], [(DUP, _po(2))]),
        ("T07 blanks around a number", [_po(1), f"  {_po(1)} "], [(DUP, _po(1))]),
        ("T08 empty values", ["", _po(1), "   ", "", _po(2), None], []),
        ("T09 both", [_po(1), _po(2), _po(3), _po(4), _po(1)], [(DUP, _po(1)), (CNT, 4)]),
        ("one warning for a number printed three times", [_po(1)] * 3, [(DUP, _po(1))])):
    @test(f"PO {tid}")
    def _():
        assert [(k, v) for k, _d, v in _po_findings(_sc_with(pos))] == want, _po_findings(_sc_with(pos))


@test("PO T06 the same P/O in two contracts is not a duplicate")
def _():
    assert not _po_findings(_sc_with([_po(1), _po(2)], "a.pdf"), _sc_with([_po(1), _po(3)], "b.pdf"))


@test("PO T10 several contracts: each warning on its own contract, with its number and the places")
def _():
    a, b = _sc_with([_po(1), _po(1)], "a.pdf"), _sc_with([_po(n) for n in (1, 2, 3, 4)], "b.pdf")
    assert _po_findings(a, b, _sc_with([_po(1)], "c.pdf")) == [(DUP, "a.pdf", _po(1)), (CNT, "b.pdf", 4)]
    out = []
    rules.r_sc_po_numbers([a, b], out)
    assert [len(f.locs) for f in out] == [2, 4] and out[0].params["sc"] == a.f["sc_no"].value
    assert out[0].text("en") == f"Sales Contract {_po(1)}, {_po(1)} contains a duplicate P/O number: {_po(1)} (2 times)", out[0].text("en")
    assert "contains 4 distinct P/O numbers. The maximum allowed is 3" in out[1].text("en")
    assert all(_po(1) in out[0].text(x) for x in ("en", "vi"))


@test("PO integration: both warnings through the engine, the package verdict does not become RED or lose core checks")
def _():
    docs = package()
    finds0, checks0 = validate_checks(docs)
    st = {c.check_id: c.status for c in checks0}
    assert (st[DUP], st[CNT]) == (CheckStatus.PASS, CheckStatus.PASS)
    docs[1].lists["po_refs"] = [F(p) for p in (PO, _po(2), _po(3), _po(4), PO)]
    finds, checks = validate_checks(docs)
    st = {c.check_id: c.status for c in checks}
    assert (st[DUP], st[CNT]) == (CheckStatus.REVIEW_REQUIRED, CheckStatus.REVIEW_REQUIRED)
    new = [f for f in finds if f.key in (DUP, CNT)]
    assert len(new) == 2 and len(finds) == len(finds0) + 2
    v0, v = (verdict([c.to_dict() for c in cs], [dict(no=i, severity=f.severity, suspect="") for i, f in enumerate(fs, 1)])
             for cs, fs in ((checks0, finds0), (checks, finds)))
    assert v["state"] == v0["state"] and v["open_errors"] == v0["open_errors"], (v0, v)
    docs[1].f["sc_no"] = None                          # not read: never PASS
    docs[1].lists["po_refs"] = []
    assert {c.status for c in validate_checks(docs)[1] if c.check_id in (DUP, CNT)} == {CheckStatus.NOT_RUN}


@test("HS list: suggestions from checked documents (evidence for and against); nothing is used before it is added")
def _():
    from engine.hs_suggest import suggest
    items = {"AB-X10(W1)": dict(model="AB-X10(W1)", hs="11112222"), "EF-O10": dict(model="EF-O10", hs="33334444")}
    fld = lambda **k: {a: dict(value=v) for a, v in k.items()}
    ci = dict(name="ci", kind="CI", fields={}, items=[dict(model=m, _page=1) for m in (
        "AB-X10(W2)", "AB-X10(W1)", "CD-Y20", "GH-Z30", "IJ-Q40", "EF-010")])
    co = lambda name, *rows: dict(name=name, kind="CO", form="E", fields={}, items=[
        dict(model=m, hs=h, inv_ref="I1", _page=1) for m, h in rows])
    bl = dict(name="bl", kind="BL", fields=fld(invoice_no="I1", hs_all="1111.22, 555566, 333344"), items=[])
    s = dict(shipment="S1", docs=[ci, bl, co("co", ("AB-X10(W2)", "1111.22"), ("CD-Y20", "555566"), ("GH-Z30", "777788"),
                                             ("EF-010", "333344"), ("CD-Y2O", "555566"))])
    s2 = dict(shipment="S2", docs=[ci, co("co2", ("CD-Y20", "555577"))])
    got = {r["model"]: r for r in suggest([s], items)}
    assert set(got) == {"AB-X10(W2)", "CD-Y20", "GH-Z30", "IJ-Q40", "EF-010"}, set(got)      # not the one only the C/O names
    assert (got["AB-X10(W2)"]["hs"], got["AB-X10(W2)"]["from_series"], got["AB-X10(W2)"]["state"]) == ("11112222", True, "ok")
    assert (got["CD-Y20"]["hs"], got["CD-Y20"]["state"], got["CD-Y20"]["bl_ok"]) == ("555566", "ok", 1)
    assert got["GH-Z30"]["state"] == "check" and got["GH-Z30"]["bl_no"] == 1
    assert got["IJ-Q40"]["state"] == "none" and got["EF-010"]["typo_of"] == "EF-O10" and got["EF-010"]["state"] == "check"
    got = {r["model"]: r for r in suggest([s, s2], items)}
    assert got["CD-Y20"]["conflict"] == ["555566", "555577"] and got["CD-Y20"]["hs"] == "" and got["CD-Y20"]["state"] == "check"


@test("Invoice lines not read: SC_VS_CI and CO_ITEMS do not run (no false ERROR), the package is not confirmed")
def _():
    docs = package()
    next(d for d in docs if d.kind == "CI").items = []
    fs, res, v = gated(docs)
    assert not {f.key for f in fs} & {"SC_VS_CI", "CO_ITEMS"}, [f.key for f in fs]
    st = {r.check_id: (r.status, r.reason) for r in res}
    assert st["SC_VS_CI"] == st["CO_ITEMS"] == ("NOT_RUN", "items_not_read"), (st["SC_VS_CI"], st["CO_ITEMS"])
    assert v["state"] == "AMBER", v
    docs = package()                                              # a line missing among others is still an error
    ci = next(d for d in docs if d.kind == "CI")
    ci.items = ci.items + [dict(ci.items[0])]
    assert {"SC_VS_CI", "CO_ITEMS"} <= {f.key for f in gated(docs)[0]}


@test("Master list: goods name and unit, with the spellings that do not matter; a wrong one names its documents")
def _():
    import openpyxl
    from engine import rules_master as rm
    for p, r, ok in (('"ACME" BRAND RICE COOKER', "ACME RICE COOKER", 1), ("RICE COOKER SERIES 1.8L(AB)", "ACME RICE COOKER", 1),
                     ("ACME  Rice\u00a0Cookers", " ACME RICE COOKER", 1), ("ELECTRIC HOT POT", "ACME ELECTRIC HOTPOT", 1),
                     ("OVEN 20L(AB20)SERIES", "ACME OVEN", 1), ("ZETA RICE COOKER", "ACME RICE COOKER", 0),
                     ("ACME OVEN", "ACME OVEN (WITH LID)", 0), ("ACME OVEN (WITH LID)", "ACME OVEN", 0), ("", "ACME", 0)):
        assert rm.same_name(p, r) == bool(ok), (p, r)
    assert rm.unit_key("SET(S)") == rm.unit_key("sets") == rm.unit_key("Bộ") == "SET"
    assert rm.unit_key("PIECE") == rm.unit_key("cái") == "PCS" and rm.unit_key("BOX") != "SET"
    _, res = run(package())                                    # the Excel of the other tests has no such columns
    assert status(res, "MASTER_NAME") == status(res, "MASTER_UNIT") == {"NOT_APPLICABLE"}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Mã NPL/SP", "Mã HS", "TÊN", "ĐƠN VỊ"])
    for r in ([MODEL, "8516.60.10", " ACME RICE\u00a0COOKER", "SET"], ["CD-Y20(W1)VN", "85166010", "ACME KETTLE", "SET"],
              ["CD-Y20(W1)VN", "85166010", "ACME OVEN", "SET"]):
        ws.append(r)
    p = Path(tempfile.mkdtemp()) / "m.xlsx"
    wb.save(p)
    s = master.import_xlsx(p)
    try:
        assert len(s["skipped"]) == 1 and master.row_for(MODEL)["name"] == "ACME RICE COOKER"
        fs, res = run(package())
        assert not [f for f in fs if f.key.startswith("MASTER_")], [(f.key, f.current) for f in fs]
        assert status(res, "MASTER_NAME") == {"PASS"}, by_id(res, "MASTER_NAME")
        docs = package()
        co = next(d for d in docs if d.kind == "CO")
        co.items[0]["goods_full"] = F('"ZETA" BRAND RICE COOKER')
        co.items[0]["unit"] = "PIECE"
        fs, res = run(docs)
        got = {f.key: f for f in fs if f.key.startswith("MASTER_")}
        assert {k: f.severity for k, f in got.items()} == {"MASTER_NAME": "ERROR", "MASTER_UNIT": "WARNING"}, got
        assert got["MASTER_NAME"].suggested == "ACME RICE COOKER" and got["MASTER_UNIT"].suggested == "SET"
        assert [d.kind for d in got["MASTER_NAME"].docs] == ["CO"], got["MASTER_NAME"].docs
        # a heading with several names: each must be the name of a model; the C/O's wrong name shares its finding
        docs = package()
        sc = next(d for d in docs if d.kind == "SC")
        sc.f["goods_full"] = F("ACME RICE COOKER AND ACME KETTLE")
        fs, _ = run(docs)
        got = [f for f in fs if f.key == "MASTER_NAME_EXTRA"]
        assert [(f.current, f.severity, [d.kind for d in f.docs]) for f in got] == [("ACME KETTLE", "WARNING", ["SC"])], got
        co = next(d for d in docs if d.kind == "CO")
        co.items[0]["goods_full"] = F("ACME KETTLE")
        fs, _ = run(docs)
        got = [(f.key, sorted(d.kind for d in f.docs)) for f in fs if f.key.startswith("MASTER_NAME")]
        assert got == [("MASTER_NAME", ["CO", "SC"])], got
        # a name that the list does not have at all: ERROR, beside a model or in a heading
        docs = package()
        next(d for d in docs if d.kind == "CO").items[0]["goods_full"] = F("ACME GADGET")
        assert [(f.key, f.severity) for f in run(docs)[0] if f.key.startswith("MASTER_NAME")] == [("MASTER_NAME", "ERROR")]
        docs = package()
        next(d for d in docs if d.kind == "SC").f["goods_full"] = F("ACME RICE COOKER AND ACME GADGET")
        got = [(f.key, f.severity, f.current) for f in run(docs)[0] if f.key.startswith("MASTER_NAME")]
        assert got == [("MASTER_NAME_MISSING", "ERROR", "ACME GADGET")], got
        # a list imported by an older LDV (no names) is imported again by itself
        import json as _j
        f = master._json()
        d = _j.loads(f.read_text(encoding="utf-8"))
        d.pop("format")
        for i in d["items"].values():
            i.pop("name"), i.pop("unit")
        f.write_text(_j.dumps(d), encoding="utf-8")
        master._cache["key"] = None
        assert master.refresh() and master.row_for(MODEL)["unit"] == "SET"
    finally:
        setup_master()


@test("Place names: unknown ones are suggested with the B/L's city, used only after the user adds them, and can be removed")
def _():
    from engine import places
    bl = lambda name, **k: dict(docs=[dict(name=name, kind="BL", fields={a: dict(value=v) for a, v in k.items()})])
    s1 = bl("b1", final_dest="QX-ZED", delivery="HAI PHONG", pod="HAIPHONG")
    s2 = bl("b2", final_dest="QX\u2011ZED", delivery="DA NANG")
    s3 = bl("b3", final_dest="QX-ZED", delivery="NOWHERE", pod="CAT LAI")
    got = places.suggest([s1])
    assert [(r["name"], r["city"]) for r in got] == [("QX-ZED", "HAI PHONG")], got
    assert places.city("QX-ZED") is None                          # a suggestion is not used
    got = {r["key"]: r for r in places.suggest([s1, s2])}
    assert got["QXZED"]["city"] == "" and got["QXZED"]["conflict"] == ["DA NANG", "HAI PHONG"]
    assert {r["key"] for r in places.suggest([s3])} == {"QXZED", "NOWHERE"}
    for bad in (("QX-ZED", ""), ("", "HAI PHONG"), ("CAT LAI", "HAI PHONG")):      # no city / no name / another city's name
        try:
            places.add(*bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    places.add("QX-ZED", "hph", ["b1"], "someone")
    try:
        assert places.city("QX\u2011ZED") == "HAI PHONG" and places.city("CAT LAI") == "HO CHI MINH CITY"
        assert not places.suggest([s1])
    finally:
        places.remove("QXZED")
    assert places.city("QX-ZED") is None


@test("HS list: added models are used, the Excel wins, wrong codes are refused; the added list reads back as a master Excel")
def _():
    assert master.hs_for("NEW-M1") is None
    for bad in ("12345", "ABC", "", "8516.60.1O"):
        try:
            master.add("NEW-M1", bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    master.add("New-M1", "9999.88", ["co.pdf"], "someone")
    try:
        assert master.hs_for("NEW-M1") == "999988"
        p = Path(tempfile.mkdtemp()) / "added.xlsx"
        p.write_bytes(master.added_xlsx())
        assert master.read_xlsx(p)[0]["NEW-M1"]["hs"] == "999988"
        try:
            master.add(MODEL, "999988")
            raise AssertionError("the Excel has this model")
        except ValueError:
            pass
        # a 6-digit code from a Form E: compared on its digits; another code is still an error
        assert master.agrees("9999.88.10", "999988", "NEW-M1", "D") and not master.agrees("9999.77.10", "999988", "NEW-M1", "D")
        # Form E prints 6 digits of the 8-digit master code; a Form D must print the code itself
        assert master.agrees("1111.22", "11112222", MODEL, "E") and not master.agrees("1111.33", "11112222", MODEL, "E")
        assert not master.agrees("1111.22", "11112222", MODEL, "D") and not master.agrees("1111", "11112222", MODEL, "E")
        assert not master.agrees("11112222", "111122", MODEL, "D")            # a 6-digit code of the Excel: exact as before
    finally:
        master.remove("NEW-M1")
    assert master.hs_for("NEW-M1") is None


print("RESULT:", "ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
