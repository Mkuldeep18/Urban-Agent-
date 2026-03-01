from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone
import traceback, uuid

from simulator import get_water_data, get_power_data
from agents    import analyze_water, analyze_power
from reasoning import make_decision


# ── App setup ──────────────────────────────────────────────────────────────────
app = FastAPI(
    title       = "UIAMA — Urban Infrastructure Autonomous Monitoring Agent",
    description = "City infrastructure monitoring with citizen complaint integration.",
    version     = "2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# ── In-memory complaint store (replace with a DB in production) ────────────────
complaint_store: list[dict] = []


# ── Pydantic model for incoming complaints ─────────────────────────────────────
class ComplaintSubmission(BaseModel):
    name        : str              = Field(...,  min_length=2,  max_length=80,  example="Ravi Kumar")
    phone       : Optional[str]    = Field(None, max_length=20, example="+91-9876543210")
    district    : str              = Field(...,  example="District-4")
    category    : str              = Field(...,  example="water")   # water | power | garbage | road | other
    severity    : str              = Field(...,  example="high")    # low | medium | high | critical
    description : str              = Field(...,  min_length=10, max_length=500,
                                        example="There is a large water leak on Elm Street near the bus stop.")
    location    : str              = Field(...,  min_length=3,  max_length=200,
                                        example="Elm Street, near Bus Stop 12")


# ── Allowed values ─────────────────────────────────────────────────────────────
VALID_DISTRICTS  = {f"District-{i}" for i in range(1, 7)}
VALID_CATEGORIES = {"water", "power", "garbage", "road", "other"}
VALID_SEVERITIES = {"low", "medium", "high", "critical"}


# ── Health check ───────────────────────────────────────────────────────────────
@app.get("/", tags=["System"])
def root():
    return {
        "service" : "UIAMA Backend v2",
        "status"  : "online",
        "endpoints": {
            "city_status"       : "GET  /city-status",
            "submit_complaint"  : "POST /complaints",
            "list_complaints"   : "GET  /complaints",
            "update_complaint"  : "PUT  /complaints/{id}",
            "docs"              : "/docs",
        }
    }


# ── POST /complaints — citizen submits a new complaint ────────────────────────
@app.post("/complaints", summary="Submit a Citizen Complaint", tags=["Complaints"])
def submit_complaint(body: ComplaintSubmission):
    """
    Called by the Citizen Portal when a resident submits a complaint.
    Validates the input, assigns an ID and timestamp, sets status to 'open',
    and stores it in the complaint list.
    """
    # Validate controlled fields
    if body.district not in VALID_DISTRICTS:
        raise HTTPException(400, f"Invalid district. Choose from: {sorted(VALID_DISTRICTS)}")
    if body.category not in VALID_CATEGORIES:
        raise HTTPException(400, f"Invalid category. Choose from: {VALID_CATEGORIES}")
    if body.severity not in VALID_SEVERITIES:
        raise HTTPException(400, f"Invalid severity. Choose from: {VALID_SEVERITIES}")

    complaint = {
        "id"          : str(uuid.uuid4())[:8].upper(),
        "name"        : body.name,
        "phone"       : body.phone or "—",
        "district"    : body.district,
        "category"    : body.category,
        "severity"    : body.severity,
        "description" : body.description,
        "location"    : body.location,
        "status"      : "open",          # open | in-progress | resolved
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "resolved_at" : None,
    }

    complaint_store.append(complaint)

    return JSONResponse(status_code=201, content={
        "message"      : "Complaint submitted successfully. Our team will review it shortly.",
        "complaint_id" : complaint["id"],
        "complaint"    : complaint,
    })


# ── GET /complaints — dashboard fetches all complaints ────────────────────────
@app.get("/complaints", summary="List All Complaints", tags=["Complaints"])
def list_complaints(district: Optional[str] = None, status: Optional[str] = None, category: Optional[str] = None):
    """
    Returns all complaints, optionally filtered by district, status, or category.
    The dashboard calls this to populate the complaints panel.
    """
    results = complaint_store.copy()

    if district : results = [c for c in results if c["district"]  == district]
    if status   : results = [c for c in results if c["status"]    == status]
    if category : results = [c for c in results if c["category"]  == category]

    # Sort newest first
    results.sort(key=lambda c: c["submitted_at"], reverse=True)

    return JSONResponse(content={
        "total"      : len(results),
        "open"       : sum(1 for c in results if c["status"] == "open"),
        "in_progress": sum(1 for c in results if c["status"] == "in-progress"),
        "resolved"   : sum(1 for c in results if c["status"] == "resolved"),
        "complaints" : results,
    })


# ── PUT /complaints/{id} — update complaint status ────────────────────────────
@app.put("/complaints/{complaint_id}", summary="Update Complaint Status", tags=["Complaints"])
def update_complaint(complaint_id: str, status: str):
    """
    Allows the dashboard operator to mark a complaint as in-progress or resolved.
    """
    if status not in {"open", "in-progress", "resolved"}:
        raise HTTPException(400, "status must be: open | in-progress | resolved")

    for c in complaint_store:
        if c["id"] == complaint_id.upper():
            c["status"] = status
            if status == "resolved":
                c["resolved_at"] = datetime.now(timezone.utc).isoformat()
            return JSONResponse(content={"message": f"Complaint {complaint_id} updated.", "complaint": c})

    raise HTTPException(404, f"Complaint ID '{complaint_id}' not found.")


# ── GET /city-status — full pipeline including real complaints ─────────────────
@app.get("/city-status", summary="Get Full City Infrastructure Status", tags=["City Monitor"])
def city_status():
    """
    Runs the full pipeline:
      1. Simulate water + power sensor readings
      2. Analyze with domain agents
      3. Pull open citizen complaints and treat them as additional signals
      4. Pass everything to make_decision() for unified reasoning
      5. Return complete JSON to dashboard
    """
    try:
        # Sensor pipeline
        water_data   = get_water_data()
        power_data   = get_power_data()
        water_result = analyze_water(water_data)
        power_result = analyze_power(power_data)

        # Complaints as signals — only open/in-progress ones
        open_complaints = [c for c in complaint_store if c["status"] != "resolved"]

        # Convert complaints into agent-style result dicts so make_decision() can reason over them
        complaint_results = []
        sev_map = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "critical": "CRITICAL"}
        for c in open_complaints:
            complaint_results.append({
                "sensor_id"         : f"CMP-{c['id']}",
                "district"          : c["district"],
                "issue_type"        : f"CITIZEN_COMPLAINT_{c['category'].upper()}",
                "severity"          : sev_map.get(c["severity"], "MEDIUM"),
                "severity_score"    : {"LOW":1,"MEDIUM":2,"HIGH":3,"CRITICAL":4}.get(sev_map.get(c["severity"],"MEDIUM"), 2),
                "message"           : f"Citizen complaint ({c['category']}): {c['description'][:100]}",
                "recommended_action": f"Investigate complaint #{c['id']} at {c['location']} in {c['district']}.",
                "timestamp"         : c["submitted_at"],
                "raw"               : c,
            })

        # Unified reasoning over sensors + complaints
        all_signals = [water_result, power_result] + complaint_results
        decision    = make_decision(all_signals)

        # Attach extras
        decision["raw_readings"]    = {"water": water_data, "power": power_data}
        decision["complaints"]      = {
            "total"      : len(complaint_store),
            "open"       : len([c for c in complaint_store if c["status"] == "open"]),
            "in_progress": len([c for c in complaint_store if c["status"] == "in-progress"]),
            "resolved"   : len([c for c in complaint_store if c["status"] == "resolved"]),
            "recent"     : sorted(complaint_store, key=lambda c: c["submitted_at"], reverse=True)[:5],
        }

        return JSONResponse(content=decision, status_code=200)

    except Exception as e:
        raise HTTPException(500, detail={"error": str(e), "trace": traceback.format_exc()})
