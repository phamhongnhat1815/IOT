"""Visual components shared by Signal Lab pages. No measurement or database logic."""
from html import escape
from pathlib import Path
import streamlit as st

ICONS = {
    "pulse": "M3 12h4l3-8 4 16 3-8h4",
    "oxygen": "M12 3C9 7 5 11 5 15a7 7 0 0 0 14 0c0-4-4-8-7-12Z",
    "temperature": "M9 14.5V5a3 3 0 0 1 6 0v9.5a5 5 0 1 1-6 0ZM12 8v9",
    "calendar": "M8 2v4m8-4v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14H3V6a2 2 0 0 1 2-2ZM7 14h3m4 0h3m-10 4h3",
    "bell": "M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM10 21h4",
    "database": "M20 6c0 2-4 4-8 4S4 8 4 6s4-4 8-4 8 2 8 4ZM4 6v12c0 2 4 4 8 4s8-2 8-4V6M4 12c0 2 4 4 8 4s8-2 8-4",
}


def icon(name, size=22):
    path = ICONS.get(name, ICONS["pulse"])
    return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="{path}"/></svg>'


def styles():
    css = Path(__file__).with_name("dashboard.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def badge(text, tone="neutral"):
    tone = tone if tone in ("neutral", "blue", "amber", "teal") else "neutral"
    return f'<span class="sl-badge {tone}">{escape(str(text))}</span>'


def section(title, subtitle="", symbol=None):
    marker = f'<span class="sl-section-icon">{icon(symbol, 17)}</span>' if symbol else ""
    st.markdown(f'<div class="sl-section"><h3>{marker}{escape(title)}</h3><p>{escape(subtitle)}</p></div>', unsafe_allow_html=True)


def empty_state(title, description, symbol="database"):
    st.markdown(f'<div class="sl-empty"><span class="sl-empty-icon">{icon(symbol, 28)}</span><h3>{escape(title)}</h3><p>{escape(description)}</p></div>', unsafe_allow_html=True)


def chart_heading(title, subtitle, color="#3974d5"):
    st.markdown(f'<div class="sl-chart-heading"><span class="sl-chart-dot" style="background:{color}"></span><div><strong>{escape(title)}</strong><small>{escape(subtitle)}</small></div><span class="sl-chart-unit">PPG</span></div>', unsafe_allow_html=True)


def page_header(source, date):
    st.markdown(
        '<div class="sl-workspace-bar"><span>SIGNAL LAB <b>/ KHÔNG GIAN THEO DÕI</b></span>'
        f'<span class="sl-workspace-date">{icon("calendar", 15)}{escape(date)}<small>UTC+7</small></span></div>'
        '<div class="sl-page-header"><div><div class="sl-page-kicker">BẢNG ĐIỀU KHIỂN</div><h1>Theo dõi chỉ số</h1>'
        '<p>Nắm bắt kết quả đo. Chủ động theo dõi mỗi ngày.</p></div>'
        f'<div class="sl-header-meta"><span>{icon("database", 15)}{escape(source)}</span></div></div>',
        unsafe_allow_html=True,
    )


def panel_empty(title, description, symbol):
    st.markdown(f'<div class="sl-panel-empty"><span>{icon(symbol, 26)}</span><strong>{escape(title)}</strong><p>{escape(description)}</p></div>', unsafe_allow_html=True)
