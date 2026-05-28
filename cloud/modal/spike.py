"""Minimal Modal spike — verify deploy + web endpoint + volume."""

import os
import modal

app = modal.App("ck-spike")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .pip_install("fastapi[standard]")
)

volume = modal.Volume.from_name("ck-state", create_if_missing=True)


@app.function(image=image, volumes={"/state": volume}, timeout=60)
@modal.fastapi_endpoint(method="POST")
def ping(body: dict):
    state_files = []
    if os.path.exists("/state"):
        for root, dirs, files in os.walk("/state"):
            for f in files:
                state_files.append(os.path.join(root, f))

    marker = "/state/spike-marker.txt"
    with open(marker, "w") as f:
        f.write("spike ran")
    volume.commit()

    return {
        "ok": True,
        "body_received": body,
        "state_files_count": len(state_files),
        "marker_written": True,
    }
