"""一键部署：打包本地代码 → SFTP 上传 → 服务器解包 → 重建 api → 验证。

- 后端：backend/app + alembic + tests + requirements.txt + Dockerfile + .env.example
  （排除 .venv/__pycache__/.env/.*.pyc）
- 前端：frontend/dist 全量（nginx 容器挂载此目录）
- 服务器上的 docker-compose.yml / nginx.conf / .env / backup.sh / scripts/ops
  一律不动（用户自维护）。

凭据走环境变量：SSH_HOST / SSH_USER / SSH_PASS
"""

import io
import os
import posixpath
import sys
import tarfile

import paramiko

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from remote import connect, run  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _backend_tar() -> bytes:
    buf = io.BytesIO()
    exclude = {".venv", "__pycache__", ".env", ".pytest_cache", ".ruff_cache"}
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for rel in ("app", "alembic", "tests", "requirements.txt", "Dockerfile", ".env.example"):
            src = os.path.join(ROOT, "backend", rel)
            if not os.path.exists(src):
                continue
            tf.add(src, arcname=f"backend/{rel}", recursive=True, filter=lambda i: None if os.path.basename(i.name) in exclude else i)
    return buf.getvalue()


def _dist_tar() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(os.path.join(ROOT, "frontend", "dist"), arcname="frontend/dist", recursive=True)
    return buf.getvalue()


def upload_sftp(client, data: bytes, remote: str):
    sftp = client.open_sftp()
    try:
        with sftp.open(remote, "wb") as f:
            f.write(data)
    finally:
        sftp.close()
    print(f"uploaded {remote} ({len(data)} bytes)", flush=True)


def main():
    host = os.environ.get("SSH_HOST", "43.156.52.101")
    user = os.environ.get("SSH_USER", "root")
    pwd = os.environ.get("SSH_PASS", "")
    client = connect()

    backend_tar = _backend_tar()
    dist_tar = _dist_tar()

    try:
        upload_sftp(client, backend_tar, "/tmp/vnss-backend.tar.gz")
        upload_sftp(client, dist_tar, "/tmp/vnss-dist.tar.gz")

        run(client, "cd /opt/vn-script-studio && tar -xzf /tmp/vnss-backend.tar.gz && echo backend-extracted")
        run(client, "cd /opt/vn-script-studio && mkdir -p frontend/dist && tar -xzf /tmp/vnss-dist.tar.gz --strip-components=1 -C frontend/dist && echo dist-extracted")
        run(client, "rm -f /tmp/vnss-backend.tar.gz /tmp/vnss-dist.tar.gz")

        # 后端有改动 → 重建 api 镜像并重启（不影响 pg/redis/web）
        run(client, "cd /opt/vn-script-studio && docker compose build api 2>&1 | tail -5", timeout=600)
        run(client, "cd /opt/vn-script-studio && docker compose up -d api 2>&1 | tail -5", timeout=300)
        run(client, "sleep 4 && docker ps --filter name=vnss-api --format '{{.Status}}'")

        # 验证
        run(client, "curl -s -o /dev/null -w 'local %{http_code}\\n' http://localhost:8000/health", timeout=60)
        run(client, "curl -s -o /dev/null -w 'web %{http_code}\\n' http://localhost/", timeout=60)
    finally:
        client.close()
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
