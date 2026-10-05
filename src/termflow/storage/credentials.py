import keyring

SERVICE = "TermFlow"


def store(provider: str, api_key: str) -> None:
    keyring.set_password(SERVICE, provider, api_key)


def get(provider: str) -> str | None:
    return keyring.get_password(SERVICE, provider)


def delete(provider: str) -> None:
    try:
        keyring.delete_password(SERVICE, provider)
    except keyring.errors.PasswordDeleteError:
        pass
