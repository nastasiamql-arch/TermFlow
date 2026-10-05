from packaging.version import InvalidVersion, Version

from termflow.version import __version__


def is_newer(tag: str, installed: str = __version__) -> bool:
    try:
        return Version(tag.removeprefix("v")) > Version(installed)
    except InvalidVersion:
        return False
