"""Authenticated Streamable HTTP server and narrowly scoped calendar tools."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Annotated, Any, Literal
from urllib.parse import parse_qs, urlsplit

import anyio
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import BaseRoute, Route

from ..calendar.providers.base import CalendarProviderError
from ..messages_ru import (
    MCP_INSTRUCTIONS,
    MCP_INVALID_INPUT,
    MCP_LINK_EXPIRED,
    MCP_LOGIN_ERROR,
    MCP_TEMPORARY_ERROR,
    MCP_UNCONFIRMED_CREATE,
    MCP_UNCONFIRMED_PARTSTAT,
    mcp_login_html,
)
from .accounts import CalendarAccountStore
from .oauth import LOGIN_TTL, SCOPE, MailOAuthProvider, OAuthState
from .service import MailCalendarService
from .settings import McpSettings

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
    # HTML form POSTs under no-referrer send Origin:null. Preserve same-origin
    # validation while keeping authorization paths and query strings private.
    "Referrer-Policy": "strict-origin",
    "X-Content-Type-Options": "nosniff",
}


def create_server(
    settings: McpSettings,
    accounts: CalendarAccountStore,
    oauth: MailOAuthProvider,
    service: MailCalendarService,
) -> MCPServer:
    server = MCPServer(
        "mail_calendar_mcp",
        instructions=MCP_INSTRUCTIONS,
        auth_server_provider=oauth,
        auth=AuthSettings.model_validate(
            {
                # Validate strings here so the SDK preserves an empty URL path.
                # A prebuilt AnyHttpUrl would append '/' and change the issuer.
                "issuer_url": settings.base_url,
                "resource_server_url": settings.resource_url,
                "validate_token_resource": True,
                "required_scopes": [SCOPE],
                "client_registration_options": ClientRegistrationOptions(
                    enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]
                ),
                "revocation_options": RevocationOptions(enabled=True),
            }
        ),
    )
    semaphore = asyncio.Semaphore(4)
    login_attempts: deque[float] = deque()

    async def invoke(
        method: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        token = get_access_token()
        if (
            token is None
            or not token.subject
            or token.resource != settings.resource_url
            or SCOPE not in token.scopes
        ):
            raise ToolError(MCP_LOGIN_ERROR)
        try:
            account_id = int(token.subject)
            # Check the allowlist even after a login is revoked in configuration.
            service.context(account_id)
            async with semaphore:
                return await anyio.to_thread.run_sync(lambda: method(account_id, *args, **kwargs))
        except CalendarProviderError as exc:
            messages = {
                "CREATE_UNCONFIRMED": MCP_UNCONFIRMED_CREATE,
                "PARTSTAT_UPDATE_UNCONFIRMED": MCP_UNCONFIRMED_PARTSTAT,
            }
            raise ToolError(messages.get(exc.error_code, MCP_TEMPORARY_ERROR)) from None
        except ValueError:
            raise ToolError(MCP_INVALID_INPUT) from None
        except Exception:  # noqa: BLE001 - never return CalDAV credentials or raw responses
            raise ToolError(MCP_TEMPORARY_ERROR) from None

    def tool(*, write: bool = False, destructive: bool = False, profile: bool = False):
        meta: dict[str, Any] = {"securitySchemes": [{"type": "oauth2", "scopes": [SCOPE]}]}
        if profile:
            meta["openai/profile"] = True
        return server.tool(
            annotations=ToolAnnotations(
                read_only_hint=not write,
                destructive_hint=destructive,
                idempotent_hint=not write,
                open_world_hint=False,
            ),
            meta=meta,
        )

    @tool(profile=True)
    async def mail_calendar_get_profile() -> dict[str, Any]:
        """Get the connected Mail account, timezone and current local date/time. Call before resolving 'today' or 'tomorrow'."""
        return await invoke(service.profile)

    @tool()
    async def mail_calendar_list_calendars() -> dict[str, Any]:
        """List calendars in this account. Use returned calendar_id when selecting a calendar for reading or creation."""
        return await invoke(service.calendars)

    @tool()
    async def mail_calendar_list_events(
        start_date: date,
        end_date: date,
        query: Annotated[str, Field(max_length=200)] = "",
        calendar_id: str | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 50,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> dict[str, Any]:
        """Read/search meetings over 1–90 days. Start date inclusive, end date exclusive, in profile timezone. Searches title, location and description. Follow next_offset for all results. Includes declined meetings with their response."""
        return await invoke(
            service.events,
            start_date,
            end_date,
            query=query,
            calendar_id=calendar_id,
            limit=limit,
            offset=offset,
        )

    @tool()
    async def mail_calendar_list_invitations(
        start_date: date,
        end_date: date,
        limit: Annotated[int, Field(ge=1, le=100)] = 50,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> dict[str, Any]:
        """Read verified unanswered invitations. End date exclusive, max 90 days. For the usual view use today minus 14 days through today plus 61 days. Returns event_id for responding."""
        return await invoke(
            service.events, start_date, end_date, limit=limit, offset=offset, invitations=True
        )

    @tool()
    async def mail_calendar_find_free_time(
        start_date: date,
        end_date: date,
        duration_minutes: Annotated[int, Field(ge=1, le=1440)] = 30,
        work_start: str = "10:00",
        work_end: str = "19:00",
    ) -> dict[str, Any]:
        """Find maximal free intervals in this user's calendars over up to 31 days (end exclusive), in profile timezone. Cancelled and declined meetings do not block time; pending invitations and all-day events do. Does not know other people's availability or reserve a slot."""
        return await invoke(
            service.availability,
            start_date,
            end_date,
            duration_minutes=duration_minutes,
            work_start=work_start,
            work_end=work_end,
        )

    @tool(write=True)
    async def mail_calendar_create_event(
        title: Annotated[str, Field(min_length=1, max_length=500)],
        start: datetime,
        end: datetime,
        calendar_id: str | None = None,
        location: Annotated[str | None, Field(max_length=1000)] = None,
        description: Annotated[str | None, Field(max_length=8000)] = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Preview (confirm=false) or create (confirm=true) one meeting. Start/end MUST contain UTC offset, e.g. 2026-09-30T15:00:00+03:00. Defaults to primary calendar. Creates without inviting attendees. Only confirm a specific user-authorized action. Never automatically retry an uncertain creation."""
        return await invoke(
            service.create,
            title,
            start,
            end,
            calendar_id=calendar_id,
            location=location,
            description=description,
            confirm=confirm,
        )

    @tool(write=True, destructive=True)
    async def mail_calendar_respond_to_invitation(
        event_id: str,
        response: Literal["ACCEPTED", "DECLINED", "TENTATIVE"],
        confirm: bool = False,
        confirm_series: bool = False,
    ) -> dict[str, Any]:
        """Preview or change your RSVP to an invitation. event_id comes from a fresh event/invitation list. A recurring invitation affects the ENTIRE series: explain this and set confirm_series only if the user authorized the series response. Set confirm=true only for an authorized response."""
        return await invoke(
            service.respond, event_id, response, confirm=confirm, confirm_series=confirm_series
        )

    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    def login_form(ticket: str, client_name: str, *, error: bool = False) -> Response:
        csrf = secrets.token_urlsafe(32)
        oauth.prepare_form(ticket, csrf)
        response = HTMLResponse(
            mcp_login_html(
                ticket, csrf, client_name, error=error, connect_path=settings.connect_path
            ),
            headers=SECURITY_HEADERS,
        )
        response.set_cookie(
            "mail_calendar_csrf",
            csrf,
            secure=settings.base_url.startswith("https://"),
            httponly=True,
            samesite="strict",
            max_age=LOGIN_TTL,
            path=settings.connect_path,
        )
        return response

    @server.custom_route("/connect", methods=["GET", "POST"])
    async def connect(request: Request) -> Response:
        if request.method == "GET":
            ticket = request.query_params.get("ticket", "")
            pending = oauth.state.get("pending", ticket) if len(ticket) <= 128 else None
            if not pending:
                return HTMLResponse(MCP_LINK_EXPIRED, status_code=400, headers=SECURITY_HEADERS)
            client = await oauth.get_client(pending["client_id"])
            return login_form(ticket, (client.client_name if client else None) or "ChatGPT")
        if request.headers.get("origin") != settings.origin:
            return HTMLResponse(MCP_LINK_EXPIRED, status_code=403, headers=SECURITY_HEADERS)
        body_size = 0
        chunks = []
        async for chunk in request.stream():
            body_size += len(chunk)
            if body_size > 8192:
                return Response(status_code=413)
            chunks.append(chunk)
        if (
            request.headers.get("content-type", "").split(";")[0]
            != "application/x-www-form-urlencoded"
        ):
            return Response(status_code=400)
        try:
            fields = parse_qs(b"".join(chunks).decode("utf-8"), max_num_fields=8)
            if any(len(values) != 1 for values in fields.values()):
                return Response(status_code=400)
            form = {key: values[0] for key, values in fields.items()}
        except (ValueError, UnicodeError):
            return Response(status_code=400)
        now = time.monotonic()
        while login_attempts and login_attempts[0] < now - 60:
            login_attempts.popleft()
        if len(login_attempts) >= 10:
            return Response(status_code=429, headers={"Retry-After": "60"})
        login_attempts.append(now)
        ticket, csrf = str(form.get("ticket") or ""), str(form.get("csrf") or "")
        try:
            pending = oauth.check_form(ticket, csrf, request.cookies.get("mail_calendar_csrf", ""))
        except ValueError:
            return HTMLResponse(MCP_LINK_EXPIRED, status_code=403, headers=SECURITY_HEADERS)
        try:
            async with semaphore:
                account = await anyio.to_thread.run_sync(
                    lambda: service.connect(
                        str(form.get("login") or ""), str(form.get("secret") or "")
                    )
                )
            redirect = oauth.complete_login(pending, account.account_id)
        except Exception:  # noqa: BLE001 - no credential-bearing exceptions in responses
            oauth.state.put("pending", ticket, pending, LOGIN_TTL)
            return login_form(ticket, "ChatGPT", error=True)
        response = RedirectResponse(redirect, status_code=303, headers=SECURITY_HEADERS)
        response.delete_cookie("mail_calendar_csrf", path=settings.connect_path)
        return response

    return server


def create_app(server: MCPServer, service: MailCalendarService, state: OAuthState) -> Starlette:
    settings = service.settings
    app = server.streamable_http_app(
        host=settings.host,
        stateless_http=True,
        json_response=True,
        max_request_body_size=64 * 1024,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[urlsplit(settings.base_url).netloc],
            allowed_origins=[settings.origin],
        ),
    )
    prefix = settings.path_prefix
    if prefix:
        # The SDK publishes OAuth endpoints relative to the issuer, while
        # RFC 8414/9728 discovery lives at the origin's .well-known directory.
        routes: list[BaseRoute] = []
        for route in app.routes:
            if not isinstance(route, Route):
                raise TypeError("Expected an HTTP route in the calendar MCP application")
            if route.path == "/.well-known/oauth-authorization-server":
                path = route.path + prefix
            elif route.path.startswith("/.well-known/oauth-protected-resource"):
                path = route.path
            else:
                path = prefix + route.path
            routes.append(
                Route(
                    path,
                    endpoint=route.endpoint,
                    methods=route.methods,
                    name=route.name,
                    include_in_schema=route.include_in_schema,
                )
            )
        app.router.routes = routes
    transport_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: Starlette) -> AsyncIterator[Any]:
        # A stateless MCP request has its own SDK server lifespan. Shared CalDAV
        # clients and OAuth state belong to the HTTP application, not a request.
        try:
            async with transport_lifespan(application) as context:
                yield context
        finally:
            await anyio.to_thread.run_sync(service.close)
            state.close()

    app.router.lifespan_context = lifespan
    return app


def build_app(settings: McpSettings) -> Starlette:
    from ..security.token_vault import TokenVault

    accounts = CalendarAccountStore(
        settings.data_dir / "users.json", TokenVault(settings.encryption_key)
    )
    state = OAuthState(settings.data_dir / "oauth.sqlite3", settings.encryption_key)
    oauth = MailOAuthProvider(settings, state)
    service = MailCalendarService(settings, accounts)
    return create_app(create_server(settings, accounts, oauth, service), service, state)
