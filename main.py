from fastapi import FastAPI, UploadFile, File, HTTPException
from typing import Dict, List
from bs4 import BeautifulSoup
import re

app = FastAPI()

# ---------------------------
# In-memory storage (per-student isolation)
# ---------------------------
students: Dict[str, dict] = {}

# ---------------------------
# Student helpers
# ---------------------------
def init_student(student_id: str):
    if student_id not in students:
        students[student_id] = {
            "history": [],
            "plan": []
        }


def get_student(student_id: str):
    return students.get(student_id)

# ---------------------------
# Transcript parser (canonical spec)
# ---------------------------
def parse_transcript(html: str):
    soup = BeautifulSoup(html, "html.parser")

    records = []

    for row in soup.find_all("tr"):
        cols = [c.get_text(strip=True) for c in row.find_all("td")]

        if len(cols) < 6:
            continue

        status = cols[0].strip()
        course_code = cols[1].strip()
        term = cols[4].strip()
        credits_raw = cols[5].strip()

        # valid row rule
        if status not in {"Completed", "In-Progress", "Attempted"}:
            continue

        if not term:
            continue

        match = re.search(r"\d+", credits_raw)
        credits = int(match.group()) if match else 0

        records.append({
            "course_code": course_code,
            "term": term,
            "credits_earned": credits,
            "status": status
        })

    # ---------------------------
    # Dedup rule: (course_code, term)
    # keep higher credits
    # ---------------------------
    dedup = {}
    for r in records:
        key = (r["course_code"], r["term"])

        if key not in dedup:
            dedup[key] = r
        else:
            if r["credits_earned"] > dedup[key]["credits_earned"]:
                dedup[key] = r

    return list(dedup.values())

# ======================================================
# HISTORY ENDPOINTS
# ======================================================

@app.post(
    "/api/v1/students/{student_id}/history/import",
    status_code=201
)
async def import_history(student_id: str, file: UploadFile = File(...)):
    html = (await file.read()).decode("utf-8-sig")

    parsed = parse_transcript(html)

    init_student(student_id)

    students[student_id]["history"] = parsed

    return {
        "status": "success",
        "past_courses_imported": len(parsed)
    }


@app.put("/api/v1/students/{student_id}/history")
def update_history(student_id: str, payload: dict):
    student = get_student(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    student["history"] = payload["history"]

    return {
        "status": "success",
        "message": "Academic history updated successfully"
    }


@app.delete("/api/v1/students/{student_id}/history")
def delete_history(student_id: str):
    student = get_student(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    student["history"] = []
    return {"status": "success"}

# ======================================================
# PLAN ENDPOINTS
# ======================================================

@app.post("/api/v1/students/{student_id}/plan")
def create_plan(student_id: str, payload: dict):
    student = get_student(student_id)
    if not student:
        raise HTTPException(status_code=404)

    student["plan"] = payload["planned_courses"]

    return {
        "status": "success",
        "planned_courses_saved": len(payload["planned_courses"])
    }


@app.put("/api/v1/students/{student_id}/plan")
def replace_plan(student_id: str, payload: dict):
    student = get_student(student_id)
    if not student:
        raise HTTPException(status_code=404)

    student["plan"] = payload["planned_courses"]

    return {
        "status": "success",
        "planned_courses_saved": len(payload["planned_courses"])
    }


@app.delete("/api/v1/students/{student_id}/plan")
def delete_plan(student_id: str):
    student = get_student(student_id)
    if not student:
        raise HTTPException(status_code=404)

    student["plan"] = []
    return {"status": "success"}

# ======================================================
# PROFILE ENDPOINT
# ======================================================

@app.get("/api/v1/students/{student_id}/profile")
def get_profile(student_id: str):
    student = get_student(student_id)

    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    return {
        "student_id": student_id,
        "history": student["history"],
        "plan": student["plan"]
    }