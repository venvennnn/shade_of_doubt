import hashlib
import re
from dataclasses import dataclass

from app.errors import AuthError

# Opaque browser secret. The raw value stays in localStorage. The database stores only its hash.
_SESSION = re.compile(r"^[A-Za-z0-9_-]{32,200}$")


@dataclass
class Principal:
    user_id: str


def principal_from_session(token: str) -> Principal:
    token = token.strip()
    if not _SESSION.fullmatch(token):
        raise AuthError(
            "invalid_session",
            "This browser session is missing or malformed.",
            "Reload the page. Shade of Doubt stores a random session in this browser and does not create accounts.",
        )
    return Principal(user_id=hashlib.sha256(token.encode("utf-8")).hexdigest())
