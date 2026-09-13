#!/usr/bin/env python3
"""Register a local video or download a user-authorized public video URL."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from media_tools import resolve_binary


VIDEO_SUFFIXES = {
    ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".wmv", ".3gp", ".mpeg", ".mpg"
}
CHUNK_SIZE = 1024 * 1024


class AcquireError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


def redacted_url(raw_url: str) -> str:
    parts = urlsplit(raw_url)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def safe_filename(value: str, fallback: str = "video") -> str:
    value = unquote(value).strip().replace("\x00", "")
    value = re.sub(r"[^\w.\-]+", "-", value, flags=re.UNICODE)
    value = value.strip("-._")[:120]
    return value or fallback


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_destination(path: Path, force: bool) -> None:
    if path.exists() and not force:
        raise AcquireError(f"输出文件已存在：{path}；请换目录或使用 --force", 4)
    path.parent.mkdir(parents=True, exist_ok=True)


def register_local(source: str, output_dir: Path, copy_local: bool, force: bool) -> tuple[Path, str]:
    path = Path(source).expanduser()
    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise AcquireError(f"本地文件不可读：{exc}", 2) from exc
    if not path.is_file():
        raise AcquireError(f"输入不是文件：{path}", 2)
    if copy_local:
        name = safe_filename(path.stem, "local-video") + path.suffix.lower()
        destination = output_dir / name
        ensure_destination(destination, force)
        shutil.copy2(path, destination)
        return destination.resolve(), "local-copy"
    return path, "local-reference"


def choose_ytdlp_result(output_dir: Path, stdout: str) -> Path | None:
    for line in reversed(stdout.splitlines()):
        candidate = Path(line.strip()).expanduser()
        if candidate.is_file():
            return candidate.resolve()
        relative = output_dir / line.strip()
        if relative.is_file():
            return relative.resolve()
    candidates = [
        path for path in output_dir.iterdir()
        if path.is_file() and path.name != "source_manifest.json" and not path.name.endswith(".part")
    ]
    return max(candidates, key=lambda item: item.stat().st_mtime).resolve() if candidates else None


def download_with_ytdlp(
    source: str,
    output_dir: Path,
    ytdlp: str,
    max_bytes: int,
    force: bool,
) -> Path:
    template = str(output_dir / "%(title).100s-[%(id)s].%(ext)s")
    command = [
        ytdlp,
        "--no-playlist",
        "--restrict-filenames",
        "--max-filesize",
        str(max_bytes),
        "--print",
        "after_move:filepath",
        "-o",
        template,
    ]
    ffmpeg = resolve_binary("ffmpeg", "FFMPEG_BIN")
    if ffmpeg:
        command.extend([
            "--format", "bv*+ba/b",
            "--merge-output-format", "mp4",
            "--ffmpeg-location", str(Path(ffmpeg).parent),
        ])
    else:
        command.extend(["--format", "b[ext=mp4]/b"])
    command.append("--force-overwrites" if force else "--no-overwrites")
    command.append(source)
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip().splitlines()
        detail = message[-1] if message else f"exit {result.returncode}"
        detail = detail.replace(source, redacted_url(source))
        raise AcquireError(f"yt-dlp 下载失败：{detail}", 3)
    path = choose_ytdlp_result(output_dir, result.stdout)
    if not path:
        raise AcquireError("yt-dlp 未返回可用的视频文件", 3)
    if path.stat().st_size > max_bytes:
        raise AcquireError("下载文件超过 --max-bytes 限制", 3)
    return path


def filename_from_headers(headers, final_url: str, content_type: str) -> str:
    disposition = headers.get("Content-Disposition", "")
    match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", disposition, re.IGNORECASE)
    if match:
        name = safe_filename(match.group(1), "downloaded-video")
    else:
        name = safe_filename(Path(urlsplit(final_url).path).name, "downloaded-video")
    suffix = Path(name).suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip()) or ".mp4"
        if guessed not in VIDEO_SUFFIXES:
            guessed = ".mp4"
        name = safe_filename(Path(name).stem, "downloaded-video") + guessed
    return name


def download_direct(
    source: str,
    output_dir: Path,
    max_bytes: int,
    timeout: float,
    force: bool,
) -> tuple[Path, str]:
    request = Request(source, headers={"User-Agent": "Mozilla/5.0 viral-video-skill/1.0"})
    try:
        response = urlopen(request, timeout=timeout)
    except Exception as exc:
        raise AcquireError(f"直接下载失败：{exc}", 3) from exc
    try:
        content_type = response.headers.get_content_type().lower()
        final_url = response.geturl()
        final_suffix = Path(urlsplit(final_url).path).suffix.lower()
        if not (
            content_type.startswith("video/")
            or content_type == "application/octet-stream"
            or final_suffix in VIDEO_SUFFIXES
        ):
            raise AcquireError(
                f"链接返回 {content_type}，不像直接视频；请安装 yt-dlp 或提供本地文件",
                3,
            )
        length = response.headers.get("Content-Length")
        if length and int(length) > max_bytes:
            raise AcquireError("远端文件超过 --max-bytes 限制", 3)
        destination = output_dir / filename_from_headers(response.headers, final_url, content_type)
        ensure_destination(destination, force)
        temp_handle = tempfile.NamedTemporaryFile(
            prefix=".download-", suffix=".part", dir=output_dir, delete=False
        )
        temp_path = Path(temp_handle.name)
        total = 0
        try:
            with temp_handle:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise AcquireError("下载内容超过 --max-bytes 限制", 3)
                    temp_handle.write(chunk)
            os.replace(temp_path, destination)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return destination.resolve(), redacted_url(final_url)
    finally:
        response.close()


def write_manifest(
    output_dir: Path,
    source_kind: str,
    source_display: str,
    method: str,
    video_path: Path,
    force: bool,
) -> Path:
    manifest = {
        "schema_version": "1.0",
        "source_kind": source_kind,
        "source": source_display,
        "acquisition_method": method,
        "video_path": str(video_path.resolve()),
        "sha256": sha256_file(video_path),
        "size_bytes": video_path.stat().st_size,
    }
    manifest_path = output_dir / "source_manifest.json"
    ensure_destination(manifest_path, force)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire or register a benchmark video")
    parser.add_argument("source", help="local file path or HTTP(S) URL")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--copy-local", action="store_true", help="copy a local file into output-dir")
    parser.add_argument("--direct-only", action="store_true", help="skip yt-dlp for URLs")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-bytes", type=int, default=4 * 1024 * 1024 * 1024)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    is_url = re.match(r"^https?://", args.source, re.IGNORECASE) is not None
    try:
        if args.timeout <= 0 or args.max_bytes <= 0:
            raise AcquireError("--timeout 与 --max-bytes 必须为正数", 1)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = args.output_dir / "source_manifest.json"
        if manifest_path.exists() and not args.force:
            raise AcquireError(
                f"输出文件已存在：{manifest_path}；请换目录或使用 --force",
                4,
            )
        if not is_url:
            video_path, method = register_local(
                args.source, args.output_dir, args.copy_local, args.force
            )
            source_kind = "local"
            source_display = str(Path(args.source).expanduser())
        else:
            source_kind = "url"
            source_display = redacted_url(args.source)
            ytdlp = None if args.direct_only else resolve_binary("yt-dlp", "YTDLP_BIN")
            ytdlp_error = None
            if ytdlp:
                try:
                    video_path = download_with_ytdlp(
                        args.source, args.output_dir, ytdlp, args.max_bytes, args.force
                    )
                    method = "yt-dlp"
                except AcquireError as exc:
                    ytdlp_error = str(exc)
                    video_path = None
            else:
                video_path = None
            if video_path is None:
                try:
                    video_path, final_display = download_direct(
                        args.source,
                        args.output_dir,
                        args.max_bytes,
                        args.timeout,
                        args.force,
                    )
                    method = "direct-http"
                    source_display = final_display
                except AcquireError as direct_error:
                    prefix = f"{ytdlp_error}; " if ytdlp_error else ""
                    detail = str(direct_error).replace(args.source, redacted_url(args.source))
                    raise AcquireError(prefix + detail, direct_error.exit_code)

        manifest_path = write_manifest(
            args.output_dir, source_kind, source_display, method, video_path, args.force
        )
    except AcquireError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    print(str(manifest_path.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
