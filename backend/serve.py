"""Start birbTrack: uvicorn on BT_PORT (8894). TLS is the reverse proxy's job."""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("main:app", host=os.environ.get("BT_HOST", "0.0.0.0"), port=int(os.environ.get("BT_PORT", "8894")),
                proxy_headers=False, server_header=False, date_header=True, log_level="warning",
                timeout_graceful_shutdown=5)
