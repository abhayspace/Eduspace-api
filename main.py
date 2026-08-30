"""EduSpace School ERP — FastAPI application entrypoint.

Multi-tenant backend backed by Supabase (PostgreSQL). Every content row is
scoped by ``school_id``. Authentication is FastAPI-issued JWT (bcrypt + PyJWT);
Supabase is used only as storage via its service-role key.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from config import get_settings
from database import close_supabase, init_supabase
from middleware.profiling import ProfilingMiddleware
from routers import (
    academic,
    achievements,
    announcements,
    appointments,
    school_medical,
    attendance,
    auth,
    calendar,
    complaints_behaviour,
    dev_message,
    eddy,
    examinations,
    expenses,
    fees,
    feed,
    forms,
    forgot,
    gallery,
    help,
    homework,
    leave_requests,
    library,
    messages,
    misc,
    notes,
    notifications,
    otp,
    parents,
    quiz,
    payment_gateway,
    receipts,
    results,
    schedule,
    schools,
    staff,
    students,
    student_settings,
    study_material,
    support,
    syllabus,
    teachers,
    timetable,
    transport,
)

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("eduspace")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_supabase()
    settings = get_settings()
    if settings.database_url:
        try:
            from migrate import run_migrations

            await run_migrations(settings.database_url)
            logger.info("Database migrations applied.")
        except Exception as exc:
            logger.warning("Database migration skipped/failed: %s", exc)
    logger.info("EduSpace API started.")
    yield
    await close_supabase()
    logger.info("EduSpace API stopped.")


app = FastAPI(title="EduSpace API", version="2.0.0", lifespan=lifespan)

# All API routes live under /api to preserve the existing frontend contract.
ROUTERS = [
    misc.router,
    auth.router,
    forgot.router,
    otp.router,
    schools.router,
    support.router,
    dev_message.router,
    student_settings.router,
    students.router,
    teachers.router,
    staff.router,
    academic.router,
    parents.router,
    announcements.router,
    calendar.router,
    homework.router,
    timetable.router,
    schedule.router,
    attendance.router,
    fees.router,
    payment_gateway.router,
    receipts.router,
    expenses.router,
    gallery.router,
    leave_requests.router,
    appointments.router,
    school_medical.router,
    library.router,
    syllabus.router,
    examinations.router,
    results.router,
    achievements.router,
    feed.router,
    forms.router,
    help.router,
    notifications.router,
    messages.router,
    notes.router,
    quiz.router,
    eddy.router,
    eddy.public_router,
    complaints_behaviour.router,
    transport.router,
    study_material.router,
]
for r in ROUTERS:
    app.include_router(r, prefix="/api")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError):
    logger.info("Validation error: %s", exc.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(ProfilingMiddleware)
