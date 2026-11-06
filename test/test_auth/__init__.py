"""Team permission tests use local sessions without depending on external sign-in."""

from auth.models import User
from auth.service import auth_service


async def issue_test_session(username: str) -> str:
    return (await auth_service.issue_session(await User.get(username=username))).token
