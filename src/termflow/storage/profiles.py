import os
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from termflow.storage.paths import APPDATA


class NovelProfile(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    source_path: str = ""
    vocab_path: str = ""
    search_chunks: int = 1
    selected_search_prompt: str = "builtin-search"
    selected_polish_prompt: str = "builtin-polish"


class ProfileCollection(BaseModel):
    active_profile_id: str = ""
    profiles: list[NovelProfile] = Field(default_factory=list)


class FileSnapshot(BaseModel):
    text: str
    sha256: str


def profiles_path() -> Path:
    return APPDATA / "profiles.json"


def load_profiles() -> ProfileCollection:
    try:
        return ProfileCollection.model_validate_json(profiles_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ProfileCollection()


def save_profiles(collection: ProfileCollection) -> None:
    path = profiles_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(collection.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporary, path)


def create_profile(name: str) -> NovelProfile:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Profile name cannot be empty")
    collection = load_profiles()
    profile = NovelProfile(name=cleaned)
    collection.profiles.append(profile)
    if not collection.active_profile_id:
        collection.active_profile_id = profile.id
    save_profiles(collection)
    return profile


def update_profile(profile_id: str, **changes) -> NovelProfile:
    collection = load_profiles()
    profile = next((item for item in collection.profiles if item.id == profile_id), None)
    if profile is None:
        raise KeyError(profile_id)
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        if not changes["name"]:
            raise ValueError("Profile name cannot be empty")
    updated = profile.model_copy(update=changes)
    collection.profiles = [updated if item.id == profile_id else item for item in collection.profiles]
    save_profiles(collection)
    return updated


def set_active_profile(profile_id: str) -> None:
    collection = load_profiles()
    if profile_id not in {item.id for item in collection.profiles}:
        raise KeyError(profile_id)
    collection.active_profile_id = profile_id
    save_profiles(collection)


def delete_profile(profile_id: str) -> None:
    collection = load_profiles()
    collection.profiles = [item for item in collection.profiles if item.id != profile_id]
    if len(collection.profiles) == 0:
        raise ValueError("At least one novel profile must remain")
    if collection.active_profile_id == profile_id:
        collection.active_profile_id = collection.profiles[0].id
    save_profiles(collection)


def file_snapshot(path: str | Path) -> FileSnapshot:
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    return FileSnapshot(text=text, sha256=sha256(raw).hexdigest())
