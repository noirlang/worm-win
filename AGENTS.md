# amele-win

Python-based GUI/CLI application acting as the Windows forensic agent for the Amele desktop app.

## Quick start

```bash
# Check syntax
python -m py_compile windows.py

# Run agent locally (requires Windows platform dependencies)
python windows.py
```

## CI rules

- All pushes to the `dev` branch trigger the GitHub Actions workflow.
- **Automated Builds & Prereleases** are only run if the commit message contains the `[build]` tag:
  ```bash
  git commit -m "feat: add capability [build]"
  ```
- Triggering manually via `workflow_dispatch` is also supported.
- Pipeline outputs: `amele-win.exe` standalone executable (packaged via PyInstaller).

## Architecture

- Uses `winpmem` dynamically for RAM acquisition and other local tools for disk imaging.
- Connects and streams outputs to `amele-next`.
