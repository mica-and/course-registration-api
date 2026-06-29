from fastapi import FastAPI, UploadFile, File, HTTPException
from typing import Dict
from bs4 import BeautifulSoup
import re

app = FastAPI()

# ---------------------------
# In-memory storage
# ---------------------------
courses: Dict[str, dict] = {}
students: Dict[str, dict] = {}

# ---------------------------
# Helpers
# ---------------------------

def normalize_code(code: str) -> str:
    return re.sub(r"[\s-]", "", code.upper())


def normalize_term(term: str) -> str:
    return term.strip().upper()


def get_text(tag):
    return tag.get_text(" ", strip=True) if tag else None


def extract_course_codes(text: str):
    if not text:
        return []
    return re.findall(r"[A-Z]{4}\s*\d{4}", text.upper())


def parse_prerequisites(text: str):
    return [normalize_code(code) for code in extract_course_codes(text)]


def parse_schedule(row):
    schedule_block = row.select_one(".schedule")

    if not schedule_block:
        return {"days": [], "time": None, "room": None}

    return {
        "days": [d.get_text(strip=True) for d in schedule_block.select(".day")],
        "time": get_text(schedule_block.select_one(".time")),
        "room": get_text(schedule_block.select_one(".room"))
    }


# ---------------------------
# Term ordering (FIXED)
# ---------------------------
SEASON_ORDER = {"W": 0, "SP": 1, "S": 2, "F": 3}

def term_key(term: str):
    m = re.match(r"(\d{2})(W|SP|S|F)", term)
    if not m:
        return (float("inf"), float("inf"))
    return (int(m.group(1)), SEASON_ORDER[m.group(2)])


# ======================================================
# PHASE 1 - CATALOG
# ======================================================

@app.post("/api/v1/admin/catalog/import")
async def import_catalog(file: UploadFile = File(...)):
    html = (await file.read()).decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    courses.clear()

    for row in soup.select("tr.course"):

        course_code = get_text(row.select_one(".course_code"))
        title = get_text(row.select_one(".course_title"))

        if not course_code or not title:
            continue

        credits_raw = get_text(row.select_one(".credits"))
        match = re.search(r"\d+", credits_raw or "")
        credits = int(match.group()) if match else 0

        code = normalize_code(course_code)

        courses[code] = {
            "course_code": code,
            "title": title,
            "description": get_text(row.select_one(".description")),
            "credits": credits,
            "department": get_text(row.select_one(".department")),
            "instructor": get_text(row.select_one(".instructor")),
            "prerequisites": parse_prerequisites(
                get_text(row.select_one(".prerequisites"))
            ),
            "cross_listed": [
                normalize_code(c.get_text(strip=True))
                for c in row.select(".course-listed")
            ],
            "schedule": parse_schedule(row)
        }

    return {"status": "success", "imported": len(courses)}


@app.get("/api/v1/catalog/courses/{course_code}")
def get_course(course_code: str):
    code = normalize_code(course_code)
    course = courses.get(code)

    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    return course


# ======================================================
# STUDENTS
# ======================================================

def init_student(student_id: str):
    if student_id not in students:
        students[student_id] = {"history": [], "plan": []}


def get_student(student_id: str):
    return students.get(student_id)


# ======================================================
# TRANSCRIPT PARSER
# ======================================================

def parse_transcript(html: str):
    soup = BeautifulSoup(html, "html.parser")
    records = []

    for row in soup.find_all("tr"):
        cols = [c.get_text(strip=True) for c in row.find_all("td")]

        if len(cols) < 6:
            continue

        status = cols[0].strip()
        course_code = normalize_code(cols[1])
        term = normalize_term(cols[4])
        credits_raw = cols[5].strip()

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

    # deduplicate (latest best attempt wins)
    dedup = {}
    for r in records:
        key = (r["course_code"], r["term"])
        if key not in dedup or r["credits_earned"] > dedup[key]["credits_earned"]:
            dedup[key] = r

    return list(dedup.values())


# ======================================================
# HISTORY
# ======================================================

@app.post("/api/v1/students/{student_id}/history/import", status_code=201)
async def import_history(student_id: str, file: UploadFile = File(...)):
    html = (await file.read()).decode("utf-8-sig")

    parsed = parse_transcript(html)
    init_student(student_id)

    students[student_id]["history"] = parsed

    return {"status": "success", "past_courses_imported": len(parsed)}


@app.put("/api/v1/students/{student_id}/history")
def update_history(student_id: str, payload: dict):
    student = get_student(student_id)
    if not student:
        raise HTTPException(status_code=404)

    history = []
    for r in payload["history"]:
        history.append({
            "course_code": normalize_code(r["course_code"]),
            "term": normalize_term(r["term"]),
            "credits_earned": r["credits_earned"],
            "status": r["status"]
        })

    student["history"] = history
    return {"status": "success"}


@app.delete("/api/v1/students/{student_id}/history")
def delete_history(student_id: str):
    student = get_student(student_id)
    if not student:
        raise HTTPException(status_code=404)

    student["history"] = []
    return {"status": "success"}


# ======================================================
# PLAN
# ======================================================

@app.post("/api/v1/students/{student_id}/plan")
def create_plan(student_id: str, payload: dict):
    student = get_student(student_id)
    if not student:
        raise HTTPException(status_code=404)

    plan = []
    for course in payload["planned_courses"]:
        plan.append({
            "course_code": normalize_code(course["course_code"]),
            "term": normalize_term(course["term"])
        })

    student["plan"] = plan
    return {"status": "success", "planned_courses_saved": len(plan)}


@app.put("/api/v1/students/{student_id}/plan")
def replace_plan(student_id: str, payload: dict):
    student = get_student(student_id)
    if not student:
        raise HTTPException(status_code=404)

    plan = []
    for course in payload["planned_courses"]:
        plan.append({
            "course_code": normalize_code(course["course_code"]),
            "term": normalize_term(course["term"])
        })

    student["plan"] = plan
    return {"status": "success", "planned_courses_saved": len(plan)}


@app.delete("/api/v1/students/{student_id}/plan")
def delete_plan(student_id: str):
    student = get_student(student_id)
    if not student:
        raise HTTPException(status_code=404)

    student["plan"] = []
    return {"status": "success"}


# ======================================================
# PROFILE
# ======================================================

@app.get("/api/v1/students/{student_id}/profile")
def get_profile(student_id: str):
    student = get_student(student_id)

    if not student:
        raise HTTPException(status_code=404)

    return {
        "student_id": student_id,
        "history": student["history"],
        "plan": student["plan"]
    }


# ======================================================
# AUDIT REPORT (FIXED + CLEAN)
# ======================================================

@app.get("/api/v1/students/{student_id}/audit-report")
def audit_report(student_id: str, strict: bool = False):

    student = get_student(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    history = student["history"]
    plan = student["plan"]

    # ---------------------------
    # completed courses (latest wins)
    # ---------------------------
    completed = {}
    for h in history:
        if h["status"] != "Completed":
            continue

        code = h["course_code"]

        if code not in completed or term_key(h["term"]) > term_key(completed[code]["term"]):
            completed[code] = h

    timeline_validation = []
    cross_list_violations = []
    errors_by_term = {}

    # ---------------------------
    # PLAN VALIDATION
    # ---------------------------
    for course in plan:
        code = course["course_code"]
        term = course["term"]
        course_term_key = term_key(term)

        course_info = courses.get(code)
        if not course_info:
            continue

        # prerequisites
        for prereq in course_info.get("prerequisites", []):

            if prereq not in completed:
                errors_by_term.setdefault(term, []).append({
                    "course_code": code,
                    "type": "MISSING_PREREQUISITE",
                    "message": f"Missing prerequisite: {prereq}"
                })
            else:
                if term_key(completed[prereq]["term"]) >= course_term_key:
                    errors_by_term.setdefault(term, []).append({
                        "course_code": code,
                        "type": "INVALID_TIMING",
                        "message": f"{prereq} must be completed before {term}"
                    })

        # cross-list
        for cross in course_info.get("cross_listed", []):
            if cross in completed:
                cross_list_violations.append({
                    "course_code": code,
                    "type": "CROSS_LIST_CONFLICT",
                    "message": f"Cross-listed conflict with {cross}"
                })

    # timeline output
    for term in sorted(errors_by_term.keys(), key=term_key):
        timeline_validation.append({
            "term": term,
            "errors": errors_by_term[term]
        })

    # credit calculation (safe)
    total_earned = sum(c["credits_earned"] for c in completed.values())

    total_planned = 0
    seen = set()
    for c in plan:
        if c["course_code"] in seen:
            continue
        if c["course_code"] in courses:
            total_planned += courses[c["course_code"]]["credits"]
            seen.add(c["course_code"])

    total_remaining = max(0, 120 - total_earned - total_planned)

    # status
    has_issues = bool(timeline_validation or cross_list_violations)

    if not has_issues:
        status = "ok"
    elif strict:
        status = "failed"
    else:
        status = "warning"

    return {
        "student_id": student_id,
        "status": status,
        "timeline_validation": timeline_validation,
        "cross_list_violations": cross_list_violations,
        "credit_summary": {
            "total_earned": total_earned,
            "total_planned": total_planned,
            "total_remaining_for_graduation": total_remaining
        }
    }