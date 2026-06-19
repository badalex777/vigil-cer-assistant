"""
Vigil - UI theme (Streamlit branding).

Sober, institutional palette for a regulatory tool a PRRC must trust:
  ink     #1A1A1A  near-black text
  navy    #1F2D4D  primary (headings, active step, primary buttons)
  brown   #4A3B2E  dark brown accent (secondary emphasis, rules)
  slate   #5C6470  muted grey text
  line    #E2E1DD  hairline borders
  paper   #FFFFFF  surface
  canvas  #F7F6F3  page background (warm off-white, not stark)

The look: clean, quiet, document-like. Boldness is spent in one place - the
stepper that mirrors the locked regulatory workflow - and everything else stays
disciplined. No gradients, minimal radius, generous whitespace.
"""
import streamlit as st

INK = "#1A1A1A"
NAVY = "#1F2D4D"
BROWN = "#4A3B2E"
SLATE = "#5C6470"
LINE = "#E2E1DD"
PAPER = "#FFFFFF"
CANVAS = "#F7F6F3"

_CSS = """
<style>
/* ---- import a clean serif for display + a workhorse sans for body ---- */
@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&family=Inter:wght@400;500;600&display=swap');

/* hide Streamlit chrome for a product look */
#MainMenu, header, footer {visibility: hidden;}
[data-testid="stToolbar"] {display: none;}
[data-testid="stDecoration"] {display: none;}

/* page background */
.stApp { background: %(canvas)s; }
.block-container { max-width: 980px; padding-top: 2.2rem; padding-bottom: 4rem; }

/* typography */
html, body, [class*="css"] { font-family: 'Inter', -apple-system, sans-serif; color: %(ink)s; }
h1, h2, h3, h4 { font-family: 'Source Serif 4', Georgia, serif; color: %(navy)s; letter-spacing: -0.01em; }
h1 { font-weight: 700; font-size: 1.9rem; }
h2 { font-weight: 600; font-size: 1.35rem; margin-top: 0.4rem; }
h3 { font-weight: 600; font-size: 1.1rem; color: %(brown)s; }

/* section subheaders (st.subheader renders an h3) must be visible on cream */
[data-testid="stHeading"] h1, [data-testid="stHeading"] h2,
[data-testid="stHeading"] h3 { color: %(navy)s !important; }

/* field labels - dark, legible on the cream canvas */
[data-testid="stWidgetLabel"] label, [data-testid="stWidgetLabel"] p,
label, .stTextInput label, .stTextArea label, .stSelectbox label,
.stCheckbox label { color: %(ink)s !important; font-weight: 500; opacity: 1 !important; }

/* input fields - white surface, dark text, hairline border */
.stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div,
[data-baseweb="input"] input, [data-baseweb="textarea"] textarea {
  background: %(paper)s !important; color: %(ink)s !important;
  border: 1px solid %(line)s !important; border-radius: 4px !important;
  caret-color: %(navy)s !important;
}
.stTextInput input::placeholder, .stTextArea textarea::placeholder {
  color: #9CA0A8 !important; opacity: 1;
}
.stSelectbox div[data-baseweb="select"] * { color: %(ink)s !important; }

/* ---- DISABLED WIDGETS: Streamlit sets opacity:0.4 on the CONTAINER, not the input.
   We must restore opacity at every level to keep labels and values readable. ---- */
/* Container level - these are Streamlit's testid wrappers */
[data-testid="stTextInput"],
[data-testid="stTextArea"],
[data-testid="stSelectbox"],
[data-testid="stMultiSelect"],
[data-testid="stDateInput"],
[data-testid="stCheckbox"],
[data-testid="stNumberInput"] { opacity: 1 !important; }
/* BaseWeb component level */
[data-baseweb="input"],
[data-baseweb="textarea"],
[data-baseweb="select"],
[data-baseweb="checkbox"] { opacity: 1 !important; }
/* The actual input/textarea elements when disabled */
.stTextInput input:disabled,
.stTextArea textarea:disabled,
[data-baseweb="input"] input:disabled,
[data-baseweb="textarea"] textarea:disabled {
  color: %(ink)s !important; opacity: 1 !important;
  background: #F0EFEb !important;
  -webkit-text-fill-color: %(ink)s !important;
}
/* Disabled selectbox and multiselect inner text */
[data-baseweb="select"][aria-disabled="true"] *,
.stSelectbox [aria-disabled="true"] *,
.stMultiSelect [aria-disabled="true"] * { color: %(ink)s !important; opacity: 1 !important; }
/* Disabled checkboxes */
.stCheckbox [data-testid="stWidgetLabel"] p { color: %(ink)s !important; opacity: 1 !important; }
/* Disabled date_input */
[data-testid="stDateInput"] input:disabled {
  color: %(ink)s !important; opacity: 1 !important;
  -webkit-text-fill-color: %(ink)s !important;
}
/* Widget labels - Streamlit sometimes dims these too */
[data-testid="stWidgetLabel"] { opacity: 1 !important; }
[data-testid="stWidgetLabel"] p { color: %(ink)s !important; }

/* the Vigil wordmark */
.vigil-mark {
  font-family: 'Source Serif 4', serif; font-weight: 700; font-size: 1.5rem;
  color: %(navy)s; letter-spacing: 0.02em;
}
.vigil-mark .tld { color: %(brown)s; }
.vigil-sub { color: %(slate)s; font-size: 0.82rem; margin-top: -0.2rem; }

/* hairline rule */
.rule { border: none; border-top: 1px solid %(line)s; margin: 1.1rem 0; }

/* stepper */
.stepper { display: flex; gap: 0; margin: 0.6rem 0 1.6rem 0; flex-wrap: wrap; }
.step {
  display: flex; align-items: center; gap: 0.5rem; padding: 0.45rem 0.9rem;
  font-size: 0.82rem; color: %(slate)s; border-bottom: 2px solid %(line)s;
  flex: 1; min-width: 120px;
}
.step .num {
  width: 1.5rem; height: 1.5rem; border-radius: 50%%; display: inline-flex;
  align-items: center; justify-content: center; font-weight: 600; font-size: 0.78rem;
  background: %(paper)s; border: 1px solid %(line)s; color: %(slate)s;
}
.step.active { color: %(navy)s; border-bottom-color: %(navy)s; font-weight: 600; }
.step.active .num { background: %(navy)s; color: #fff; border-color: %(navy)s; }
.step.done { color: %(brown)s; border-bottom-color: %(brown)s; }
.step.done .num { background: %(brown)s; color: #fff; border-color: %(brown)s; }

/* cards */
.card {
  background: %(paper)s; border: 1px solid %(line)s; border-radius: 4px;
  padding: 1.2rem 1.4rem; margin: 0.8rem 0;
}
.card h3 { margin-top: 0; }

/* metric chips */
.chips { display: flex; gap: 0.8rem; flex-wrap: wrap; margin: 0.4rem 0 0.8rem 0; }
.chip {
  background: %(paper)s; border: 1px solid %(line)s; border-radius: 4px;
  padding: 0.6rem 0.9rem; min-width: 120px;
}
.chip .k { font-size: 0.72rem; color: %(slate)s; text-transform: uppercase; letter-spacing: 0.04em; }
.chip .v { font-size: 1.3rem; font-weight: 600; color: %(navy)s; font-family: 'Source Serif 4', serif; }
.chip.warn .v { color: #9A3B2E; }

/* primary button */
.stButton > button {
  background: %(navy)s !important; color: #fff !important; border: none; border-radius: 4px;
  padding: 0.5rem 1.2rem; font-weight: 600; font-size: 0.9rem;
}
.stButton > button:hover { background: #16223c !important; color: #fff !important; }
.stButton > button p, .stButton > button div, .stButton > button span {
  color: #fff !important;
}
/* download button - same treatment so it is never transparent */
.stDownloadButton > button {
  background: %(navy)s !important; color: #fff !important; border: none;
  border-radius: 4px; font-weight: 600;
}
.stDownloadButton > button:hover { background: #16223c !important; color: #fff !important; }
.stDownloadButton > button p { color: #fff !important; }

/* expander header - visible without hover (was transparent) */
[data-testid="stExpander"] summary, .streamlit-expanderHeader,
[data-testid="stExpander"] details summary {
  background: %(paper)s !important; color: %(navy)s !important;
  border: 1px solid %(line)s !important; border-radius: 4px !important;
  font-weight: 600; padding: 0.5rem 0.9rem !important;
}
[data-testid="stExpander"] summary:hover { background: #F0EFEB !important; }
[data-testid="stExpander"] summary p, [data-testid="stExpander"] summary span {
  color: %(navy)s !important;
}
[data-testid="stExpander"] { border: none !important; }

/* multiselect tags - readable */
[data-baseweb="tag"] { background: %(navy)s !important; }
[data-baseweb="tag"] span { color: #fff !important; }

/* disclaimer banner */
.disclaimer {
  background: #FBF3E9; border: 1px solid #E6D3BC; border-left: 3px solid %(brown)s;
  border-radius: 4px; padding: 0.7rem 1rem; font-size: 0.84rem; color: %(brown)s;
  margin: 0.6rem 0;
}
/* lock notice */
.locknote {
  background: #EEF1F7; border: 1px solid #D3DCEC; border-left: 3px solid %(navy)s;
  border-radius: 4px; padding: 0.7rem 1rem; font-size: 0.84rem; color: %(navy)s;
}
small, .muted { color: %(slate)s; }
.sectionnote {
  color: %(slate)s; font-size: 0.86rem; line-height: 1.5; margin: -0.2rem 0 0.8rem 0;
  padding: 0.5rem 0.8rem; background: #FAFAF8; border-left: 2px solid %(line)s;
  border-radius: 3px;
}
.sectionnote b { color: %(brown)s; }
.loadingcard {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 2.5rem 1rem; background: %(paper)s; border: 1px solid %(line)s;
  border-radius: 6px; margin: 1rem 0;
}
.loadingcard .spinner {
  width: 38px; height: 38px; border: 3px solid %(line)s; border-top-color: %(navy)s;
  border-radius: 50%%; animation: vigilspin 0.9s linear infinite; margin-bottom: 1rem;
}
@keyframes vigilspin { to { transform: rotate(360deg); } }
.loadingcard .loadtitle {
  font-family: 'Source Serif 4', serif; font-size: 1.2rem; font-weight: 600;
  color: %(navy)s;
}
.loadmsgs {
  position: relative; height: 1.4em; width: 100%%;
  overflow: hidden; margin-top: 0.5rem;
}
.loadmsg {
  position: absolute; width: 100%%; text-align: center;
  color: %(slate)s; font-size: 0.86rem;
  opacity: 0; animation: msgfade linear infinite;
}
@keyframes msgfade {
  0%% { opacity: 0; }
  8%% { opacity: 1; }
  88%% { opacity: 1; }
  96%% { opacity: 0; }
  100%% { opacity: 0; }
}
code { color: %(brown)s; background: #F2EFEA; }
</style>
""" % {"canvas": CANVAS, "ink": INK, "navy": NAVY, "brown": BROWN,
       "slate": SLATE, "line": LINE, "paper": PAPER}


STEPS = [
    "Device Profile",
    "Review & Approve Search",
    "Lock & Start",
    "Research in Progress",
    "Phase B - Manual Upload",
    "Document Set",
]


def inject():
    st.markdown(_CSS, unsafe_allow_html=True)


def header():
    st.markdown(
        '<div class="vigil-mark">VIGIL</div>'
        '<div class="vigil-sub">CER Literature Review Assistant - EU MDR clinical '
        'evaluation support</div><hr class="rule"/>',
        unsafe_allow_html=True)


def stepper(current_index: int):
    html = ['<div class="stepper">']
    for i, name in enumerate(STEPS):
        cls = "step"
        if i < current_index:
            cls += " done"
        elif i == current_index:
            cls += " active"
        num = "OK" if i < current_index else str(i + 1)
        html.append(f'<div class="{cls}"><span class="num">{num}</span>{name}</div>')
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def disclaimer():
    st.markdown(
        '<div class="disclaimer"><b>AI-generated first draft.</b> Every output requires '
        'review, completion, and sign-off by a qualified PRRC / clinical evaluator. '
        'Vigil describes evidence; it does not conclude on safety, performance, '
        'equivalence, or conformity.</div>',
        unsafe_allow_html=True)


def section_note(text: str):
    """Render an explanatory note under a section header (for the PRRC using the tool)."""
    st.markdown(f'<div class="sectionnote">{text}</div>', unsafe_allow_html=True)


def loading_card(placeholder, title="Searching", messages=None):
    """Render a branded loading state with rotating fun-fact messages (pure CSS, no JS)."""
    if messages is None:
        messages = ["Working..."]
    n = len(messages)
    cycle = n * 10   # 10 seconds per message
    spans = ""
    for i, msg in enumerate(messages):
        spans += (f'<span class="loadmsg" '
                  f'style="animation-duration:{cycle}s;animation-delay:{i * 10}s">'
                  f'{msg}</span>')
    placeholder.markdown(
        f'<div class="loadingcard">'
        f'<div class="spinner"></div>'
        f'<div class="loadtitle">{title}</div>'
        f'<div class="loadmsgs">{spans}</div>'
        f'</div>', unsafe_allow_html=True)
