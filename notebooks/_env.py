"""Load AWS Bedrock settings from .env.local and switch between mock and live calls."""
import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ENV_FILE = Path(__file__).resolve().parent / ".env.local"
FORBIDDEN = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
DEFAULT_MODELS = {
    "MODEL_FAST": "bedrock/us.anthropic.claude-haiku-5-5",
    "MODEL_SMART": "bedrock/us.anthropic.claude-opus-5-5",
    "MODEL_ALT": "bedrock/us.amazon.nova-2-lite-v1:0",
}

# Long-lived keys are a security risk; credentials come from an SSO profile.
_in_file = [k for k in FORBIDDEN if ENV_FILE.exists() and k in dotenv_values(ENV_FILE)]
if _in_file:
    raise RuntimeError(f"remove {', '.join(_in_file)} from {ENV_FILE.name}; use AWS_PROFILE "
                       "with `aws sso login` or `aws login` instead")

_from_shell = {k for k in ("AWS_PROFILE", "AWS_REGION", *DEFAULT_MODELS) if os.environ.get(k)}
# override=False: a variable already exported in the shell wins over the file.
load_dotenv(ENV_FILE, override=False)
# Must be set before litellm is imported, or it fetches the price table from GitHub.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("AWS_REGION", "us-west-2")

LIVE = os.environ.get("LIVE") == "1"
FAST, SMART, ALT = (os.environ.get(k) or v for k, v in DEFAULT_MODELS.items())
MODELS = [FAST, SMART, ALT]


def mock(text):
    """Return completion kwargs that fake the reply unless LIVE=1."""
    return {} if LIVE else {"mock_response": text}


def _source(key):
    return "shell" if key in _from_shell else ".env.local"


def status():
    """Print the mode, region and models; never a credential, profile name or account ID."""
    print(f"env file    : {ENV_FILE.name} ({'found' if ENV_FILE.exists() else 'not found'})")
    print(f"mode        : {'LIVE (real Bedrock calls, real cost)' if LIVE else 'offline (mock responses)'}")
    # Never print the profile name: SSO profile names often embed the AWS account ID.
    profile_state = f"set (from {_source('AWS_PROFILE')})" if os.environ.get("AWS_PROFILE") else "not set (default AWS credential chain)"
    print(f"AWS_PROFILE : {profile_state}")
    print(f"AWS_REGION  : {os.environ['AWS_REGION']}")
    for key, default in DEFAULT_MODELS.items():
        value = os.environ.get(key)
        print(f"{key:11} : {value or default}{'' if value else ' (default)'}")
    if any(os.environ.get(k) for k in FORBIDDEN):
        print("\nwarning: AWS access keys are exported in your shell and will be used; "
              "prefer `unset` them and use AWS_PROFILE")
