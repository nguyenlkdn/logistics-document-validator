"""All UI strings in one place (English, Vietnamese). Document text and rule messages come from config.json.

t("key") gives the string in the chosen UI language; in "Both" mode it gives "English / Tiếng Việt".
"""
import streamlit as st

from engine.rules import CONFIG

LANGS = {"en": "EN", "vi": "VI", "both": "EN + VI"}     # short: fits the sidebar

T = {
    # ---- app / navigation
    "app": ("Logistics Document Validator", "Kiểm tra bộ chứng từ XNK"),
    "nav_dashboard": ("Dashboard", "Tổng quan"),
    "nav_new": ("New review", "Kiểm tra mới"),
    "nav_review": ("Findings", "Kết quả kiểm tra"),
    "nav_history": ("Review history", "Lịch sử kiểm tra"),
    "nav_reference": ("Reference data", "Dữ liệu tham chiếu"),
    "nav_settings": ("Settings", "Cài đặt"),
    "sec_review": ("Review", "Kiểm tra"),
    "sec_records": ("Records", "Lưu trữ"),
    "sec_data": ("Data & settings", "Dữ liệu & cài đặt"),
    "lang": ("Language / Ngôn ngữ", "Ngôn ngữ / Language"),
    "version": ("Version", "Phiên bản"),
    "workspace": ("Open review", "Đang xem"),
    "no_workspace": ("No review open", "Chưa mở lô hàng nào"),
    "recent": ("Recent reviews", "Gần đây"),
    "rev": ("Revision", "Lần"),
    "rev_short": ("rev.", "lần"),
    # ---- workflow
    "step_upload": ("Upload", "Tải lên"),
    "step_analyze": ("Analyze", "Phân tích"),
    "step_review": ("Review findings", "Xem lỗi"),
    "step_resolve": ("Resolve", "Xử lý"),
    "step_report": ("Report", "Báo cáo"),
    # ---- severity / status
    "st_open": ("Open", "Chưa xử lý"),
    "st_fixed": ("Fixed", "Đã sửa"),
    "st_not_error": ("Not an error", "Không phải lỗi"),
    "st_waiting": ("Waiting for supplier", "Chờ NCC sửa"),
    "status": ("Status", "Trạng thái"),
    "severity": ("Severity", "Mức độ"),
    # ---- dashboard
    "dash_title": ("Review overview", "Tổng quan lô hàng"),
    "checked_at": ("Checked {when}", "Kiểm tra lúc {when}"),
    "verdict_errors": ("Not ready — {n} open error(s)", "Chưa đạt — còn {n} lỗi chưa xử lý"),
    "verdict_warn": ("Needs verification — {n} open warning(s)", "Cần kiểm tra lại — còn {n} cảnh báo"),
    "verdict_ok": ("No open errors or warnings — ready for reviewer sign-off",
                   "Không còn lỗi hay cảnh báo — sẵn sàng để người kiểm tra xác nhận"),
    "verdict_gaps": ("{n} item(s) could not be read; check them by hand.",
                     "{n} mục không đọc được; cần kiểm tra thủ công."),
    "k_package": ("Document package", "Bộ chứng từ"),
    "k_findings": ("Findings", "Lỗi phát hiện"),
    "k_progress": ("Review progress", "Tiến độ xử lý"),
    "k_docs": ("Documents", "Chứng từ"),
    "k_analyzed": ("Analyzed", "Đã phân tích"),
    "k_unrec": ("Not checked", "Chưa kiểm tra"),
    "k_total": ("Total", "Tổng"),
    "k_open": ("Open", "Chưa xử lý"),
    "k_waiting": ("Waiting", "Đang chờ"),
    "k_resolved": ("Resolved", "Đã xử lý"),
    "distribution": ("Findings by severity", "Lỗi theo mức độ"),
    "docs_status": ("Documents", "Chứng từ"),
    "docs_click": ("Select a document to open its findings and preview.",
                   "Chọn một chứng từ để xem lỗi và xem trước."),
    "progress_txt": ("{done} of {n} findings handled (Info findings need no action)",
                     "Đã xử lý {done}/{n} lỗi (mục Thông tin không cần xử lý)"),
    "empty_title": ("No review open", "Chưa mở lô hàng nào"),
    "empty_body": ("Start a new review by uploading one shipment's documents, or open a past review.",
                   "Bắt đầu kiểm tra mới bằng cách tải lên bộ chứng từ của một lô hàng, hoặc mở lại một lần kiểm tra cũ."),
    "start_new": ("Start a new review", "Kiểm tra lô hàng mới"),
    "open_hist": ("Open review history", "Xem lịch sử"),
    "click_hint": ("Click a number to see those findings.", "Bấm vào một con số để xem các lỗi tương ứng."),
    "unrec_title": ("Not checked / not read", "Chưa kiểm tra / không đọc được"),
    "all_ok": ("Everything recognised.", "Đã đọc được toàn bộ."),
    # ---- new review
    "new_title": ("New review", "Kiểm tra mới"),
    "new_intro": ("Upload ONE shipment: a .zip, or its PDF files. Documents are only read, never changed.",
                  "Tải lên MỘT lô hàng: một file .zip hoặc các file PDF. Chứng từ chỉ được đọc, không bị sửa."),
    "upload": ("Shipment documents", "Bộ chứng từ"),
    "upload_help": ("Accepted: .zip or .pdf (several PDFs at once), up to 200 MB per file. "
                    "Images (.jpg, .png) are listed but not checked.",
                    "Chấp nhận: .zip hoặc .pdf (nhiều file PDF cùng lúc), tối đa 200 MB mỗi file. "
                    "Ảnh (.jpg, .png) được liệt kê nhưng không được kiểm tra."),
    "inventory": ("Files to check", "Các file sẽ kiểm tra"),
    "inv_hint": ("Remove a file with the ✕ next to it in the upload box.",
                 "Bỏ một file bằng nút ✕ bên cạnh file trong ô tải lên."),
    "col_file": ("File", "Tên file"),
    "col_in": ("In", "Trong"),
    "col_type": ("Detected type", "Loại nhận diện"),
    "col_kind": ("Type", "Loại"),
    "col_pages": ("Pages", "Trang"),
    "col_size": ("Size", "Dung lượng"),
    "col_status": ("Status", "Trạng thái"),
    "col_findings": ("Findings", "Lỗi"),
    "col_doc": ("Document", "Chứng từ"),
    "ok_ready": ("Ready", "Sẵn sàng"),
    "ok_dup": ("Duplicate of {name}", "Trùng với {name}"),
    "ok_unrec": ("Type not recognised — will be listed as not checked", "Không nhận diện được — sẽ ghi là chưa kiểm tra"),
    "ok_notpdf": ("Not a PDF — will not be checked", "Không phải PDF — sẽ không được kiểm tra"),
    "ok_broken": ("Cannot be opened", "Không mở được"),
    "one_zip": ("Please check one shipment at a time: upload one .zip, or PDF files only.",
                "Vui lòng kiểm tra từng lô hàng: tải lên một file .zip, hoặc chỉ các file PDF."),
    "bad_zip": ("{name} is not a valid .zip file.", "{name} không phải file .zip hợp lệ."),
    "dup_warn": ("Some files are duplicates; only the first copy matters for the checks.",
                 "Có file bị trùng; chỉ bản đầu tiên được dùng khi kiểm tra."),
    "missing_kind": ("No {kind} found in these files.", "Không thấy {kind} trong các file này."),
    "start": ("Start analysis", "Bắt đầu phân tích"),
    "running": ("Analyzing {n} file(s)…", "Đang phân tích {n} file…"),
    "run_done": ("Analysis finished", "Đã phân tích xong"),
    "from_menu": ("Checked from right-click menu", "Kiểm tra từ menu chuột phải"),
    # ---- review
    "flt_sev": ("Severity", "Mức độ"),
    "flt_status": ("Status", "Trạng thái"),
    "flt_search": ("Search findings", "Tìm lỗi"),
    "flt_search_ph": ("Message, value, rule…", "Nội dung, giá trị, quy tắc…"),
    "flt_clear": ("Clear filters", "Bỏ lọc"),
    "all_docs": ("All documents", "Tất cả chứng từ"),
    "showing_n": ("Showing {n} of {total} findings", "Đang hiển thị {n}/{total} lỗi"),
    "none": ("No issues found.", "Không phát hiện lỗi."),
    "none_match": ("No findings match the filters.", "Không có lỗi nào khớp bộ lọc."),
    "current": ("Current", "Hiện tại"),
    "suggested": ("Suggested", "Đề xuất"),
    "doc": ("Document", "Chứng từ"),
    "related": ("Compared with", "So với"),
    "page": ("page", "trang"),
    "pages": ("pages", "trang"),
    "note": ("Note", "Ghi chú"),
    "note_in": ("Reviewer note", "Ghi chú người kiểm tra"),
    "rule": ("Rule", "Quy tắc"),
    "preview": ("Document preview", "Xem trước chứng từ"),
    "boxes": ("Boxes on the page: red = Error, orange = Warning, yellow = Minor, blue = Info; #n = finding number",
              "Khung trên trang: đỏ = Lỗi, cam = Cảnh báo, vàng = Lỗi nhỏ, xanh dương = Thông tin; #n = số thứ tự lỗi"),
    "legend": ("Red box = value to check · Green box = reference value",
               "Khung đỏ = giá trị cần kiểm tra · Khung xanh = giá trị tham chiếu"),
    "in_preview": ("Highlighted as #{n} in the document preview", "Được đánh dấu #{n} trong phần xem trước"),
    "show_doc": ("Show in document", "Xem trên chứng từ"),
    "no_preview": ("The document copy is not in the report folder any more.",
                   "Bản sao chứng từ không còn trong thư mục báo cáo."),
    "legacy": ("Saved by an older LDV version: on-page highlights are not available for this review.",
               "Được lưu bởi phiên bản LDV cũ: không có đánh dấu trên trang cho lần kiểm tra này."),
    "not_draft": ("not marked DRAFT", "không có chữ DRAFT"),
    "download": ("Excel report", "Báo cáo Excel"),
    "open_folder": ("Open report folder", "Mở thư mục báo cáo"),
    "saved": ("Report saved in", "Báo cáo đã lưu tại"),
    "saved_marks": ("Saved", "Đã lưu"),
    "rev_info": ("Revision {rev} of {ship}: {res} fixed since revision {prev}, {still} still there, {new} new",
                 "Lần {rev} của {ship}: {res} lỗi đã sửa so với lần {prev}, {still} lỗi còn lại, {new} lỗi mới"),
    "resolved_prev": ("Fixed since previous revision", "Đã sửa so với lần trước"),
    # ---- history
    "hist_title": ("Review history", "Lịch sử kiểm tra"),
    "no_hist": ("No reviews yet.", "Chưa có lần kiểm tra nào."),
    "hist_search": ("Search", "Tìm kiếm"),
    "hist_search_ph": ("Shipment / invoice no., file name…", "Số lô / số hóa đơn, tên file…"),
    "hist_state": ("Show", "Hiển thị"),
    "hs_all": ("All", "Tất cả"),
    "hs_open": ("With open issues", "Còn lỗi chưa xử lý"),
    "hs_clear": ("No open issues", "Không còn lỗi"),
    "hist_dates": ("Checked between", "Kiểm tra trong khoảng"),
    "hist_pick": ("Select a row to open the review or download its report.",
                  "Chọn một dòng để mở lại hoặc tải báo cáo."),
    "date": ("Checked", "Ngày kiểm tra"),
    "shipment": ("Shipment", "Lô hàng"),
    "open_cnt": ("Still open", "Còn mở"),
    "files": ("Files", "File"),
    "open_review": ("Open review", "Mở lại"),
    "quick_edit": ("Quick status edit", "Sửa nhanh trạng thái"),
    "export": ("Feedback Excel (all findings + status)", "Excel phản hồi (tất cả lỗi + trạng thái)"),
    "n_reviews": ("{n} review(s)", "{n} lần kiểm tra"),
    "missing_folder": ("The report folder of this review was moved or deleted.",
                       "Thư mục báo cáo của lần kiểm tra này đã bị di chuyển hoặc xóa."),
    # ---- reference data
    "ref_title": ("Reference data", "Dữ liệu tham chiếu"),
    "hs_master": ("HS master list", "Danh mục mã HS"),
    "hs_intro": ("The company's HS code list (Excel: model | HS code). Form D and B/L HS codes are checked against it.",
                 "Danh mục mã HS của công ty (Excel: model | mã HS). Mã HS trên C/O và B/L được kiểm tra theo danh mục này."),
    "hs_none": ("No HS master list yet: HS codes are only compared between documents.",
                "Chưa có danh mục mã HS: mã HS chỉ được so sánh giữa các chứng từ."),
    "hs_models": ("Models", "Số model"),
    "hs_imported": ("Last imported", "Nhập lần cuối"),
    "hs_skipped_n": ("Ignored rows", "Dòng bị bỏ qua"),
    "hs_source": ("Source file", "File nguồn"),
    "hs_missing": ("The Excel file is not found at this path any more; the last import is used.",
                   "Không còn thấy file Excel ở đường dẫn này; đang dùng lần nhập gần nhất."),
    "hs_auto": ("Edit the Excel any time: LDV re-imports it automatically before the next check. The Excel is never changed.",
                "Có thể sửa file Excel bất cứ lúc nào: LDV tự nhập lại trước lần kiểm tra sau. File Excel không bao giờ bị sửa."),
    "hs_path": ("Excel file path", "Đường dẫn file Excel"),
    "hs_preview_btn": ("Preview", "Xem trước"),
    "hs_preview": ("Preview of {name}", "Xem trước {name}"),
    "hs_valid": ("{n} models will be imported, {s} row(s) ignored.", "Sẽ nhập {n} model, bỏ qua {s} dòng."),
    "hs_diff": ("Compared with the current list: {a} added, {r} removed, {c} changed.",
                "So với danh mục hiện tại: thêm {a}, bỏ {r}, đổi {c}."),
    "hs_confirm": ("Replace the current HS master list with this file", "Thay danh mục mã HS hiện tại bằng file này"),
    "hs_import": ("Import", "Nhập"),
    "hs_done": ("Imported {n} models: {a} added, {r} removed, {c} changed", "Đã nhập {n} model: thêm {a}, bỏ {r}, đổi {c}"),
    "hs_browse": ("Current list", "Danh mục hiện tại"),
    "hs_filter": ("Find model or HS code", "Tìm model hoặc mã HS"),
    "hs_col_model": ("Model", "Model"),
    "hs_col_hs": ("HS code", "Mã HS"),
    "hs_col_row": ("Excel row", "Dòng Excel"),
    "hs_col_reason": ("Reason", "Lý do"),
    # ---- settings
    "set_title": ("Settings", "Cài đặt"),
    "set_folders": ("Folders", "Thư mục"),
    "set_reports": ("Reports and history", "Báo cáo và lịch sử"),
    "set_data": ("Reference data", "Dữ liệu tham chiếu"),
    "set_rules": ("Check rules", "Quy tắc kiểm tra"),
    "set_rules_txt": ("Rule texts, port names and required fields are set in config.json in the app folder.",
                      "Nội dung quy tắc, tên cảng và các trường bắt buộc được cài trong file config.json của thư mục ứng dụng."),
    "set_about": ("About", "Thông tin"),
    "set_about_txt": ("LDV reads shipment documents and reports discrepancies. It never changes the documents.",
                      "LDV đọc bộ chứng từ và báo cáo sai lệch. LDV không bao giờ sửa chứng từ."),
}


def lang() -> str:
    return st.session_state.get("lang") or "en"      # the selector can be cleared: fall back to English


def langs() -> list[str]:
    return ["en", "vi"] if lang() == "both" else [lang()]


def t(key: str, **kw) -> str:
    pair = T[key]
    parts = [pair[0 if l == "en" else 1].format(**kw) if kw else pair[0 if l == "en" else 1] for l in langs()]
    return parts[0] if len(parts) == 1 or parts[0] == parts[1] else f"{parts[0]} / {parts[1]}"


def t1(key: str, **kw) -> str:
    """Single language only (for tight spots: buttons, chips). 'Both' shows English."""
    s = T[key][1 if lang() == "vi" else 0]
    return s.format(**kw) if kw else s


def sev_label(s: str) -> str:
    return " / ".join(CONFIG["severity"][s][l] for l in langs())


def sev_short(s: str) -> str:
    return CONFIG["severity"][s]["vi" if lang() == "vi" else "en"]


def kind_label(k: str, short: bool = False) -> str:
    if k not in CONFIG["doc_kinds"]:
        return "—"
    if short:
        return {"CI": "CI / PL", "SC": "S/C", "BL": "B/L", "CO": "Form D"}.get(k, k)
    return " / ".join(CONFIG["doc_kinds"][k][l] for l in langs())


def msg(f: dict) -> str:
    return " — ".join(f[f"msg_{l}"] for l in langs() if f.get(f"msg_{l}"))


def note(f: dict) -> str:
    return "  \n".join(f[f"note_{l}"] for l in langs() if f.get(f"note_{l}"))


def unrec_text(u: dict) -> str:
    return " / ".join(u["what" if l == "en" else "vi"] for l in langs())


def status_label(k: str) -> str:
    return t1(f"st_{k}")
