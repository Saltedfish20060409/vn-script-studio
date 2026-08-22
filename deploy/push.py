"""一键部署（单连接断点续传 + 校验）：
    python deploy/push.py            # 全量：后端 + 前端
    python deploy/push.py --backend  # 只推后端
    python deploy/push.py --frontend # 只推前端

流程：本地打包 → 分片(2MB) → 单 paramiko 连接断点续传上传 → 远端重组+大小校验 →
      解包 → 重启 vnss-web / 重建 api → 健康检查 + 前端 hash 对比。

可中断：再次运行会自动跳过已传完的分片继续。

凭据走环境变量：SSH_HOST / SSH_USER / SSH_PASS
"""

import io
import os
import sys
import tarfile

import paramiko

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from remote import connect  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
REMOTE_DIR = "/opt/vn-script-studio"
PART = 2_000_000  # 2MB 分片


def build_backend_tar() -> bytes:
    buf = io.BytesIO()
    exclude = {".venv", "__pycache__", ".env", ".pytest_cache", ".ruff_cache"}
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for rel in ("app", "alembic", "tests", "requirements.txt", "Dockerfile", ".env.example"):
            src = os.path.join(BACKEND, rel)
            if os.path.exists(src):
                tf.add(src, arcname=f"backend/{rel}", recursive=True,
                       filter=lambda i: None if os.path.basename(i.name) in exclude else i)
    return buf.getvalue()


def upload_resume(sftp, local_bytes: bytes, remote: str):
    """单连接断点续传：远端已传长度 >= 本地 → 跳过；否则从偏移续写。"""
    try:
        existing = sftp.stat(remote).st_size
    except IOError:
        existing = 0
    if existing >= len(local_bytes):
        print(f"  skip (up-to-date): {remote}")
        return
    mode = "r+b" if existing > 0 else "wb"
    with sftp.open(remote, mode) as rf:
        if existing > 0:
            rf.seek(existing)
        done = existing
        while done < len(local_bytes):
            chunk = local_bytes[done : done + (1 << 20)]
            rf.write(chunk)
            done += len(chunk)
    final = sftp.stat(remote).st_size
    if final != len(local_bytes):
        raise SystemExit(f"size mismatch {remote}: local={len(local_bytes)} remote={final}")
    print(f"  uploaded {remote} ({final} bytes)")


def upload_split(sftp, data: bytes, remote_dir: str, prefix: str):
    for i in range(0, len(data), PART):
        part = data[i : i + PART]
        name = f"{prefix}.part{i // PART:02d}"
        upload_resume(sftp, part, f"{remote_dir}/{name}")


def run(client, command: str, timeout: int = 300):
    print(f"$ {command[:120]}{'...' if len(command) > 120 else ''}", flush=True)
    _in, _out, _err = client.exec_command(command, timeout=timeout)
    out = _out.read().decode("utf-8", "replace")
    err = _err.read().decode("utf-8", "replace")
    if out.strip():
        print(out.rstrip(), flush=True)
    if err.strip():
        print("[stderr] " + err.rstrip()[:800], flush=True)
    code = _out.channel.recv_exit_status()
    if code != 0:
        raise SystemExit(f"remote command failed (exit {code}): {command[:120]}")
    return out


def main():
    args = set(sys.argv[1:])
    do_backend = not args or "--backend" in args or "--all" in args
    do_frontend = not args or "--frontend" in args or "--all" in args

    client = connect()
    try:
        sftp = client.open_sftp()
        try:
            run(client, "mkdir -p /tmp/vnss-bk /tmp/vnss-ds")

            if do_backend:
                print("=== backend ===")
                backend_tar = build_backend_tar()
                print(f"packed {len(backend_tar)} bytes -> {len(backend_tar)//PART + 1} parts")
                upload_split(sftp, backend_tar, "/tmp/vnss-bk", "bk")

            if do_frontend:
                print("=== frontend ===")
                dist_tar = os.path.join(ROOT, "deploy", "artifacts", "dist.tar.gz")
                if not os.path.exists(dist_tar):
                    raise SystemExit("缺少 deploy/artifacts/dist.tar.gz，请先运行 deploy/pack.py")
                with open(dist_tar, "rb") as f:
                    dist_data = f.read()
                print(f"packed {len(dist_data)} bytes -> {len(dist_data)//PART + 1} parts")
                upload_split(sftp, dist_data, "/tmp/vnss-ds", "ds")
        finally:
            sftp.close()

        if do_backend and do_frontend:
            run(client, "cat /tmp/vnss-bk/bk.part* > /tmp/vnss-backend.tar.gz && "
                        "cat /tmp/vnss-ds/ds.part* > /tmp/vnss-dist.tar.gz && "
                        "ls -l /tmp/vnss-backend.tar.gz /tmp/vnss-dist.tar.gz")
        elif do_backend:
            run(client, "cat /tmp/vnss-bk/bk.part* > /tmp/vnss-backend.tar.gz && ls -l /tmp/vnss-backend.tar.gz")
        else:
            run(client, "cat /tmp/vnss-ds/ds.part* > /tmp/vnss-dist.tar.gz && ls -l /tmp/vnss-dist.tar.gz")

        if do_backend:
            run(client, f"cd {REMOTE_DIR} && tar -xzf /tmp/vnss-backend.tar.gz && "
                        "docker compose build api 2>&1 | tail -1 && "
                        "docker compose up -d api 2>&1 | tail -1 && sleep 12", timeout=600)
        if do_frontend:
            run(client, f"cd {REMOTE_DIR} && rm -rf frontend/dist && mkdir -p frontend/dist && "
                        "tar -xzf /tmp/vnss-dist.tar.gz --strip-components=2 -C frontend/dist && "
                        "docker restart vnss-web && sleep 3", timeout=300)

        run(client, "docker exec vnss-web wget -q -O- --timeout=6 http://vnss-api:8000/health")
        out = run(client, "grep -o 'assets/index-[A-Za-z0-9_-]*\\.js' /opt/vn-script-studio/frontend/dist/index.html | head -1")
        out2 = run(client, "curl -s --max-time 10 https://studio.nexesr.top/ | grep -o 'assets/index-[A-Za-z0-9_-]*\\.js' | head -1")
        if out.strip() and out.strip() == out2.strip():
            print(f"HASH OK: {out.strip()}")
        else:
            print(f"HASH MISMATCH: server={out.strip()} public={out2.strip()}")
        run(client, "rm -f /tmp/vnss-*.tar.gz /tmp/vnss-bk/* /tmp/vnss-ds/* && echo CLEANED")
    finally:
        client.close()
    print("DONE")


if __name__ == "__main__":
    main()
