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
  background: %(navy)s; color: #fff; border: none; border-radius: 4px;
  padding: 0.5rem 1.2rem; font-weight: 600; font-size: 0.9rem;
}
.stButton > button:hover { background: #16223c; color: #fff; }

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
