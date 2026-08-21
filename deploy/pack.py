"""本地打包部署产物：deploy/artifacts/backend.tar.gz + dist.tar.gz"""

import os
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artifacts")
os.makedirs(OUT, exist_ok=True)


def _backend_tar(path: str):
    exclude = {".venv", "__pycache__", ".env", ".pytest_cache", ".ruff_cache"}
    with tarfile.open(path, "w:gz") as tf:
        for rel in ("app", "alembic", "tests", "requirements.txt", "Dockerfile", ".env.example"):
            src = os.path.join(ROOT, "backend", rel)
            if not os.path.exists(src):
                continue
            tf.add(
                src,
                arcname=f"backend/{rel}",
                recursive=True,
                filter=lambda i: None if os.path.basename(i.name) in exclude else i,
            )


def _dist_tar(path: str):
    with tarfile.open(path, "w:gz") as tf:
        tf.add(os.path.join(ROOT, "frontend", "dist"), arcname="frontend/dist", recursive=True)


if __name__ == "__main__":
    b = os.path.join(OUT, "backend.tar.gz")
    d = os.path.join(OUT, "dist.tar.gz")
    _backend_tar(b)
    _dist_tar(d)
    print(f"backend={os.path.getsize(b)} dist={os.path.getsize(d)}")
