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
    "nav_review": ("Review workspace", "Rà soát chứng từ"),
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
    "st_in_review": ("In review", "Đang xem xét"),
    "st_accepted": ("Accepted – no action", "Chấp nhận – không cần sửa"),
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
    "verdict_gaps_only": ("No open errors or warnings, but {n} item(s) could not be read — check them by hand before sign-off",
                          "Không còn lỗi hay cảnh báo, nhưng {n} mục không đọc được — cần kiểm tra thủ công trước khi xác nhận"),
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
    "type_help": ("Change it if LDV recognised the document wrongly", "Đổi nếu LDV nhận diện sai loại chứng từ"),
    "type_hint": ("If a type is wrong or missing, pick the right one in the Detected type column.",
                  "Nếu loại chứng từ sai hoặc chưa nhận diện được, chọn lại ở cột Loại nhận diện."),
    "type_changed": ("Type set by you for: {files}", "Loại chứng từ do bạn chọn: {files}"),
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
    # ---- review workspace (viewer + finding panel)
    "pg_prev": ("Previous page", "Trang trước"),
    "pg_next": ("Next page", "Trang sau"),
    "zoom": ("Zoom", "Thu phóng"),
    "fit_width": ("Fit width", "Vừa chiều ngang"),
    "fit_page": ("Fit page", "Vừa trang"),
    "find_in_doc": ("Find in this document", "Tìm trong chứng từ này"),
    "find_hits": ("{n} match(es) on page {pages}", "{n} kết quả ở trang {pages}"),
    "find_none": ("No match in this document", "Không tìm thấy trong chứng từ này"),
    "orig_pdf": ("Original PDF", "PDF gốc"),
    "orig_pdf_help": ("The unchanged file, to open in your PDF reader", "File gốc không chỉnh sửa, mở bằng trình đọc PDF"),
    "boxes_v2": ("Solid box = value to check (colour = severity, #n = finding) · dashed green = reference value of the "
                 "selected finding · yellow = search match. Text can be selected and copied.",
                 "Khung liền = giá trị cần kiểm tra (màu = mức độ, #n = số lỗi) · khung xanh lá nét đứt = giá trị tham chiếu "
                 "của lỗi đang chọn · vàng = kết quả tìm kiếm. Có thể chọn và sao chép chữ."),
    "pick_finding": ("Select a finding to see its details and jump to its place in the document. ↑/↓ move between findings.",
                     "Chọn một lỗi để xem chi tiết và đến đúng vị trí trên chứng từ. ↑/↓ để chuyển giữa các lỗi."),
    "scope": ("Show", "Hiển thị"),
    "scope_doc": ("This document", "Chứng từ này"),
    "scope_all": ("All", "Tất cả"),
    "prev_finding": ("Previous finding (↑)", "Lỗi trước (↑)"),
    "next_finding": ("Next finding (↓)", "Lỗi sau (↓)"),
    "close_panel": ("Close (Esc)", "Đóng (Esc)"),
    "found": ("Found", "Trên chứng từ"),
    "expected": ("Expected", "Đúng ra là"),
    "evidence_at": ("Evidence", "Bằng chứng"),
    "wrong_value": ("value to check", "giá trị cần kiểm tra"),
    "ref_value": ("reference value", "giá trị tham chiếu"),
    "no_location": ("This finding has no position in the document (e.g. something missing); check it by its description.",
                    "Lỗi này không có vị trí trên chứng từ (vd thiếu thông tin); kiểm tra theo mô tả."),
    "action": ("What to check", "Cần kiểm tra"),
    "decided_at": ("Status set {when}", "Cập nhật trạng thái lúc {when}"),
    "snapshots": ("Evidence snapshots", "Ảnh bằng chứng"),
    "activity": ("Reviewer activity", "Lịch sử xử lý"),
    "note_changed": ("note updated", "cập nhật ghi chú"),
    # ---- findings management
    "nav_findings": ("Findings", "Danh sách lỗi"),
    "fm_title": ("Findings", "Danh sách lỗi"),
    "fm_sub": ("Every finding with its reviewer status. Select rows to change their status or add a comment. "
               "Automated results are never changed; each decision is logged with who made it and when.",
               "Tất cả lỗi kèm trạng thái xử lý. Chọn các dòng để đổi trạng thái hoặc thêm ghi chú. "
               "Kết quả tự động không bị thay đổi; mỗi quyết định được ghi lại cùng người và thời điểm."),
    "fm_scope": ("Scope", "Phạm vi"),
    "fm_scope_open": ("Open review", "Lô đang xem"),
    "fm_scope_latest": ("All shipments (latest revision)", "Tất cả lô hàng (lần mới nhất)"),
    "fm_scope_all": ("All revisions", "Tất cả các lần"),
    "fm_search_ph": ("ID, message, value, document, shipment…", "Mã, nội dung, giá trị, chứng từ, lô hàng…"),
    "fm_count": ("{n} finding(s), {open} still to handle", "{n} lỗi, còn {open} lỗi cần xử lý"),
    "fm_id": ("Finding ID", "Mã lỗi"),
    "fm_finding": ("Finding", "Nội dung"),
    "fm_export": ("Excel", "Excel"),
    "fm_pick": ("Tick rows to change their status, add a comment, or open one in the review workspace.",
                "Đánh dấu các dòng để đổi trạng thái, thêm ghi chú hoặc mở trong trang rà soát."),
    "fm_selected": ("{n} selected", "Đã chọn {n}"),
    "fm_set_status": ("Set status", "Đặt trạng thái"),
    "fm_keep": ("(keep current)", "(giữ nguyên)"),
    "fm_comment": ("Reviewer comment", "Ghi chú người kiểm tra"),
    "fm_comment_ph": ("Replaces the note of the selected findings", "Thay ghi chú của các lỗi đã chọn"),
    "fm_apply": ("Apply", "Áp dụng"),
    "fm_applied": ("{n} finding(s) updated", "Đã cập nhật {n} lỗi"),
    "fm_open": ("Open in workspace", "Mở trang rà soát"),
    "fm_no_name": ("Tip: enter your name in Settings so status changes show who made them.",
                   "Gợi ý: nhập tên của bạn trong Cài đặt để ghi lại người thay đổi trạng thái."),
    "set_name": ("Your name", "Tên của bạn"),
    "set_name_help": ("Saved on this PC and recorded with each status change (there is no login).",
                      "Lưu trên máy này và ghi kèm mỗi lần đổi trạng thái (không cần đăng nhập)."),
    "set_saved": ("Saved", "Đã lưu"),
    # ---- cross-document comparison
    "nav_compare": ("Cross-check", "Đối chiếu chứng từ"),
    "cmp_title": ("Cross-check", "Đối chiếu chứng từ"),
    "cmp_sub": ("the same information side by side in every document. Only values LDV has read are compared.",
                "cùng một thông tin trên từng chứng từ. Chỉ so sánh các giá trị LDV đọc được."),
    "cmp_legacy": ("This review was saved by an older LDV version without the extracted values. Check the files again to compare them.",
                   "Lần kiểm tra này được lưu bởi phiên bản LDV cũ, không có giá trị trích xuất. Hãy kiểm tra lại bộ chứng từ để đối chiếu."),
    "cmp_show": ("Show", "Hiển thị"),
    "cmp_all": ("All fields", "Tất cả"),
    "cmp_diff": ("Differences only", "Chỉ chỗ khác nhau"),
    "cmp_no_diff": ("No differences between the documents.", "Các chứng từ không có chỗ khác nhau."),
    "cmp_field": ("Field", "Thông tin"),
    "cmp_result": ("Result", "Kết quả"),
    "cmp_match": ("Match", "Khớp"),
    "cmp_mismatch": ("Mismatch", "Không khớp"),
    "cmp_incomplete": ("Not read everywhere", "Thiếu giá trị"),
    "cmp_single": ("Only one document", "Chỉ một chứng từ"),
    "cmp_none": ("Not read", "Không đọc được"),
    "cmp_missing": ("not read", "không đọc được"),
    "cmp_nodoc": ("no document", "không có chứng từ"),
    "cmp_legend": ("Red: differs from the other documents. Yellow: should be on this document but was not read. "
                   "“·”: not on this kind of document. Click a value to see where it comes from.",
                   "Đỏ: khác các chứng từ còn lại. Vàng: phải có trên chứng từ này nhưng không đọc được. "
                   "“·”: không có trên loại chứng từ này. Bấm vào một giá trị để xem nguồn."),
    "cmp_odd": ("differs from the other documents", "khác các chứng từ còn lại"),
    "cmp_open": ("Open this page", "Mở trang này"),
    "cmp_open_line": ("Open {doc}, page {page}", "Mở {doc}, trang {page}"),
    "cmp_missing_txt": ("This value should be on this document but LDV could not read it. Check the document by hand.",
                        "Giá trị này phải có trên chứng từ nhưng LDV không đọc được. Hãy kiểm tra thủ công."),
    "cmp_na_txt": ("This information is not on this kind of document.", "Loại chứng từ này không có thông tin này."),
    "cmp_nodoc_txt": ("This kind of document is not in the package.", "Bộ chứng từ không có loại chứng từ này."),
    "cmp_lines": ("Goods lines by model", "Dòng hàng theo model"),
    "cmp_lines_sub": ("Quantity per model on each document and the unit price on the invoice and the sales contract.",
                      "Số lượng từng model trên mỗi chứng từ và đơn giá trên hóa đơn và hợp đồng."),
    "cmp_qty": ("Qty", "SL"),
    "cmp_price": ("Price", "Đơn giá"),
    "cmp_not_read": ("Not compared because LDV does not read them yet: {fields}.",
                     "Chưa đối chiếu vì LDV chưa đọc các thông tin: {fields}."),
    "cmp_link": ("Cross-check: {n} field(s) differ between documents", "Đối chiếu: {n} thông tin khác nhau giữa các chứng từ"),
    "cmp_link_ok": ("Cross-check: documents agree", "Đối chiếu: các chứng từ khớp nhau"),
    # ---- report + sign-off
    "nav_report": ("Report", "Báo cáo"),
    "rep_title": ("Report and sign-off", "Báo cáo và xác nhận"),
    "so_title": ("Reviewer sign-off", "Xác nhận của người kiểm tra"),
    "so_auto": ("Automated result (LDV)", "Kết quả tự động (LDV)"),
    "so_human": ("Reviewer conclusion", "Kết luận của người kiểm tra"),
    "so_none": ("Not signed off yet", "Chưa xác nhận"),
    "so_approved": ("Approved", "Đạt"),
    "so_approved_exception": ("Approved with exception", "Đạt có ngoại lệ"),
    "so_returned": ("Returned for correction", "Trả lại để sửa"),
    "so_by": ("{who}, {ts}", "{who}, {ts}"),
    "so_result": ("Conclusion", "Kết luận"),
    "so_note": ("Reason / note", "Lý do / ghi chú"),
    "so_note_req": ("Required: why is it accepted / what must be corrected?", "Bắt buộc: lý do chấp nhận / cần sửa gì?"),
    "so_blocked": ("{n} error(s) are still open, so the package cannot be simply approved. Resolve them, return the "
                   "package for correction, or record an exception with the reason.",
                   "Còn {n} lỗi chưa xử lý nên không thể xác nhận Đạt. Hãy xử lý lỗi, trả lại để sửa, hoặc ghi nhận "
                   "ngoại lệ kèm lý do."),
    "so_use_exception": ("Choose 'Approved with exception' and write the reason.",
                         "Chọn 'Đạt có ngoại lệ' và ghi lý do."),
    "so_sign": ("Sign off", "Xác nhận"),
    "so_saved": ("Sign-off recorded", "Đã ghi nhận xác nhận"),
    "so_history": ("Sign-off history", "Lịch sử xác nhận"),
    "so_open_at": ("{e} error(s), {w} warning(s) open at the time", "lúc đó còn {e} lỗi, {w} cảnh báo"),
    "rep_report": ("Review report", "Báo cáo kiểm tra"),
    "rep_lang": ("Report language", "Ngôn ngữ báo cáo"),
    "rep_info": ("Include Info findings", "Gồm mục Thông tin"),
    "rep_open": ("Only unresolved findings", "Chỉ lỗi chưa xử lý"),
    "rep_snaps": ("Evidence snapshots", "Ảnh bằng chứng"),
    "rep_cross": ("Cross-check table", "Bảng đối chiếu"),
    "rep_make_pdf": ("Create PDF", "Tạo PDF"),
    "rep_make_xlsx": ("Create Excel", "Tạo Excel"),
    "rep_make_html": ("Create HTML", "Tạo HTML"),
    "rep_making": ("Creating the report…", "Đang tạo báo cáo…"),
    "rep_made": ("Report created: {name}", "Đã tạo báo cáo: {name}"),
    "rep_download": ("Download {name}", "Tải {name}"),
    "rep_where": ("Reports are saved in {path}", "Báo cáo được lưu tại {path}"),
    "rep_preview": ("Preview", "Xem trước"),
    "rep_earlier": ("Earlier reports for this review", "Các báo cáo trước của lần kiểm tra này"),
    "rep_dl": ("Download", "Tải"),
    "hist_report": ("Report", "Báo cáo"),
    # ---- global search
    "gs_btn": ("Search", "Tìm kiếm"),
    "gs_title": ("Search reviews, documents and findings", "Tìm lô hàng, chứng từ và lỗi"),
    "gs_label": ("Search", "Tìm kiếm"),
    "gs_ph": ("Shipment, invoice / B/L / contract no., file name, finding ID or text…",
              "Lô hàng, số hóa đơn / vận đơn / hợp đồng, tên file, mã lỗi hoặc nội dung…"),
    "gs_hint": ("Type at least 2 characters. All words must match. Searches every review in the history.",
                "Nhập ít nhất 2 ký tự. Phải khớp tất cả các từ. Tìm trong toàn bộ lịch sử kiểm tra."),
    "gs_none": ("Nothing found.", "Không tìm thấy."),
    "gs_reviews": ("Reviews", "Lần kiểm tra"),
    "gs_refs": ("Reference numbers in documents", "Số tham chiếu trên chứng từ"),
    "gs_findings": ("Findings (latest revision)", "Lỗi (lần kiểm tra mới nhất)"),
    "gs_docs": ("Documents", "Chứng từ"),
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
