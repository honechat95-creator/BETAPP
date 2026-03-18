import math
import unicodedata

import pandas as pd
import requests
import streamlit as st

# =========================================================
# TOKENS / CONFIG
# =========================================================
ODDS_API_KEY = "eadde401e09ffab2dd0cce38db739680"
FOOTBALL_DATA_TOKEN = "3b00a840d8364bdfb65c282efbb72a0c"
TELEGRAM_BOT_TOKEN = "8687893562:AAFgU1Mtl24-G5T_BXV54K7goF4dHg1RTsM" 
TELEGRAM_CHAT_ID = "1506188246"

ODDS_BASE = "https://api.the-odds-api.com/v4"
FD_BASE = "https://api.football-data.org/v4"
TG_BASE = "https://api.telegram.org"

TIMEOUT = 20
DEFAULT_BANKROLL = 1000.0
DEFAULT_EDGE = 2.5
KELLY_FRACTION = 0.25
RECENT_MATCHES = 8

# =========================================================
# FILTRO MUCHO MÁS ESTRICTO
# =========================================================
MIN_ODDS = 1.35
MAX_ODDS = 3.20
MIN_MODEL_PROB = 0.42
MAX_STAKE_PCT = 0.025   # 2.5% máximo
MAX_FAIR_ODDS = 3.00    # si el modelo cree que "fair" es más alta, descartamos
ONLY_MARKET_FAVORITE = True   # solo picks que estén entre las opciones más probables del mercado

LEAGUES = {
    "Premier League": {"odds_key": "soccer_epl", "fd_code": "PL"},
    "La Liga": {"odds_key": "soccer_spain_la_liga", "fd_code": "PD"},
    "Bundesliga": {"odds_key": "soccer_germany_bundesliga", "fd_code": "BL1"},
    "Serie A": {"odds_key": "soccer_italy_serie_a", "fd_code": "SA"},
    "Ligue 1": {"odds_key": "soccer_france_ligue_one", "fd_code": "FL1"},
    "Eredivisie": {"odds_key": "soccer_netherlands_eredivisie", "fd_code": "DED"},
    "Primeira Liga": {"odds_key": "soccer_portugal_primeira_liga", "fd_code": "PPL"},
    "Champions League": {"odds_key": "soccer_uefa_champs_league", "fd_code": "CL"},
}

st.set_page_config(page_title="AI Betting Pro Max", page_icon="📊", layout="wide")
st.title("📊 AI Betting Pro Max")
st.caption("Versión filtrada para picks más estables y menos sorpresas extremas.")

# =========================================================
# HELPERS
# =========================================================
def norm_text(text: str) -> str:
    if text is None:
        return ""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    for r in [" fc", " cf", " sc", " ac", " afc", ".", ",", "-", "_", "'", '"']:
        text = text.replace(r, " ")
    return " ".join(text.split())

def safe_get(url, headers=None, params=None):
    r = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)

def edge_percent(prob, odds):
    if not prob or not odds or odds <= 1:
        return None
    return ((prob * odds) - 1) * 100

def fractional_kelly(prob, odds, bankroll, fraction=0.25):
    if not prob or not odds or odds <= 1:
        return 0.0
    b = odds - 1
    q = 1 - prob
    f = (b * prob - q) / b
    f = max(0.0, f) * fraction
    f = min(f, MAX_STAKE_PCT)
    return bankroll * f

def conservative_score(prob, odds, edge, fair_odds, market_rank):
    if prob is None or odds is None or edge is None or fair_odds is None:
        return -9999

    # Castigo muy fuerte a cuotas altas y a selecciones secundarias del mercado
    odds_penalty = max(0, odds - 2.60) * 18
    fair_penalty = max(0, fair_odds - 2.60) * 20
    rank_penalty = 12 if market_rank > 1 else 0
    prob_bonus = prob * 100
    edge_bonus = edge * 1.2

    return prob_bonus + edge_bonus - odds_penalty - fair_penalty - rank_penalty

def fd_headers():
    return {"X-Auth-Token": FOOTBALL_DATA_TOKEN}

def telegram_send(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False, "Falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID"

    url = f"{TG_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    params = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return True, r.text
    except Exception as e:
        return False, str(e)

def get_market_rank(best_market_dict, selection):
    prices = []
    for sel, item in best_market_dict.items():
        prices.append((sel, item["odds"]))
    prices = sorted(prices, key=lambda x: x[1])  # menor cuota = más favorito
    for idx, (sel, _) in enumerate(prices, start=1):
        if sel == selection:
            return idx
    return 99

# =========================================================
# ODDS API
# =========================================================
def fetch_events_with_odds(sport_key: str):
    url = f"{ODDS_BASE}/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h,totals",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    data = safe_get(url, params=params)
    if not isinstance(data, list):
        raise ValueError("Respuesta inesperada de The Odds API")
    return data

def map_h2h(name, home_team, away_team):
    n = norm_text(name)
    h = norm_text(home_team)
    a = norm_text(away_team)
    if n == h:
        return "1"
    if n == a:
        return "2"
    if "draw" in n or n == "empate" or n == "x":
        return "X"
    return None

def map_totals(name, point):
    n = norm_text(name)
    if point is None:
        return None
    if "over" in n:
        return f"Over {point}"
    if "under" in n:
        return f"Under {point}"
    return None

def extract_odds_rows(event):
    rows = []
    home_team = event["home_team"]
    away_team = event["away_team"]

    for bookmaker in event.get("bookmakers", []):
        book = bookmaker.get("title", "Desconocido")

        for market in bookmaker.get("markets", []):
            mkey = market.get("key")

            for outcome in market.get("outcomes", []):
                price = outcome.get("price")
                if not isinstance(price, (int, float)) or price <= 1:
                    continue

                selection = None
                market_name = None

                if mkey == "h2h":
                    selection = map_h2h(outcome.get("name", ""), home_team, away_team)
                    market_name = "1X2"

                elif mkey == "totals":
                    selection = map_totals(outcome.get("name", ""), outcome.get("point"))
                    if selection:
                        market_name = f"Totales {outcome.get('point')}"

                if selection:
                    rows.append({
                        "bookmaker": book,
                        "market": market_name,
                        "selection": selection,
                        "odds": float(price)
                    })

    return pd.DataFrame(rows)

def best_odds_by_market(df_market, market_name):
    sub = df_market[df_market["market"] == market_name].copy()
    result = {}

    for sel in sorted(sub["selection"].unique()):
        s = sub[sub["selection"] == sel].sort_values("odds", ascending=False)
        if len(s):
            row = s.iloc[0]
            result[sel] = {
                "odds": float(row["odds"]),
                "bookmaker": row["bookmaker"]
            }

    return result

# =========================================================
# FOOTBALL-DATA
# =========================================================
def fd_competition_teams(fd_code: str):
    url = f"{FD_BASE}/competitions/{fd_code}/teams"
    data = safe_get(url, headers=fd_headers())
    return data.get("teams", [])

def fd_competition_standings(fd_code: str):
    url = f"{FD_BASE}/competitions/{fd_code}/standings"
    data = safe_get(url, headers=fd_headers())
    standings = data.get("standings", [])
    total_table = None

    for s in standings:
        if s.get("type") == "TOTAL":
            total_table = s.get("table", [])
            break

    if total_table is None and standings:
        total_table = standings[0].get("table", [])

    return total_table or []

def fd_team_matches(team_id: int, limit: int = 8):
    url = f"{FD_BASE}/teams/{team_id}/matches"
    params = {"status": "FINISHED", "limit": limit}
    data = safe_get(url, headers=fd_headers(), params=params)
    return data.get("matches", [])

def match_odds_team_to_fd(odds_name: str, fd_teams: list):
    target = norm_text(odds_name)
    best = None
    best_score = -1

    for team in fd_teams:
        candidates = [
            team.get("name", ""),
            team.get("shortName", ""),
            team.get("tla", "")
        ]
        for c in candidates:
            c_norm = norm_text(c)
            if not c_norm:
                continue

            score = 0
            if target == c_norm:
                score = 100
            elif target in c_norm or c_norm in target:
                score = 80
            else:
                overlap = len(set(target.split()) & set(c_norm.split()))
                score = overlap * 10

            if score > best_score:
                best_score = score
                best = team

    return best if best_score >= 10 else None

def compute_recent_team_stats(matches, team_id):
    played = wins = draws = losses = 0
    gf = ga = 0
    home_gf = home_ga = home_p = 0
    away_gf = away_ga = away_p = 0

    for m in matches:
        full = m.get("score", {}).get("fullTime", {})
        hg, ag = full.get("home"), full.get("away")
        if hg is None or ag is None:
            continue

        home_id = m.get("homeTeam", {}).get("id")
        away_id = m.get("awayTeam", {}).get("id")

        if home_id == team_id:
            team_gf, team_ga = hg, ag
            home_gf += team_gf
            home_ga += team_ga
            home_p += 1
        elif away_id == team_id:
            team_gf, team_ga = ag, hg
            away_gf += team_gf
            away_ga += team_ga
            away_p += 1
        else:
            continue

        played += 1
        gf += team_gf
        ga += team_ga

        if team_gf > team_ga:
            wins += 1
        elif team_gf == team_ga:
            draws += 1
        else:
            losses += 1

    if played == 0:
        return {
            "played": 0,
            "gfpg": 1.20,
            "gapg": 1.20,
            "ppg": 1.00,
            "home_gfpg": 1.20,
            "home_gapg": 1.20,
            "away_gfpg": 1.20,
            "away_gapg": 1.20
        }

    points = wins * 3 + draws
    return {
        "played": played,
        "gfpg": gf / played,
        "gapg": ga / played,
        "ppg": points / played,
        "home_gfpg": home_gf / home_p if home_p else gf / played,
        "home_gapg": home_ga / home_p if home_p else ga / played,
        "away_gfpg": away_gf / away_p if away_p else gf / played,
        "away_gapg": away_ga / away_p if away_p else ga / played
    }

def standings_lookup(table):
    lookup = {}
    total_goals_for = 0
    total_played = 0

    for row in table:
        team = row.get("team", {})
        tid = team.get("id")
        played = row.get("playedGames", 0) or 0
        gf = row.get("goalsFor", 0) or 0
        ga = row.get("goalsAgainst", 0) or 0
        pts = row.get("points", 0) or 0
        pos = row.get("position", 0) or 0

        total_goals_for += gf
        total_played += played

        lookup[tid] = {
            "position": pos,
            "played": played,
            "gfpg": (gf / played) if played else 1.20,
            "gapg": (ga / played) if played else 1.20,
            "ppg": (pts / played) if played else 1.00
        }

    league_avg_gfpg = (total_goals_for / total_played) if total_played else 1.35
    return lookup, league_avg_gfpg

# =========================================================
# MODEL
# =========================================================
def build_real_model(fd_code, home_name, away_name):
    teams = fd_competition_teams(fd_code)
    table = fd_competition_standings(fd_code)
    table_lookup, league_avg = standings_lookup(table)

    home_team = match_odds_team_to_fd(home_name, teams)
    away_team = match_odds_team_to_fd(away_name, teams)

    if not home_team or not away_team:
        raise ValueError("No pude mapear uno de los equipos a football-data.org")

    home_id = home_team["id"]
    away_id = away_team["id"]

    home_matches = fd_team_matches(home_id, RECENT_MATCHES)
    away_matches = fd_team_matches(away_id, RECENT_MATCHES)

    home_recent = compute_recent_team_stats(home_matches, home_id)
    away_recent = compute_recent_team_stats(away_matches, away_id)

    home_table = table_lookup.get(home_id, {"gfpg": league_avg, "gapg": league_avg, "ppg": 1.20, "position": 10})
    away_table = table_lookup.get(away_id, {"gfpg": league_avg, "gapg": league_avg, "ppg": 1.20, "position": 10})

    home_attack = 0.35 * home_recent["gfpg"] + 0.25 * home_recent["home_gfpg"] + 0.40 * home_table["gfpg"]
    away_attack = 0.35 * away_recent["gfpg"] + 0.25 * away_recent["away_gfpg"] + 0.40 * away_table["gfpg"]

    home_def_weak = 0.35 * home_recent["gapg"] + 0.25 * home_recent["home_gapg"] + 0.40 * home_table["gapg"]
    away_def_weak = 0.35 * away_recent["gapg"] + 0.25 * away_recent["away_gapg"] + 0.40 * away_table["gapg"]

    home_ppg = 0.5 * home_recent["ppg"] + 0.5 * home_table["ppg"]
    away_ppg = 0.5 * away_recent["ppg"] + 0.5 * away_table["ppg"]

    strength_boost_home = 1 + max(-0.18, min(0.18, (home_ppg - away_ppg) * 0.05))
    strength_boost_away = 1 + max(-0.18, min(0.18, (away_ppg - home_ppg) * 0.05))

    home_advantage = 1.10

    raw_home_lambda = ((home_attack + away_def_weak) / 2) * strength_boost_home * home_advantage
    raw_away_lambda = ((away_attack + home_def_weak) / 2) * strength_boost_away

    home_lambda = max(0.25, min(3.60, raw_home_lambda))
    away_lambda = max(0.20, min(3.60, raw_away_lambda))

    max_goals = 8
    p_home = {i: poisson_pmf(i, home_lambda) for i in range(max_goals + 1)}
    p_away = {i: poisson_pmf(i, away_lambda) for i in range(max_goals + 1)}

    p1 = px = p2 = 0.0
    p_over_25 = 0.0

    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = p_home[i] * p_away[j]
            if i > j:
                p1 += p
            elif i == j:
                px += p
            else:
                p2 += p
            if i + j > 2:
                p_over_25 += p

    p_under_25 = max(0.0, 1 - p_over_25)

    return {
        "home_lambda": home_lambda,
        "away_lambda": away_lambda,
        "probs_1x2": {"1": p1, "X": px, "2": p2},
        "probs_totals_25": {"Over 2.5": p_over_25, "Under 2.5": p_under_25},
        "meta": {
            "home_recent": home_recent,
            "away_recent": away_recent,
            "home_table": home_table,
            "away_table": away_table
        }
    }

# =========================================================
# UI
# =========================================================
with st.sidebar:
    st.header("Configuración")
    bankroll = st.number_input("Bankroll", min_value=1.0, value=DEFAULT_BANKROLL, step=50.0)
    edge_min = st.slider("Edge mínimo (%)", min_value=0.0, max_value=15.0, value=float(DEFAULT_EDGE), step=0.5)
    st.markdown("---")
    st.write(f"Cuotas permitidas: {MIN_ODDS} a {MAX_ODDS}")
    st.write(f"Probabilidad mínima: {int(MIN_MODEL_PROB * 100)}%")
    st.write(f"Fair odds máxima: {MAX_FAIR_ODDS}")
    st.caption("Filtro diseñado para evitar underdogs extremos.")

league_name = st.selectbox("Competición", list(LEAGUES.keys()))
league = LEAGUES[league_name]

try:
    with st.spinner("Cargando partidos y cuotas..."):
        events = fetch_events_with_odds(league["odds_key"])

    if not events:
        st.warning("No hay partidos disponibles.")
        st.stop()

    labels = {}
    for e in events:
        label = f"{e['home_team']} vs {e['away_team']} | {e.get('commence_time', 'N/D')}"
        labels[label] = e

    selected_label = st.selectbox("Partido", list(labels.keys()))

    if st.button("Analizar partido", use_container_width=True):
        event = labels[selected_label]
        odds_df = extract_odds_rows(event)

        if len(odds_df) == 0:
            st.error("No encontré cuotas válidas para este partido.")
            st.stop()

        model = build_real_model(league["fd_code"], event["home_team"], event["away_team"])

        st.subheader(f"{event['home_team']} vs {event['away_team']}")
        st.write(f"**Inicio:** {event.get('commence_time', 'N/D')}")

        picks = []

        best_1x2 = best_odds_by_market(odds_df, "1X2")
        for sel in ["1", "X", "2"]:
            item = best_1x2.get(sel)
            if not item:
                continue

            prob = model["probs_1x2"].get(sel)
            edge = edge_percent(prob, item["odds"])
            stake = fractional_kelly(prob, item["odds"], bankroll, KELLY_FRACTION)
            fair_odds = (1 / prob) if prob else None
            market_rank = get_market_rank(best_1x2, sel)

            if (
                item["odds"] < MIN_ODDS
                or item["odds"] > MAX_ODDS
                or prob < MIN_MODEL_PROB
                or fair_odds is None
                or fair_odds > MAX_FAIR_ODDS
            ):
                continue

            if ONLY_MARKET_FAVORITE and market_rank > 1:
                continue

            picks.append({
                "Mercado": "1X2",
                "Selección": sel,
                "Mejor cuota": round(item["odds"], 2),
                "Casa": item["bookmaker"],
                "Prob. modelo %": round(prob * 100, 2),
                "Fair odds": round(fair_odds, 2),
                "Edge %": round(edge, 2) if edge is not None else None,
                "Stake €": round(stake, 2),
                "Score": round(conservative_score(prob, item["odds"], edge, fair_odds, market_rank), 2),
                "Value": "Sí" if edge is not None and edge >= edge_min else "No"
            })

        total_markets = [m for m in odds_df["market"].dropna().unique() if str(m).startswith("Totales 2.5")]
        if total_markets:
            best_totals = best_odds_by_market(odds_df, total_markets[0])

            for sel in ["Over 2.5", "Under 2.5"]:
                item = best_totals.get(sel)
                if not item:
                    continue

                prob = model["probs_totals_25"].get(sel)
                edge = edge_percent(prob, item["odds"])
                stake = fractional_kelly(prob, item["odds"], bankroll, KELLY_FRACTION)
                fair_odds = (1 / prob) if prob else None
                market_rank = get_market_rank(best_totals, sel)

                if (
                    item["odds"] < MIN_ODDS
                    or item["odds"] > MAX_ODDS
                    or prob < MIN_MODEL_PROB
                    or fair_odds is None
                    or fair_odds > MAX_FAIR_ODDS
                ):
                    continue

                picks.append({
                    "Mercado": total_markets[0],
                    "Selección": sel,
                    "Mejor cuota": round(item["odds"], 2),
                    "Casa": item["bookmaker"],
                    "Prob. modelo %": round(prob * 100, 2),
                    "Fair odds": round(fair_odds, 2),
                    "Edge %": round(edge, 2) if edge is not None else None,
                    "Stake €": round(stake, 2),
                    "Score": round(conservative_score(prob, item["odds"], edge, fair_odds, market_rank), 2),
                    "Value": "Sí" if edge is not None and edge >= edge_min else "No"
                })

        if not picks:
            st.warning("No hay picks que cumplan el filtro estable.")
            st.session_state.pop("telegram_msg", None)
            st.stop()

        result_df = pd.DataFrame(picks)
        result_df = result_df[result_df["Value"] == "Sí"]

        if len(result_df) == 0:
            st.warning("No hay value claro dentro del filtro estable.")
            st.session_state.pop("telegram_msg", None)
            st.stop()

        result_df = result_df.sort_values(
            by=["Score", "Prob. modelo %", "Edge %"],
            ascending=False,
            na_position="last"
        )

        st.dataframe(result_df, use_container_width=True, hide_index=True)
        st.success(f"Se detectaron {len(result_df)} picks estables con value.")

        top = result_df.iloc[0]
        msg = (
            f"📊 AI Betting Pro Max\n"
            f"{event['home_team']} vs {event['away_team']}\n"
            f"Pick: {top['Mercado']} - {top['Selección']}\n"
            f"Cuota: {top['Mejor cuota']} @ {top['Casa']}\n"
            f"Prob modelo: {top['Prob. modelo %']}%\n"
            f"Edge: {top['Edge %']}%\n"
            f"Stake: {top['Stake €']}€"
        )
        st.session_state["telegram_msg"] = msg

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("### Modelo")
            st.write(f"λ local: {round(model['home_lambda'], 3)}")
            st.write(f"λ visitante: {round(model['away_lambda'], 3)}")
            st.write(model["meta"]["home_recent"])
            st.write(model["meta"]["away_recent"])
        with c2:
            st.markdown("### Tabla temporada")
            st.write(model["meta"]["home_table"])
            st.write(model["meta"]["away_table"])

        st.markdown("### Cuotas por casa")
        pretty = odds_df.rename(columns={
            "bookmaker": "Casa",
            "market": "Mercado",
            "selection": "Selección",
            "odds": "Cuota"
        }).copy()
        pretty["Cuota"] = pretty["Cuota"].round(2)
        st.dataframe(pretty, use_container_width=True, hide_index=True)

    if "telegram_msg" in st.session_state:
        if st.button("Enviar mejor pick a Telegram", use_container_width=True):
            ok, info = telegram_send(st.session_state["telegram_msg"])
            if ok:
                st.success("Pick enviado a Telegram.")
            else:
                st.error(f"No se pudo enviar: {info}")

    if st.button("TEST TELEGRAM", use_container_width=True):
        ok, info = telegram_send("🚀 BOT FUNCIONANDO")
        if ok:
            st.success("Mensaje de prueba enviado")
        else:
            st.error(f"Error Telegram: {info}")

except requests.HTTPError as e:
    st.error(f"Error HTTP: {e}")
except requests.RequestException as e:
    st.error(f"Error de conexión: {e}")
except Exception as e:
    st.error(f"Error: {e}")
