import httpx

REPOSITORY = "nastasiamql-arch/TermFlow"
API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"


def latest_release() -> dict:
    with httpx.Client(timeout=20, follow_redirects=True, headers={"Accept": "application/vnd.github+json"}) as client:
        response = client.get(API)
        response.raise_for_status()
        data = response.json()
    if data.get("draft") or data.get("prerelease"):
        raise ValueError("No stable release is available")
    return data
