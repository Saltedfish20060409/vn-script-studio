"""SSH 部署辅助：paramiko 连接 + 执行远端命令。

密码从环境变量读取（SSH_HOST / SSH_USER / SSH_PASS），不落盘。
用法:
  $env:SSH_HOST='43.156.52.101'; $env:SSH_USER='root'; $env:SSH_PASS='...'
  python deploy/remote.py "uname -a"
"""

import os
import sys

import paramiko


def connect():
    host = os.environ.get("SSH_HOST") or "43.156.52.101"
    user = os.environ.get("SSH_USER") or "root"
    pwd = os.environ.get("SSH_PASS") or ""
    port = int(os.environ.get("SSH_PORT") or "22")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=pwd, timeout=25)
    return client


def run(client, command: str, timeout: int = 300) -> str:
    print(f"$ {command}", flush=True)
    _in, _out, _err = client.exec_command(command, timeout=timeout)
    out = _out.read().decode("utf-8", "replace")
    err = _err.read().decode("utf-8", "replace")
    if out:
        print(out.rstrip(), flush=True)
    if err:
        print("[stderr] " + err.rstrip(), flush=True)
    code = _out.channel.recv_exit_status()
    if code != 0:
        print(f"[exit code: {code}]", flush=True)
    return out


def main():
    cmds = sys.argv[1:] or ["echo connected"]
    client = connect()
    try:
        for c in cmds:
            run(client, c)
    finally:
        client.close()


if __name__ == "__main__":
    main()
