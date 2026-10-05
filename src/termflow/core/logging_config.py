import logging
import re
from logging.handlers import RotatingFileHandler

from termflow.storage.credentials import get
from termflow.storage.paths import LOCAL


class SecretFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        for provider in ("openai", "anthropic", "gemini", "compatible"):
            secret = get(provider)
            if secret:
                message = message.replace(secret, "[REDACTED]")
        message = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+", r"\1[REDACTED]", message)
        record.msg, record.args = message, ()
        return True


def configure_logging(debug=False):
    folder = LOCAL / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / "termflow.log", maxBytes=2_000_000, backupCount=4, encoding="utf-8")
    handler.addFilter(SecretFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)
