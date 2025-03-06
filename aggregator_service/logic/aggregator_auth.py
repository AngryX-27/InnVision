# aggregator_auth.py
import os
import requests
import urllib.parse
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, HTTPException, Depends, status
from sqlalchemy.orm import Session

from aggregator_service.aggregator_db.models import UpworkToken
# Ваш метод для получения SQLAlchemy Session
from aggregator_service.aggregator_db.session import get_db

router = APIRouter()

# Читаем CLIENT_ID/SECRET/REDIRECT_URI/и т.д. из .env или другого источника
UPWORK_CLIENT_ID = os.getenv("UPWORK_CLIENT_ID", "")
UPWORK_CLIENT_SECRET = os.getenv("UPWORK_CLIENT_SECRET", "")
UPWORK_REDIRECT_URI = os.getenv(
    "UPWORK_REDIRECT_URI", "https://bcca-2a03-32c0-32-fa2c-28fc-e2ff-a979-2719/callback")

# OAuth-эндпоинты Upwork
UPWORK_OAUTH_AUTHORIZE_URL = "https://www.upwork.com/ab/account-security/oauth2/authorize"
UPWORK_OAUTH_TOKEN_URL = "https://www.upwork.com/api/v3/oauth2/token"

# ----------- Вспомогательные функции ----------- #


def build_authorize_url(client_id: str, redirect_uri: str, scope: str = "", state: str = "xyz123") -> str:
    """
    Формируем URL, на который надо отправить пользователя для авторизации на Upwork.
    scope: может быть "profiles:read jobs:read proposals:write" и т.д. (в зависимости от требований).
    state: защита от CSRF, передаётся обратно в колбэк.
    """
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,   # может быть набор разрешений через пробел
        "state": state
    }
    return f"{UPWORK_OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def save_tokens_in_db(db: Session, tokens: dict):
    """
    Сохраняем (или обновляем) токены в БД.
    Предполагаем, что Upwork у нас один аккаунт, поэтому либо
    перезатираем единственную запись, либо используем другие критерии.
    """
    # Пытаемся найти запись (id=1), если предполагаем одну запись
    existing_token = db.query(UpworkToken).first()

    if not existing_token:
        existing_token = UpworkToken()
        db.add(existing_token)

    existing_token.access_token = tokens.get("access_token")
    existing_token.refresh_token = tokens.get("refresh_token")
    existing_token.token_type = tokens.get("token_type")
    existing_token.scope = tokens.get("scope")
    # expires_in обычно int секунд
    existing_token.expires_in = tokens.get("expires_in", 0)
    existing_token.created_at = datetime.utcnow()

    db.commit()


def get_stored_token(db: Session) -> UpworkToken:
    """
    Возвращает запись UpworkToken из БД (или None, если нет).
    """
    return db.query(UpworkToken).first()


def is_token_expired(token_obj: UpworkToken) -> bool:
    """
    Проверяем, не протух ли access_token.
    Если текущая дата > (token.created_at + expires_in), считаем, что он просрочен.
    """
    if not token_obj:
        return True

    if token_obj.expires_in is None:
        return True

    # Считаем время истечения
    expires_at = token_obj.created_at + timedelta(seconds=token_obj.expires_in)
    return datetime.utcnow() > expires_at


def refresh_upwork_token(db: Session) -> str:
    """
    Обновляем access_token с помощью refresh_token, если он у нас есть.
    Возвращает новый access_token (или бросает исключение).
    """
    token_obj = get_stored_token(db)
    if not token_obj or not token_obj.refresh_token:
        raise HTTPException(
            status_code=400, detail="No stored token or no refresh_token available")

    try:
        resp = requests.post(
            UPWORK_OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": token_obj.refresh_token,
                "client_id": UPWORK_CLIENT_ID,
                "client_secret": UPWORK_CLIENT_SECRET
            },
            timeout=15
        )
        resp.raise_for_status()
        tokens = resp.json()
        save_tokens_in_db(db, tokens)
        return tokens.get("access_token")
    except requests.RequestException as e:
        raise HTTPException(
            status_code=500, detail=f"Refresh token failed: {e}")


def get_valid_upwork_token(db: Session) -> str:
    """
    Возвращает действующий access_token. Если просрочен — делает refresh.
    Если не удаётся рефреш, бросает исключение.
    """
    token_obj = get_stored_token(db)
    if not token_obj:
        raise HTTPException(
            status_code=401, detail="No Upwork token found. Please authorize first.")

    if is_token_expired(token_obj):
        # Пытаемся рефрешить
        return refresh_upwork_token(db)
    else:
        return token_obj.access_token


# ----------- Маршруты API ----------- #

@router.get("/upwork/oauth/start")
def start_upwork_oauth(db: Session = Depends(get_db)):
    """
    Начало OAuth: формируем ссылку на авторизацию и отдаём её клиенту или сразу редиректим.
    Для упрощения — отдадим в ответ JSON со ссылкой, 
    но можно сразу сделать RedirectResponse (если нужно).
    """
    # Пример scope. Зависит от того, какие разрешения вы запросили в Upwork Dev Center
    scope = "freelancer_approvals:write jobs:read proposals:write"
    url = build_authorize_url(UPWORK_CLIENT_ID, UPWORK_REDIRECT_URI, scope)
    return {"authorize_url": url}


@router.get("/upwork/oauth/callback")
def upwork_oauth_callback(
    code: str = None,
    state: str = None,
    error: str = None,
    db: Session = Depends(get_db)
):
    """
    Эндпоинт, куда Upwork перенаправляет пользователя с параметрами:
    ?code=XXX&state=YYY (или ?error=...)
    """
    if error:
        # Например, user_cancelled, access_denied
        raise HTTPException(
            status_code=400, detail=f"Upwork OAuth error: {error}")

    if not code:
        raise HTTPException(
            status_code=400, detail="No authorization code provided")

    # Обмениваем code на access_token
    try:
        resp = requests.post(
            UPWORK_OAUTH_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": UPWORK_REDIRECT_URI,
                "client_id": UPWORK_CLIENT_ID,
                "client_secret": UPWORK_CLIENT_SECRET
            },
            timeout=15
        )
        resp.raise_for_status()
        tokens = resp.json()
        # Сохраняем в БД
        save_tokens_in_db(db, tokens)

        return {
            "status": "success",
            "access_token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token"),
            "expires_in": tokens.get("expires_in"),
            "token_type": tokens.get("token_type"),
            "scope": tokens.get("scope")
        }
    except requests.RequestException as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to obtain token: {e}")
