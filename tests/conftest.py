import os

# Test runs get their own secrets, never the deployment's, and no demo code helper.
os.environ["INSAKA_SECRET_KEY"] = "test-secret-key-for-insaka-tests"
os.environ["INSAKA_DEMO_PASSWORD"] = "test-password"
os.environ.pop("INSAKA_DEMO_MFA_HELPER", None)
os.environ["INSAKA_DEMO_SIGNIN"] = "0"         # the full password + code flow
os.environ.pop("INSAKA_CORS_ORIGINS", None)


def auth_headers(app, user: str) -> dict:
    """A real access token for user, issued by the app's own authenticator."""
    token = app.extensions["insaka"]["auth"].issue(user)["access_token"]
    return {"Authorization": f"Bearer {token}"}
