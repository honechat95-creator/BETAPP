import math
import unicodedata
import pandas as pd
import requests
import streamlit as st

# ================= CONFIG =================
ODDS_API_KEY = "eadde401e09ffab2dd0cce38db739680"
FOOTBALL_DATA_TOKEN = "3b00a840d8364bdfb65c282efbb72a0c"
TELEGRAM_BOT_TOKEN = "8687893562:AAFgU1Mtl24-G5T_BXV54K7goF4dHg1RTsM" 
TELEGRAM_CHAT_ID = "1506188246"

ODDS_BASE = "https://api.the-odds-api.com/v4"
FD_BASE = "https://api.football-data.org/v4"
TIMEOUT = 20

# FILTRO PRO
MIN_ODDS = 1.35
MAX_ODDS = 3.2
MIN_PROB = 0.42

# ================= UI =================
st.set_page_config(layout="wide")
st.title("🔥 AI BETTING PRO MAX")

tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "⚽ Partido", "📈 Datos"])

# ================= HELPERS =================
def safe_get(url, headers=None, params=None):
    r = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def norm(x):
    return unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode().lower()

def telegram_send(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.get(url, params={"chat_id": TELEGRAM_CHAT_ID, "text": msg})

def poisson(k, lam):
    return math.exp(-lam) * (lam ** k) / math.factorial(k)

# ================= DATA =================
def get_events():
    return safe_get(
        f"{ODDS_BASE}/sports/soccer_spain_la_liga/odds",
        params={"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h,totals"}
    )

def get_teams():
    return safe_get(
        f"{FD_BASE}/competitions/PD/teams",
        headers={"X-Auth-Token": FOOTBALL_DATA_TOKEN}
    )["teams"]

def get_table():
    data = safe_get(
        f"{FD_BASE}/competitions/PD/standings",
        headers={"X-Auth-Token": FOOTBALL_DATA_TOKEN}
    )
    return data["standings"][0]["table"]

# ================= MODEL =================
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

# ================= DASHBOARD =================
with tab1:
    st.header("📊 Mejores oportunidades")

    events = get_events()

    picks = []

    for e in events:
        probs = model(e["home_team"], e["away_team"])

        for b in e["bookmakers"]:
            for m in b["markets"]:
                if m["key"] != "h2h":
                    continue

                for o in m["outcomes"]:
                    price = o["price"]
                    name = o["name"]

                    sel = "1" if name == e["home_team"] else "2" if name == e["away_team"] else "X"
                    prob = probs[sel]

                    edge = prob * price - 1

                    if price < MIN_ODDS or price > MAX_ODDS or prob < MIN_PROB:
                        continue

                    picks.append({
                        "Partido": f"{e['home_team']} vs {e['away_team']}",
                        "Pick": sel,
                        "Cuota": price,
                        "Prob": round(prob * 100, 1),
                        "Edge": round(edge * 100, 2)
                    })

    df = pd.DataFrame(picks).sort_values("Edge", ascending=False)

    st.dataframe(df, use_container_width=True)

# ================= PARTIDO =================
with tab2:
    st.header("⚽ Analizar partido")

    events = get_events()
    names = [f"{e['home_team']} vs {e['away_team']}" for e in events]

    sel = st.selectbox("Partido", names)
    e = events[names.index(sel)]

    probs = model(e["home_team"], e["away_team"])

    c1, c2, c3 = st.columns(3)

    c1.metric("Local", f"{round(probs['1']*100)}%")
    c2.metric("Empate", f"{round(probs['X']*100)}%")
    c3.metric("Visitante", f"{round(probs['2']*100)}%")

    st.subheader("Cuotas")

    for b in e["bookmakers"]:
        for m in b["markets"]:
            if m["key"] == "h2h":
                for o in m["outcomes"]:
                    st.write(b["title"], o["name"], o["price"])

    if st.button("Enviar a Telegram"):
        telegram_send(f"Pick {sel}")

# ================= DATOS =================
with tab3:
    st.header("📈 Datos equipos")

    table = get_table()

    df = pd.DataFrame([{
        "Equipo": t["team"]["name"],
        "Pts": t["points"],
        "GF": t["goalsFor"],
        "GC": t["goalsAgainst"]
    } for t in table])

    st.dataframe(df, use_container_width=True)
