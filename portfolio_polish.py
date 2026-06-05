"""Portfolio presentation polish — screenshot mode, demo mode, summaries. No feature changes."""

from __future__ import annotations

import html

SESSION_KEY = "portfolio_screenshot_mode"
DEMO_SESSION_KEY = "portfolio_demo_mode"


def is_screenshot_mode(st) -> bool:
    return bool(st.session_state.get(SESSION_KEY, False))


def is_demo_mode(st) -> bool:
    return bool(st.session_state.get(DEMO_SESSION_KEY, False))


def _clear_demo_flags(st) -> None:
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith("_pp_demo_"):
            st.session_state.pop(key, None)


def render_sidebar_toggle(st) -> None:
    st.sidebar.divider()
    prev_demo = bool(st.session_state.get(DEMO_SESSION_KEY, False))
    st.sidebar.toggle(
        "Portfolio Screenshot Mode",
        value=bool(st.session_state.get(SESSION_KEY, False)),
        key=SESSION_KEY,
        help="Hides instructional clutter, tightens spacing, and optimizes hero pages for portfolio screenshots.",
    )
    demo_on = st.sidebar.toggle(
        "Portfolio Demo Mode",
        value=prev_demo,
        key=DEMO_SESSION_KEY,
        help="Auto-loads curated examples, populates forms, and expands key outputs for instant portfolio storytelling.",
    )
    if demo_on and not prev_demo:
        _clear_demo_flags(st)
    if is_screenshot_mode(st):
        st.sidebar.caption("Screenshot mode — layout optimized for captures")
    if is_demo_mode(st):
        st.sidebar.caption("Demo mode — curated portfolio examples active")


def inject_polish_css(st, *, app_slug: str = "app") -> None:
    screenshot = is_screenshot_mode(st)
    ss = ""
    if screenshot or is_demo_mode(st):
        ss = """
        .page-guide, .small-note, .pp-instructional { display: none !important; }
        .block-container { padding-top: 0.6rem !important; padding-bottom: 1.25rem !important; }
        [data-testid="stSidebar"] .stCaption { opacity: 0.85; }
        .hero-badges { display: none !important; }
        .pp-hero-screenshot .section-title { font-size: 1.35rem !important; }
        """
    st.markdown(
        f"""
        <style>
        /* Portfolio polish — {app_slug} */
        h1, h2, h3, h4 {{ letter-spacing: -0.02em; }}
        [data-testid="stMetricValue"] {{
            font-size: 1.55rem !important;
            font-weight: 700 !important;
        }}
        [data-testid="stMetricLabel"] {{
            font-size: 0.78rem !important;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}
        .pp-exec-summary {{
            background: linear-gradient(135deg, #f0f6ff 0%, #f8fafc 100%);
            border: 1px solid #c8daf5;
            border-left: 4px solid #1f6feb;
            border-radius: 10px;
            padding: 12px 16px;
            margin: 0 0 14px 0;
        }}
        .pp-exec-title {{
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: #0b3d6e;
            margin-bottom: 8px;
        }}
        .pp-exec-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 8px 16px;
        }}
        .pp-exec-item {{ font-size: 13px; line-height: 1.4; color: #2c3e50; }}
        .pp-exec-item strong {{ color: #12324a; }}
        .pp-empty-state {{
            background: #f6f8fa;
            border: 1px dashed #d0d7de;
            border-radius: 10px;
            padding: 14px 16px;
            margin: 8px 0;
        }}
        .pp-empty-title {{ font-weight: 700; color: #24292f; margin-bottom: 4px; }}
        .pp-empty-body {{ color: #57606a; font-size: 14px; line-height: 1.45; }}
        .pp-hero-screenshot {{
            background: linear-gradient(135deg, #0d1117 0%, #161b22 55%, #1f2937 100%);
            color: #f0f6fc;
            border-radius: 12px;
            padding: 18px 20px;
            margin-bottom: 14px;
            border: 1px solid #30363d;
        }}
        .pp-hero-screenshot h2 {{ margin: 0; font-size: 1.4rem; color: #f0f6fc; }}
        .pp-hero-screenshot p {{ margin: 6px 0 0; color: #8b949e; font-size: 0.9rem; }}
        .pp-demo-banner {{
            background: linear-gradient(90deg, #ecfdf5 0%, #f0fdf4 100%);
            border: 1px solid #86efac;
            border-radius: 8px;
            padding: 8px 12px;
            margin-bottom: 10px;
            font-size: 13px;
            color: #166534;
        }}
        @media (max-width: 768px) {{
            [data-testid="column"] {{ min-width: 0 !important; }}
            .block-container {{ padding-left: 0.75rem !important; padding-right: 0.75rem !important; }}
            [data-testid="stSelectbox"] > div {{ width: 100% !important; }}
            .pp-exec-grid {{ grid-template-columns: 1fr; }}
        }}
        {ss}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_executive_summary(st, what: str, why: str, outputs: str) -> None:
    st.markdown(
        f"""
        <div class="pp-exec-summary">
            <div class="pp-exec-title">At a glance</div>
            <div class="pp-exec-grid">
                <div class="pp-exec-item"><strong>What this does:</strong> {html.escape(what)}</div>
                <div class="pp-exec-item"><strong>Why it matters:</strong> {html.escape(why)}</div>
                <div class="pp-exec-item"><strong>Key outputs:</strong> {html.escape(outputs)}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_hero_banner(st, title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="pp-hero-screenshot">
            <h2>{html.escape(title)}</h2>
            <p>{html.escape(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_professional_empty(st, message: str, *, title: str = "Next step") -> None:
    if is_demo_mode(st):
        return
    st.markdown(
        f"""
        <div class="pp-empty-state">
            <div class="pp-empty-title">{html.escape(title)}</div>
            <div class="pp-empty-body">{html.escape(message)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def instructional_caption(st, text: str) -> None:
    if not is_screenshot_mode(st) and not is_demo_mode(st):
        st.caption(text)


def expander_default(st, *, default: bool = False) -> bool:
    if is_screenshot_mode(st) or is_demo_mode(st):
        return False
    return default


def chart_default_visible(st) -> bool:
    return is_screenshot_mode(st) or is_demo_mode(st)


def demo_applied(st, page_key: str) -> bool:
    return bool(st.session_state.get(f"_pp_demo_applied_{page_key}"))


def mark_demo_applied(st, page_key: str) -> None:
    st.session_state[f"_pp_demo_applied_{page_key}"] = True
