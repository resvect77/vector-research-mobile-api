#!/usr/bin/env python3
"""
================================================================================
VECTOR RESEARCH // INDEPENDENT MOBILE TELEMETRY API
DOCUMENT REF: VR-MOBILE-API-2026-V1
Standalone FastAPI service for real-time and queried orbital drag analytics.
================================================================================
"""

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone
import math
import json
import urllib.request

app = FastAPI(
    title="Vector Research Mobile Telemetry API",
    version="1.0.0",
    description="Standalone orbital drag and atmospheric forecast engine for mobile applications."
)

# Enable CORS Middleware so mobile devices and web frontends can query the API directly
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows connections from mobile apps and external origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*'
}

@app.get("/")
def root():
    """Health check endpoint."""
    return {
        "status": "ONLINE",
        "system": "Vector Research Mobile API Engine",
        "server_time_utc": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/v1/forecast")
def get_orbital_forecast(
    altitude_km: float = Query(340.0, description="Target altitude in km (e.g. 340, 530, 570)"),
    target_date: str = Query(None, description="Target date in YYYY-MM-DD format"),
    target_time_utc: str = Query(None, description="Target time in HH:MM format")
):
    """
    Main Telemetry Endpoint:
    Ingests live NOAA space weather, calculates thermospheric density (rho),
    and evaluates drag accommodation coefficients (Cd) for specified altitudes.
    """
    now_utc = datetime.now(timezone.utc)
    date_str = target_date if target_date else now_utc.strftime("%Y-%m-%d")
    time_str = target_time_utc if target_time_utc else now_utc.strftime("%H:00")

    # 1. Ingest SWPC Solar Wind Telemetry (Plasma Vx, Magnetic Bz)
    vx, bz = 350.0, 1.0
    try:
        url_plasma = "https://services.swpc.noaa.gov/products/solar-wind/plasma-2-hour.json"
        req_p = urllib.request.Request(url_plasma, headers=HEADERS)
        with urllib.request.urlopen(req_p, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            for row in reversed(data[1:]):
                if len(row) > 1 and row[1] is not None:
                    vx = float(row[1])
                    break

        url_mag = "https://services.swpc.noaa.gov/products/solar-wind/mag-2-hour.json"
        req_m = urllib.request.Request(url_mag, headers=HEADERS)
        with urllib.request.urlopen(req_m, timeout=5) as resp:
            data_m = json.loads(resp.read().decode())
            for row in reversed(data_m[1:]):
                if len(row) > 3 and row[3] is not None:
                    bz = float(row[3])
                    break
    except Exception:
        pass  # Graceful fallback to quiet-state baseline

    # Calculate planetary Kp index estimate
    bz_south = abs(bz) if bz < 0 else 0.0
    kp = round(min(9.0, max(0.0, 0.005 * (vx - 300.0) + bz_south * 0.3)), 1)

    # 2. Thermospheric Density Core Math
    RHO_QUIET_250KM = 1.25e-11
    scale_height = 45.0
    alt_factor = math.exp(-(altitude_km - 250.0) / scale_height)
    rho_baseline = RHO_QUIET_250KM * alt_factor

    # Quiet-State Boundary Evaluation
    is_quiet = (kp < 2.5) and (bz > -3.0) and (vx < 450.0)

    if is_quiet:
        density_delta_pct = 1.19
        status = "QUIET"
    else:
        alpha_dynamic = 2.5e-06 * (1.0 + 0.15 * math.log(1.0 + kp))
        coupling_exponent = alpha_dynamic * vx * bz_south
        shell_coupling = math.exp(coupling_exponent)
        density_delta_pct = round((shell_coupling - 1.0) * 100.0, 2)
        status = "HIGH-DRAG" if density_delta_pct > 50 else "ELEVATED"

    rho_predicted = rho_baseline * (1.0 + (density_delta_pct / 100.0))
    cd_accommodation = round(2.2 + (0.0005 * altitude_km), 3)

    return {
        "request_parameters": {
            "target_altitude_km": altitude_km,
            "target_timestamp_utc": f"{date_str} {time_str} UTC"
        },
        "space_weather": {
            "solar_wind_velocity_km_s": vx,
            "interplanetary_mag_bz_nT": bz,
            "planetary_kp_index": kp
        },
        "prediction_metrics": {
            "status": status,
            "baseline_density_kg_m3": f"{rho_baseline:.5e}",
            "predicted_density_kg_m3": f"{rho_predicted:.5e}",
            "density_surge_pct": density_delta_pct,
            "drag_coefficient_Cd": cd_accommodation
        }
    }
