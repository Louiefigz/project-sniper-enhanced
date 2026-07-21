"""Active network-namespace proof for the exact running render container."""
from __future__ import annotations

import contextlib
import hashlib
import json
import socket
import subprocess
import threading
import uuid
from dataclasses import dataclass
from typing import Iterator

from headless.container_policy import DockerRuntime, command, docker_env

_NODE_PROBE = r"""
const dns = require('node:dns');
const net = require('node:net');
const decoyPort = Number(process.argv[1]);
function denied(host, port, family) {
  return new Promise((resolve) => {
    const socket = net.createConnection({host, port, family});
    let done = false;
    const finish = (value) => { if (!done) { done = true; socket.destroy(); resolve(value); } };
    socket.setTimeout(2000, () => finish({reached:false,error:'TIMEOUT'}));
    socket.once('connect', () => finish({reached:true,error:null}));
    socket.once('error', (error) => finish({reached:false,error:error.code || error.name}));
  });
}
async function ownLoopback() {
  const token = 'container-loopback-ok';
  const server = net.createServer((client) => client.end(token));
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  const port = server.address().port;
  const received = await new Promise((resolve, reject) => {
    let data = '';
    const client = net.createConnection({host:'127.0.0.1',port}, () => {});
    client.setEncoding('utf8'); client.on('data', chunk => data += chunk);
    client.once('end', () => resolve(data)); client.once('error', reject);
  });
  await new Promise((resolve) => server.close(resolve));
  return {ok:received === token,port};
}
function lookup() {
  return new Promise((resolve) => {
    let done = false;
    const timer = setTimeout(() => { if (!done) { done=true; resolve({resolved:false,error:'TIMEOUT'}); } }, 2000);
    dns.lookup('example.com', {all:true}, (error, addresses) => {
      if (done) return; done=true; clearTimeout(timer);
      resolve(error ? {resolved:false,error:error.code || error.name} : {resolved:true,error:null,count:addresses.length});
    });
  });
}
(async () => console.log(JSON.stringify({schemaVersion:1,decoyPort,
  ownLoopback:await ownLoopback(),
  hostLoopbackDecoy:await denied('127.0.0.1',decoyPort,4),
  externalIpv4:await denied('1.1.1.1',443,4),
  externalIpv6:await denied('2606:4700:4700::1111',443,6),dns:await lookup()})))()
  .catch((error) => { console.error(error.stack || String(error)); process.exit(70); });
"""


@dataclass(frozen=True)
class _Decoy:
    server: socket.socket
    stop: threading.Event
    thread: threading.Thread
    port: int
    nonce: bytes


def _serve(server: socket.socket, nonce: bytes, stop: threading.Event) -> None:
    server.settimeout(0.2)
    while not stop.is_set():
        try:
            client, _ = server.accept()
        except TimeoutError:
            continue
        except OSError:
            return
        with client:
            client.sendall(nonce)


def _prove_host_decoy(decoy: _Decoy, nonce: bytes) -> None:
    with socket.create_connection(("127.0.0.1", decoy.port), timeout=2) as client:
        if client.recv(len(nonce)) != nonce:
            raise RuntimeError("host loopback decoy positive control failed")


@contextlib.contextmanager
def _host_decoy() -> Iterator[_Decoy]:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    stop = threading.Event()
    thread: threading.Thread | None = None
    try:
        server.bind(("127.0.0.1", 0))
        server.listen(4)
        nonce = uuid.uuid4().hex.encode("ascii")
        thread = threading.Thread(
            target=_serve, args=(server, nonce, stop), daemon=True)
        thread.start()
        decoy = _Decoy(server, stop, thread, server.getsockname()[1], nonce)
        _prove_host_decoy(decoy, nonce)
        yield decoy
    finally:
        stop.set()
        server.close()
        if thread is not None:
            thread.join(timeout=2)


def _validate(container: dict, decoy: _Decoy) -> dict:
    denied = ("hostLoopbackDecoy", "externalIpv4", "externalIpv6")
    failures = [container.get(key) or {} for key in denied]
    dns = container.get("dns") or {}
    if (container.get("schemaVersion") != 1
            or container.get("decoyPort") != decoy.port
            or (container.get("ownLoopback") or {}).get("ok") is not True
            or any(row.get("reached") is not False or not row.get("error")
                   for row in failures)
            or dns.get("resolved") is not False or not dns.get("error")):
        raise RuntimeError("render-container active network denial proof failed")
    return {"schemaVersion": 1, "hostDecoyPositive": True,
            "hostDecoyPort": decoy.port,
            "hostDecoyNonceSha256": hashlib.sha256(decoy.nonce).hexdigest(),
            "container": container}


def probe_container(runtime: DockerRuntime, config_dir: str, name: str) -> dict:
    """Prove working own-loopback plus denied host/external/DNS access."""
    with _host_decoy() as decoy:
        proc = subprocess.run(
            command(runtime, "container", "exec", name, "/usr/bin/node", "-e",
                    _NODE_PROBE, str(decoy.port)), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, env=docker_env(config_dir),
            timeout=15, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"render-container network probe failed: "
                               f"{proc.stderr.strip()[-240:]}")
        try:
            container = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("render-container network probe returned invalid JSON") \
                from exc
        return _validate(container, decoy)
