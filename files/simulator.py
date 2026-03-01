"""
simulator.py — Realistic City Infrastructure Data Generators
=============================================================
WHAT MAKES THIS REALISTIC:

1. TIME-OF-DAY PATTERNS
   Water demand and power load follow real daily usage curves:
   - Water: peaks in morning (6-9am) and evening (6-9pm)
   - Power: peaks in afternoon/evening (4-10pm), low at night

2. WEATHER INFLUENCE
   Simulated weather state affects both water and power realistically:
   - Heatwave: high power (AC), low water pressure (high demand)
   - Storm: voltage fluctuations, pipe stress
   - Cold snap: burst pipe risk, heating load spike

3. GRADUAL ANOMALY PROGRESSION
   Real infrastructure doesn't fail instantly. A pipe leak starts
   as a small pressure drop, worsens over time, then bursts.
   Uses shared state to simulate progressive degradation.

4. SENSOR NOISE AND DRIFT
   Real sensors have Gaussian noise, calibration drift, and rare faults.

5. DISTRICT CHARACTERISTICS
   Each district has different baseline water/power demand and pipe age.

6. CORRELATED FAILURES
   A water main break raises pressure in adjacent districts.
"""

import random
import math
from datetime import datetime, timezone

# ── Shared simulation state (persists between calls) ──────────────────────────
_state = {
    "weather"           : "normal",
    "weather_timer"     : 20,
    "water_stress"      : {f"District-{i}": 0.0 for i in range(1, 7)},
    "power_stress"      : {f"District-{i}": 0.0 for i in range(1, 7)},
    "water_drift"       : {f"District-{i}": 0.0 for i in range(1, 7)},
    "power_drift"       : {f"District-{i}": 0.0 for i in range(1, 7)},
    "active_water_event": set(),
    "tick"              : 0,
}

DISTRICT_PROFILES = {
    "District-1": {"type": "residential", "water_base": 55,  "power_base": 115, "age_factor": 0.8},
    "District-2": {"type": "commercial",  "water_base": 65,  "power_base": 120, "age_factor": 0.6},
    "District-3": {"type": "industrial",  "water_base": 70,  "power_base": 122, "age_factor": 0.9},
    "District-4": {"type": "residential", "water_base": 52,  "power_base": 113, "age_factor": 1.3},
    "District-5": {"type": "mixed",       "water_base": 60,  "power_base": 118, "age_factor": 0.7},
    "District-6": {"type": "industrial",  "water_base": 75,  "power_base": 121, "age_factor": 1.1},
}

def _noise(value, std_pct=0.02):
    return round(value + random.gauss(0, value * std_pct), 2)

def _time_of_day():
    hour = datetime.now().hour
    water_curve = [0.55,0.50,0.48,0.47,0.50,0.65,0.90,1.30,1.35,1.10,0.95,0.90,
                   0.85,0.80,0.78,0.80,0.88,1.20,1.30,1.25,1.10,0.95,0.80,0.65]
    power_curve = [0.55,0.50,0.48,0.46,0.47,0.52,0.65,0.78,0.88,0.92,0.94,0.95,
                   0.96,0.95,0.94,0.96,1.05,1.15,1.25,1.30,1.28,1.15,1.00,0.80]
    return water_curve[hour], power_curve[hour]

def _weather_mods():
    w = _state["weather"]
    return {
        "normal"   : (1.00, 1.00, 1.0),
        "heatwave" : (0.88, 0.93, 1.6),
        "storm"    : (0.95, 0.90, 2.0),
        "cold_snap": (0.92, 0.94, 1.8),
    }[w]

def _update_weather():
    _state["weather_timer"] -= 1
    if _state["weather_timer"] <= 0:
        roll = random.random()
        if   roll < 0.60: _state["weather"] = "normal";   _state["weather_timer"] = random.randint(30, 60)
        elif roll < 0.75: _state["weather"] = "heatwave"; _state["weather_timer"] = random.randint(15, 35)
        elif roll < 0.88: _state["weather"] = "storm";    _state["weather_timer"] = random.randint(10, 25)
        else:             _state["weather"] = "cold_snap";_state["weather_timer"] = random.randint(10, 20)

def _evolve_stress(district, stress_dict, age_factor):
    _, _, risk_mult = _weather_mods()
    fail_prob = 0.04 * age_factor * risk_mult
    s = stress_dict[district]
    if random.random() < fail_prob:
        stress_dict[district] = min(1.0, s + random.uniform(0.05, 0.20))
    else:
        stress_dict[district] = max(0.0, s - random.uniform(0.01, 0.04))


# ── WATER SENSOR ──────────────────────────────────────────────────────────────

def get_water_data() -> dict:
    _state["tick"] += 1
    _update_weather()

    district = random.choice(list(DISTRICT_PROFILES.keys()))
    profile  = DISTRICT_PROFILES[district]
    _evolve_stress(district, _state["water_stress"], profile["age_factor"])
    stress = _state["water_stress"][district]

    water_f, _ = _time_of_day()
    pres_mod, _, _ = _weather_mods()

    # Base pressure: higher demand (morning/evening) slightly lowers pressure
    demand_drop = 1.0 - (water_f - 1.0) * 0.12
    stress_drop = 1.0 - stress * 0.70
    true_psi    = profile["water_base"] * demand_drop * pres_mod * stress_drop

    # Hydraulic coupling: nearby district events raise pressure slightly
    for d in _state["active_water_event"]:
        if d != district:
            true_psi *= (1.0 + random.uniform(0.02, 0.05))

    # Sensor drift
    _state["water_drift"][district] = max(-5, min(5,
        _state["water_drift"][district] + random.gauss(0, 0.03)))
    pressure_psi = max(0.0, _noise(true_psi + _state["water_drift"][district], 0.015))

    # Rare sensor fault (0.5%)
    sensor_fault = random.random() < 0.005
    if sensor_fault:
        pressure_psi = random.choice([0.0, 999.9, round(true_psi * 3.1, 2)])

    # Flow rate: correlated with pressure and time-of-day demand
    base_flow  = 180 + water_f * 120
    true_flow  = base_flow * (pressure_psi / profile["water_base"]) * random.uniform(0.92, 1.08)
    flow_rate  = round(max(0.0, _noise(true_flow, 0.025)), 2)

    # Track active events for hydraulic coupling
    if pressure_psi < 20 or pressure_psi > 90:
        _state["active_water_event"].add(district)
    else:
        _state["active_water_event"].discard(district)

    # Turbidity: spikes when pipes are stressed (sediment disturbance)
    turbidity_ntu = round(random.uniform(0.1, 0.5) + stress * 4.5, 2)

    # Pipe temperature: cold snap raises freeze risk
    pipe_temp_c = {
        "normal"   : round(random.uniform(8, 18), 1),
        "heatwave" : round(random.uniform(20, 30), 1),
        "storm"    : round(random.uniform(5, 15), 1),
        "cold_snap": round(random.uniform(-3, 6), 1),
    }[_state["weather"]]

    # pH (normal: 6.5–8.5; stressed pipes leach minerals)
    ph = round(random.uniform(6.5, 8.5) - stress * 0.8, 2)

    return {
        "sensor_id"            : f"WTR-{district[-1]}-{random.randint(100,999):03d}",
        "district"             : district,
        "pressure_psi"         : round(pressure_psi, 2),
        "flow_rate_gpm"        : flow_rate,
        "turbidity_ntu"        : turbidity_ntu,
        "pipe_temp_c"          : pipe_temp_c,
        "ph"                   : ph,
        "infrastructure_stress": round(stress, 3),
        "weather"              : _state["weather"],
        "sensor_fault"         : sensor_fault,
        "battery_pct"          : round(random.uniform(55, 100), 1),
        "signal_strength_pct"  : round(random.uniform(60, 100), 1),
        "timestamp"            : datetime.now(timezone.utc).isoformat(),
        "unit"                 : "PSI / GPM / NTU / C / pH",
    }


# ── POWER SENSOR ──────────────────────────────────────────────────────────────

def get_power_data() -> dict:
    district = random.choice(list(DISTRICT_PROFILES.keys()))
    profile  = DISTRICT_PROFILES[district]
    _evolve_stress(district, _state["power_stress"], profile["age_factor"])
    stress = _state["power_stress"][district]

    _, power_f = _time_of_day()
    _, volt_mod, _ = _weather_mods()
    weather = _state["weather"]

    # Load: industrial flat, residential peaks hard in evening
    if profile["type"] == "industrial":
        base_load = 55 + (power_f - 1.0) * 20
    elif profile["type"] == "commercial":
        base_load = 35 + (power_f - 1.0) * 45
    else:
        base_load = 25 + (power_f - 1.0) * 55

    weather_load = {"normal":1.0, "heatwave":1.30, "storm":1.10, "cold_snap":1.25}[weather]
    true_load = min(105, base_load * weather_load + stress * 25)

    # Voltage sags under high load (Ohm's law)
    load_sag     = (true_load / 100) * 8
    true_voltage = (profile["power_base"] - load_sag) * volt_mod - stress * 15

    # Sensor drift
    _state["power_drift"][district] = max(-3, min(3,
        _state["power_drift"][district] + random.gauss(0, 0.05)))
    voltage_v    = max(0.0, _noise(true_voltage + _state["power_drift"][district], 0.008))
    load_percent = max(0.0, _noise(true_load, 0.01))

    # Outage: likely only when stress is very high during storm
    outage_thresh = 0.85 if weather == "storm" else 0.93
    outage_flag   = stress > outage_thresh and random.random() < 0.4
    if outage_flag:
        voltage_v = 0.0; load_percent = 0.0

    # Frequency: healthy = 60.00 Hz; stress causes drift
    frequency_hz = round(60.0 + random.gauss(0, 0.015) + stress * 0.08, 3)

    # Power factor: lower for industrial (motors), higher for residential
    pf_base = {"industrial":0.82, "commercial":0.88, "residential":0.94, "mixed":0.90}
    power_factor = round(max(0.5, min(1.0,
        pf_base[profile["type"]] - stress * 0.06 + random.gauss(0, 0.01))), 3)

    # Total harmonic distortion: higher in industrial, spikes under stress
    thd_pct = round(random.uniform(1.5, 4.0) + stress * 8.0 +
                    (3.0 if profile["type"] == "industrial" else 0), 2)

    # Estimated demand kW
    capacity_kw = {"residential":5000, "commercial":8000, "industrial":15000, "mixed":7000}
    demand_kw   = round(capacity_kw[profile["type"]] * (load_percent / 100), 1)

    return {
        "sensor_id"            : f"PWR-{district[-1]}-{random.randint(100,999):03d}",
        "district"             : district,
        "voltage_v"            : round(voltage_v, 2),
        "load_percent"         : round(load_percent, 2),
        "demand_kw"            : demand_kw,
        "frequency_hz"         : frequency_hz,
        "power_factor"         : power_factor,
        "thd_pct"              : thd_pct,
        "outage_flag"          : outage_flag,
        "infrastructure_stress": round(stress, 3),
        "weather"              : weather,
        "battery_pct"          : round(random.uniform(55, 100), 1),
        "signal_strength_pct"  : round(random.uniform(60, 100), 1),
        "timestamp"            : datetime.now(timezone.utc).isoformat(),
        "unit"                 : "V / % / kW / Hz",
    }
