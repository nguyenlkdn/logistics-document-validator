"""Settings: where LDV keeps its files, and what can be configured."""
import streamlit as st

from engine import master, report_root

from .. import components as ui
from .. import state
from ..i18n import LANGS, t, t1


def render():
    ui.header(t("set_title"))
    st.subheader(t("lang"))
    st.segmented_control(t("lang"), list(LANGS), format_func=LANGS.get, key="lang_settings",
                         default=st.session_state.get("lang", "en"), on_change=_sync, label_visibility="collapsed")
    st.subheader(t("set_folders"))
    st.markdown(f"**{t1('set_reports')}:** `{report_root()}`")
    st.markdown(f"**{t1('set_data')}:** `{master.data_dir()}`")
    st.subheader(t("set_rules"))
    st.markdown(f"{t('set_rules_txt')}  \n`{state.APP / 'config.json'}`")
    st.subheader(t("set_about"))
    st.write(t("set_about_txt"))
    st.caption(f"LDV {t1('version')} {state.VERSION}")


def _sync():
    if st.session_state.get("lang_settings"):
        st.session_state["lang"] = st.session_state["lang_settings"]
