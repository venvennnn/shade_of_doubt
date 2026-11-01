from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

from app.config import Settings, get_settings
from app.errors import AuthError, ConfigurationError

_jwks: dict[str, PyJWKClient] = {}


@dataclass
class Principal:
    user_id: str
    email: str | None = None


def _jwks_client(supabase_url: str) -> PyJWKClient:
    base = supabase_url.rstrip("/")
    if base not in _jwks:
        _jwks[base] = PyJWKClient(base + "/auth/v1/.well-known/jwks.json")
    return _jwks[base]


def decode_supabase_jwt(token: str, settings: Settings | None = None) -> Principal:
    settings = settings or get_settings()
    if not settings.supabase_url and not settings.supabase_jwt_secret:
        raise ConfigurationError(
            "auth_unconfigured",
            "Supabase JWT verification is not configured.",
            "Set SUPABASE_URL and either SUPABASE_JWT_SECRET (HS256) or rely on the project JWKS (RS256/ES256).",
        )
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthError("invalid_token", "The session token could not be read.", "Sign in again.") from exc
    algorithm = header.get("alg")
    issuer = settings.supabase_url.rstrip("/") + "/auth/v1" if settings.supabase_url else None
    options = {"require": ["exp", "sub"]}
    try:
        if algorithm == "HS256":
            if not settings.supabase_jwt_secret:
                raise ConfigurationError(
                    "jwt_secret_missing",
                    "This token uses HS256 but SUPABASE_JWT_SECRET is empty.",
                    "Set the JWT secret from the Supabase project, or use the asymmetric signing keys.",
                )
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience=settings.supabase_jwt_audience,
                issuer=issuer,
                options={**options, "verify_iss": bool(issuer)},
            )
        elif algorithm in {"RS256", "ES256"}:
            if not settings.supabase_url:
                raise ConfigurationError(
                    "jwks_unconfigured",
                    "This token uses asymmetric signing but SUPABASE_URL is empty.",
                    "Set SUPABASE_URL so the API can fetch the JWKS and check the issuer.",
                )
            key = _jwks_client(settings.supabase_url).get_signing_key_from_jwt(token).key
            payload = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                audience=settings.supabase_jwt_audience,
                issuer=issuer,
                options=options,
            )
        else:
            raise AuthError("unsupported_alg", "The session token uses an unsupported algorithm.", "Sign in again.")
    except ConfigurationError:
        raise
    except AuthError:
        raise
    except jwt.PyJWTError as exc:
        raise AuthError("invalid_token", "The session token was rejected.", "Sign in again.") from exc
    if issuer and payload.get("iss") != issuer:
        raise AuthError("issuer_mismatch", "The session token issuer does not match this project.", "Sign in again.")
    subject = str(payload.get("sub") or "")
    if not subject:
        raise AuthError("subject_missing", "The session token has no subject.", "Sign in again.")
    return Principal(user_id=subject, email=payload.get("email"))
