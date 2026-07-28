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
from routers import (
    academic,
    announcements,
    attendance,
    auth,
    calendar,
    examinations,
    expenses,
    fees,
    forgot,
    gallery,
    homework,
    messages,
    misc,
    notifications,
    otp,
    parents,
    payment_gateway,
    receipts,
    results,
    schedule,
    schools,
    staff,
    students,
    support,
    teachers,
    timetable,
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
    examinations.router,
    results.router,
    notifications.router,
    messages.router,
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
