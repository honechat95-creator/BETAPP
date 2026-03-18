import math
import unicodedata
import pandas as pd
import requests
import streamlit as st

# ================= TOKENS =================
ODDS_API_KEY = "PEGA_AQUI"
FOOTBALL_DATA_TOKEN = "PEGA_AQUI"
TELEGRAM_BOT_TOKEN = "PEGA_AQUI"
TELEGRAM_CHAT_ID = "PEGA_AQUI"

# ================= CONFIG =================
MIN_ODDS = 1.35
MAX_ODDS = 3.20
MIN_PROB = 0.42

ODDS_BASE = "https://api.the-odds-api.com/v4"
FD_BASE = "https://api.football-data.org/v4"

LEAGUES = {
    # 🇪🇸 ESPAÑA
    "La Liga": {"odds": "soccer_spain_la_liga", "fd": "PD"},
    "Segunda División": {"odds": "soccer_spain_segunda_division", "fd": "SD"},

    # 🏴 INGLATERRA
    "Premier League": {"odds": "soccer_epl", "fd": "PL"},
    "Championship": {"odds": "soccer_efl_championship", "fd": "ELC"},

    # 🇮🇹 ITALIA
    "Serie A": {"odds": "soccer_italy_serie_a", "fd": "SA"},
    "Serie B": {"odds": "soccer_italy_serie_b", "fd": "SB"},

    # 🇩🇪 ALEMANIA
    "Bundesliga": {"odds": "soccer_germany_bundesliga", "fd": "BL1"},
    "Bundesliga 2": {"odds": "soccer_germany_bundesliga2", "fd": "BL2"},

    # 🇫🇷 FRANCIA
    "Ligue 1": {"odds": "soccer_france_ligue_one", "fd": "FL1"},
    "Ligue 2": {"odds": "soccer_france_ligue_two", "fd": "FL2"},

    # 🇳🇱 HOLANDA
    "Eredivisie": {"odds": "soccer_netherlands_eredivisie", "fd": "DED"},

    # 🇵🇹 PORTUGAL
    "Primeira Liga": {"odds": "soccer_portugal_primeira_liga", "fd": "PPL"},

    # 🇧🇪 BELGICA
    "Belgian Pro League": {"odds": "soccer_belgium_first_div", "fd": "BSA"},

    # 🌍 EUROPEAS
    "Champions League": {"odds": "soccer_uefa_champs_league", "fd": "CL"},
    "Europa League": {"odds": "soccer_uefa_europa_league", "fd": "EL"},
    "Conference League": {"odds": "soccer_uefa_europa_conference_league", "fd": "ECL"},
}

# ================= UI =================
st.set_page_config(layout="wide")
st.title("🔥 AI Betting PRO MAX")

tab1, tab2, tab3 = st.tabs(["📊 Picks", "⚽ Partido", "📈 Datos"])

# ================= HELPERS =================
def safe_get(url, headers=None, params=None):
    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def norm(x):
    return unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode().lower()

def poisson(k, lam):
    return math.exp(-lam) * (lam ** k) / math.factorial(k)

def telegram_send(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.get(url, params={"chat_id": TELEGRAM_CHAT_ID, "text": msg})

# ================= MODELO =================
def model(home, away):
    lam_home = 1.5
    lam_away = 1.2

    p1 = px = p2 = 0

    for i in range(6):
        for j in range(6):
            p = poisson(i, lam_home) * poisson(j, lam_away)
            if i > j:
                p1 += p
            elif i == j:
                px += p
            else:
                p2 += p

    return {"1": p1, "X": px, "2": p2}

# ================= SELECTOR LIGA =================
league_name = st.selectbox("Liga", list(LEAGUES.keys()))
league = LEAGUES[league_name]

events = safe_get(
    f"{ODDS_BASE}/sports/{league['odds']}/odds",
    params={"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h,totals"}
)

# ================= TAB 1 (PICKS) =================
with tab1:
    st.header("📊 Mejores picks")

    picks = []

    for e in events:
        probs = model(e["home_team"], e["away_team"])

        for b in e["bookmakers"]:
            for m in b["markets"]:
                if m["key"] != "h2h":
                    continue

                for o in m["outcomes"]:
                    price = o["price"]

                    sel = "1" if o["name"] == e["home_team"] else "2" if o["name"] == e["away_team"] else "X"
                    prob = probs[sel]
                    edge = prob * price - 1

                    if price < MIN_ODDS or price > MAX_ODDS or prob < MIN_PROB:
                        continue

                    picks.append({
                        "Partido": f"{e['home_team']} vs {e['away_team']}",
                        "Pick": sel,
                        "Cuota": price,
                        "Prob %": round(prob * 100, 1),
                        "Edge %": round(edge * 100, 2),
                        "Casa": b["title"]
                    })

    df = pd.DataFrame(picks)

    if len(df):
        df = df.sort_values("Edge %", ascending=False)
        st.dataframe(df, use_container_width=True)
    else:
        st.warning("No hay picks con filtro actual")

# ================= TAB 2 (PARTIDO) =================
with tab2:
    st.header("⚽ Analizar partido")

    names = [f"{e['home_team']} vs {e['away_team']}" for e in events]
    selected = st.selectbox("Selecciona partido", names)

    e = events[names.index(selected)]

    probs = model(e["home_team"], e["away_team"])

    c1, c2, c3 = st.columns(3)
    c1.metric("Local", f"{round(probs['1']*100)}%")
    c2.metric("Empate", f"{round(probs['X']*100)}%")
    c3.metric("Visitante", f"{round(probs['2']*100)}%")

    st.subheader("💰 Mejores cuotas")

    for b in e["bookmakers"]:
        for m in b["markets"]:
            if m["key"] == "h2h":
                for o in m["outcomes"]:
                    st.write(b["title"], "-", o["name"], "-", o["price"])

    if st.button("Enviar pick a Telegram"):
        telegram_send(f"Pick: {selected}")

# ================= TAB 3 (DATOS) =================
with tab3:
    st.header("📈 Tabla liga")

    table = safe_get(
        f"{FD_BASE}/competitions/{league['fd']}/standings",
        headers={"X-Auth-Token": FOOTBALL_DATA_TOKEN}
    )

    table = table["standings"][0]["table"]

    df = pd.DataFrame([{
        "Equipo": t["team"]["name"],
        "Pts": t["points"],
        "GF": t["goalsFor"],
        "GC": t["goalsAgainst"]
    } for t in table])

    st.dataframe(df, use_container_width=True)
