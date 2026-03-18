import math
import unicodedata
import pandas as pd
import requests
import streamlit as st

# ================= TOKENS =================
ODDS_API_KEY = "eadde401e09ffab2dd0cce38db739680"
FOOTBALL_DATA_TOKEN = "3b00a840d8364bdfb65c282efbb72a0c"
TELEGRAM_BOT_TOKEN = "8687893562:AAFgU1Mtl24-G5T_BXV54K7goF4dHg1RTsM" 
TELEGRAM_CHAT_ID = "1506188246"

# ================= CONFIG =================
MIN_ODDS = 1.35
MAX_ODDS = 3.20
MIN_PROB = 0.42
MAX_STAKE_PCT = 0.025
DEFAULT_BANKROLL = 1000.0
DEFAULT_EDGE = 2.5
KELLY_FRACTION = 0.25
RECENT_MATCHES = 8

ODDS_BASE = "https://api.the-odds-api.com/v4"
FD_BASE = "https://api.football-data.org/v4"
REGIONS = "eu,uk,us"

LEAGUES = {
    "La Liga": {"odds": "soccer_spain_la_liga", "fd": "PD"},
    "Premier League": {"odds": "soccer_epl", "fd": "PL"},
    "Serie A": {"odds": "soccer_italy_serie_a", "fd": "SA"},
    "Bundesliga": {"odds": "soccer_germany_bundesliga", "fd": "BL1"},
    "Ligue 1": {"odds": "soccer_france_ligue_one", "fd": "FL1"},
    "Champions League": {"odds": "soccer_uefa_champs_league", "fd": "CL"},
    "Europa League": {"odds": "soccer_uefa_europa_league", "fd": "EL"},
}

FALLBACK_ORDER = [
    "Premier League",
    "La Liga",
    "Serie A",
    "Bundesliga",
    "Ligue 1",
    "Champions League",
    "Europa League",
]

# ================= UI =================
st.set_page_config(page_title="AI Betting PRO MAX", page_icon="🔥", layout="wide")
st.title("🔥 AI Betting PRO MAX")
st.caption("Multi-liga + datos reales + fallback automático + Telegram")

tab1, tab2, tab3 = st.tabs(["📊 Picks", "⚽ Partido", "📈 Datos"])

# ================= HELPERS =================
def safe_get(url, headers=None, params=None):
    try:
        r = requests.get(url, headers=headers, params=params, timeout=20)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None

def norm_text(x):
    if x is None:
        return ""
    return unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode().lower().strip()

def poisson(k, lam):
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

def conservative_score(prob, odds, edge):
    if prob is None or odds is None or edge is None:
        return -9999
    odds_penalty = max(0, odds - 2.60) * 18
    prob_bonus = prob * 100
    edge_bonus = edge * 1.2
    return prob_bonus + edge_bonus - odds_penalty

def telegram_send(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False, "Faltan credenciales de Telegram"
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.get(url, params={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=20)
        if r.status_code == 200:
            return True, r.text
        return False, r.text
    except Exception as e:
        return False, str(e)

def map_h2h(name, home, away):
    n = norm_text(name)
    h = norm_text(home)
    a = norm_text(away)
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

# ================= ODDS FETCH =================
def fetch_events_for_sport(sport_key):
    return safe_get(
        f"{ODDS_BASE}/sports/{sport_key}/odds",
        params={
            "apiKey": ODDS_API_KEY,
            "regions": REGIONS,
            "markets": "h2h,totals",
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        },
    )

def fetch_events_with_fallback(selected_league_name):
    tried = []
    first = LEAGUES[selected_league_name]
    events = fetch_events_for_sport(first["odds"])
    tried.append(selected_league_name)

    if events and isinstance(events, list) and len(events) > 0:
        return events, selected_league_name, tried

    for league_name in FALLBACK_ORDER:
        if league_name == selected_league_name:
            continue
        league = LEAGUES[league_name]
        events = fetch_events_for_sport(league["odds"])
        tried.append(league_name)
        if events and isinstance(events, list) and len(events) > 0:
            return events, league_name, tried

    return [], selected_league_name, tried

# ================= FOOTBALL DATA =================
def fd_headers():
    return {"X-Auth-Token": FOOTBALL_DATA_TOKEN}

def fd_competition_standings(fd_code):
    data = safe_get(
        f"{FD_BASE}/competitions/{fd_code}/standings",
        headers=fd_headers()
    )
    if not data:
        return []
    standings = data.get("standings", [])
    if not standings:
        return []
    return standings[0].get("table", [])

def fd_competition_teams(fd_code):
    data = safe_get(
        f"{FD_BASE}/competitions/{fd_code}/teams",
        headers=fd_headers()
    )
    if not data:
        return []
    return data.get("teams", [])

def fd_team_matches(team_id, limit=8):
    data = safe_get(
        f"{FD_BASE}/teams/{team_id}/matches",
        headers=fd_headers(),
        params={"status": "FINISHED", "limit": limit}
    )
    if not data:
        return []
    return data.get("matches", [])

def match_odds_team_to_fd(odds_name, fd_teams):
    target = norm_text(odds_name)
    best = None
    best_score = -1

    for team in fd_teams:
        candidates = [team.get("name", ""), team.get("shortName", ""), team.get("tla", "")]
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
            "played": 0, "gfpg": 1.20, "gapg": 1.20, "ppg": 1.00,
            "home_gfpg": 1.20, "home_gapg": 1.20,
            "away_gfpg": 1.20, "away_gapg": 1.20
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

# ================= MODELO =================
def build_real_model(fd_code, home_name, away_name):
    teams = fd_competition_teams(fd_code)
    table = fd_competition_standings(fd_code)
    if not teams or not table:
        return None

    table_lookup, league_avg = standings_lookup(table)

    home_team = match_odds_team_to_fd(home_name, teams)
    away_team = match_odds_team_to_fd(away_name, teams)
    if not home_team or not away_team:
        return None

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

    p1 = px = p2 = 0.0
    p_over_25 = 0.0

    for i in range(9):
        for j in range(9):
            p = poisson(i, home_lambda) * poisson(j, away_lambda)
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

# ================= SIDEBAR =================
with st.sidebar:
    st.header("Configuración")
    bankroll = st.number_input("Bankroll", min_value=1.0, value=DEFAULT_BANKROLL, step=50.0)
    edge_min = st.slider("Edge mínimo (%)", min_value=0.0, max_value=15.0, value=float(DEFAULT_EDGE), step=0.5)
    st.write(f"Cuotas permitidas: {MIN_ODDS} a {MAX_ODDS}")
    st.write(f"Probabilidad mínima: {int(MIN_PROB * 100)}%")

selected_league_name = st.selectbox("Liga / Competición", list(LEAGUES.keys()))
events, active_league_name, tried_leagues = fetch_events_with_fallback(selected_league_name)

if not events:
    st.warning("⚠️ No hay partidos disponibles ahora mismo en ninguna liga soportada.")
    st.stop()

active_league = LEAGUES[active_league_name]

if active_league_name != selected_league_name:
    st.info(f"No había partidos en {selected_league_name}. Mostrando {active_league_name} como fallback.")

# ================= TAB 1: PICKS =================
with tab1:
    st.header("📊 Mejores picks")
    st.caption(f"Liga mostrada: {active_league_name}")

    all_picks = []

    for e in events:
        model = build_real_model(active_league["fd"], e["home_team"], e["away_team"])
        if model is None:
            continue

        odds_df = extract_odds_rows(e)
        if len(odds_df) == 0:
            continue

        best_1x2 = best_odds_by_market(odds_df, "1X2")
        for sel in ["1", "X", "2"]:
            item = best_1x2.get(sel)
            if not item:
                continue
            prob = model["probs_1x2"].get(sel)
            edge = edge_percent(prob, item["odds"])
            stake = fractional_kelly(prob, item["odds"], bankroll, KELLY_FRACTION)

            if (
                item["odds"] < MIN_ODDS
                or item["odds"] > MAX_ODDS
                or prob < MIN_PROB
                or edge is None
                or edge < edge_min
            ):
                continue

            all_picks.append({
                "Partido": f"{e['home_team']} vs {e['away_team']}",
                "Mercado": "1X2",
                "Pick": sel,
                "Cuota": round(item["odds"], 2),
                "Prob %": round(prob * 100, 1),
                "Edge %": round(edge, 2),
                "Stake €": round(stake, 2),
                "Casa": item["bookmaker"],
                "Score": round(conservative_score(prob, item["odds"], edge), 2)
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

                if (
                    item["odds"] < MIN_ODDS
                    or item["odds"] > MAX_ODDS
                    or prob < MIN_PROB
                    or edge is None
                    or edge < edge_min
                ):
                    continue

                all_picks.append({
                    "Partido": f"{e['home_team']} vs {e['away_team']}",
                    "Mercado": total_markets[0],
                    "Pick": sel,
                    "Cuota": round(item["odds"], 2),
                    "Prob %": round(prob * 100, 1),
                    "Edge %": round(edge, 2),
                    "Stake €": round(stake, 2),
                    "Casa": item["bookmaker"],
                    "Score": round(conservative_score(prob, item["odds"], edge), 2)
                })

    if all_picks:
        df = pd.DataFrame(all_picks).sort_values(["Score", "Edge %"], ascending=False)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.warning("No hay picks con el filtro actual.")

# ================= TAB 2: PARTIDO =================
with tab2:
    st.header("⚽ Analizar partido")

    names = [f"{e['home_team']} vs {e['away_team']}" for e in events]
    selected = st.selectbox("Selecciona partido", names, key="partido_select")

    event = events[names.index(selected)]
    model = build_real_model(active_league["fd"], event["home_team"], event["away_team"])

    if model is None:
        st.warning("No pude cargar el modelo de este partido.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Local", f"{round(model['probs_1x2']['1'] * 100)}%")
        c2.metric("Empate", f"{round(model['probs_1x2']['X'] * 100)}%")
        c3.metric("Visitante", f"{round(model['probs_1x2']['2'] * 100)}%")

        st.subheader("💰 Cuotas por casa")
        odds_df = extract_odds_rows(event)
        if len(odds_df):
            pretty = odds_df.rename(columns={
                "bookmaker": "Casa",
                "market": "Mercado",
                "selection": "Selección",
                "odds": "Cuota"
            }).copy()
            pretty["Cuota"] = pretty["Cuota"].round(2)
            st.dataframe(pretty, use_container_width=True, hide_index=True)

            picks = []
            best_1x2 = best_odds_by_market(odds_df, "1X2")
            for sel in ["1", "X", "2"]:
                item = best_1x2.get(sel)
                if not item:
                    continue
                prob = model["probs_1x2"].get(sel)
                edge = edge_percent(prob, item["odds"])
                if (
                    item["odds"] < MIN_ODDS
                    or item["odds"] > MAX_ODDS
                    or prob < MIN_PROB
                    or edge is None
                    or edge < edge_min
                ):
                    continue
                picks.append({
                    "Mercado": "1X2",
                    "Selección": sel,
                    "Cuota": round(item["odds"], 2),
                    "Prob %": round(prob * 100, 1),
                    "Edge %": round(edge, 2),
                    "Casa": item["bookmaker"]
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
                    if (
                        item["odds"] < MIN_ODDS
                        or item["odds"] > MAX_ODDS
                        or prob < MIN_PROB
                        or edge is None
                        or edge < edge_min
                    ):
                        continue
                    picks.append({
                        "Mercado": total_markets[0],
                        "Selección": sel,
                        "Cuota": round(item["odds"], 2),
                        "Prob %": round(prob * 100, 1),
                        "Edge %": round(edge, 2),
                        "Casa": item["bookmaker"]
                    })

            if picks:
                picks_df = pd.DataFrame(picks).sort_values("Edge %", ascending=False)
                st.subheader("✅ Picks del partido")
                st.dataframe(picks_df, use_container_width=True, hide_index=True)

                top = picks_df.iloc[0]
                msg = (
                    f"📊 AI Betting PRO MAX\n"
                    f"{event['home_team']} vs {event['away_team']}\n"
                    f"Pick: {top['Mercado']} - {top['Selección']}\n"
                    f"Cuota: {top['Cuota']} @ {top['Casa']}\n"
                    f"Prob modelo: {top['Prob %']}%\n"
                    f"Edge: {top['Edge %']}%"
                )
                st.session_state["telegram_msg"] = msg
            else:
                st.info("No hay picks válidos para este partido con el filtro actual.")
                st.session_state.pop("telegram_msg", None)

        left, right = st.columns(2)
        with left:
            st.markdown("### Modelo")
            st.write(f"λ local: {round(model['home_lambda'], 3)}")
            st.write(f"λ visitante: {round(model['away_lambda'], 3)}")
            st.write(model["meta"]["home_recent"])
            st.write(model["meta"]["away_recent"])
        with right:
            st.markdown("### Tabla temporada")
            st.write(model["meta"]["home_table"])
            st.write(model["meta"]["away_table"])

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

# ================= TAB 3: DATOS =================
with tab3:
    st.header("📈 Datos de la competición")
    st.caption(f"Competición activa: {active_league_name}")

    table = fd_competition_standings(active_league["fd"])
    if table:
        df_table = pd.DataFrame([{
            "Equipo": t["team"]["name"],
            "Pos": t["position"],
            "Pts": t["points"],
            "PJ": t["playedGames"],
            "GF": t["goalsFor"],
            "GC": t["goalsAgainst"]
        } for t in table])
        st.dataframe(df_table, use_container_width=True, hide_index=True)
    else:
        st.warning("No pude cargar la tabla de esta competición.")
