# Vector Research // Mobile Telemetry API
**Document Ref:** `VR-MOBILE-API-2026-V1`

A lightweight, high-performance FastAPI microservice designed for mobile clients and edge nodes. It ingests live space weather telemetry from NOAA's Space Weather Prediction Center (SWPC) to dynamically model LEO thermospheric density variations ($\rho$) and drag accommodation coefficients ($C_d$).

---

## Technical Features

* **Real-time Ingestion**: Live integration with NOAA SWPC 2-hour plasma and magnetometer JSON feeds.
* **Deterministic Atmospheric Modeling**:
  * Scale-height thermospheric baseline density calculation anchored at 250 km altitude ($\rho_0 = 1.25 \times 10^{-11} \text{ kg/m}^3$).
  * Dynamic solar wind geomagnetic coupling exponent using bulk plasma speed ($v_x$) and southward IMF ($B_z$).
  * Synthetic Planetary $K_p$ index estimation.
  * Altitude-dependent drag accommodation coefficient ($C_d$).
* **Cross-Origin Ready**: Integrated CORS middleware configured for mobile and web frontends.
* **Resilient Fallbacks**: Graceful degradation to quiet-state baseline parameters during upstream API timeouts or connectivity disruptions.

---

## Core Analytical Equations

### 1. Baseline Thermospheric Density
$$\rho_{\text{baseline}} = \rho_{250} \cdot \exp\left(-\frac{h - 250}{H}\right)$$
*Where $H = 45.0 \text{ km}$ (Scale Height) and $\rho_{250} = 1.25 \times 10^{-11} \text{ kg/m}^3$.*

### 2. Estimated $K_p$ Index Model
$$K_p = \min\left(9.0, \max\left(0.0, 0.005(v_x - 300) + 0.3 |B_z^-|\right)\right)$$

### 3. Drag Coefficient ($C_d$) Accommodation
$$C_d = 2.2 + 0.0005 \cdot h$$

---

## Quickstart & Deployment

### Prerequisites
* Python 3.9+
* `fastapi`
* `uvicorn`

### Setup
```bash
# Clone the repository
git clone [https://github.com/vector-research/mobile-telemetry-api.git](https://github.com/vector-research/mobile-telemetry-api.git)
cd mobile-telemetry-api

# Install dependencies
pip install fastapi uvicorn
