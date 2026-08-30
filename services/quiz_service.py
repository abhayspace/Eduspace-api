"""Quiz service: teacher upsert/publish, student list/take/submit attempts."""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, status

from database import get_client
from schemas.quiz import (
    QuizAttemptOut,
    QuizAttemptSubmitIn,
    QuizDetailOut,
    QuizListItemOut,
    QuizUpsertIn,
)

QUIZZES = "quizzes"
ATTEMPTS = "quiz_attempts"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _student_class_section(school_id: str, user_id: str) -> tuple[Optional[str], Optional[str], str, str]:
    """Return (class_id, section_id, class_name, section_name) for a student."""
    client = get_client()
    res = (
        await client.table("students")
        .select("class_id,section_id")
        .eq("school_id", school_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None, None, "", ""
    row = res.data[0]
    class_id = row.get("class_id")
    section_id = row.get("section_id")
    class_name = ""
    section_name = ""
    if class_id:
        cls = (
            await client.table("classes")
            .select("name")
            .eq("school_id", school_id)
            .eq("id", class_id)
            .limit(1)
            .execute()
        )
        if cls.data:
            class_name = cls.data[0].get("name") or ""
    if section_id:
        sec = (
            await client.table("sections")
            .select("name")
            .eq("school_id", school_id)
            .eq("id", section_id)
            .limit(1)
            .execute()
        )
        if sec.data:
            section_name = sec.data[0].get("name") or ""
    return class_id, section_id, class_name, section_name


def _total_marks(questions: list) -> float:
    return sum(float(q.get("marks") or 0) for q in questions)


def _duration_seconds(questions: list) -> int:
    return sum(int(q.get("timerSeconds") or 5) for q in questions)


def _list_item(row: dict, has_attempted: bool = False, attempt_score: Optional[float] = None) -> QuizListItemOut:
    questions = row.get("questions") or []
    return QuizListItemOut(
        id=row["id"],
        title=row.get("title") or "",
        subject=row.get("subject") or "",
        className=row.get("class_name") or "",
        sectionName=row.get("section_name") or "",
        classId=row.get("class_id"),
        sectionId=row.get("section_id"),
        totalQuestions=len(questions),
        totalMarks=_total_marks(questions),
        durationSeconds=_duration_seconds(questions),
        startAt=row.get("start_at"),
        endAt=row.get("end_at"),
        status=row.get("status") or "draft",
        publishedAt=row.get("published_at"),
        participants=row.get("participants") if "participants" in row else 0,
        averageScore=row.get("average_score") if "average_score" in row else 0,
        updatedAt=row.get("updated_at"),
        createdAt=row.get("created_at"),
        hasAttempted=has_attempted,
        attemptScore=attempt_score,
    )


def _detail(row: dict, strip_answers: bool = False) -> QuizDetailOut:
    questions = row.get("questions") or []
    if strip_answers:
        questions = [
            {
                **{k: v for k, v in q.items() if k != "options"},
                "options": [
                    {k: v for k, v in opt.items() if k != "isCorrect"}
                    for opt in (q.get("options") or [])
                ],
            }
            for q in questions
        ]
    return QuizDetailOut(
        id=row["id"],
        title=row.get("title") or "",
        description=row.get("description") or "",
        subject=row.get("subject") or "",
        classId=row.get("class_id"),
        className=row.get("class_name") or "",
        sectionId=row.get("section_id"),
        sectionName=row.get("section_name") or "",
        chapter=row.get("chapter") or "",
        instructions=row.get("instructions") or "",
        coverImageUri=row.get("cover_image_uri"),
        difficulty=row.get("difficulty") or "medium",
        visibility=row.get("visibility") or "private",
        startAt=row.get("start_at"),
        endAt=row.get("end_at"),
        settings=row.get("settings") or {},
        questions=questions,
        status=row.get("status") or "draft",
        publishedAt=row.get("published_at"),
        createdAt=row.get("created_at"),
        updatedAt=row.get("updated_at"),
        participants=0,
        averageScore=0,
    )


async def upsert_quiz(school_id: str, user_id: str, body: QuizUpsertIn) -> QuizDetailOut:
    """Insert or update a quiz document (called by teachers on save/publish)."""
    client = get_client()
    now = _now_iso()
    payload = {
        "id": body.id,
        "school_id": school_id,
        "created_by_user_id": user_id,
        "title": body.title,
        "description": body.description,
        "subject": body.subject,
        "class_id": body.classId,
        "class_name": body.className,
        "section_id": body.sectionId,
        "section_name": body.sectionName,
        "chapter": body.chapter,
        "instructions": body.instructions,
        "cover_image_uri": body.coverImageUri,
        "difficulty": body.difficulty,
        "visibility": body.visibility,
        "start_at": body.startAt,
        "end_at": body.endAt,
        "settings": body.settings.model_dump() if hasattr(body.settings, "model_dump") else dict(body.settings),
        "questions": [q.model_dump() if hasattr(q, "model_dump") else dict(q) for q in body.questions],
        "status": body.status,
        "published_at": body.publishedAt,
        "updated_at": now,
    }
    # Check ownership if updating
    existing = (
        await client.table(QUIZZES)
        .select("id,created_by_user_id")
        .eq("school_id", school_id)
        .eq("id", body.id)
        .limit(1)
        .execute()
    )
    if existing.data:
        owner = existing.data[0].get("created_by_user_id")
        if owner and str(owner) != str(user_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only edit your own quizzes")
        res = await client.table(QUIZZES).update(payload).eq("id", body.id).execute()
    else:
        payload["created_at"] = body.createdAt or now
        res = await client.table(QUIZZES).insert(payload).execute()
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to save quiz")
    return _detail(res.data[0])


async def delete_quiz(school_id: str, user_id: str, quiz_id: str) -> None:
    client = get_client()
    res = (
        await client.table(QUIZZES)
        .select("created_by_user_id")
        .eq("school_id", school_id)
        .eq("id", quiz_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    owner = res.data[0].get("created_by_user_id")
    if owner and str(owner) != str(user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only delete your own quizzes")
    await client.table(QUIZZES).delete().eq("id", quiz_id).execute()


async def list_quizzes_teacher(school_id: str, user_id: str) -> List[QuizListItemOut]:
    """List quizzes created by this teacher."""
    client = get_client()
    res = (
        await client.table(QUIZZES)
        .select("*")
        .eq("school_id", school_id)
        .eq("created_by_user_id", user_id)
        .order("updated_at", desc=True)
        .limit(500)
        .execute()
    )
    return [_list_item(row) for row in (res.data or [])]


async def list_quizzes_student(school_id: str, user_id: str) -> List[QuizListItemOut]:
    """List published quizzes for this student's class/section."""
    class_id, section_id, _, _ = await _student_class_section(school_id, user_id)
    client = get_client()
    query = (
        client.table(QUIZZES)
        .select("*")
        .eq("school_id", school_id)
        .eq("status", "published")
    )
    # Filter by class/section if the student has one; otherwise show all published
    if class_id:
        query = query.eq("class_id", class_id)
    if section_id:
        query = query.eq("section_id", section_id)
    res = await query.order("updated_at", desc=True).limit(500).execute()
    rows = res.data or []

    # Fetch this student's attempts to mark attempted quizzes
    if rows:
        quiz_ids = [r["id"] for r in rows]
        att_res = (
            await client.table(ATTEMPTS)
            .select("quiz_id,score")
            .eq("school_id", school_id)
            .eq("student_user_id", user_id)
            .in_("quiz_id", quiz_ids)
            .execute()
        )
        attempted = {a["quiz_id"]: a for a in (att_res.data or [])}
    else:
        attempted = {}

    return [
        _list_item(
            row,
            has_attempted=row["id"] in attempted,
            attempt_score=float(attempted[row["id"]]["score"]) if row["id"] in attempted else None,
        )
        for row in rows
    ]


async def get_quiz_teacher(school_id: str, user_id: str, quiz_id: str) -> QuizDetailOut:
    client = get_client()
    res = (
        await client.table(QUIZZES)
        .select("*")
        .eq("school_id", school_id)
        .eq("id", quiz_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    return _detail(res.data[0])


async def get_quiz_student(school_id: str, user_id: str, quiz_id: str) -> QuizDetailOut:
    """Get a published quiz for a student — strips correct-answer flags."""
    client = get_client()
    res = (
        await client.table(QUIZZES)
        .select("*")
        .eq("school_id", school_id)
        .eq("id", quiz_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    row = res.data[0]
    if row.get("status") != "published":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    return _detail(row, strip_answers=True)


async def list_attempts(school_id: str, quiz_id: str) -> List[QuizAttemptOut]:
    client = get_client()
    res = (
        await client.table(ATTEMPTS)
        .select("*")
        .eq("school_id", school_id)
        .eq("quiz_id", quiz_id)
        .order("score", desc=True)
        .order("time_taken_seconds")
        .order("submitted_at")
        .execute()
    )
    rows = res.data or []
    out: List[QuizAttemptOut] = []
    for i, row in enumerate(rows):
        out.append(
            QuizAttemptOut(
                id=row["id"],
                quizId=row["quiz_id"],
                studentName=row.get("student_name") or "",
                className=row.get("class_name") or "",
                sectionName=row.get("section_name") or "",
                subject=row.get("subject") or "",
                score=float(row.get("score") or 0),
                maxScore=float(row.get("max_score") or 0),
                percentage=float(row.get("percentage") or 0),
                correctCount=row.get("correct_count") or 0,
                wrongCount=row.get("wrong_count") or 0,
                skippedCount=row.get("skipped_count") or 0,
                passed=bool(row.get("passed")),
                timeTakenSeconds=row.get("time_taken_seconds") or 0,
                startedAt=row.get("started_at"),
                submittedAt=row.get("submitted_at"),
                rank=i + 1,
            )
        )
    return out


def _score_attempt_server_side(questions: list, answers: list, settings: dict) -> dict:
    """Score an attempt using the quiz's stored questions (with correct answers)."""
    by_qid = {a.get("questionId"): a.get("value") for a in answers}
    score = 0.0
    max_score = 0.0
    correct = 0
    wrong = 0
    skipped = 0
    passing_marks = float(settings.get("passingMarks", 40))
    negative_marking = bool(settings.get("negativeMarking", False))
    negative_value = float(settings.get("negativeMarkValue", 0.25))

    for q in questions:
        marks = float(q.get("marks") or 0)
        max_score += marks
        qid = q.get("id")
        value = by_qid.get(qid)
        empty = value is None or (isinstance(value, str) and not value.strip()) or (
            isinstance(value, list) and len(value) == 0
        )
        if empty:
            skipped += 1
            continue

        is_correct = False
        qtype = q.get("type", "multiple_choice")
        if qtype in ("multiple_choice", "true_false", "image"):
            options = q.get("options") or []
            is_correct = any(
                o.get("isCorrect") and o.get("id") == value for o in options
            )
        elif qtype == "one_word":
            text = str(value).strip().lower()
            accepted = [str(a).strip().lower() for a in (q.get("acceptedAnswers") or []) if a]
            is_correct = text in accepted if accepted else False

        if is_correct:
            correct += 1
            score += marks
        else:
            wrong += 1
            if negative_marking:
                score -= negative_value * marks

    score = max(0.0, round(score * 100) / 100)
    percentage = round((score / max_score) * 1000) / 10 if max_score > 0 else 0
    return {
        "score": score,
        "max_score": max_score,
        "percentage": percentage,
        "correct_count": correct,
        "wrong_count": wrong,
        "skipped_count": skipped,
        "passed": score >= passing_marks,
    }


async def submit_attempt(
    school_id: str,
    user_id: str,
    user_name: str,
    quiz_id: str,
    body: QuizAttemptSubmitIn,
) -> QuizAttemptOut:
    client = get_client()
    # Verify quiz exists and is published
    quiz_res = (
        await client.table(QUIZZES)
        .select("id,class_name,section_name,subject,settings,questions")
        .eq("school_id", school_id)
        .eq("id", quiz_id)
        .limit(1)
        .execute()
    )
    if not quiz_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
    quiz_row = quiz_res.data[0]

    # Check for existing attempt (unique constraint)
    existing = (
        await client.table(ATTEMPTS)
        .select("id")
        .eq("school_id", school_id)
        .eq("quiz_id", quiz_id)
        .eq("student_user_id", user_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        raise HTTPException(status.HTTP_409_CONFLICT, "You have already attempted this quiz")

    class_name = quiz_row.get("class_name") or ""
    section_name = quiz_row.get("section_name") or ""
    subject = quiz_row.get("subject") or ""
    questions = quiz_row.get("questions") or []
    settings = quiz_row.get("settings") or {}

    # Score server-side using stored questions (with correct answers)
    scored = _score_attempt_server_side(questions, body.answers, settings)

    payload = {
        "school_id": school_id,
        "quiz_id": quiz_id,
        "student_user_id": user_id,
        "student_name": user_name,
        "class_name": class_name,
        "section_name": section_name,
        "subject": subject,
        "answers": [a.model_dump() if hasattr(a, "model_dump") else dict(a) for a in body.answers],
        "score": scored["score"],
        "max_score": scored["max_score"],
        "percentage": scored["percentage"],
        "correct_count": scored["correct_count"],
        "wrong_count": scored["wrong_count"],
        "skipped_count": scored["skipped_count"],
        "passed": scored["passed"],
        "time_taken_seconds": body.timeTakenSeconds,
        "started_at": body.startedAt,
    }
    res = await client.table(ATTEMPTS).insert(payload).execute()
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to submit attempt")
    row = res.data[0]
    return QuizAttemptOut(
        id=row["id"],
        quizId=row["quiz_id"],
        studentName=row.get("student_name") or "",
        className=row.get("class_name") or "",
        sectionName=row.get("section_name") or "",
        subject=row.get("subject") or "",
        score=float(row.get("score") or 0),
        maxScore=float(row.get("max_score") or 0),
        percentage=float(row.get("percentage") or 0),
        correctCount=row.get("correct_count") or 0,
        wrongCount=row.get("wrong_count") or 0,
        skippedCount=row.get("skipped_count") or 0,
        passed=bool(row.get("passed")),
        timeTakenSeconds=row.get("time_taken_seconds") or 0,
        startedAt=row.get("started_at"),
        submittedAt=row.get("submitted_at"),
        rank=None,
    )


async def get_student_attempt(school_id: str, user_id: str, quiz_id: str) -> Optional[QuizAttemptOut]:
    """Check if a student already attempted a quiz."""
    client = get_client()
    res = (
        await client.table(ATTEMPTS)
        .select("*")
        .eq("school_id", school_id)
        .eq("quiz_id", quiz_id)
        .eq("student_user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    row = res.data[0]
    return QuizAttemptOut(
        id=row["id"],
        quizId=row["quiz_id"],
        studentName=row.get("student_name") or "",
        className=row.get("class_name") or "",
        sectionName=row.get("section_name") or "",
        subject=row.get("subject") or "",
        score=float(row.get("score") or 0),
        maxScore=float(row.get("max_score") or 0),
        percentage=float(row.get("percentage") or 0),
        correctCount=row.get("correct_count") or 0,
        wrongCount=row.get("wrong_count") or 0,
        skippedCount=row.get("skipped_count") or 0,
        passed=bool(row.get("passed")),
        timeTakenSeconds=row.get("time_taken_seconds") or 0,
        startedAt=row.get("started_at"),
        submittedAt=row.get("submitted_at"),
        rank=None,
    )
