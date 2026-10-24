# YotoLib

FastAPI app (`server.py`, started by `yotolib.py`) with a plain JS front end in `static/`. It backs up Yoto cards the user owns into a local library.

## Personal card data stays local

`library/`, `backups/`, custom folders in `config.json`, and Yoto card URLs (`https://yoto.io/<id>...`) are this machine's card collection. That includes `card.json`, `recovery.json`, covers, audio, track icons, and backup zips.

- Do not stage, commit, push, attach, paste, or upload them. Do not put titles, track lists, or card URLs into commits, pull requests, issues, release notes, or tracked files.
- Do not `git add -f` those paths, copy them into tracked files, or drop `library/` or `backups/` from `.gitignore`.
- Do not commit `config.json` or `drive-token.json`. They store local paths and a Google token.
- Reading and editing the app locally is fine. The hook in `.claude/hooks/block-personal-cards.py` denies a violating command. Do not retry with `--force`, `--no-verify`, or by copying the files somewhere else first.
- Before a commit, push, PR, or release, follow the `protect-personal-cards` skill.

## Run and test

- Run: `YOTOLIB_OPEN_BROWSER=0 python yotolib.py` (port 8765 by default).
- UI tests (headless Chromium at phone and desktop sizes) use a made-up library in a temp folder, never `library/`:
  ```bash
  pip install -r requirements-dev.txt
  python -m playwright install --with-deps chromium
  pytest tests/ui
  ```
  Screenshots go to `test-results/ui/` (gitignored). Set `YOTOLIB_UI_BASE_URL` to test a running copy.
  Without root for `--with-deps`, run the tests in the `mcr.microsoft.com/playwright/python:v1.64.1-noble` image.
- CI (`.github/workflows/ci.yml`) runs the smoke test, the UI tests, manifest validation, and the image build.
