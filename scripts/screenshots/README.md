# Report screenshots (developer tool)

These scripts drive a headless Google Chrome over the DevTools protocol (Node 22+, no extra
packages) to capture the panel and body screenshots in `docs/screenshots/`, and to check
that real mouse hover over the 3D body reaches every region.

1. Start the app with `.venv/bin/python run.py`.
2. Create an account, load a demo patient and convene the panel once.
3. Then run:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --remote-debugging-port=9333 \
  --user-data-dir=/tmp/cc-chrome --use-angle=swiftshader --enable-unsafe-swiftshader about:blank &
CC_SHOT_EMAIL=you@example.com CC_SHOT_PASSWORD=... CC_SHOT_CASE=1 node scripts/screenshots/capture.mjs 9333 docs/screenshots main
CC_SHOT_EMAIL=you@example.com CC_SHOT_PASSWORD=... CC_SHOT_CASE=1 node scripts/screenshots/hover_test.mjs 9333 docs/screenshots/body_hover.png
```

For the 2D fallback, start Chrome with `--disable-webgl --disable-3d-apis` and use mode `nogl`.
