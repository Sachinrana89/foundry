from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse

import msal
import requests

from app.agents import AGENTS
from app.config import DOCUMENT_DIR, settings
from .extractors import SUPPORTED

GRAPH = "https://graph.microsoft.com/v1.0"


class SharePointError(RuntimeError):
    pass


class SharePointClient:
    """Read-only SharePoint Online connector using Microsoft Graph app-only auth.

    The app is intentionally read-only. Files are mirrored into the local
    document cache only so the existing FAISS/RAG pipeline can index them.
    SharePoint remains the source of truth for SharePoint-sourced documents;
    local browser uploads are stored separately and are preserved across syncs.
    """

    def __init__(self):
        self.enabled = bool(settings.sharepoint_enabled)
        self.tenant_id = settings.sharepoint_tenant_id.strip()
        self.client_id = settings.sharepoint_client_id.strip()
        self.client_secret = settings.sharepoint_client_secret.strip()
        self.site_url = settings.sharepoint_site_url.strip().rstrip("/")
        self.drive_name = settings.sharepoint_drive_name.strip() or "Documents"
        self.agent_paths = settings.sharepoint_agent_paths
        self._token = None

    def configured(self) -> bool:
        return self.enabled and all([
            self.tenant_id,
            self.client_id,
            self.client_secret,
            self.site_url,
        ])

    def status(self):
        return {
            "enabled": self.enabled,
            "configured": self.configured(),
            "site_url": self.site_url,
            "drive_name": self.drive_name,
            "agent_paths": self.agent_paths,
            "message": (
                "SharePoint is configured."
                if self.configured()
                else "Configure SHAREPOINT_TENANT_ID, CLIENT_ID, CLIENT_SECRET and SITE_URL."
            ),
        }

    def _access_token(self) -> str:
        if self._token:
            return self._token
        if not self.configured():
            raise SharePointError("SharePoint is not configured.")
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        app = msal.ConfidentialClientApplication(
            self.client_id,
            authority=authority,
            client_credential=self.client_secret,
        )
        result = app.acquire_token_for_client(scopes=[f"{GRAPH}/.default"])
        token = result.get("access_token")
        if not token:
            detail = result.get("error_description") or result.get("error") or "unknown token error"
            raise SharePointError(f"Microsoft Entra token acquisition failed: {detail}")
        self._token = token
        return token

    def _request(self, method: str, url: str, **kwargs):
        headers = kwargs.pop("headers", {})
        headers = {**headers, "Authorization": f"Bearer {self._access_token()}"}
        response = requests.request(method, url, headers=headers, timeout=60, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message") or response.text
            except Exception:
                detail = response.text
            raise SharePointError(f"Microsoft Graph {response.status_code}: {detail}")
        return response

    def _site_id(self) -> str:
        parsed = urlparse(self.site_url)
        if not parsed.hostname:
            raise SharePointError("SHAREPOINT_SITE_URL is invalid.")
        path = parsed.path.rstrip("/") or "/"
        url = f"{GRAPH}/sites/{parsed.hostname}:{path}"
        return self._request("GET", url).json()["id"]

    def _drive_id(self, site_id: str) -> str:
        url = f"{GRAPH}/sites/{site_id}/drives"
        data = self._request("GET", url).json().get("value", [])
        for drive in data:
            if drive.get("name", "").lower() == self.drive_name.lower():
                return drive["id"]
        available = ", ".join(d.get("name", "") for d in data)
        raise SharePointError(
            f"Document library '{self.drive_name}' was not found. Available libraries: {available or 'none'}"
        )

    def _folder_item(self, drive_id: str, folder_path: str):
        folder_path = folder_path.strip("/")
        if not folder_path:
            return self._request("GET", f"{GRAPH}/drives/{drive_id}/root").json()
        encoded = requests.utils.quote(folder_path, safe="/")
        return self._request("GET", f"{GRAPH}/drives/{drive_id}/root:/{encoded}").json()

    def _children(self, drive_id: str, item_id: str):
        url = f"{GRAPH}/drives/{drive_id}/items/{item_id}/children"
        while url:
            data = self._request("GET", url).json()
            yield from data.get("value", [])
            url = data.get("@odata.nextLink")

    def _walk(self, drive_id: str, item_id: str, relative=""):
        for item in self._children(drive_id, item_id):
            name = item.get("name", "")
            rel = f"{relative}/{name}".strip("/")
            if "folder" in item:
                yield from self._walk(drive_id, item["id"], rel)
            elif "file" in item:
                yield item, rel

    def _download(self, drive_id: str, item_id: str, destination: Path):
        destination.parent.mkdir(parents=True, exist_ok=True)
        url = f"{GRAPH}/drives/{drive_id}/items/{item_id}/content"
        response = self._request("GET", url, allow_redirects=True)
        destination.write_bytes(response.content)

    def sync_agent(self, agent_id: str):
        if agent_id not in AGENTS:
            raise SharePointError(f"Unknown agent: {agent_id}")
        if not self.configured():
            raise SharePointError("SharePoint is not configured.")

        site_id = self._site_id()
        drive_id = self._drive_id(site_id)
        folder_path = self.agent_paths.get(agent_id, "")
        root = self._folder_item(drive_id, folder_path)
        target = DOCUMENT_DIR / agent_id
        target.mkdir(parents=True, exist_ok=True)
        sharepoint_target = target / "_sharepoint"
        sharepoint_target.mkdir(parents=True, exist_ok=True)

        # SharePoint is the source of truth for the SharePoint mirror only.
        # Local browser uploads live directly under the agent directory and are
        # intentionally preserved when SharePoint is synchronized.
        for child in sharepoint_target.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

        metadata = {}
        downloaded = 0
        skipped = 0
        for item, relative in self._walk(drive_id, root["id"]):
            suffix = Path(relative).suffix.lower()
            if suffix not in SUPPORTED:
                skipped += 1
                continue
            safe_relative = Path(*[part.replace("..", "_") for part in Path(relative).parts])
            destination = sharepoint_target / safe_relative
            self._download(drive_id, item["id"], destination)
            downloaded += 1
            metadata[destination.relative_to(target).as_posix()] = {
                "name": item.get("name", destination.name),
                "relative_path": relative,
                "web_url": item.get("webUrl", ""),
                "last_modified": item.get("lastModifiedDateTime", ""),
                "size": int(item.get("size", destination.stat().st_size)),
                "drive_id": drive_id,
                "item_id": item["id"],
            }

        metadata_path = target / ".sharepoint.json"
        metadata_path.write_text(json.dumps({
            "site_url": self.site_url,
            "drive_name": self.drive_name,
            "folder_path": folder_path,
            "files": metadata,
        }, indent=2), encoding="utf-8")

        return {
            "agent_id": agent_id,
            "downloaded": downloaded,
            "skipped": skipped,
            "site_url": self.site_url,
            "drive_name": self.drive_name,
            "folder_path": folder_path,
        }


sharepoint = SharePointClient()
