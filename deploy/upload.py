"""SFTP 上传单个文件（断点续传）：python deploy/upload.py <local> <remote>

- 远端已存在且长度 >= 本地 → 跳过（幂等）
- 远端存在但更短 → 从已传字节数继续（append 写入），中断后重跑即续传
- 传完可校验远端大小
"""

import os
import stat
import sys

import paramiko

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from remote import connect  # noqa: E402


def remote_size(sftp, remote: str):
    try:
        return sftp.stat(remote).st_size
    except (FileNotFoundError, IOError):
        return 0


def main():
    local = sys.argv[1]
    remote = sys.argv[2]
    local_size = os.path.getsize(local)

    client = connect()
    try:
        sftp = client.open_sftp()
        try:
            existing = remote_size(sftp, remote)
            if existing >= local_size:
                print(f"already up-to-date: {remote} {existing}/{local_size} bytes")
                return
            if existing == 0:
                # 新建文件
                with sftp.open(remote, "wb") as rf:
                    rf.truncate(0)
                existing = 0
            else:
                print(f"resume: {remote} {existing}/{local_size} bytes")
            with open(local, "rb") as f:
                f.seek(existing)
                with sftp.open(remote, "r+b") as rf:
                    rf.seek(existing)
                    done = existing
                    while True:
                        chunk = f.read(1 << 20)
                        if not chunk:
                            break
                        rf.write(chunk)
                        done += len(chunk)
            final = remote_size(sftp, remote)
            if final != local_size:
                print(f"WARN: size mismatch local={local_size} remote={final}")
            else:
                print(f"uploaded {remote} {final} bytes")
        finally:
            sftp.close()
    finally:
        client.close()


if __name__ == "__main__":
    main()
