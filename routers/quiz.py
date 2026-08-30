"""Quiz routes: teacher upsert/delete, student list/get/submit attempts."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status

from schemas.quiz import (
    QuizAttemptOut,
    QuizAttemptSubmitIn,
    QuizDetailOut,
    QuizListItemOut,
    QuizUpsertIn,
)
from services import quiz_service
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/quiz", tags=["quiz"])

staff_only = require_roles("teacher", "school_admin", "principal", "vice_principal")


@router.get("", response_model=List[QuizListItemOut])
async def list_quizzes(user: dict = Depends(current_user)) -> List[QuizListItemOut]:
    if user["role"] == "student":
        return await quiz_service.list_quizzes_student(user["school_id"], user["id"])
    return await quiz_service.list_quizzes_teacher(user["school_id"], user["id"])


@router.get("/{quiz_id}", response_model=QuizDetailOut)
async def get_quiz(quiz_id: str, user: dict = Depends(current_user)) -> QuizDetailOut:
    if user["role"] == "student":
        return await quiz_service.get_quiz_student(user["school_id"], user["id"], quiz_id)
    return await quiz_service.get_quiz_teacher(user["school_id"], user["id"], quiz_id)


@router.put("", response_model=QuizDetailOut)
async def upsert_quiz(
    body: QuizUpsertIn,
    user: dict = Depends(staff_only),
) -> QuizDetailOut:
    return await quiz_service.upsert_quiz(user["school_id"], user["id"], body)


@router.delete("/{quiz_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quiz(
    quiz_id: str,
    user: dict = Depends(staff_only),
) -> Response:
    await quiz_service.delete_quiz(user["school_id"], user["id"], quiz_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{quiz_id}/attempts", response_model=List[QuizAttemptOut])
async def list_attempts(
    quiz_id: str,
    user: dict = Depends(staff_only),
) -> List[QuizAttemptOut]:
    return await quiz_service.list_attempts(user["school_id"], quiz_id)


@router.post("/{quiz_id}/attempts", response_model=QuizAttemptOut, status_code=status.HTTP_201_CREATED)
async def submit_attempt(
    quiz_id: str,
    body: QuizAttemptSubmitIn,
    user: dict = Depends(current_user),
) -> QuizAttemptOut:
    if user["role"] != "student":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only students can submit attempts")
    return await quiz_service.submit_attempt(
        user["school_id"],
        user["id"],
        user.get("full_name") or "Student",
        quiz_id,
        body,
    )


@router.get("/{quiz_id}/my-attempt", response_model=QuizAttemptOut | None)
async def my_attempt(
    quiz_id: str,
    user: dict = Depends(current_user),
):
    return await quiz_service.get_student_attempt(user["school_id"], user["id"], quiz_id)
