"""Small GitHub REST client for the review queue (drafts are Issues)."""
from __future__ import annotations

import requests

from .config import env

API = "https://api.github.com"

LABELS = {
    "draft": ("FCD116", "مسودة خبر بانتظار المراجعة"),
    "approved": ("1E8E3E", "موافقة: انشر على X"),
    "published": ("1D3D8F", "تم النشر على X"),
    "publish-failed": ("D93025", "فشل النشر، راجع التعليق"),
    "official": ("0B57D0", "من جهة رسمية"),
    "report": ("9AA0A6", "تقرير غير مؤكد"),
    "x-account": ("000000", "من حساب على X"),
}


class GitHub:
    def __init__(self) -> None:
        self.token = env("GITHUB_TOKEN")
        self.repo = env("GITHUB_REPOSITORY")
        if not (self.token and self.repo):
            raise RuntimeError("GITHUB_TOKEN و GITHUB_REPOSITORY مطلوبة")
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    @staticmethod
    def available() -> bool:
        return bool(env("GITHUB_TOKEN") and env("GITHUB_REPOSITORY"))

    def _url(self, path: str) -> str:
        return f"{API}/repos/{self.repo}{path}"

    def _check(self, r: requests.Response) -> dict:
        if r.status_code >= 400:
            raise RuntimeError(f"GitHub {r.status_code}: {r.text[:300]}")
        return r.json() if r.text else {}

    def ensure_labels(self, extra: dict[str, tuple[str, str]] | None = None) -> None:
        wanted = {**LABELS, **(extra or {})}
        existing = {l["name"] for l in self._check(self.s.get(self._url("/labels"), params={"per_page": 100}))}
        for name, (color, desc) in wanted.items():
            if name not in existing:
                self.s.post(self._url("/labels"), json={"name": name, "color": color, "description": desc})

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict:
        return self._check(self.s.post(self._url("/issues"), json={"title": title, "body": body, "labels": labels}))

    def get_issue(self, number: int) -> dict:
        return self._check(self.s.get(self._url(f"/issues/{number}")))

    def comment(self, number: int, body: str) -> None:
        self._check(self.s.post(self._url(f"/issues/{number}/comments"), json={"body": body}))

    def add_labels(self, number: int, labels: list[str]) -> None:
        self._check(self.s.post(self._url(f"/issues/{number}/labels"), json={"labels": labels}))

    def remove_label(self, number: int, label: str) -> None:
        self.s.delete(self._url(f"/issues/{number}/labels/{label}"))

    def close(self, number: int, reason: str = "completed") -> None:
        self._check(self.s.patch(self._url(f"/issues/{number}"), json={"state": "closed", "state_reason": reason}))
