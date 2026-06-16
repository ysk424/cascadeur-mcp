"""Cascadeur MCP server.

Exposes the running Cascadeur instance to an MCP client (e.g. Claude). For every
tool call the server:

1. binds a localhost TCP server socket and writes the chosen port to a port file,
2. launches ``cascadeur.exe --run-script commands.externals.csc_mcp_exec`` which the
   already-running Cascadeur dispatches on its main thread,
3. accepts the call-back connection from that command,
4. sends the request and reads the JSON response.

This "per-call --run-script" design mirrors the proven cascadeur_bridge addon: all
``csc`` access happens on Cascadeur's main thread and the UI is never blocked between
calls. The trade-off is a small per-call launch latency.
"""

import json
import os
import socket
import subprocess
import tempfile
import time
import uuid

from mcp.server.fastmcp import FastMCP, Image

CSC_EXE = os.environ.get(
    "CASCADEUR_EXE_PATH", r"C:\Program Files\Cascadeur\cascadeur.exe"
)
PORT = int(os.environ.get("CASCADEUR_MCP_PORT", "53151"))
CONNECT_TIMEOUT = float(os.environ.get("CASCADEUR_MCP_TIMEOUT", "60"))
COMMAND = "commands.externals.csc_mcp_exec"
HEADER = 64
PORT_FILE = os.path.join(tempfile.gettempdir(), "cascadeur_mcp.json")

mcp = FastMCP("cascadeur")


# --------------------------------------------------------------------------- #
# Wire protocol (64-byte ASCII length header + UTF-8 JSON body)
# --------------------------------------------------------------------------- #
def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Socket closed before expected bytes were received")
        buf += chunk
    return buf


def _recv_json(sock):
    length = int(_recv_exact(sock, HEADER).decode("utf-8").strip())
    return json.loads(_recv_exact(sock, length).decode("utf-8"))


def _send_json(sock, obj):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    header = str(len(data)).encode("utf-8")
    header += b" " * (HEADER - len(header))
    sock.sendall(header)
    sock.sendall(data)


def _write_port_file(port):
    with open(PORT_FILE, "w", encoding="utf-8") as f:
        json.dump({"port": port}, f)


def _call_cascadeur(request):
    """Run a single round-trip with Cascadeur and return the parsed response dict."""
    if not os.path.exists(CSC_EXE):
        raise RuntimeError(
            f"Cascadeur executable not found at {CSC_EXE!r}. "
            f"Set CASCADEUR_EXE_PATH."
        )

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("localhost", PORT))
    srv.listen(1)
    srv.settimeout(CONNECT_TIMEOUT)
    _write_port_file(PORT)

    try:
        subprocess.Popen([CSC_EXE, "--run-script", COMMAND])
        try:
            client, _ = srv.accept()
        except socket.timeout:
            raise RuntimeError(
                "Cascadeur did not connect within "
                f"{CONNECT_TIMEOUT:.0f}s. Is Cascadeur running and is "
                "csc_mcp_exec.py installed under "
                "resources/scripts/python/commands/externals/?"
            )
        try:
            _send_json(client, request)
            return _recv_json(client)
        finally:
            client.close()
    finally:
        srv.close()


def _execute(code):
    resp = _call_cascadeur({"code": code})
    return json.dumps(resp, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
@mcp.tool()
def execute_cascadeur_code(code: str) -> str:
    """Execute arbitrary Python inside the running Cascadeur instance.

    Available names in scope: ``csc`` (the Cascadeur API), ``scene`` (the current
    ``csc.domain.Scene``), and ``app`` (``csc.app.get_application()``).

    To return data, assign it to a variable named ``result`` (it must be
    JSON-serialisable; otherwise its repr is returned). Anything printed to stdout
    is captured and returned under ``stdout``.

    Scene mutations must go through the modify API, e.g.
    ``scene.modify_with_session("My op", mod_func)`` where ``mod_func`` has the
    signature ``(model, update, sc, session)``.

    Returns a JSON string: {"status", "result"/"message", "stdout"}.
    """
    return _execute(code)


@mcp.tool()
def get_scene_info() -> str:
    """Return basic information about the current Cascadeur scene."""
    code = """
sm = app.get_scene_manager()
sc = sm.current_scene()
mv = scene.model_viewer()
ids = mv.get_objects()
result = {
    "scene_name": sc.name(),
    "object_count": len(ids),
    "objects": [mv.get_object_name(i) for i in list(ids)[:50]],
}
"""
    return _execute(code)


@mcp.tool()
def export_fbx(file_path: str, method: str = "export_all_objects") -> str:
    """Export the current Cascadeur scene to an FBX file.

    Parameters:
    - file_path: absolute path of the .fbx to write.
    - method: a FbxSceneLoader export method name, e.g. "export_all_objects",
      "export_model", "export_joints", "export_scene_selected".
    """
    code = f"""
loader = app.get_tools_manager().get_tool("FbxSceneLoader").get_fbx_loader(scene)
settings = csc.fbx.FbxSettings()
settings.mode = csc.fbx.FbxSettingsMode.Binary
settings.bake_animation = True
loader.set_settings(settings)
getattr(loader, {method!r})({file_path!r})
result = {{"exported": {file_path!r}, "method": {method!r}}}
"""
    return _execute(code)


@mcp.tool()
def import_fbx(file_path: str, method: str = "import_model") -> str:
    """Import an FBX file into the current Cascadeur scene.

    Parameters:
    - file_path: absolute path of the .fbx to import.
    - method: a FbxSceneLoader import method name, e.g. "import_model",
      "import_scene", "import_animation", "add_model".
    """
    code = f"""
loader = app.get_tools_manager().get_tool("FbxSceneLoader").get_fbx_loader(scene)
getattr(loader, {method!r})({file_path!r})
result = {{"imported": {file_path!r}, "method": {method!r}}}
"""
    return _execute(code)


@mcp.tool()
def capture_viewport(width: int = 960, height: int = 540, samples: int = 1) -> Image:
    """Render the current Cascadeur viewport to an image and return it.

    Lets you visually verify the scene/animation. Parameters control the output
    resolution and anti-aliasing sample count.

    Note: Cascadeur renders the image on its main loop slightly after the call
    returns, so the server waits for the file to be written before reading it.
    """
    out_path = os.path.join(
        tempfile.gettempdir(), f"csc_mcp_shot_{uuid.uuid4().hex}.png"
    )
    code = f"""
import csc, os
A = csc.app.get_application()
tm = A.get_tools_manager()
rtf = None
try:
    rtf = tm.get_tool("RenderToFile")
except Exception:
    pass
if rtf is None:
    for t in tm.tools():
        if isinstance(t, csc.tools.RenderToFile):
            rtf = t
            break
view = A.current_scene()
rp = csc.tools.RenderParameters()
rp.width = {int(width)}
rp.height = {int(height)}
rp.samples = {int(samples)}
# Remove any stale file so we can detect the fresh render.
if os.path.exists({out_path!r}):
    os.remove({out_path!r})
rtf.take_image(view, rp, {out_path!r})
result = {{"queued": {out_path!r}}}
"""
    resp = json.loads(_execute(code))
    if resp.get("status") != "success":
        raise RuntimeError(resp.get("message", "capture failed"))

    # The render is deferred to Cascadeur's main loop after run() returns; poll.
    deadline = time.time() + 15
    while time.time() < deadline:
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            with open(out_path, "rb") as f:
                data = f.read()
            try:
                os.remove(out_path)
            except OSError:
                pass
            return Image(data=data, format="png")
        time.sleep(0.2)
    raise RuntimeError(
        "Cascadeur did not write the screenshot within 15s. "
        "Is a 3D viewport visible?"
    )


def main():
    mcp.run()


if __name__ == "__main__":
    main()
