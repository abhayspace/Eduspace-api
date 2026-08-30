"""Quiz schemas — teacher-created quizzes and student attempts."""
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class QuizOptionIn(BaseModel):
    id: str
    label: str = ""
    isCorrect: bool = False
    imageUri: Optional[str] = None


class QuizQuestionIn(BaseModel):
    id: str
    type: str = "multiple_choice"
    title: str = ""
    marks: float = 1
    required: bool = True
    options: List[QuizOptionIn] = Field(default_factory=list)
    explanation: str = ""
    imageUri: Optional[str] = None
    timerSeconds: int = 5
    acceptedAnswers: List[str] = Field(default_factory=list)


class QuizSettingsIn(BaseModel):
    passingMarks: float = 40
    negativeMarking: bool = False
    negativeMarkValue: float = 0.25
    shuffleQuestions: bool = False
    shuffleOptions: bool = False
    showCorrectAnswers: bool = True
    showScoreAfterSubmission: bool = True
    allowReview: bool = True
    allowMultipleAttempts: bool = False
    maxAttempts: int = 1
    enableLeaderboard: bool = True
    enableAutoSubmit: bool = True
    requireLogin: bool = True


class QuizUpsertIn(BaseModel):
    """Full quiz document uploaded by the teacher on publish/save."""
    id: str
    title: str = ""
    description: str = ""
    subject: str = ""
    classId: Optional[str] = None
    className: str = ""
    sectionId: Optional[str] = None
    sectionName: str = ""
    chapter: str = ""
    instructions: str = ""
    coverImageUri: Optional[str] = None
    difficulty: str = "medium"
    visibility: str = "private"
    startAt: Optional[str] = None
    endAt: Optional[str] = None
    settings: QuizSettingsIn = Field(default_factory=QuizSettingsIn)
    questions: List[QuizQuestionIn] = Field(default_factory=list)
    status: str = "draft"
    publishedAt: Optional[str] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


class QuizListItemOut(BaseModel):
    id: str
    title: str = ""
    subject: str = ""
    className: str = ""
    sectionName: str = ""
    classId: Optional[str] = None
    sectionId: Optional[str] = None
    totalQuestions: int = 0
    totalMarks: float = 0
    durationSeconds: int = 0
    startAt: Optional[str] = None
    endAt: Optional[str] = None
    status: str = "draft"
    publishedAt: Optional[datetime] = None
    participants: int = 0
    averageScore: float = 0
    updatedAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None
    hasAttempted: bool = False
    attemptScore: Optional[float] = None


class QuizDetailOut(BaseModel):
    """Full quiz — for students, correct-answer flags are stripped."""
    id: str
    title: str = ""
    description: str = ""
    subject: str = ""
    classId: Optional[str] = None
    className: str = ""
    sectionId: Optional[str] = None
    sectionName: str = ""
    chapter: str = ""
    instructions: str = ""
    coverImageUri: Optional[str] = None
    difficulty: str = "medium"
    visibility: str = "private"
    startAt: Optional[str] = None
    endAt: Optional[str] = None
    settings: dict = Field(default_factory=dict)
    questions: List[dict] = Field(default_factory=list)
    status: str = "draft"
    publishedAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
    participants: int = 0
    averageScore: float = 0


class QuizAttemptAnswerIn(BaseModel):
    questionId: str
    value: Any = None
    lockedAt: Optional[str] = None
    timeSpentSeconds: int = 0


class QuizAttemptSubmitIn(BaseModel):
    answers: List[QuizAttemptAnswerIn] = Field(default_factory=list)
    score: float = 0
    maxScore: float = 0
    percentage: float = 0
    correctCount: int = 0
    wrongCount: int = 0
    skippedCount: int = 0
    passed: bool = False
    timeTakenSeconds: int = 0
    startedAt: Optional[str] = None


class QuizAttemptOut(BaseModel):
    id: str
    quizId: str
    studentName: str = ""
    className: str = ""
    sectionName: str = ""
    subject: str = ""
    score: float = 0
    maxScore: float = 0
    percentage: float = 0
    correctCount: int = 0
    wrongCount: int = 0
    skippedCount: int = 0
    passed: bool = False
    timeTakenSeconds: int = 0
    startedAt: Optional[datetime] = None
    submittedAt: Optional[datetime] = None
    rank: Optional[int] = None
