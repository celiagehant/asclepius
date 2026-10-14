"""Accounts: sign up, log in, log out, and the `current_user` dependency.

Passwords are hashed with scrypt (Python standard library) and a random salt per user;
the plain password is never stored or logged. Sessions are random tokens kept in an
HttpOnly, SameSite=Lax cookie; only the token's SHA-256 hash is stored in the database.
Repeated failed logins for the same email are slowed down.
"""

from __future__ import annotations

import base64
import hashlib
import os
import hmac
import re
import secrets
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from . import db

COOKIE = "cc_session"
SESSION_DAYS = 14
SCRYPT = {"n": 2**14, "r": 8, "p": 1}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_FAILED = 8            # per email, per window
FAILED_WINDOW_S = 15 * 60
_failed: dict[str, list[float]] = defaultdict(list)
MAX_SIGNUPS_PER_IP = int(os.environ.get("CC_SIGNUPS_PER_IP_PER_HOUR", "5"))  # a public demo should not hand out unlimited accounts
_signups: dict[str, list[float]] = defaultdict(list)

router = APIRouter(prefix="/api/auth")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **SCRYPT)
    return "scrypt${n}${r}${p}${salt}${hash}".format(
        **SCRYPT, salt=base64.b64encode(salt).decode(), hash=base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, expected = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), dklen=32, n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(digest, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Credentials(BaseModel):
    email: str
    password: str
    adult_confirmed: bool = False  # sign-up only: "I am 18 or older"


def _start_session(response: Response, user_id: int, secure: bool) -> None:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    db.create_session(_token_hash(token), user_id, expires.isoformat(timespec="seconds"))
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=secure, path="/")


def current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE)
    row = db.user_for_session(_token_hash(token)) if token else None
    if not row:
        raise HTTPException(401, "Please log in.")
    return {"id": row["id"], "email": row["email"]}


@router.post("/signup")
def signup(body: Credentials, request: Request, response: Response) -> dict:
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Please enter a valid email address.")
    if len(body.password) < 8:
        raise HTTPException(400, "Use a password of at least 8 characters.")
    if not body.adult_confirmed:
        raise HTTPException(400, "Accounts are for adults (18+). A parent or guardian can add a child's profile from their account.")
    ip = request.client.host if request.client else "unknown"
    _signups[ip] = [t for t in _signups[ip] if time.time() - t < 3600]
    if len(_signups[ip]) >= MAX_SIGNUPS_PER_IP:
        raise HTTPException(429, "Too many new accounts from this network. Please try again later.")
    _signups[ip].append(time.time())
    try:
        user_id = db.create_user(email, hash_password(body.password))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "An account with this email already exists. Please log in.")
    _start_session(response, user_id, request.url.scheme == "https")
    return {"id": user_id, "email": email}


@router.post("/login")
def login(body: Credentials, request: Request, response: Response) -> dict:
    email = body.email.strip().lower()
    recent = [t for t in _failed[email] if time.time() - t < FAILED_WINDOW_S]
    _failed[email] = recent
    if len(recent) >= MAX_FAILED:
        raise HTTPException(429, "Too many failed attempts. Please wait 15 minutes and try again.")
    user = db.user_by_email(email)
    if not user or not verify_password(body.password, user["password_hash"]):
        _failed[email].append(time.time())
        raise HTTPException(401, "Email or password is incorrect.")
    _failed.pop(email, None)
    _start_session(response, user["id"], request.url.scheme == "https")
    return {"id": user["id"], "email": email}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(COOKIE)
    if token:
        db.delete_session(_token_hash(token))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(current_user)) -> dict:
    return user
