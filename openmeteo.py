import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta, date
from io import BytesIO
import plotly.express as px
import math

# -------------------------------------------------------------------
# CONFIG GLOBALE
# -------------------------------------------------------------------

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"

# Références "stations" / points météo de suivi en Bretagne
# Tu peux en rajouter autant que tu veux (ex: magasins, villes, etc.).
KNOWN_SITES = [
    {
        "name": "Saint-Brieuc",
        "lat": 48.514,
        "lon": -2.765,
    },
    {
        "name": "Brest",
        "lat": 48.390,
        "lon": -4.486,
    },
    {
        "name": "Rennes",
        "lat": 48.117,
        "lon": -1.677,
    },
    {
        "name": "Quimper",
        "lat": 47.996,
        "lon": -4.098,
    },
    {
        "name": "Vannes",
        "lat": 47.658,
        "lon": -2.760,
    },
]

st.set_page_config(
    page_title="Météo journalière Bretagne",
    page_icon="🌤️",
    layout="wide",
)

st.title("🌤️ Météo journalière Bretagne / Open-Meteo")
st.caption(
    "Températures max/min, pluie journalière. Source : Open-Meteo. "
    "Sélectionne ta zone, récupère les données jour par jour et exporte en Excel."
)

# -------------------------------------------------------------------
# OUTILS MÉTÉO
# -------------------------------------------------------------------

def fetch_daily_weather(lat, lon, start_date_str, end_date_str):
    """
    Récupère les données journalières d'Open-Meteo :
    - Température max/min (°C)
    - Pluie cumulée journalière (mm)
    Timezone Europe/Paris → une ligne = un jour.
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
        return pd.DataFrame(), None

    try:
        data = r.json()
    except Exception as e:
        st.error(f"Réponse API illisible (pas du JSON) : {e}")
        st.write("Réponse brute:", r.text[:500])
        return pd.DataFrame(), None

    if "daily" not in data:
        st.warning("Pas de champ 'daily' dans la réponse.")
        return pd.DataFrame(), None

    daily = data["daily"]
    df = pd.DataFrame(daily)

    # conversion des dates
    df["date"] = pd.to_datetime(df["time"], errors="coerce").dt.date

    df = df.rename(
        columns={
            "temperature_2m_max": "temp_max_C",
            "temperature_2m_min": "temp_min_C",
            "precipitation_sum": "rain_mm",
        }
    )

    df = df[["date", "temp_max_C", "temp_min_C", "rain_mm"]]

    # l'API renvoie aussi meta type 'latitude', 'longitude', 'elevation' si on veut afficher l'altitude
    meta = {
        "lat_used": data.get("latitude"),
        "lon_used": data.get("longitude"),
        "elevation_m": data.get("elevation"),
    }

    return df, meta


def check_missing_days_daily(df: pd.DataFrame, start_date_obj: date, end_date_obj: date):
    """
    Vérifie la complétude : on veut une ligne par jour dans l'intervalle demandé.
    """
    expected_days = pd.date_range(start=start_date_obj, end=end_date_obj, freq="D").date

    if df.empty:
        return list(expected_days), False

    got_days = set(df["date"].astype("object"))
    missing = [d for d in expected_days if d not in got_days]

    return missing, (len(missing) == 0)


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    """
    Convertit le df (date/temp/pluie) en Excel en mémoire pour téléchargement.
    """
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="meteo_journalier")
    return buffer.getvalue()


# -------------------------------------------------------------------
# OUTILS LOCALISATION
# -------------------------------------------------------------------

def haversine_km(lat1, lon1, lat2, lon2):
    """
    Distance approx en km entre deux points lat/lon.
    Formule de Haversine (sphère ~ Terre).
    """
    R = 6371.0  # rayon moyen Terre en km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def find_closest_site(lat_user, lon_user, sites):
    """
    Retourne (site_dict, distance_km) du site connu le plus proche du point (lat_user, lon_user).
    """
    best_site = None
    best_dist = None
    for site in sites:
        d = haversine_km(lat_user, lon_user, site["lat"], site["lon"])
        if best_dist is None or d < best_dist:
            best_dist = d
            best_site = site
    return best_site, best_dist


# -------------------------------------------------------------------
# SIDEBAR - PARAMÈTRES TEMPORELS
# -------------------------------------------------------------------

st.sidebar.header("🗓 Période d'analyse")

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

# -------------------------------------------------------------------
# LOCALISATION UI
# -------------------------------------------------------------------

st.sidebar.header("📍 Localisation météo")

# 1. Choix direct d'un site connu
site_names = [site["name"] for site in KNOWN_SITES]
default_site_index = 0  # Saint-Brieuc par défaut
chosen_site_name = st.sidebar.selectbox(
    "Site / station de référence",
    options=site_names,
    index=default_site_index,
    help="Choisis une ville / point de référence en Bretagne."
)

chosen_site = next(s for s in KNOWN_SITES if s["name"] == chosen_site_name)

st.sidebar.write(
    f"→ {chosen_site['name']} : lat={chosen_site['lat']:.3f}, lon={chosen_site['lon']:.3f}"
)

# 2. Saisie manuelle d'un point perso (ex: magasin précis)
st.sidebar.markdown("Ou bien précise un point personnalisé :")
custom_lat = st.sidebar.number_input(
    "Latitude perso",
    value=chosen_site["lat"],
    format="%.6f"
)
custom_lon = st.sidebar.number_input(
    "Longitude perso",
    value=chosen_site["lon"],
    format="%.6f"
)

closest_site, closest_dist_km = find_closest_site(custom_lat, custom_lon, KNOWN_SITES)

st.sidebar.markdown(
    f"📌 Site connu le plus proche de ton point perso : **{closest_site['name']}** "
    f"({closest_dist_km:.1f} km)"
)

st.sidebar.caption(
    "On va interroger Open-Meteo directement à la latitude/longitude perso. "
    "Le nom affiché sert juste pour étiqueter les graphes."
)

run_query = st.sidebar.button("🔍 Récupérer la météo")


# -------------------------------------------------------------------
# CARTE DES SITES
# -------------------------------------------------------------------

st.subheader("🗺 Carte des sites météo connus / points d'analyse")

map_df = pd.DataFrame(
    [
        {
            "site": site["name"],
            "lat": site["lat"],
            "lon": site["lon"],
        }
        for site in KNOWN_SITES
    ]
)

st.map(
    data=map_df.rename(columns={"lat": "latitude", "lon": "longitude"}),
    zoom=7,
)

st.caption(
    "Les points affichés sont les localisations de référence configurées. "
    "Tu peux saisir une latitude/longitude perso dans la barre latérale."
)

st.markdown("---")


# -------------------------------------------------------------------
# MAIN : APPEL METEO + ANALYSE
# -------------------------------------------------------------------

if run_query:
    start_str = start_date_input.strftime("%Y-%m-%d")
    end_str   = end_date_input.strftime("%Y-%m-%d")

    # On interroge Open-Meteo AVEC la localisation perso (custom_lat/custom_lon)
    with st.spinner("Appel Open-Meteo (données journalières)..."):
        daily_df, meta_info = fetch_daily_weather(
            lat=custom_lat,
            lon=custom_lon,
            start_date_str=start_str,
            end_date_str=end_str,
        )

    if daily_df.empty:
        st.warning("Aucune donnée retournée par Open-Meteo pour cet intervalle.")
    else:
        # bloc info localisation effective
        st.subheader("📌 Localisation utilisée")
        colA, colB, colC = st.columns(3)
        with colA:
            st.metric("Point choisi (lat)", f"{custom_lat:.4f}")
        with colB:
            st.metric("Point choisi (lon)", f"{custom_lon:.4f}")
        with colC:
            st.write(f"Site connu le plus proche : **{closest_site['name']}** ({closest_dist_km:.1f} km)")
        if meta_info:
            st.write(
                f"ℹ️ Open-Meteo a répondu pour lat={meta_info['lat_used']}, "
                f"lon={meta_info['lon_used']}, altitude≈{meta_info['elevation_m']} m."
            )

        # tableau météo jour par jour
        st.subheader("📅 Données météo journalières normalisées")
        st.dataframe(daily_df, use_container_width=True)

        # contrôle complétude
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

        # graph température max
        if daily_df["temp_max_C"].notna().any():
            fig_tmax = px.line(
                daily_df,
                x="date",
                y="temp_max_C",
                markers=True,
                title=f"Température max quotidienne (°C) - {closest_site['name']}",
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
                title=f"Pluie cumulée sur la journée (mm) - {closest_site['name']}",
            )
            fig_rain.update_layout(
                xaxis_title="Jour",
                yaxis_title="mm / jour",
            )
            st.plotly_chart(fig_rain, use_container_width=True)

        # export Excel
        excel_bytes = to_excel_bytes(daily_df)
        st.download_button(
            label="⬇ Télécharger l'Excel (météo journalière)",
            data=excel_bytes,
            file_name=f"meteo_{closest_site['name'].lower().replace(' ','-')}_{start_str}_to_{end_str}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

else:
    st.info("➡ Choisis ta période, ta localisation personnalisée (ou une ville connue), puis clique sur 'Récupérer la météo'.")


# -------------------------------------------------------------------
# NOTES TECH
# -------------------------------------------------------------------

with st.expander("🔎 Notes techniques / intégration métier"):
    st.markdown(
        """
        **Comment ça marche :**
        - Les points affichés sur la carte sont des localisations de référence (villes/stations Bretagne).
        - Tu peux saisir une latitude / longitude perso (par ex. l'adresse d'un magasin).
        - On calcule automatiquement le point connu le plus proche, juste pour l'étiquette.
        - L'appel Open-Meteo se fait sur TES coordonnées perso en direct.
        - Résultat : une ligne/jour (température max/min, pluie cumulée).
        - On contrôle qu'il ne manque pas de jour entre les bornes.
        - Tu peux télécharger l'Excel pour le merger avec ton CA journalier.
        """
    )
