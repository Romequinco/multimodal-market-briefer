"""Exporta el pitch deck (pitch/pitch_briefly.html) a PDF con Chrome o Edge en modo headless.

Uso:
    python scripts/build_pitch.py                 # PDF en pitch/pitch_briefly.pdf
    python scripts/build_pitch.py --preview DIR   # además, una PNG por diapositiva en DIR (revisión)
    python scripts/build_pitch.py --demo-url URL  # además, QR de la demo en pitch/assets/qr_demo.png
                                                  # (necesita `pip install segno`; si no, se omite)

Antes de exportar extrae un fotograma del vídeo del briefing pregenerado
(data/samples/demo_briefing/video.mp4) a pitch/assets/video_frame.png para la maqueta del móvil.
Sin dependencias nuevas: usa imageio-ffmpeg (ya en requirements) y pypdfium2 (para --preview).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PITCH = ROOT / "pitch"
HTML = PITCH / "pitch_briefly.html"
PDF = PITCH / "pitch_briefly.pdf"
ASSETS = PITCH / "assets"
VIDEO = ROOT / "data" / "samples" / "demo_briefing" / "video.mp4"

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "google-chrome",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
]


def find_browser() -> str:
    for candidate in BROWSERS:
        if Path(candidate).is_file():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    sys.exit("No se encontró Chrome ni Edge. Instala uno o exporta a mano (Imprimir → Guardar como PDF).")


def extract_video_frame(seconds: float = 40.0) -> None:
    """Fotograma del vídeo 9:16 del pregenerado para la diapositiva de producto."""
    out = ASSETS / "video_frame.png"
    if not VIDEO.is_file():
        print(f"(sin vídeo en {VIDEO.relative_to(ROOT)}: la maqueta del móvil mostrará su marco)")
        return
    try:
        import imageio_ffmpeg
    except ImportError:
        print("(imageio-ffmpeg no disponible: se omite el fotograma del vídeo)")
        return
    ASSETS.mkdir(parents=True, exist_ok=True)
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", str(seconds),
           "-i", str(VIDEO), "-frames:v", "1", str(out)]
    subprocess.run(cmd, check=True)
    print(f"Fotograma del vídeo → {out.relative_to(ROOT)}")


def make_qr(url: str) -> None:
    try:
        import segno
    except ImportError:
        print("(segno no instalado: sin QR; la diapositiva de la demo muestra el marcador)")
        return
    ASSETS.mkdir(parents=True, exist_ok=True)
    out = ASSETS / "qr_demo.png"
    segno.make(url, error="m").save(str(out), scale=10, border=2, dark="#12151B", light="#FFFFFF")
    print(f"QR de la demo → {out.relative_to(ROOT)} (cambia también el texto del enlace en el HTML)")


def export_pdf(browser: str) -> None:
    with tempfile.TemporaryDirectory() as profile:
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--allow-file-access-from-files",
            f"--user-data-dir={profile}",
            "--no-pdf-header-footer",
            "--virtual-time-budget=5000",
            f"--print-to-pdf={PDF}",
            HTML.as_uri(),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
    if not PDF.is_file():
        sys.exit("El navegador no generó el PDF.")
    print(f"PDF → {PDF.relative_to(ROOT)}")


def render_preview(out_dir: Path) -> None:
    import pypdfium2 as pdfium

    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(PDF))
    for i, page in enumerate(pdf, start=1):
        w, h = page.get_size()
        page.render(scale=1.0).to_pil().save(out_dir / f"slide_{i:02d}.png")
        if i == 1:
            print(f"Tamaño de página: {w:.0f} × {h:.0f} pt")
    print(f"{len(pdf)} páginas · vistas previas en {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--preview", type=Path, help="Carpeta donde volcar una PNG por diapositiva")
    parser.add_argument("--demo-url", help="URL de la demo grabada para generar el QR")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):  # consola cp1252 de Windows: sin traceback por «→»
        sys.stdout.reconfigure(errors="replace")

    extract_video_frame()
    if args.demo_url:
        make_qr(args.demo_url)
    export_pdf(find_browser())
    if args.preview:
        render_preview(args.preview)
    else:
        import pypdfium2 as pdfium

        print(f"{len(pdfium.PdfDocument(str(PDF)))} páginas")


if __name__ == "__main__":
    main()
