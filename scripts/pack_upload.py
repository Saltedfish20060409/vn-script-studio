"""Pack VNSS sources and upload to the VPS. Auth: SSH key only.

Always wipe remote frontend/dist before extract so leftover hashed
chunks (and the PWA precache of them) cannot resurrect old UI.
"""
from __future__ import annotations

import secrets
import tarfile
import time
from pathlib import Path

import paramiko

ROOT = Path(r"D:\Projects\vn-script-studio")
DEPLOY = Path(r"C:\Users\46431\AppData\Local\Temp\vnss-deploy")
KEY = Path.home() / ".ssh" / "id_ed25519_vnss"
HOST = "43.156.52.101"
REMOTE_DIR = "/opt/vn-script-studio"
TAR_PATH = DEPLOY / "vnss-src.tar.gz"


def connect() -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c.connect(
        HOST,
        username="root",
        pkey=pkey,
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    return c


def run(c: paramiko.SSHClient, cmd: str, timeout: int = 120) -> str:
    stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if code != 0:
        raise RuntimeError(f"cmd failed ({code}): {cmd}\n{out}\n{err}")
    return out


def pack() -> None:
    dist = ROOT / "frontend" / "dist"
    if not (dist / "index.html").exists():
        raise SystemExit("frontend/dist missing — wait for npm run build")

    skip_parts = {
        "__pycache__",
        ".pytest_cache",
        ".venv",
        "node_modules",
        ".git",
        ".mypy_cache",
        ".ruff_cache",
    }

    def filter_backend(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        parts = set(Path(info.name).parts)
        if parts & skip_parts:
            return None
        if info.name.endswith(".pyc"):
            return None
        return info

    TAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TAR_PATH.exists():
        TAR_PATH.unlink()
    with tarfile.open(TAR_PATH, "w:gz") as tar:
        tar.add(ROOT / "backend" / "app", arcname="backend/app", filter=filter_backend)
        tar.add(ROOT / "backend" / "alembic", arcname="backend/alembic", filter=filter_backend)
        tar.add(ROOT / "backend" / "alembic.ini", arcname="backend/alembic.ini")
        tar.add(ROOT / "backend" / "requirements.txt", arcname="backend/requirements.txt")
        tar.add(DEPLOY / "Dockerfile", arcname="backend/Dockerfile")
        tar.add(dist, arcname="frontend/dist")
        tar.add(DEPLOY / "nginx.conf", arcname="nginx.conf")
        tar.add(DEPLOY / "docker-compose.yml", arcname="docker-compose.yml")
        ops = ROOT / "scripts" / "ops"
        if ops.is_dir():
            tar.add(ops, arcname="scripts/ops")

    print("packed", TAR_PATH, "bytes", TAR_PATH.stat().st_size)


def upload_and_start() -> None:
    pack()
    c = connect()
    try:
        run(c, f"mkdir -p {REMOTE_DIR}")
        sftp = c.open_sftp()
        remote_tar = "/tmp/vnss-src.tar.gz"
        print("uploading tar...")
        sftp.put(str(TAR_PATH), remote_tar)
        sftp.close()
        print("extracting...")
        run(
            c,
            f"mkdir -p {REMOTE_DIR} && "
            f"rm -rf {REMOTE_DIR}/frontend/dist && "
            f"tar -xzf {remote_tar} -C {REMOTE_DIR} && rm -f {remote_tar}",
        )

        check = run(c, f"test -f {REMOTE_DIR}/.env && echo YES || echo NO").strip()
        if check == "NO":
            pg = secrets.token_urlsafe(24)
            sk = secrets.token_hex(32)
            env = (
                f"POSTGRES_PASSWORD={pg}\n"
                f"DATABASE_URL=postgresql+asyncpg://vnss:{pg}@postgres:5432/vnss\n"
                f"SECRET_KEY={sk}\n"
                f"ACCESS_TOKEN_EXPIRE_MINUTES=10080\n"
                f"CORS_ORIGINS=https://studio.nexesr.top,http://studio.nexesr.top\n"
                f"DEEPSEEK_API_KEY=\n"
                f"DEEPSEEK_BASE_URL=https://api.deepseek.com\n"
                f"DEEPSEEK_MODEL=deepseek-v4-flash\n"
                f"LLM_PROVIDER=openai\n"
                f"AGENT_CRAFT_MODE=auto\n"
                f"AGENT_SELF_REVIEW=auto\n"
                f"RATE_LIMIT_ENABLED=true\n"
            )
            sftp = c.open_sftp()
            with sftp.file(f"{REMOTE_DIR}/.env", "w") as f:
                f.write(env)
            sftp.chmod(f"{REMOTE_DIR}/.env", 0o600)
            sftp.close()
            print("wrote .env")
        else:
            print(".env exists, keeping")

        run(
            c,
            f"grep -q '^REDIS_URL=' {REMOTE_DIR}/.env || "
            f"echo 'REDIS_URL=redis://redis:6379/0' >> {REMOTE_DIR}/.env",
        )
        run(c, f"chmod +x {REMOTE_DIR}/scripts/ops/*.sh 2>/dev/null || true")
        run(
            c,
            f"bash {REMOTE_DIR}/scripts/ops/install_cron.sh {REMOTE_DIR}",
        )

        sftp = c.open_sftp()
        sftp.put(str(DEPLOY / "vnss.yaml"), "/data/coolify/proxy/dynamic/vnss.yaml")
        sftp.close()
        print("wrote traefik vnss.yaml")

        print("docker compose up...")
        out = run(
            c,
            f"cd {REMOTE_DIR} && docker compose up -d --build",
            timeout=600,
        )
        print(out)
        time.sleep(8)
        print(run(c, "docker ps --filter name=vnss --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"))
        print(run(c, "docker compose -f /opt/vn-script-studio/docker-compose.yml logs --tail 40 api"))
        print(
            run(
                c,
                "echo '=== login chunks ==='; ls /opt/vn-script-studio/frontend/dist/assets/LoginPage-*",
            )
        )
    finally:
        c.close()


if __name__ == "__main__":
    upload_and_start()
