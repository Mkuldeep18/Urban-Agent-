"""
agents.py — Infrastructure Analysis Agents (Updated for realistic sensor data)
===============================================================================
Now uses the richer fields from the new simulator:
  Water: turbidity, pipe_temp, pH, infrastructure_stress, sensor_fault
  Power: frequency_hz, power_factor, thd_pct, demand_kw, infrastructure_stress
"""

SEVERITY = {"NONE":0, "LOW":1, "MEDIUM":2, "HIGH":3, "CRITICAL":4}


def analyze_water(data: dict) -> dict:
    psi      = data["pressure_psi"]
    flow     = data["flow_rate_gpm"]
    turb     = data.get("turbidity_ntu", 0)
    temp     = data.get("pipe_temp_c", 10)
    ph       = data.get("ph", 7.0)
    stress   = data.get("infrastructure_stress", 0)
    fault    = data.get("sensor_fault", False)
    district = data["district"]

    # ── Sensor fault takes priority ───────────────────────────────────
    if fault:
        return _result(data, "SENSOR_FAULT", "MEDIUM",
            f"Sensor fault detected on {data['sensor_id']} in {district}. Reading unreliable.",
            "Schedule sensor recalibration. Do not act on this reading alone.")

    # ── Freeze risk (pipe_temp below 2°C) ─────────────────────────────
    if temp < 2:
        return _result(data, "FREEZE_RISK", "CRITICAL",
            f"Pipe temperature {temp}°C in {district}. High freeze/burst risk.",
            "Emergency insulation team dispatch. Pre-stage repair crews.")

    # ── Pressure rules ────────────────────────────────────────────────
    if psi > 150:
        issue, sev = "PRESSURE_CRITICAL", "CRITICAL"
        msg = f"Extreme pressure {psi} PSI in {district}. Imminent pipe burst."
        act = "Dispatch emergency plumber. Shut isolation valve immediately."
    elif psi > 90:
        issue, sev = "PRESSURE_SPIKE", "HIGH"
        msg = f"Pressure spike {psi} PSI in {district} (normal 40–80)."
        act = "Dispatch plumber. Monitor adjacent district sensors."
    elif psi < 10:
        issue, sev = "MAIN_BREAK", "CRITICAL"
        msg = f"Near-zero pressure {psi} PSI in {district}. Suspected main break."
        act = "Emergency crew dispatch. Notify water authority. Isolate zone."
    elif psi < 20:
        issue, sev = "LOW_PRESSURE", "HIGH"
        msg = f"Low pressure {psi} PSI in {district}. Possible leak."
        act = "Dispatch field inspector to check mains and joints."

    # ── Flow rules ────────────────────────────────────────────────────
    elif flow > 800:
        issue, sev = "FLOW_SURGE", "HIGH"
        msg = f"Abnormal flow {flow} GPM in {district}. Possible major leak."
        act = "Cross-check with nearby sensors. Consider shutting sector valve."
    elif flow > 600:
        issue, sev = "HIGH_FLOW", "MEDIUM"
        msg = f"Elevated flow {flow} GPM in {district}. Monitor for escalation."
        act = "Alert operations team. No immediate dispatch required."
    elif flow < 50:
        issue, sev = "LOW_FLOW", "MEDIUM"
        msg = f"Low flow {flow} GPM in {district}. Possible blockage."
        act = "Schedule routine inspection within 24 hours."

    # ── Water quality rules ───────────────────────────────────────────
    elif turb > 4.0:
        issue, sev = "HIGH_TURBIDITY", "HIGH"
        msg = f"Turbidity {turb} NTU in {district} — possible contamination or pipe damage."
        act = "Issue boil-water advisory. Dispatch water quality team."
    elif turb > 1.0:
        issue, sev = "ELEVATED_TURBIDITY", "MEDIUM"
        msg = f"Turbidity slightly elevated ({turb} NTU) in {district}."
        act = "Monitor water quality. Check upstream filtration."
    elif ph < 6.0 or ph > 9.0:
        issue, sev = "PH_ABNORMAL", "HIGH"
        msg = f"Water pH {ph} in {district} — outside safe range (6.5–8.5). Possible contamination."
        act = "Dispatch water quality inspector. Consider advisory notice."

    # ── High stress (infrastructure degradation) ──────────────────────
    elif stress > 0.7:
        issue, sev = "INFRASTRUCTURE_DEGRADED", "HIGH"
        msg = f"Infrastructure stress {stress:.0%} in {district}. Failure likely soon."
        act = "Schedule urgent pipe inspection and preventive maintenance."
    elif stress > 0.4:
        issue, sev = "INFRASTRUCTURE_STRESSED", "MEDIUM"
        msg = f"Moderate infrastructure stress ({stress:.0%}) in {district}."
        act = "Add to maintenance schedule. Monitor closely."

    else:
        issue, sev = "NORMAL", "NONE"
        msg = f"Water systems normal in {district}. PSI: {psi}, Flow: {flow} GPM, pH: {ph}."
        act = "No action required."

    return _result(data, issue, sev, msg, act)


def analyze_power(data: dict) -> dict:
    voltage  = data["voltage_v"]
    load     = data["load_percent"]
    outage   = data["outage_flag"]
    freq     = data.get("frequency_hz", 60.0)
    pf       = data.get("power_factor", 0.95)
    thd      = data.get("thd_pct", 2.0)
    stress   = data.get("infrastructure_stress", 0)
    demand   = data.get("demand_kw", 0)
    district = data["district"]

    # ── Outage ────────────────────────────────────────────────────────
    if outage:
        return _result(data, "POWER_OUTAGE", "CRITICAL",
            f"Complete power outage in {district}. Voltage: 0V. Demand was {demand} kW.",
            "Dispatch electrician. Activate backup generator protocol. Alert emergency services.")

    # ── Voltage rules ─────────────────────────────────────────────────
    if voltage < 90:
        issue, sev = "SEVERE_BROWNOUT", "CRITICAL"
        msg = f"Severe brownout {voltage}V in {district}. Critical systems at risk."
        act = "Emergency dispatch. Notify hospital and emergency services in zone."
    elif voltage < 105:
        issue, sev = "BROWNOUT", "HIGH"
        msg = f"Brownout {voltage}V in {district} (normal 110–125V)."
        act = "Dispatch electrician. Check substation load balancing."
    elif voltage > 140:
        issue, sev = "SEVERE_SURGE", "CRITICAL"
        msg = f"Voltage surge {voltage}V in {district}. Equipment damage likely."
        act = "Cut supply to zone. Dispatch grid engineer immediately."
    elif voltage > 130:
        issue, sev = "VOLTAGE_SURGE", "HIGH"
        msg = f"Voltage spike {voltage}V in {district}. Appliance damage risk."
        act = "Dispatch electrician. Check surge protector status."

    # ── Load rules ────────────────────────────────────────────────────
    elif load > 95:
        issue, sev = "CRITICAL_OVERLOAD", "CRITICAL"
        msg = f"Substation at {load:.1f}% capacity in {district} ({demand} kW). Cascade failure imminent."
        act = "Immediately redistribute load. Activate emergency demand response."
    elif load > 85:
        issue, sev = "OVERLOAD", "HIGH"
        msg = f"Substation at {load:.1f}% capacity in {district}. Cascade failure risk."
        act = "Redistribute load to adjacent grid. Alert grid operations center."
    elif load > 75:
        issue, sev = "HIGH_LOAD", "MEDIUM"
        msg = f"Elevated load {load:.1f}% in {district}. Monitor for further increase."
        act = "Alert operations team. Prepare load-shedding plan."

    # ── Frequency deviation (healthy grid = exactly 60Hz) ─────────────
    elif abs(freq - 60.0) > 0.5:
        issue, sev = "FREQUENCY_DEVIATION", "HIGH"
        msg = f"Grid frequency {freq} Hz in {district} (normal: 60.00 Hz). Grid stability at risk."
        act = "Alert grid control centre. Check generation-load balance."
    elif abs(freq - 60.0) > 0.2:
        issue, sev = "FREQUENCY_DRIFT", "MEDIUM"
        msg = f"Minor frequency drift {freq} Hz in {district}. Monitor for worsening."
        act = "Log event. Alert grid operations if trend continues."

    # ── Power quality rules ───────────────────────────────────────────
    elif pf < 0.75:
        issue, sev = "LOW_POWER_FACTOR", "HIGH"
        msg = f"Power factor {pf} in {district}. High reactive load — increased line losses."
        act = "Install capacitor banks. Inspect motor loads in district."
    elif pf < 0.85:
        issue, sev = "POOR_POWER_FACTOR", "MEDIUM"
        msg = f"Power factor {pf} in {district}. Suboptimal but not critical."
        act = "Schedule power factor correction assessment."
    elif thd > 10:
        issue, sev = "HIGH_HARMONIC_DISTORTION", "HIGH"
        msg = f"THD {thd}% in {district}. Harmonic distortion may damage equipment."
        act = "Inspect industrial loads. Install harmonic filters if needed."
    elif thd > 6:
        issue, sev = "ELEVATED_THD", "MEDIUM"
        msg = f"Elevated harmonic distortion ({thd}%) in {district}."
        act = "Monitor power quality. Schedule assessment."

    # ── Infrastructure stress ─────────────────────────────────────────
    elif stress > 0.7:
        issue, sev = "INFRASTRUCTURE_DEGRADED", "HIGH"
        msg = f"Electrical infrastructure stress {stress:.0%} in {district}. Risk of fault."
        act = "Schedule urgent equipment inspection and maintenance."
    elif stress > 0.4:
        issue, sev = "INFRASTRUCTURE_STRESSED", "MEDIUM"
        msg = f"Moderate infrastructure stress ({stress:.0%}) in {district}."
        act = "Add to maintenance schedule. Monitor."

    else:
        issue, sev = "NORMAL", "NONE"
        msg = f"Power normal in {district}. Voltage: {voltage}V, Load: {load:.1f}%, Freq: {freq} Hz."
        act = "No action required."

    return _result(data, issue, sev, msg, act)


def _result(data, issue_type, severity, message, action):
    return {
        "sensor_id"         : data["sensor_id"],
        "district"          : data["district"],
        "issue_type"        : issue_type,
        "severity"          : severity,
        "severity_score"    : SEVERITY[severity],
        "message"           : message,
        "recommended_action": action,
        "timestamp"         : data["timestamp"],
        "raw"               : data,
    }
