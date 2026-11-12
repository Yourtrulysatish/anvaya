"""Document ingestion: PDF, DOCX, XLSX, CSV, JSON, TXT, Markdown, URLs. Validation + text extraction + chunking."""
from __future__ import annotations

import csv
import io
import ipaddress
import json
import re
import socket
from typing import Optional
from urllib.parse import urlparse

import httpx

from .config import settings

ALLOWED = {"pdf", "docx", "xlsx", "csv", "json", "txt", "md", "markdown"}
MAX_TEXT = 400_000


class IngestError(ValueError):
    pass


def safe_filename(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", (name or "upload").split("/")[-1].split("\\")[-1])[:120]
    return name or "upload"


def validate_upload(filename: str, data: bytes) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED:
        raise IngestError(f"Unsupported file type '.{ext}'. Allowed: {', '.join(sorted(ALLOWED))}")
    if len(data) == 0:
        raise IngestError("File is empty")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise IngestError(f"File exceeds the {settings.max_upload_mb} MB upload limit")
    if ext == "pdf" and not data.startswith(b"%PDF"):
        raise IngestError("File content is not a PDF")
    if ext in ("docx", "xlsx") and not data.startswith(b"PK"):
        raise IngestError(f"File content is not a valid .{ext}")
    return ext


def extract_text(ext: str, data: bytes) -> dict:
    """Returns {text, kind, meta, table?}. `table` = {columns, rows} for tabular sources (kept for analytics)."""
    meta: dict = {}
    table = None
    if ext == "pdf":
        from pypdf import PdfReader
        r = PdfReader(io.BytesIO(data))
        if r.is_encrypted:
            raise IngestError("Encrypted PDFs are not supported")
        pages = [(p.extract_text() or "") for p in r.pages[:300]]
        text = "\n\n".join(pages); meta["pages"] = len(r.pages)
    elif ext == "docx":
        import docx
        d = docx.Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs if p.text.strip()]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text.strip() for c in row.cells))
        text = "\n".join(parts)
    elif ext == "xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        lines, rows_all = [], []
        for ws in wb.worksheets[:10]:
            lines.append(f"## Sheet: {ws.title}")
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i > 20000:
                    break
                vals = ["" if v is None else str(v) for v in row]
                if any(vals):
                    lines.append(" | ".join(vals))
                    if ws is wb.worksheets[0]:
                        rows_all.append(vals)
        text = "\n".join(lines)
        if len(rows_all) > 1:
            table = {"columns": rows_all[0], "rows": rows_all[1:5001]}
    elif ext == "csv":
        s = data.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(s)))
        text = "\n".join(" | ".join(r) for r in rows[:20000])
        if len(rows) > 1:
            table = {"columns": rows[0], "rows": rows[1:5001]}
    elif ext == "json":
        obj = json.loads(data.decode("utf-8-sig", errors="replace"))
        text = json.dumps(obj, indent=1, ensure_ascii=False)
        if isinstance(obj, list) and obj and all(isinstance(o, dict) for o in obj):
            cols = sorted({k for o in obj[:500] for k in o})
            table = {"columns": cols, "rows": [[str(o.get(c, "")) for c in cols] for o in obj[:5000]]}
    else:
        text = data.decode("utf-8-sig", errors="replace")
    text = text.replace("\x00", "")[:MAX_TEXT]
    return {"text": text, "kind": ext, "meta": meta, "table": table}


def chunk_text(text: str, size: int = 5500, overlap: int = 300) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    out, i = [], 0
    while i < len(text):
        end = min(len(text), i + size)
        if end < len(text):
            cut = max(text.rfind("\n\n", i, end), text.rfind(". ", i, end))
            if cut > i + size * 0.5:
                end = cut + 1
        out.append(text[i:end].strip())
        if end >= len(text):
            break
        i = end - overlap
    return [c for c in out if c]


# ----------------------------------------------------------------- URL fetching with SSRF protection

def _is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
    return True


async def fetch_url(url: str, max_bytes: int = 2_000_000) -> dict:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise IngestError("Only http(s) URLs are supported")
    if not _is_public_host(u.hostname):
        raise IngestError("URL resolves to a non-public address and was blocked")
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"User-Agent": "ANVAYA-research/1.0"}) as c:
        cur = url
        for _ in range(4):
            pu = urlparse(cur)
            if not pu.hostname or not _is_public_host(pu.hostname):
                raise IngestError("Redirect target is not a public address")
            async with c.stream("GET", cur) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    cur = str(httpx.URL(cur).join(r.headers["location"])); continue
                if r.status_code >= 400:
                    raise IngestError(f"URL returned HTTP {r.status_code}")
                ctype = r.headers.get("content-type", "")
                buf = bytearray()
                async for part in r.aiter_bytes():
                    buf += part
                    if len(buf) > max_bytes:
                        break
                break
        else:
            raise IngestError("Too many redirects")
    if "pdf" in ctype or bytes(buf[:4]) == b"%PDF":
        return {**extract_text("pdf", bytes(buf)), "title": u.hostname + u.path}
    html = bytes(buf).decode("utf-8", errors="replace")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "svg"]):
        t.decompose()
    title = (soup.title.string or "").strip() if soup.title else u.hostname
    main = soup.find("article") or soup.find("main") or soup.body or soup
    text = re.sub(r"\n{3,}", "\n\n", main.get_text("\n", strip=True))
    return {"text": text[:MAX_TEXT], "kind": "url", "meta": {"url": url, "content_type": ctype}, "table": None, "title": title[:200]}
