from fastapi import FastAPI, UploadFile, File, HTTPException
from bs4 import BeautifulSoup
import re

app = FastAPI()

courses = {}

def get_text(tag):
    return tag.get_text(" ", strip=True) if tag else None

def normalize_course_code(code: str):
    if not code:
        return None
    return re.sub(r"\s+", "", code.upper())

def extract_course_codes(text: str):
    if not text:
        return []

    matches = re.findall(r"[A-Z]{4}\s*\d{4}", text.upper())
    return [normalize_course_code(m) for m in matches]

def parse_prerequisites(text: str):
    return extract_course_codes(text)

def parse_schedule(row):
    schedule_block = row.select_one(".schedule")

    if not schedule_block:
        return {
            "days": [],
            "time": None,
            "room": None
        }

    return {
        "days": [
            d.get_text(strip=True)
            for d in schedule_block.select(".day")
        ],
        "time": get_text(schedule_block.select_one(".time")),
        "room": get_text(schedule_block.select_one(".room"))
    }

@app.post("/api/v1/admin/catalog/import")
def import_catalog(file: UploadFile = File(...)):
    html = file.file.read()
    soup = BeautifulSoup(
        html.decode("utf-8", errors="ignore"),
        "html.parser"
    )

    imported = 0

    for row in soup.select("tr.course"):

        raw_course_code = get_text(
            row.select_one(".course_code")
        )

        title = get_text(
            row.select_one(".course_title")
        )

        credits_raw = get_text(
            row.select_one(".credits")
        )

        credits_match = re.search(
            r"\d+",
            credits_raw or ""
        )

        credits = (
            int(credits_match.group())
            if credits_match
            else None
        )

        if not raw_course_code or not title:
            continue

        course_code = normalize_course_code(
            raw_course_code
        )

        description = get_text(
            row.select_one(".description")
        )

        department = get_text(
            row.select_one(".department")
        )

        instructor = get_text(
            row.select_one(".instructor")
        )

        prereq_text = get_text(
            row.select_one(".prerequisites")
        )

        prerequisites = parse_prerequisites(
            prereq_text
        )

        cross_listed = [
            normalize_course_code(
                c.get_text(strip=True)
            )
            for c in row.select(".course-listed")
        ]

        schedule = parse_schedule(row)

        courses[course_code] = {
            "course_code": course_code,
            "title": title,
            "description": description,
            "credits": credits,
            "department": department,
            "instructor": instructor,
            "prerequisites": prerequisites,
            "cross_listed": cross_listed,
            "schedule": schedule
        }

        imported += 1

    return {
        "status": "success",
        "imported": imported
    }

@app.get("/api/v1/catalog/courses/{course_code}")
def get_course(course_code: str):
    normalized_code = normalize_course_code(
        course_code
    )

    course = courses.get(normalized_code)

    if not course:
        raise HTTPException(
            status_code=404,
            detail="Course not found"
        )

    return course

@app.get("/")
def root():
    return {"status": "running"}

@app.get("/debug")
def debug():
    return {
        "stored_course_codes": list(courses.keys())
    }