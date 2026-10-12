"""Small Google Drive upload implementation for conduit."""

from pathlib import Path
from typing import Callable


SCOPES = ["https://www.googleapis.com/auth/drive"]


def _media_file_upload(path: Path):
    from googleapiclient.http import MediaFileUpload

    return MediaFileUpload(str(path))


def build_drive_service(config: dict[str, str]):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token_path = Path(config["token_file"])
    credentials = None
    if token_path.is_file():
        credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                config["credentials_file"], SCOPES
            )
            credentials = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(credentials.to_json(), encoding="utf-8")
    return build("drive", "v3", credentials=credentials)


def _query_name(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def upload_files(
    config: dict[str, str],
    job_id: str,
    files: list[tuple[Path, str]],
    service=None,
    on_file: Callable[[str], None] | None = None,
) -> str | None:
    service = service or build_drive_service(config)
    parent_id = config["jobs_folder_id"]
    query = (
        f"'{parent_id}' in parents and name = '{_query_name(job_id)}' "
        "and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    existing = service.files().list(q=query, pageSize=1, fields="files(id)").execute()
    if existing.get("files"):
        raise ValueError("job folder already exists")

    folder = service.files().create(
        body={
            "name": job_id,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        },
        fields="id,webViewLink",
    ).execute()
    folder_id = folder["id"]
    for local_path, relative_path in files:
        try:
            if on_file:
                on_file(relative_path)
            service.files().create(
                body={"name": relative_path, "parents": [folder_id]},
                media_body=_media_file_upload(local_path),
                fields="id",
            ).execute()
        except Exception as exc:
            raise RuntimeError(f"{relative_path}: {exc}") from exc
    if folder.get("webViewLink"):
        return folder["webViewLink"]
    metadata = service.files().get(fileId=folder_id, fields="webViewLink").execute()
    return metadata.get("webViewLink")


def download_inputs(config, inputs, destination, service=None):
    """Check every Drive file before writing any media, then download in order."""
    from googleapiclient.http import MediaIoBaseDownload

    service = service or build_drive_service(config)
    checked = []
    total = 0
    for item in inputs:
        name = item["name"]
        try:
            meta = service.files().get(
                fileId=item["file_id"], fields="id,mimeType,size,trashed"
            ).execute()
            mime = meta.get("mimeType", "")
            if (meta.get("trashed") or not mime or
                    mime.startswith("application/vnd.google-apps.")):
                raise ValueError("not an accessible binary file")
            size = int(meta["size"])
            if size < 0 or size > 10 * 1024 * 1024:
                raise ValueError("file exceeds 10 MiB")
            total += size
            if total > 25 * 1024 * 1024:
                raise ValueError("inputs exceed 25 MiB")
            checked.append(item)
        except Exception as exc:
            raise ValueError(f"{name}: {exc}") from exc

    root = destination.resolve()
    root.mkdir(parents=True, exist_ok=False)
    actual_total = 0
    for item in checked:
        name = item["name"]
        try:
            path = root.joinpath(*name.split("/"))
            if path.exists() or path.is_symlink():
                raise ValueError("destination exists")
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.parent.resolve().is_relative_to(root):
                raise ValueError("destination escapes workspace")
            request = service.files().get_media(fileId=item["file_id"])
            with path.open("xb") as output:
                downloader = MediaIoBaseDownload(output, request, chunksize=1024 * 1024)
                done = False
                while not done:
                    _, done = downloader.next_chunk(num_retries=0)
                    size = output.tell()
                    if size > 10 * 1024 * 1024 or actual_total + size > 25 * 1024 * 1024:
                        raise ValueError("download exceeds size limit")
                actual_total += output.tell()
        except Exception as exc:
            raise ValueError(f"{name}: {exc}") from exc
    return [root.joinpath(*item["name"].split("/")) for item in checked]
