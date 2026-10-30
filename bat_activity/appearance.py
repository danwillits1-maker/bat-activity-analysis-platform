"""Small presentation layer using the supplied DJW brand assets."""
from base64 import b64encode
from pathlib import Path

import streamlit as st

BRAND = Path(__file__).resolve().parents[1] / "static" / "brand"


def apply_brand():
    # Native Streamlit theme handles widgets, focus and tables. Keep CSS local
    # to layout and a few stable test-id hooks, rather than generated classes.
    st.html("""
    <style>
      .stMainBlockContainer { max-width: 1380px; padding-top: 3.5rem; }
      [data-testid="stHeader"] { background-color: #02111B; color: #FCFCFC; }
      [data-testid="stHeader"] button,
      [data-testid="stSidebarCollapsedControl"] button { color: #FCFCFC; }
      .djw-brand { background: #02111B; padding: 1.25rem 0 1.4rem;
        margin-bottom: 1rem; border-bottom: 2px solid #E9631A;
        box-shadow: 0 0 0 100vmax #02111B; clip-path: inset(0 -100vmax); }
      .djw-brand img { display: block; width: 210px; max-width: 65%; height: auto; }
      [data-testid="stBaseButton-primary"] { color: #02111B; font-weight: 700; }
      h1 { font-size: 2rem; letter-spacing: -.035em; font-weight: 700; }
      h2, h3 { font-size: 1.3rem; letter-spacing: -.02em; }
      [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
        color: #52666F; opacity: 1; }
      [data-testid="stSidebar"] { border-right: 1px solid #36505B; }
      [data-testid="stSidebar"] [data-testid="stCaptionContainer"],
      [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p { color: #BCCFD5; }
      [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
        background-color: #152731; }
      [data-testid="stTabs"] [role="tablist"] { gap: 1.2rem;
        border-bottom: 1px solid #CCDADF; padding-bottom: .15rem; }
      [data-testid="stTabs"] [role="tab"] { padding: .6rem .1rem; }
      [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
        color: #02111B; font-weight: 700; }
      [data-testid="stMetric"] { background: #F1F6F7; border: 1px solid #CCDADF;
        border-radius: .5rem; padding: 1rem 1.2rem; }
      [data-testid="stMetricValue"] { color: #02111B; }
      [data-testid="stForm"] { background: #F1F6F7; border-color: #CCDADF; }
      @media (max-width: 700px) {
        [data-testid="stTabs"] [role="tablist"] { gap: .8rem; }
        .djw-brand img { width: 175px; }
      }
    </style>
    """)
    logo = b64encode((BRAND / "djw-logo-white.png").read_bytes()).decode("ascii")
    st.html(f'<div class="djw-brand"><img src="data:image/png;base64,{logo}" alt="DJW analytics"></div>')
