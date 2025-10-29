import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta, date
from io import BytesIO
import plotly.express as px

# -------------------------------------------------------------------
# CONFIG GÉNÉRALE
# -------------------------------------------------------------------

SAINT_BRIEUC_LAT = 48.514
SAINT_BRIEUC_LON = -2.765

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"

st.set_page_config(
    page_title="Météo journalière - Saint-Brieuc",
    page_icon="🌤️",
    layout="wide",
)

st.title("🌤️ Météo journalière (Saint-Brieuc / Open-Meteo)")
st.caption(
    "Températures max/min, cumul pluie par jour. Source : Open-Meteo (données historiques interpolées)."
)

# -------------------------------------------------------------------
# OUTILS
# -------------------------------------------------------------------

def fetch_daily_weather(lat, lon, start_date_str, end_date_str):
    """
    Récupère les données journalières d'Open-Meteo pour une paire (lat, lon)
    entre start_date_str et end_date_str (YYYY-MM-DD).
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "daily": [
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
        ],
        "timezone": "Europe/Paris",
    }

    r = requests.get(OPEN_METEO_URL, params=params, timeout=30)

    st.write("🛰️ DEBUG status_code:", r.status_code)
    st.write("🛰️ DEBUG URL appelée:", r.url)

    if r.status_code != 200:
        st.error(f"Erreur API Open-Meteo (HTTP {r.status_code})")
        st.write("Réponse brute:", r.text[:500])
        return pd.DataFrame()

    try:
        data = r.json()
    except Exception as e:
        st.error(f"Réponse API illisible (pas du JSON) : {e}")
        st.write("Réponse brute:", r.text[:500])
        return pd.DataFrame()

    if "daily" not in data:
        st.warning("Pas de champ 'daily' dans la réponse.")
        return pd.DataFrame()

    daily = data["daily"]
    df = pd.DataFrame(daily)

    # time = liste de dates en chaîne
    df["date"] = pd.to_datetime(df["time"], errors="coerce").dt.date

    df = df.rename(
        columns={
            "temperature_2m_max": "temp_max_C",
            "temperature_2m_min": "temp_min_C",
            "precipitation_sum": "rain_mm",
        }
    )

    df = df[["date", "temp_max_C", "temp_min_C", "rain_mm"]]

    return df


def check_missing_days_daily(df: pd.DataFrame, start_date_obj: date, end_date_obj: date):
    """
    Vérifie si chaque jour entre start_date_obj et end_date_obj est présent.
    """
    expected_days = pd.date_range(start=start_date_obj, end=end_date_obj, freq="D").date

    if df.empty:
        return list(expected_days), False

    got_days = set(df["date"].astype("object"))
    missing = [d for d in expected_days if d not in got_days]

    return missing, (len(missing) == 0)


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    """
    Exporte le df en Excel (XLSX) en mémoire, renvoie les bytes.
    """
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="meteo_journalier")
    return buffer.getvalue()


# -------------------------------------------------------------------
# SIDEBAR
# -------------------------------------------------------------------

st.sidebar.header("⚙️ Paramètres")

st.sidebar.write("📍 Localisation : Saint-Brieuc (Côtes-d'Armor, Bretagne)")
st.sidebar.write(f"Latitude : `{SAINT_BRIEUC_LAT}` | Longitude : `{SAINT_BRIEUC_LON}`")

today_utc = datetime.utcnow().date()
default_start = today_utc - timedelta(days=14)

start_date_input = st.sidebar.date_input(
    "Date début (inclus)",
    value=default_start,
    max_value=today_utc,
)

end_date_input = st.sidebar.date_input(
    "Date fin (inclus)",
    value=today_utc,
    max_value=today_utc,
    min_value=start_date_input,
)

run_query = st.sidebar.button("🔍 Récupérer la météo")

st.markdown("---")

# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------

if run_query:
    start_str = start_date_input.strftime("%Y-%m-%d")
    end_str   = end_date_input.strftime("%Y-%m-%d")

    with st.spinner("Appel Open-Meteo (données journalières)..."):
        daily_df = fetch_daily_weather(
            lat=SAINT_BRIEUC_LAT,
            lon=SAINT_BRIEUC_LON,
            start_date_str=start_str,
            end_date_str=end_str,
        )

    if daily_df.empty:
        st.warning("Aucune donnée retournée par Open-Meteo pour cet intervalle.")
    else:
        st.subheader("📅 Données météo journalières normalisées")
        st.dataframe(daily_df, use_container_width=True)

        # check complétude
        missing_days, ok_all_days = check_missing_days_daily(
            daily_df,
            start_date_obj=start_date_input,
            end_date_obj=end_date_input,
        )

        if ok_all_days:
            st.success("✅ Toutes les dates entre début et fin sont présentes.")
        else:
            st.warning(
                "⚠ Certaines dates n'ont pas de ligne météo : "
                + ", ".join(str(d) for d in missing_days)
            )

        # graph temp max
        if daily_df["temp_max_C"].notna().any():
            fig_tmax = px.line(
                daily_df,
                x="date",
                y="temp_max_C",
                markers=True,
                title="Température max quotidienne (°C)",
            )
            fig_tmax.update_layout(
                xaxis_title="Jour",
                yaxis_title="°C",
            )
            st.plotly_chart(fig_tmax, use_container_width=True)

        # graph pluie
        if daily_df["rain_mm"].notna().any():
            fig_rain = px.bar(
                daily_df,
                x="date",
                y="rain_mm",
                title="Pluie cumulée sur la journée (mm)",
            )
            fig_rain.update_layout(
                xaxis_title="Jour",
                yaxis_title="mm / jour",
            )
            st.plotly_chart(fig_rain, use_container_width=True)

        # export excel
        excel_bytes = to_excel_bytes(daily_df)
        st.download_button(
            label="⬇ Télécharger l'Excel (météo journalière)",
            data=excel_bytes,
            file_name=f"meteo_saint-brieuc_{start_str}_to_{end_str}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

else:
    st.info("➡ Choisis la période dans la barre latérale puis clique sur 'Récupérer la météo'.")

with st.expander("🔎 Notes techniques"):
    st.markdown(
        """
        - Source : Open-Meteo Archive API.
        - Résolution : quotidienne (déjà agrégée).
        - temp_max_C / temp_min_C : °C.
        - rain_mm : mm cumulés sur la journée.
        - Les dates sont déjà en timezone Europe/Paris via l'API.
        - Le bouton Excel exporte exactement ce tableau, prêt à fusionner avec ton CA journalier.
        """
    )
