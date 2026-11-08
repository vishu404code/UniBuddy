import re
from pathlib import Path

from app.config import Settings

TEMPLATE = Path(__file__).resolve().parent.parent / ".env.example"


def _template_keys() -> set[str]:
    keys = set()
    for line in TEMPLATE.read_text().splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if match:
            keys.add(match.group(1))
    return keys


def test_env_example_lists_every_setting_the_code_reads():
    expected = {name.upper() for name in Settings.model_fields}
    assert _template_keys() == expected


def test_env_example_contains_no_real_looking_secrets():
    text = TEMPLATE.read_text()
    assert not re.search(r"sb_(secret|publishable)_[A-Za-z0-9]{20,}", text)
    assert not re.search(r"sk-[A-Za-z0-9]{20,}", text)
    assert not re.search(r"eyJ[A-Za-z0-9_-]{20,}", text)
