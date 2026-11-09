"""Run with python app.py, then open http://localhost:8000."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import json
import logging
from logging.handlers import RotatingFileHandler
import secrets
import time
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import httpx
from pydantic import BaseModel, Field
from microsoft_agents_a365.runtime.utility import Utility

from config import ROOT, Settings
from auth import AgentOboAuth, AuthError, UserContext
from onedrive import OneDriveClient
from extractors import DocumentError
from agent import FoundryClient, ProtectedAgent, AgentError, PolicyBlocked
from purview import PurviewEvaluator, PurviewError

SESSION_SECONDS = 3600
COOKIE = "onedrive_agent_session"


@dataclass
class Session:
    expires: float
    csrf: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    flow: dict | None = field(default=None, repr=False)
    user: UserContext | None = field(default=None, repr=False)
    history: list = field(default_factory=list, repr=False)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    file_path: str = Field(default="", max_length=1024)


def configure_logging():
    # Log policy metadata only; never enable SDK HTTP debug logging or access
    # logs containing callback authorization codes / signed download URLs.
    (ROOT / "logs").mkdir(exist_ok=True)
    handler = RotatingFileHandler(ROOT / "logs" / "policy-decisions.jsonl", maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    for name in ("agent.policy", "policy_decisions"):
        logger = logging.getLogger(name)
        if not logger.handlers:
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    for name in ("httpx", "httpcore", "httpx2", "openai", "msal", "azure", "microsoft_agents"):
        logging.getLogger(name).setLevel(logging.CRITICAL)


def create_app(settings=None, *, auth_override=None, agent_override=None):
    settings = settings or Settings.from_env()
    sessions: dict[str, Session] = {}
    auth = auth_override or AgentOboAuth(settings)

    @asynccontextmanager
    async def lifespan(app):
        configure_logging()
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30, connect=10), follow_redirects=False,
            headers={"User-Agent": Utility.get_user_agent_header("OneDrivePurview")},
        ) as client:
            foundry = FoundryClient(settings)
            app.state.agent = agent_override or ProtectedAgent(settings, auth, OneDriveClient(settings, client), PurviewEvaluator(settings, client), foundry)
            try:
                yield
            finally:
                sessions.clear()
                await foundry.close()

    app = FastAPI(title=settings.app_name, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # FastAPI's default handler includes rejected input values in its body.
        return JSONResponse({"detail": "Use a nonempty message of at most 8000 characters and a valid file path."}, status_code=422)

    @app.middleware("http")
    async def local_security(request, call_next):
        if request.method == "POST":
            if request.headers.get("origin") != settings.origin:
                return JSONResponse({"detail": "Request origin does not match this local app."}, status_code=403)
            try:
                if int(request.headers.get("content-length", "0")) > 65536:
                    return JSONResponse({"detail": "Request is too large."}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "Invalid request length."}, status_code=400)
            body = await request.body()
            if len(body) > 65536:
                return JSONResponse({"detail": "Request is too large."}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        return response

    def current_session(request, authenticated=True):
        now = time.time()
        for sid in list(sessions):
            if sessions[sid].expires <= now:
                sessions.pop(sid, None)
        session = sessions.get(request.cookies.get(COOKIE, ""))
        if not session or (authenticated and session.user is None):
            raise HTTPException(401, "Sign in with your work account.")
        return session

    def require_csrf(request, session):
        if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), session.csrf):
            raise HTTPException(403, "Refresh the page and try again.")

    @app.get("/")
    async def index():
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/static/{name}")
    async def static(name: str):
        if name not in {"app.js", "style.css"}:
            raise HTTPException(404)
        return FileResponse(ROOT / "static" / name)

    @app.get("/health")
    async def health():
        return {"status": "ok", "configured": auth.ready}

    @app.get("/api/session")
    async def get_session(request: Request):
        result = {"authenticated": False, "missing_settings": auth.missing_settings(), "test_file_path": settings.test_file_path}
        try:
            session = current_session(request)
        except HTTPException:
            return result
        result.update(authenticated=True, name=session.user.name, username=session.user.username, csrf=session.csrf)
        return result

    @app.get("/auth/login")
    async def login(request: Request):
        try:
            flow = await asyncio.to_thread(auth.begin_login)
        except AuthError as error:
            return JSONResponse({"detail": str(error)}, status_code=503)
        # The OAuth flow, PKCE verifier, assertions, and tokens stay on the server.
        now = time.time()
        for sid in list(sessions):
            if sessions[sid].expires <= now:
                sessions.pop(sid, None)
        if len(sessions) >= 50:
            raise HTTPException(429, "Too many local sessions. Restart the test app.")
        sid = secrets.token_urlsafe(32)
        sessions[sid] = Session(expires=now + 600, flow=flow)
        response = RedirectResponse(flow["auth_uri"], status_code=302)
        response.set_cookie(COOKIE, sid, httponly=True, samesite="lax", max_age=SESSION_SECONDS)
        return response

    @app.get("/auth/callback")
    async def callback(request: Request):
        session = current_session(request, authenticated=False)
        flow, session.flow = session.flow, None
        if not flow:
            raise HTTPException(400, "Start a new sign-in from the home page.")
        try:
            user = await asyncio.to_thread(auth.complete_login, flow, dict(request.query_params))
        except AuthError as error:
            sessions.pop(request.cookies.get(COOKIE, ""), None)
            return JSONResponse({"detail": str(error)}, status_code=401)
        sessions.pop(request.cookies.get(COOKIE, ""), None)
        sid = secrets.token_urlsafe(32)
        sessions[sid] = Session(expires=time.time() + SESSION_SECONDS, user=user)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(COOKIE, sid, httponly=True, samesite="lax", max_age=SESSION_SECONDS)
        return response

    @app.post("/auth/logout")
    async def logout(request: Request):
        session = current_session(request)
        require_csrf(request, session)
        sessions.pop(request.cookies.get(COOKIE, ""), None)
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE)
        return response

    @app.post("/api/chat")
    async def chat(body: ChatInput, request: Request):
        session = current_session(request)
        require_csrf(request, session)
        if session.lock.locked():
            raise HTTPException(409, "Wait for the current response.")
        async with session.lock:
            try:
                result = await app.state.agent.chat(session.user, body.message, body.file_path, session.history)
            except PolicyBlocked as error:
                return JSONResponse({"detail": str(error), "blocked": True}, status_code=403)
            except AuthError as error:
                return JSONResponse({"detail": str(error)}, status_code=401)
            except (PurviewError, AgentError, DocumentError) as error:
                return JSONResponse({"detail": str(error)}, status_code=422)
            except Exception:
                # Do not serialize traceback or raw library exceptions to UI/logs.
                return JSONResponse({"detail": "The request could not be evaluated safely. Nothing further was released."}, status_code=503)
            session.history.extend([{"role": "user", "content": body.message}, {"role": "assistant", "content": result.text}])
            session.history = session.history[-12:]
            return {"text": result.text, "correlation_id": result.correlation_id, "output_inline_evaluated": result.output_inline_evaluated}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    settings = Settings.from_env()
    port = urlparse(settings.redirect_uri).port or 8000
    print(f"Open {settings.origin} - complete .env and onboarding before signing in.")
    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")
