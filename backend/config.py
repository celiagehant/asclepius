"""Settings shared by the whole app: where keys come from and which model to call.

Keys are read from a `.env` file in two places, in this order:
  1. the repo folder (next to this README), and
  2. the folder one level above the repo (where the teaching staff keep theirs).
A value found in the repo `.env` wins over the same key in the parent `.env`.
A variable already set in the shell wins over both.

Every model call uses gpt-6-luna through Portkey's OpenAI-compatible endpoint.
The key itself is never printed, logged or sent to the browser.

Run `python -m backend.config` from the repo folder to check the setup.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_LOCATIONS = [REPO_ROOT / ".env", REPO_ROOT.parent / ".env"]

PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
MODEL_ID = "gpt-6-luna"  # the only model the course key may be used with
KEY_NAME = "PORTKEY_API_KEY"

DATA_DIR = REPO_ROOT / "data"
TEST_CASES_DIR = DATA_DIR / "test_cases"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
# Public deployment: shows "don't upload real records" notices. Set CC_PUBLIC_DEMO=1 on the host.
PUBLIC_DEMO = os.environ.get("CC_PUBLIC_DEMO", "").strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class KeyStatus:
    loaded: bool
    source: str | None  # "repo .env", "parent .env", "environment", or None
    message: str


def _load_env_files() -> KeyStatus:
    already_in_shell = bool(os.environ.get(KEY_NAME))
    found_in: str | None = "environment" if already_in_shell else None
    for label, path in zip(("repo .env", "parent .env"), ENV_LOCATIONS):
        if path.is_file():
            # override=False: the first place that sets a key keeps it.
            load_dotenv(path, override=False)
            if found_in is None and os.environ.get(KEY_NAME):
                found_in = label
    if found_in:
        return KeyStatus(True, found_in, f"{KEY_NAME} loaded from the {found_in}.")
    looked = "\n".join(f"  - {p}" for p in ENV_LOCATIONS)
    return KeyStatus(
        False,
        None,
        f"{KEY_NAME} was not found. The app looked for a .env file containing "
        f"{KEY_NAME}=... in:\n{looked}\n"
        "Copy .env.example to .env in the repo folder and paste your key, "
        "or put the .env one folder above the repo.",
    )


KEY_STATUS = _load_env_files()


class MissingKeyError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get(KEY_NAME)
    if not key:
        raise MissingKeyError(KEY_STATUS.message)
    return key


def sync_client() -> OpenAI:
    return OpenAI(api_key=_api_key(), base_url=PORTKEY_BASE_URL, timeout=60, max_retries=2)


def async_client(max_retries: int = 2) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=_api_key(), base_url=PORTKEY_BASE_URL, timeout=60, max_retries=max_retries)  # stuck requests are retried


def missing_key_banner() -> str:
    line = "=" * 72
    return f"\n{line}\n  CASE CONFERENCE: MISSING API KEY\n{line}\n{KEY_STATUS.message}\n{line}\n"


def _check() -> int:
    """`python -m backend.config`: report key status and make one tiny model call."""
    print(f"Model: {MODEL_ID} via {PORTKEY_BASE_URL}")
    if not KEY_STATUS.loaded:
        print(missing_key_banner())
        return 1
    print(KEY_STATUS.message)
    response = sync_client().responses.create(
        model=MODEL_ID, input="Reply with the single word: ready", max_output_tokens=16
    )
    print(f"Model replied: {response.output_text.strip()!r}")
    return 0


if __name__ == "__main__":
    sys.exit(_check())
