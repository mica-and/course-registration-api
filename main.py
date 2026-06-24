from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from bs4 import BeautifulSoup
from typing import List, Dict

app = FastAPI()

# ---------------------------
# In-memory storage (IMPORTANT)
# ---------------------------
students = {}

# ---------------------------
# Models
# ---------------------------
class Course(BaseModel):
    course_code: str
    term: str
    credits_earned: int = 0
    status: str

class PlanCourse(BaseModel):
    course_code: str
    term: str

class Plan(BaseModel):
    planned_courses: List[PlanCourse]

# ---------------------------
# Helper: ensure student exists
# ---------------------------
def get_student(student_id: str):
    if student_id not in students:
        raise HTTPException(status_code=404, detail="Student not found")
    return students[student_id]

# ---------------------------
# HTML PARSER (CORE REQUIREMENT)
# ---------------------------
def parse_transcript(html: str):
    soup = BeautifulSoup(html, "html.parser")

    rows = soup.find_all("tr")

    history = []

    for row in rows:
        cols = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]

        if len(cols) < 5:
            continue

        status, course, _, _, term, *rest = cols

        if status not in ["Completed", "In-Progress", "Attempted"]:
            continue

        if not term:
            continue

        credits = 0
        if rest:
            try:
                credits = int(rest[-1]) if rest[-1].isdigit() else 0
            except:
                credits = 0

        history.append({
            "course_code": course,
            "term": term,
            "credits_earned": credits,
            "status": status
        })

    # Deduplicate (course_code, term)
    dedup = {}
    for h in history:
        key = (h["course_code"], h["term"])
        if key not in dedup:
            dedup[key] = h
        else:
            # keep higher credits
            if h["credits_earned"] > dedup[key]["credits_earned"]:
                dedup[key] = h

    return list(dedup.values())

# ---------------------------
# HISTORY ENDPOINTS
# ---------------------------

@app.post("/api/v1/students/{student_id}/history/import")
async def import_history(student_id: str, file: UploadFile = File(...)):
    html = await file.read()
    parsed = parse_transcript(html.decode("utf-8"))

    students.setdefault(student_id, {})
    students[student_id]["history"] = parsed
    students[student_id].setdefault("plan", [])

    return {
        "status": "success",
        "past_courses_imported": len(parsed)
    }


@app.put("/api/v1/students/{student_id}/history")
def update_history(student_id: str, payload: Dict):
    student = get_student(student_id)
    student["history"] = payload["history"]

    return {"status": "success", "message": "Academic history updated successfully"}


@app.delete("/api/v1/students/{student_id}/history")
def delete_history(student_id: str):
    student = get_student(student_id)
    student["history"] = []
    return {"status": "success"}


# ---------------------------
# PLAN ENDPOINTS
# ---------------------------

@app.post("/api/v1/students/{student_id}/plan")
def create_plan(student_id: str, payload: Plan):
    student = get_student(student_id)
    student["plan"] = [p.dict() for p in payload.planned_courses]

    return {
        "status": "success",
        "planned_courses_saved": len(payload.planned_courses)
    }


@app.put("/api/v1/students/{student_id}/plan")
def replace_plan(student_id: str, payload: Plan):
    return create_plan(student_id, payload)


@app.delete("/api/v1/students/{student_id}/plan")
def delete_plan(student_id: str):
    student = get_student(student_id)
    student["plan"] = []
    return {"status": "success"}


# ---------------------------
# PROFILE ENDPOINT
# ---------------------------

@app.get("/api/v1/students/{student_id}/profile")
def get_profile(student_id: str):
    student = get_student(student_id)

    return {
        "student_id": student_id,
        "history": student.get("history", []),
        "plan": student.get("plan", [])
    }