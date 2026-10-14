"""Start Case Conference: `python run.py`, then open http://localhost:8000.

Options: `--port 8001` to use another port, `--reload` while developing the backend.
On a host (Render, Docker...): `python run.py --host 0.0.0.0 --proxy-headers`; the port
comes from --port or the PORT environment variable.
"""

import argparse
import os

import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Case Conference app.")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--proxy-headers", action="store_true",
                        help="trust X-Forwarded-* from the hosting proxy (real client IP, https cookies)")
    args = parser.parse_args()
    shown = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
    print(f"\n  Case Conference is starting: open http://{shown}:{args.port}\n")
    uvicorn.run("backend.main:app", host=args.host, port=args.port, reload=args.reload,
                proxy_headers=args.proxy_headers, forwarded_allow_ips="*" if args.proxy_headers else None)
