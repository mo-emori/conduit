import tomllib
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


def load_auth_paths() -> tuple[Path, Path]:
    with Path(__file__).with_name("config.toml").open("rb") as config_file:
        drive = tomllib.load(config_file)["drive"]
    return Path(drive["credentials_file"]), Path(drive["token_file"])


SCOPES = [
    "https://www.googleapis.com/auth/drive"
]

credentials_path, token_path = load_auth_paths()
flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)

creds = flow.run_local_server(port=0)

with token_path.open("w", encoding="utf-8") as f:
    f.write(creds.to_json())
