"""
Ningoshi Fisher - Minimalist Desktop Video Downloader
Auto-downloads yt-dlp.exe and ffmpeg.exe if missing, then launches GUI.
"""

import os
import sys
import json
import zipfile
import threading
import subprocess
import urllib.request
from pathlib import Path

# ── Third-party imports (installed automatically if absent) ──────────────────
def _ensure_package(package: str, import_name: str | None = None):
    import importlib
    name = import_name or package
    try:
        importlib.import_module(name)
    except ModuleNotFoundError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet"])

_ensure_package("customtkinter")

import customtkinter as ctk  # noqa: E402  (installed above if needed)

# ── Constants ────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
YTDLP_EXE   = SCRIPT_DIR / "yt-dlp.exe"
FFMPEG_EXE  = SCRIPT_DIR / "ffmpeg.exe"

# ── Change 2: Save to ~/Downloads/Ningoshi Fisher ────────────────────────────
DOWNLOAD_DIR = Path.home() / "Downloads" / "Ningoshi Fisher"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

BG          = "#1a1a1a"
SURFACE     = "#242424"
CYAN        = "#00f2ff"
CYAN_DIM    = "#009fb5"
TEXT        = "#e8e8e8"
SUBTEXT     = "#888888"
FONT_MAIN   = ("Segoe UI", 13)
FONT_TITLE  = ("Segoe UI Semibold", 22)
FONT_SMALL  = ("Segoe UI", 11)

# ── Binary auto-downloader ───────────────────────────────────────────────────
def _gh_latest_asset(repo: str, name_contains: str) -> str:
    """Return the browser_download_url for the first asset whose name contains `name_contains`."""
    api = f"https://api.github.com/repos/{repo}/releases/latest"
    with urllib.request.urlopen(api, timeout=20) as r:
        data = json.loads(r.read())
    for asset in data["assets"]:
        if name_contains.lower() in asset["name"].lower():
            return asset["browser_download_url"]
    raise RuntimeError(f"No asset matching '{name_contains}' in {repo}")


def _download_file(url: str, dest: Path, label_cb=None):
    if label_cb:
        label_cb(f"Downloading {dest.name}…")
    urllib.request.urlretrieve(url, dest)


def ensure_binaries(label_cb=None):
    """Download yt-dlp.exe and ffmpeg.exe (Windows) if not present, then auto-update yt-dlp."""

    # ── yt-dlp ───────────────────────────────────────────────────────────────
    if not YTDLP_EXE.exists():
        url = _gh_latest_asset("yt-dlp/yt-dlp", "yt-dlp.exe")
        _download_file(url, YTDLP_EXE, label_cb)

    # ── Change 3: Auto-update yt-dlp so it stays current with YouTube ────────
    if label_cb:
        label_cb("Updating yt-dlp…")
    subprocess.run(
        [str(YTDLP_EXE), "-U"],
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )

    # ── ffmpeg ───────────────────────────────────────────────────────────────
    if not FFMPEG_EXE.exists():
        if label_cb:
            label_cb("Fetching ffmpeg release info…")
        # Use the BtbN ffmpeg-builds repo (pre-built Windows essentials)
        url = _gh_latest_asset(
            "BtbN/FFmpeg-Builds",
            "ffmpeg-master-latest-win64-gpl.zip"
        )
        zip_path = SCRIPT_DIR / "_ffmpeg_tmp.zip"
        _download_file(url, zip_path, label_cb)
        if label_cb:
            label_cb("Extracting ffmpeg…")
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                if member.endswith("ffmpeg.exe") and "/bin/" in member:
                    with zf.open(member) as src, open(FFMPEG_EXE, "wb") as dst:
                        dst.write(src.read())
                    break
        zip_path.unlink(missing_ok=True)


# ── Download logic ───────────────────────────────────────────────────────────
def run_download(url: str, audio_only: bool, status_cb, progress_cb, done_cb):
    """
    Run yt-dlp in a subprocess, parse progress output,
    and call the callbacks on the main thread via `after`.
    """
    # ── Change 2: Output goes to ~/Downloads/Ningoshi Fisher ─────────────────
    output_template = str(DOWNLOAD_DIR / "%(title)s.%(ext)s")

    # ── Build cmd: shared base, then branch on audio_only ────────────────────
    cmd = [
        str(YTDLP_EXE),

        "--ffmpeg-location", str(FFMPEG_EXE),

        # Modern YouTube anti-bot fix
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",

        # 8 parallel fragment threads — faster downloads
        "-N", "8",

        # Embed title, uploader, and other info
        "--embed-metadata",

        # Embed thumbnail so it shows in Explorer / media players
        "--embed-thumbnail",

        "--newline",
        "--progress",

        "-o", output_template,
    ]

    if audio_only:
        # Extract audio, convert to highest-quality MP3
        cmd += [
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
        ]
    else:
        # Best video + best audio, any codec (AV1/VP9/4K/8K compatible)
        cmd += [
            "-f", "bv*+ba/b",
            "--merge-output-format", "mp4",
        ]

    cmd.append(url)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

        for line in proc.stdout:
            line = line.strip()
            if "[download]" in line and "%" in line:
                status_cb("Downloading…")
                # Extract percentage
                try:
                    pct_str = line.split("%")[0].split()[-1]
                    pct = float(pct_str)
                    progress_cb(pct / 100)
                except (ValueError, IndexError):
                    pass
            elif "[Merger]" in line or "Merging" in line or "ffmpeg" in line.lower():
                status_cb("Merging…")
                progress_cb(0.97)
            elif "ERROR" in line:
                done_cb(f"Error: {line}")
                return

        proc.wait()
        if proc.returncode == 0:
            progress_cb(1.0)
            kind = "MP3" if audio_only else "MP4"
            done_cb(f"✓  {kind} saved to Downloads/Ningoshi Fisher")
        else:
            done_cb("Download failed. Check URL.")
    except Exception as e:
        done_cb(f"Error: {e}")


# ── Splash / setup window ────────────────────────────────────────────────────
class SetupWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Ningoshi Fisher — Setup")
        self.geometry("420x200")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self._center()

        ctk.CTkLabel(self, text="Ningoshi Fisher", font=FONT_TITLE, text_color=CYAN).pack(pady=(28, 4))
        self.status = ctk.CTkLabel(self, text="Checking dependencies…", font=FONT_SMALL, text_color=SUBTEXT)
        self.status.pack()
        self.bar = ctk.CTkProgressBar(self, width=340, height=6,
                                       fg_color=SURFACE, progress_color=CYAN)
        self.bar.set(0)
        self.bar.pack(pady=16)

        threading.Thread(target=self._setup, daemon=True).start()

    def _center(self):
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = 420, 200
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def _set_status(self, msg: str):
        self.after(0, lambda: self.status.configure(text=msg))

    def _setup(self):
        try:
            self._set_status("Checking for yt-dlp and ffmpeg…")
            self.after(0, lambda: self.bar.set(0.1))
            ensure_binaries(self._set_status)
            self.after(0, lambda: self.bar.set(1.0))
            self._set_status("Ready!")
            self.after(600, self._launch_main)
        except Exception as e:
            self._set_status(f"Setup failed: {e}")

    def _launch_main(self):
        self.destroy()
        app = MainWindow()
        app.mainloop()


# ── Main application window ──────────────────────────────────────────────────
class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Ningoshi Fisher")
        self.geometry("560x380")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self._center()
        self._build_ui()

    def _center(self):
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = 560, 380
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        # Title row
        title_frame = ctk.CTkFrame(self, fg_color="transparent")
        title_frame.pack(pady=(36, 0))

        ctk.CTkLabel(
            title_frame, text="⬡  Ningoshi Fisher",
            font=FONT_TITLE, text_color=CYAN
        ).pack()
        ctk.CTkLabel(
            title_frame, text="drop a link. reel it in.",
            font=FONT_SMALL, text_color=SUBTEXT
        ).pack(pady=(2, 0))

        # URL entry
        entry_frame = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=12)
        entry_frame.pack(fill="x", padx=50, pady=28)

        self.url_entry = ctk.CTkEntry(
            entry_frame,
            placeholder_text="Paste video URL here…",
            font=FONT_MAIN,
            text_color=TEXT,
            placeholder_text_color=SUBTEXT,
            fg_color="transparent",
            border_width=0,
            height=44,
        )
        self.url_entry.pack(fill="x", padx=14)

        # Audio-only mode toggle
        self.audio_only = ctk.BooleanVar(value=False)

        self.audio_checkbox = ctk.CTkCheckBox(
            self,
            text="Audio Only (MP3)",
            variable=self.audio_only,
            font=FONT_SMALL,
            text_color=TEXT,
            fg_color=CYAN,
            hover_color=CYAN_DIM,
            checkmark_color=BG,
        )
        self.audio_checkbox.pack(pady=(0, 12))

        # Fish button
        self.fish_btn = ctk.CTkButton(
            self,
            text="  Fish  🎣",
            font=("Segoe UI Semibold", 14),
            fg_color=CYAN,
            text_color=BG,
            hover_color=CYAN_DIM,
            corner_radius=10,
            height=42,
            command=self._start_download,
        )
        self.fish_btn.pack(padx=50, fill="x")

        # Progress bar
        self.progress_bar = ctk.CTkProgressBar(
            self, width=460, height=5,
            fg_color=SURFACE, progress_color=CYAN,
            corner_radius=4,
        )
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=(22, 6))

        # Status label
        self.status_label = ctk.CTkLabel(
            self, text="Ready to fish.", font=FONT_SMALL, text_color=SUBTEXT
        )
        self.status_label.pack()

    # ── Download orchestration ────────────────────────────────────────────────
    def _start_download(self):
        url = self.url_entry.get().strip()
        if not url:
            self._set_status("Please enter a URL first.")
            return

        self.fish_btn.configure(state="disabled", text="Fishing…")
        self.progress_bar.set(0)
        self._set_status("Starting…")

        threading.Thread(
            target=run_download,
            args=(
                url,
                self.audio_only.get(),
                self._set_status,
                self._set_progress,
                self._on_done,
            ),
            daemon=True,
        ).start()

    def _set_status(self, msg: str):
        self.after(0, lambda: self.status_label.configure(text=msg))

    def _set_progress(self, value: float):
        self.after(0, lambda: self.progress_bar.set(max(0.0, min(1.0, value))))

    def _on_done(self, msg: str):
        self.after(0, lambda: self._finish(msg))

    def _finish(self, msg: str):
        self.status_label.configure(text=msg, text_color=CYAN if "✓" in msg else "#ff4f4f")
        self.fish_btn.configure(state="normal", text="  Fish  🎣")


# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    app = SetupWindow()
    app.mainloop()