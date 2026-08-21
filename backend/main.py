"""Study Desk — FastAPI backend (Supabase / Postgres)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from psycopg import errors as pg_errors
from pydantic import BaseModel, EmailStr, Field

from . import db


SECRET_KEY = os.getenv("STUDY_DESK_SECRET", "dev-secret-change-me")
ALGORITHM = "HS256"
TOKEN_TTL_MINUTES = 60 * 24

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ------------------------ schemas ------------------------

class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class UserOut(BaseModel):
    id: str
    email: EmailStr
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class DeckIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    is_public: bool = False


class DeckPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    is_public: Optional[bool] = None


class DeckOut(BaseModel):
    id: str
    owner_id: str
    owner_email: EmailStr
    title: str
    description: str
    is_public: bool
    shared_with: list[str]
    card_count: int
    created_at: datetime


class CardIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(default="", max_length=5000)
    code: str = Field(default="", max_length=10000)
    equation: str = Field(default="", max_length=2000)


class CardPatch(BaseModel):
    question: Optional[str] = Field(default=None, min_length=1, max_length=1000)
    answer: Optional[str] = Field(default=None, max_length=5000)
    code: Optional[str] = Field(default=None, max_length=10000)
    equation: Optional[str] = Field(default=None, max_length=2000)


class CardOut(BaseModel):
    id: str
    deck_id: str
    question: str
    answer: str
    code: str
    equation: str
    created_at: datetime


class ShareIn(BaseModel):
    email: EmailStr


class SearchHit(BaseModel):
    kind: str
    deck_id: str
    deck_title: str
    card_id: Optional[str] = None
    snippet: str


# ------------------------ SQL fragments ------------------------

# Row-level visibility, mirroring the old deck_visible_to():
#   owner OR shared-with OR public.
# Applied as a WHERE clause with parameter %(uid)s bound to the current user id.
DECK_VISIBLE_PREDICATE = """
    (
        d.owner_id = %(uid)s
        OR d.is_public
        OR EXISTS (
            SELECT 1 FROM deck_shares s
            WHERE s.deck_id = d.id AND s.user_id = %(uid)s
        )
    )
"""

# Selects a deck row along with the owner_email, card_count, and shared_with
# array of emails. Callers add a WHERE clause.
DECK_SELECT = f"""
    SELECT
        d.id,
        d.owner_id,
        u.email AS owner_email,
        d.title,
        d.description,
        d.is_public,
        d.created_at,
        COALESCE((SELECT COUNT(*) FROM cards c WHERE c.deck_id = d.id), 0) AS card_count,
        COALESCE((
            SELECT array_agg(su.email ORDER BY su.email)
            FROM deck_shares s
            JOIN users su ON su.id = s.user_id
            WHERE s.deck_id = d.id
        ), ARRAY[]::text[]) AS shared_with
    FROM decks d
    JOIN users u ON u.id = d.owner_id
"""


# ------------------------ auth helpers ------------------------

def create_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_TTL_MINUTES)
    return jwt.encode({"sub": user_id, "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)


def _fetch_user_by_id(user_id: str) -> Optional[dict]:
    with db.cursor() as cur:
        cur.execute("SELECT id, email, password_hash, created_at FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()


def _fetch_user_by_email(email: str) -> Optional[dict]:
    with db.cursor() as cur:
        cur.execute("SELECT id, email, password_hash, created_at FROM users WHERE email = %s", (email,))
        return cur.fetchone()


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    creds_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
    except JWTError:
        raise creds_exc
    if not user_id:
        raise creds_exc
    try:
        user = _fetch_user_by_id(user_id)
    except pg_errors.InvalidTextRepresentation:
        raise creds_exc
    if not user:
        raise creds_exc
    # Normalize UUIDs to str for downstream code.
    user["id"] = str(user["id"])
    return user


def _row_to_deck(row: dict) -> DeckOut:
    return DeckOut(
        id=str(row["id"]),
        owner_id=str(row["owner_id"]),
        owner_email=row["owner_email"],
        title=row["title"],
        description=row["description"],
        is_public=row["is_public"],
        shared_with=list(row.get("shared_with") or []),
        card_count=int(row["card_count"]),
        created_at=row["created_at"],
    )


def _row_to_card(row: dict) -> CardOut:
    return CardOut(
        id=str(row["id"]),
        deck_id=str(row["deck_id"]),
        question=row["question"],
        answer=row["answer"],
        code=row["code"],
        equation=row["equation"],
        created_at=row["created_at"],
    )


def _load_deck_or_404(cur, deck_id: str, *, for_update: bool = False) -> dict:
    suffix = " FOR UPDATE" if for_update else ""
    try:
        cur.execute(f"SELECT id, owner_id, is_public FROM decks WHERE id = %s{suffix}", (deck_id,))
    except pg_errors.InvalidTextRepresentation:
        raise HTTPException(status_code=404, detail="Deck not found")
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Deck not found")
    return row


def _deck_visible(cur, deck_row: dict, user_id: str) -> bool:
    if str(deck_row["owner_id"]) == user_id:
        return True
    if deck_row["is_public"]:
        return True
    cur.execute(
        "SELECT 1 FROM deck_shares WHERE deck_id = %s AND user_id = %s",
        (deck_row["id"], user_id),
    )
    return cur.fetchone() is not None


def _fetch_deck_out(cur, deck_id: str) -> DeckOut:
    cur.execute(DECK_SELECT + " WHERE d.id = %s", (deck_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Deck not found")
    return _row_to_deck(row)


# ------------------------ app ------------------------

app = FastAPI(title="Study Desk", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    if os.getenv("STUDY_DESK_INIT_SCHEMA", "1") == "1":
        db.init_schema()
    else:
        db.get_pool()


@app.on_event("shutdown")
def _shutdown() -> None:
    db.close_pool()


@app.get("/health")
def health():
    with db.cursor() as cur:
        cur.execute("SELECT (SELECT COUNT(*) FROM users) AS users,"
                    " (SELECT COUNT(*) FROM decks) AS decks,"
                    " (SELECT COUNT(*) FROM cards) AS cards")
        counts = cur.fetchone() or {"users": 0, "decks": 0, "cards": 0}
    return {"ok": True, **counts}


@app.post("/auth/signup", response_model=TokenOut, status_code=201)
def signup(body: SignupIn):
    email = body.email.lower()
    password_hash = pwd_ctx.hash(body.password)
    with db.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id",
                (email, password_hash),
            )
        except pg_errors.UniqueViolation:
            raise HTTPException(status_code=409, detail="Email already registered")
        row = cur.fetchone()
    return TokenOut(access_token=create_token(str(row["id"])))


@app.post("/auth/login", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends()):
    email = form.username.lower()
    user = _fetch_user_by_email(email)
    if not user or not pwd_ctx.verify(form.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenOut(access_token=create_token(str(user["id"])))


@app.get("/me", response_model=UserOut)
def me(user: dict = Depends(get_current_user)):
    return UserOut(id=user["id"], email=user["email"], created_at=user["created_at"])


@app.get("/decks", response_model=list[DeckOut])
def list_decks(user: dict = Depends(get_current_user)):
    with db.cursor() as cur:
        cur.execute(
            DECK_SELECT + f" WHERE {DECK_VISIBLE_PREDICATE} ORDER BY d.created_at DESC",
            {"uid": user["id"]},
        )
        rows = cur.fetchall()
    return [_row_to_deck(r) for r in rows]


@app.post("/decks", response_model=DeckOut, status_code=201)
def create_deck(body: DeckIn, user: dict = Depends(get_current_user)):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO decks (owner_id, title, description, is_public) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (user["id"], body.title, body.description, body.is_public),
        )
        deck_id = cur.fetchone()["id"]
        return _fetch_deck_out(cur, deck_id)


@app.get("/decks/{deck_id}", response_model=DeckOut)
def get_deck(deck_id: str, user: dict = Depends(get_current_user)):
    with db.cursor() as cur:
        deck = _load_deck_or_404(cur, deck_id)
        if not _deck_visible(cur, deck, user["id"]):
            raise HTTPException(status_code=403, detail="Not allowed")
        return _fetch_deck_out(cur, deck_id)


@app.patch("/decks/{deck_id}", response_model=DeckOut)
def update_deck(deck_id: str, body: DeckPatch, user: dict = Depends(get_current_user)):
    updates: dict[str, object] = {}
    for field in ("title", "description", "is_public"):
        val = getattr(body, field)
        if val is not None:
            updates[field] = val

    with db.cursor(transaction=True) as cur:
        deck = _load_deck_or_404(cur, deck_id, for_update=True)
        if str(deck["owner_id"]) != user["id"]:
            raise HTTPException(status_code=403, detail="Only the owner can edit this deck")
        if updates:
            set_clause = ", ".join(f"{k} = %({k})s" for k in updates)
            params = {**updates, "id": deck_id}
            cur.execute(f"UPDATE decks SET {set_clause} WHERE id = %(id)s", params)
        return _fetch_deck_out(cur, deck_id)


@app.delete("/decks/{deck_id}", status_code=204)
def delete_deck(deck_id: str, user: dict = Depends(get_current_user)):
    with db.cursor(transaction=True) as cur:
        deck = _load_deck_or_404(cur, deck_id, for_update=True)
        if str(deck["owner_id"]) != user["id"]:
            raise HTTPException(status_code=403, detail="Only the owner can delete this deck")
        cur.execute("DELETE FROM decks WHERE id = %s", (deck_id,))


@app.post("/decks/{deck_id}/share", response_model=DeckOut)
def share_deck(deck_id: str, body: ShareIn, user: dict = Depends(get_current_user)):
    with db.cursor(transaction=True) as cur:
        deck = _load_deck_or_404(cur, deck_id, for_update=True)
        if str(deck["owner_id"]) != user["id"]:
            raise HTTPException(status_code=403, detail="Only the owner can share this deck")
        cur.execute("SELECT id FROM users WHERE email = %s", (body.email.lower(),))
        target = cur.fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="No user with that email")
        if str(target["id"]) == user["id"]:
            raise HTTPException(status_code=400, detail="Cannot share a deck with yourself")
        cur.execute(
            "INSERT INTO deck_shares (deck_id, user_id) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING",
            (deck_id, target["id"]),
        )
        return _fetch_deck_out(cur, deck_id)


@app.get("/decks/{deck_id}/cards", response_model=list[CardOut])
def list_cards(deck_id: str, user: dict = Depends(get_current_user)):
    with db.cursor() as cur:
        deck = _load_deck_or_404(cur, deck_id)
        if not _deck_visible(cur, deck, user["id"]):
            raise HTTPException(status_code=403, detail="Not allowed")
        cur.execute(
            "SELECT id, deck_id, question, answer, code, equation, created_at "
            "FROM cards WHERE deck_id = %s ORDER BY created_at ASC",
            (deck_id,),
        )
        return [_row_to_card(r) for r in cur.fetchall()]


@app.post("/decks/{deck_id}/cards", response_model=CardOut, status_code=201)
def add_card(deck_id: str, body: CardIn, user: dict = Depends(get_current_user)):
    with db.cursor(transaction=True) as cur:
        deck = _load_deck_or_404(cur, deck_id, for_update=True)
        if str(deck["owner_id"]) != user["id"]:
            raise HTTPException(status_code=403, detail="Only the owner can add cards")
        cur.execute(
            "INSERT INTO cards (deck_id, question, answer, code, equation) "
            "VALUES (%s, %s, %s, %s, %s) "
            "RETURNING id, deck_id, question, answer, code, equation, created_at",
            (deck_id, body.question, body.answer, body.code, body.equation),
        )
        return _row_to_card(cur.fetchone())


def _load_card_or_404(cur, card_id: str, *, for_update: bool = False) -> dict:
    suffix = " FOR UPDATE" if for_update else ""
    try:
        cur.execute(
            "SELECT c.id, c.deck_id, d.owner_id "
            "FROM cards c JOIN decks d ON d.id = c.deck_id "
            f"WHERE c.id = %s{suffix}",
            (card_id,),
        )
    except pg_errors.InvalidTextRepresentation:
        raise HTTPException(status_code=404, detail="Card not found")
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Card not found")
    return row


@app.patch("/cards/{card_id}", response_model=CardOut)
def update_card(card_id: str, body: CardPatch, user: dict = Depends(get_current_user)):
    updates: dict[str, object] = {}
    for field in ("question", "answer", "code", "equation"):
        val = getattr(body, field)
        if val is not None:
            updates[field] = val

    with db.cursor(transaction=True) as cur:
        card = _load_card_or_404(cur, card_id, for_update=True)
        if str(card["owner_id"]) != user["id"]:
            raise HTTPException(status_code=403, detail="Only the owner can edit cards")
        if updates:
            set_clause = ", ".join(f"{k} = %({k})s" for k in updates)
            params = {**updates, "id": card_id}
            cur.execute(f"UPDATE cards SET {set_clause} WHERE id = %(id)s", params)
        cur.execute(
            "SELECT id, deck_id, question, answer, code, equation, created_at "
            "FROM cards WHERE id = %s",
            (card_id,),
        )
        return _row_to_card(cur.fetchone())


@app.delete("/cards/{card_id}", status_code=204)
def delete_card(card_id: str, user: dict = Depends(get_current_user)):
    with db.cursor(transaction=True) as cur:
        card = _load_card_or_404(cur, card_id, for_update=True)
        if str(card["owner_id"]) != user["id"]:
            raise HTTPException(status_code=403, detail="Only the owner can delete cards")
        cur.execute("DELETE FROM cards WHERE id = %s", (card_id,))


@app.get("/search", response_model=list[SearchHit])
def search(q: str = Query(min_length=1, max_length=200), user: dict = Depends(get_current_user)):
    like = f"%{q}%"
    params = {"uid": user["id"], "q": like}

    with db.cursor() as cur:
        cur.execute(
            f"""
            SELECT d.id AS deck_id, d.title AS deck_title, d.description
            FROM decks d
            WHERE {DECK_VISIBLE_PREDICATE}
              AND (d.title ILIKE %(q)s OR d.description ILIKE %(q)s)
            ORDER BY d.created_at DESC
            """,
            params,
        )
        deck_rows = cur.fetchall()

        cur.execute(
            f"""
            SELECT c.id AS card_id, c.question, d.id AS deck_id, d.title AS deck_title
            FROM cards c
            JOIN decks d ON d.id = c.deck_id
            WHERE {DECK_VISIBLE_PREDICATE}
              AND (
                    c.question ILIKE %(q)s
                 OR c.answer   ILIKE %(q)s
                 OR c.code     ILIKE %(q)s
                 OR c.equation ILIKE %(q)s
              )
            ORDER BY c.created_at ASC
            """,
            params,
        )
        card_rows = cur.fetchall()

    hits: list[SearchHit] = []
    for r in deck_rows:
        hits.append(SearchHit(
            kind="deck",
            deck_id=str(r["deck_id"]),
            deck_title=r["deck_title"],
            snippet=(r["description"] or "")[:140] or r["deck_title"],
        ))
    for r in card_rows:
        hits.append(SearchHit(
            kind="card",
            deck_id=str(r["deck_id"]),
            deck_title=r["deck_title"],
            card_id=str(r["card_id"]),
            snippet=r["question"][:140],
        ))
    return hits
