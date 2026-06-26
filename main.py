from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from bs4 import BeautifulSoup
from typing import List, Dict
import re

app = FastAPI()

# In-memory storage 
students = {}

# Models
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

# Helper: ensure student exists
def get_student(student_id: str):
    if student_id not in students:
        raise HTTPException(status_code=404, detail="Student not found")
    return students[student_id]

# HTML PARSER
def parse_transcript(html: str):
    soup = BeautifulSoup(html, "html.parser")

    history = []

    for row in soup.find_all("tr"):
        cols = [cell.get_text(strip=True) for cell in row.find_all(["td", "th"])]

        # Skip header rows
        if cols and cols[0] == "Status":
            continue

        if len(cols) < 6:
            continue

        status = cols[0].strip()
        course = cols[1].strip()
        term = cols[4].strip()

        if status not in {"Completed", "In-Progress", "Attempted"}:
            continue

        if not term:
            continue

        match = re.search(r"\d+", cols[5])
        credits = int(match.group()) if match else 0

        history.append({
            "course_code": course,
            "term": term,
            "credits_earned": credits,
            "status": status,
        })

    # Remove duplicates, keeping the last occurrence
    dedup = {}
    for item in history:
        dedup[(item["course_code"], item["term"])] = item

    return list(dedup.values())

# HISTORY ENDPOINTS
@app.post("/api/v1/students/{student_id}/history/import")
async def import_history(student_id: str, file: UploadFile = File(...)):
    html = (await file.read()).decode("utf-8-sig")

    parsed = parse_transcript(html)

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

# PLAN ENDPOINTS
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


# PROFILE ENDPOINT
@app.get("/api/v1/students/{student_id}/profile")
def get_profile(student_id: str):
    student = get_student(student_id)

    return {
        "student_id": student_id,
        "history": student.get("history", []),
        "plan": student.get("plan", [])
    }