import streamlit as st
import requests
import pandas as pd
from statistics import mean

# =========================
# CONFIG
# =========================
API_ODDS_KEY = "eadde401e09ffab2dd0cce38db739680"
SPORT_KEY = "soccer"
REGIONS = "eu"
MARKETS = "h2h"
ODDS_FORMAT = "decimal"
DATE_FORMAT = "iso"
TIMEOUT_SECONDS = 20
MIN_EDGE_PERCENT = 2.0  # value mínimo para marcar en verde

st.set_page_config(page_title="AI Betting App Pro", page_icon="📊", layout="centered")
st.title("📊 AI Betting App Pro")
st.caption("Selecciona un partido real disponible y analiza value bets con consenso de mercado.")

# =========================
# HELPERS
# =========================
def fetch_odds():
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT_KEY}/odds"
    params = {
        "apiKey": API_ODDS_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": DATE_FORMAT,
    }
    resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, dict) and data.get("message"):
        raise ValueError(data["message"])

    if not isinstance(data, list):
        raise ValueError("Respuesta inesperada de la API")

    return data

def outcome_side(outcome_name, home_team, away_team):
    name = str(outcome_name).strip().lower()
    home = str(home_team).strip().lower()
    away = str(away_team).strip().lower()

    if name == home:
        return "home"
    if name == away:
        return "away"
    if "draw" in name or name == "empate":
        return "draw"
    return None

def extract_market_table(event):
    rows = []
    home_team = event["home_team"]
    away_team = event["away_team"]

    for bookmaker in event.get("bookmakers", []):
        book_title = bookmaker.get("title", "Desconocido")

        for market in bookmaker.get("markets", []):
            if market.get("key") != "h2h":
                continue

            for outcome in market.get("outcomes", []):
                side = outcome_side(outcome.get("name", ""), home_team, away_team)
                price = outcome.get("price")

                if side and isinstance(price, (int, float)) and price > 1:
                    rows.append({
                        "bookmaker": book_title,
                        "side": side,
                        "odds": float(price)
                    })

    return pd.DataFrame(rows)

def get_best_odds(df_market):
    result = {}
    for side in ["home", "draw", "away"]:
        side_df = df_market[df_market["side"] == side].sort_values("odds", ascending=False)
        if len(side_df) > 0:
            best = side_df.iloc[0]
            result[side] = {
                "odds": float(best["odds"]),
                "bookmaker": best["bookmaker"]
            }
        else:
            result[side] = {
                "odds": None,
                "bookmaker": None
            }
    return result

def get_consensus_odds(df_market):
    result = {}
    for side in ["home", "draw", "away"]:
        prices = df_market[df_market["side"] == side]["odds"].tolist()
        result[side] = mean(prices) if prices else None
    return result

def no_vig_probs_from_odds(odds_dict):
    valid = {k: v for k, v in odds_dict.items() if isinstance(v, (int, float)) and v > 1}
    if len(valid) < 2:
        return None

    inv = {k: 1 / v for k, v in valid.items()}
    total = sum(inv.values())

    probs = {k: inv[k] / total for k in valid}
    for side in ["home", "draw", "away"]:
        probs.setdefault(side, None)
    return probs

def fair_odds_from_probs(probs):
    fair = {}
    for side, p in probs.items():
        if p and p > 0:
            fair[side] = 1 / p
        else:
            fair[side] = None
    return fair

def edge_percent(best_odds, fair_odds):
    if not best_odds or not fair_odds or fair_odds <= 0:
        return None
    return ((best_odds / fair_odds) - 1) * 100

def build_value_table(best_odds, consensus_probs, fair_odds):
    labels = {
        "home": "Local",
        "draw": "Empate",
        "away": "Visitante"
    }

    rows = []
    for side in ["home", "draw", "away"]:
        best_price = best_odds[side]["odds"]
        best_book = best_odds[side]["bookmaker"]
        prob = consensus_probs.get(side)
        fair = fair_odds.get(side)
        edge = edge_percent(best_price, fair)

        rows.append({
            "Mercado": labels[side],
            "Mejor cuota": round(best_price, 2) if best_price else None,
            "Casa": best_book,
            "Prob. consenso": round(prob * 100, 2) if prob else None,
            "Fair odds": round(fair, 2) if fair else None,
            "Edge %": round(edge, 2) if edge is not None else None,
            "Value": "Sí" if edge is not None and edge >= MIN_EDGE_PERCENT else "No"
        })

    return pd.DataFrame(rows)

def display_event_summary(event, df_market):
    st.subheader(f"{event['home_team']} vs {event['away_team']}")
    st.write(f"**Inicio:** {event.get('commence_time', 'N/D')}")
    st.write(f"**Bookmakers detectados:** {df_market['bookmaker'].nunique() if len(df_market) else 0}")

# =========================
# APP
# =========================
try:
    with st.spinner("Cargando partidos reales..."):
        events = fetch_odds()

    if not events:
        st.warning("No hay partidos disponibles ahora mismo en la API.")
        st.stop()

    options = []
    event_map = {}

    for event in events:
        label = f"{event['home_team']} vs {event['away_team']} | {event.get('commence_time', 'N/D')}"
        options.append(label)
        event_map[label] = event

    selected_label = st.selectbox("Selecciona un partido", options)

    if st.button("Analizar partido", use_container_width=True):
        event = event_map[selected_label]
        df_market = extract_market_table(event)

        if len(df_market) == 0:
            st.error("No se encontraron cuotas válidas para este partido.")
            st.stop()

        display_event_summary(event, df_market)

        best = get_best_odds(df_market)
        consensus_odds = get_consensus_odds(df_market)
        probs = no_vig_probs_from_odds(consensus_odds)

        if probs is None:
            st.error("No se pudo calcular el consenso del mercado.")
            st.stop()

        fair = fair_odds_from_probs(probs)
        result_df = build_value_table(best, probs, fair)

        st.markdown("### Resultado")
        st.dataframe(result_df, use_container_width=True, hide_index=True)

        value_df = result_df[result_df["Value"] == "Sí"]
        if len(value_df) > 0:
            st.success("Hay selecciones con value según el consenso del mercado.")
        else:
            st.warning("No hay value claro con el filtro actual.")

        st.markdown("### Cuotas por casa")
        market_view = df_market.copy()
        market_view["odds"] = market_view["odds"].round(2)
        market_view = market_view.rename(columns={
            "bookmaker": "Casa",
            "side": "Mercado",
            "odds": "Cuota"
        })
        market_view["Mercado"] = market_view["Mercado"].replace({
            "home": "Local",
            "draw": "Empate",
            "away": "Visitante"
        })
        st.dataframe(market_view, use_container_width=True, hide_index=True)

except requests.HTTPError as e:
    st.error(f"Error HTTP con la API: {e}")
except requests.RequestException as e:
    st.error(f"Error de conexión: {e}")
except Exception as e:
    st.error(f"Error: {e}")
