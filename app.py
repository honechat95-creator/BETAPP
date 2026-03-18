import streamlit as st
import requests
import pandas as pd

# CONFIG
API_ODDS_KEY = "eadde401e09ffab2dd0cce38db739680"

st.title("📊 AI Betting App")

# INPUT
home_team = st.text_input("Equipo local")
away_team = st.text_input("Equipo visitante")

# GET ODDS
def get_odds():
    url = "https://api.the-odds-api.com/v4/sports/soccer/odds"
    params = {
        "apiKey": API_ODDS_KEY,
        "regions": "eu",
        "markets": "h2h",
        "oddsFormat": "decimal"
    }
    return requests.get(url, params=params).json()

# FIND MATCH
def find_event(data, home, away):
    for event in data:
        if home.lower() in event["home_team"].lower() and away.lower() in event["away_team"].lower():
            return event
    return None

# BEST ODDS
def best_odds(event):
    best = {"home": 0, "draw": 0, "away": 0}

    for book in event["bookmakers"]:
        for market in book["markets"]:
            for outcome in market["outcomes"]:
                name = outcome["name"].lower()
                price = outcome["price"]

                if "draw" in name:
                    best["draw"] = max(best["draw"], price)
                elif name == event["home_team"].lower():
                    best["home"] = max(best["home"], price)
                else:
                    best["away"] = max(best["away"], price)

    return best

# PROBABILITIES
def normalize_probs(odds):
    inv = {k: 1/v for k,v in odds.items() if v > 0}
    total = sum(inv.values())
    return {k: v/total for k,v in inv.items()}

# EV
def ev(prob, odds):
    return (prob * odds) - 1

# BUTTON
if st.button("Buscar value bets"):
    data = get_odds()
    event = find_event(data, home_team, away_team)

    if not event:
        st.error("Partido no encontrado")
    else:
        odds = best_odds(event)
        probs = normalize_probs(odds)

        results = []

        for outcome in ["home", "draw", "away"]:
            if odds[outcome] == 0:
                continue

            expected_value = ev(probs[outcome], odds[outcome])

            results.append({
                "Apuesta": outcome,
                "Cuota": odds[outcome],
                "Probabilidad": round(probs[outcome],2),
                "EV": round(expected_value,2)
            })

        df = pd.DataFrame(results)
        st.table(df)
