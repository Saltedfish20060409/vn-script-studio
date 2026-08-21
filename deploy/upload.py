"""SFTP 上传单个部署产物：python deploy/upload.py <local> <remote>"""

import os
import sys

import paramiko

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from remote import connect  # noqa: E402


def main():
    local = sys.argv[1]
    remote = sys.argv[2]
    client = connect()
    try:
        sftp = client.open_sftp()
        try:
            size = os.path.getsize(local)
            with open(local, "rb") as f, sftp.open(remote, "wb") as rf:
                done = 0
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    rf.write(chunk)
                    done += len(chunk)
            print(f"uploaded {remote} {done} bytes")
        finally:
            sftp.close()
    finally:
        client.close()


if __name__ == "__main__":
    main()
