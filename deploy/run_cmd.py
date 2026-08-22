"""Deploy helper: run one remote command via paramiko (no PS quoting issues)."""
import os
import sys

import paramiko


def main():
    command = sys.argv[1]
    host = os.environ.get("SSH_HOST", "43.156.52.101")
    user = os.environ.get("SSH_USER", "root")
    pwd = os.environ.get("SSH_PASS", "")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=22, username=user, password=pwd, timeout=25)
    try:
        _in, _out, _err = client.exec_command(command, timeout=int(os.environ.get("SSH_TIMEOUT", "120")))
        out = _out.read().decode("utf-8", "replace")
        err = _err.read().decode("utf-8", "replace")
        if out:
            print(out.rstrip())
        if err:
            print("[stderr] " + err.rstrip())
        code = _out.channel.recv_exit_status()
        sys.exit(code)
    finally:
        client.close()


if __name__ == "__main__":
    main()
