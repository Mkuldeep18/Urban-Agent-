from datetime import datetime
from collections import defaultdict


COMPLAINT_CLUSTER_THRESHOLD = 3 
_escalated_districts: set = set()


# ─── HEALTH SCORE ─────────────────────────────────────────────────────────────

def _calculate_health_score(agent_results: list[dict], cluster_emergencies: list[dict]) -> int:

    deductions = {"CRITICAL": 25, "HIGH": 12, "MEDIUM": 5, "LOW": 2, "NONE": 0}
    score = 100
    for result in agent_results:
        score -= deductions.get(result.get("severity", "NONE"), 0)
    # Each complaint cluster is a CRITICAL-level deduction
    score -= len(cluster_emergencies) * 25
    return max(0, score)


# ─── COMPLAINT CLUSTER DETECTOR ───────────────────────────────────────────────

def _detect_complaint_clusters(agent_results: list[dict]) -> tuple[list[dict], list[dict]]:
    non_complaints = []
    complaint_groups = defaultdict(list)   # district → [complaint signals]

    for r in agent_results:
        issue_type = r.get("issue_type", "")
        if "CITIZEN_COMPLAINT" in issue_type:
            complaint_groups[r["district"]].append(r)
        else:
            non_complaints.append(r)

    cluster_emergencies = []
    # Districts that are currently above the threshold (used to clear stale escalations)
    districts_above_threshold = set()

    for district, complaints in complaint_groups.items():
        count = len(complaints)

        if count >= COMPLAINT_CLUSTER_THRESHOLD:
            districts_above_threshold.add(district)

            # ── Only escalate once per district ───────────────────────────
            if district in _escalated_districts:
                continue

            # First time this district hits the threshold → escalate
            _escalated_districts.add(district)

            categories = [c.get("issue_type","").replace("CITIZEN_COMPLAINT_","").lower()
                          for c in complaints]
            top_cat = max(set(categories), key=categories.count) if categories else "general"

            locations = list({
                c.get("raw", {}).get("location", "unknown")
                for c in complaints
            })
            loc_str = ", ".join(locations[:3]) + ("..." if len(locations) > 3 else "")

            cluster_emergencies.append({
                "sensor_id"         : f"CLUSTER-{district.replace(' ','-').upper()}",
                "district"          : district,
                "issue_type"        : "COMPLAINT_CLUSTER_EMERGENCY",
                "severity"          : "CRITICAL",
                "severity_score"    : 4,
                "complaint_count"   : count,
                "top_category"      : top_cat,
                "locations"         : locations,
                "message"           : (
                    f"🚨 COMPLAINT CLUSTER: {count} citizens reported {top_cat} issues "
                    f"in {district} simultaneously. Locations: {loc_str}. "
                    f"Threshold of {COMPLAINT_CLUSTER_THRESHOLD} reached — auto-escalated to CRITICAL."
                ),
                "recommended_action": (
                    f"IMMEDIATE DISPATCH to {district}. Send {top_cat} response team + supervisor. "
                    f"Contact all {count} complainants. Issue public advisory for {district}."
                ),
                "timestamp"         : datetime.utcnow().isoformat() + "Z",
                "raw"               : {"complaints": complaints},
            })

        else:
            # Below threshold — keep individual complaints as-is
            non_complaints.extend(complaints)

    stale = _escalated_districts - districts_above_threshold
    _escalated_districts.difference_update(stale)

    return non_complaints, cluster_emergencies


# ─── CROSS-SIGNAL CORRELATIONS ────────────────────────────────────────────────

def _detect_correlations(agent_results: list[dict], cluster_emergencies: list[dict]) -> list[str]:
    """
    Looks for patterns across all signals including cluster emergencies.
    """
    insights = []
    districts = defaultdict(list)

    for r in agent_results:
        if r.get("severity") not in ("NONE", None):
            districts[r["district"]].append(r)

    # Water + power anomaly in same district
    for district, issues in districts.items():
        types     = [i.get("issue_type", "") for i in issues]
        has_water = any("PRESSURE" in t or "FLOW" in t or "MAIN" in t for t in types)
        has_power = any("BROWNOUT" in t or "SURGE" in t or "OUTAGE" in t or "LOAD" in t for t in types)
        if has_water and has_power:
            insights.append(
                f"⚠ CORRELATION: Both water and power anomalies in {district} — "
                f"possible infrastructure cascade. Priority elevated."
            )

    # Complaint cluster + sensor anomaly in same district (strongest signal)
    cluster_districts = {c["district"] for c in cluster_emergencies}
    for district in cluster_districts:
        sensor_issues = [r for r in agent_results
                         if r["district"] == district and r.get("severity") not in ("NONE", None)
                         and "COMPLAINT" not in r.get("issue_type","")]
        if sensor_issues:
            insights.append(
                f"🔴 HIGH CONFIDENCE: Complaint cluster in {district} is CONFIRMED by "
                f"sensor data ({sensor_issues[0]['issue_type']}). Physical event very likely."
            )

    # City-wide emergency: 3+ CRITICAL sensor events
    critical_count = sum(1 for r in agent_results if r.get("severity") == "CRITICAL")
    if critical_count >= 3:
        insights.append(
            f"🚨 CITY-WIDE ALERT: {critical_count} simultaneous CRITICAL events. "
            f"Recommend activating Emergency Operations Center."
        )

    # Multiple clusters across different districts
    if len(cluster_emergencies) >= 2:
        districts_hit = [c["district"] for c in cluster_emergencies]
        insights.append(
            f"📢 MULTI-DISTRICT COMPLAINT SURGE: Clusters detected in "
            f"{', '.join(districts_hit)}. Possible city-wide service failure."
        )

    return insights


# ─── MAIN DECISION FUNCTION ───────────────────────────────────────────────────

def make_decision(agent_results: list[dict]) -> dict:


    # ── Step 1 & 2: Detect complaint clusters ────────────────────────
    base_signals, cluster_emergencies = _detect_complaint_clusters(agent_results)

    # ── Step 3: Merge everything for unified analysis ─────────────────
    all_signals   = base_signals + cluster_emergencies
    active_alerts = [r for r in all_signals if r.get("severity") != "NONE"]

    # ── Step 4: Health Score ──────────────────────────────────────────
    health_score = _calculate_health_score(base_signals, cluster_emergencies)

    # ── Step 5: Count by severity ─────────────────────────────────────
    critical_count = sum(1 for r in active_alerts if r["severity"] == "CRITICAL")
    high_count     = sum(1 for r in active_alerts if r["severity"] == "HIGH")
    medium_count   = sum(1 for r in active_alerts if r["severity"] == "MEDIUM")

    # ── Step 6: System status ─────────────────────────────────────────
    if critical_count > 0:
        status, status_color = "EMERGENCY", "#e53935"
    elif high_count > 0:
        status, status_color = "WARNING",   "#f57c00"
    elif medium_count > 0:
        status, status_color = "CAUTION",   "#f9a825"
    else:
        status, status_color = "NORMAL",    "#00b86b"
    cluster_districts = {ce["district"] for ce in cluster_emergencies}

    dispatches = list({
        r["recommended_action"]
        for r in active_alerts
        if r["severity"] in ("CRITICAL", "HIGH")
        # Skip individual complaints whose district is already cluster-escalated
        and not (
            "CITIZEN_COMPLAINT" in r.get("issue_type", "")
            and r.get("district") in cluster_districts
        )
    })

    # ── Step 8: Correlations ──────────────────────────────────────────
    correlations = _detect_correlations(base_signals, cluster_emergencies)

    # ── Step 9: Natural-language reasoning ────────────────────────────
    parts = []

    if cluster_emergencies:
        for ce in cluster_emergencies:
            parts.append(
                f"🚨 COMPLAINT CLUSTER ESCALATION in {ce['district']}: "
                f"{ce['complaint_count']} citizens reported {ce['top_category']} issues — "
                f"threshold of {COMPLAINT_CLUSTER_THRESHOLD} reached. Auto-escalated to CRITICAL EMERGENCY."
            )

    if not active_alerts and not cluster_emergencies:
        parts.append(
            "All infrastructure systems normal. "
            "No sensor anomalies or complaint clusters detected."
        )
    elif active_alerts:
        parts.append(
            f"Agent detected {len(active_alerts)} issue(s): "
            f"{critical_count} CRITICAL, {high_count} HIGH, {medium_count} MEDIUM."
        )
        top = sorted(active_alerts, key=lambda x: x["severity_score"], reverse=True)[:3]
        for t in top:
            if "CLUSTER" not in t.get("issue_type",""):   # clusters already described above
                parts.append(f"• {t['message']}")

    if correlations:
        parts.extend(correlations)

    if dispatches:
        parts.append(f"Initiating {len(dispatches)} autonomous dispatch action(s).")

    # ── Step 10: Return ───────────────────────────────────────────────
    return {
        "health_score"       : health_score,
        "status"             : status,
        "status_color"       : status_color,
        "active_alerts"      : active_alerts,
        "critical_count"     : critical_count,
        "high_count"         : high_count,
        "medium_count"       : medium_count,
        "total_issues"       : len(active_alerts),
        "dispatches"         : dispatches,
        "correlations"       : correlations,
        "cluster_emergencies": cluster_emergencies,   # exposed for dashboard
        "complaint_threshold": COMPLAINT_CLUSTER_THRESHOLD,
        "reasoning"          : " ".join(parts),
        "timestamp"          : datetime.utcnow().isoformat() + "Z",
    }
