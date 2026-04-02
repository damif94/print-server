# Print API

Small Python print server for a label printer using CUPS.

It serves:

- `GET /` -> basic frontend
- `GET /health` -> health check
- `POST /print` -> send PDF, JPG, or PNG to print

It also supports:

- API key authentication with `X-API-Key`
- systemd service deployment
- request/response logging through `journalctl`

## Requirements

- Linux machine
- Python 3
- CUPS installed and working
- printer already configured in CUPS
- `lp` command available

## Project structure

```text
print-api/
├── config.py
├── handlers.py
├── logging_utils.py
├── server.py
├── index.html
├── .gitignore
└── README.md
```

## 1. Clone or copy the project

```bash
mkdir -p ~/print-api
cd ~/print-api
```

Copy the project files into that folder.

## 2. Create a virtual environment

From the project folder:

```bash
python3 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

You should now see your shell prefixed with something like `.venv`.

## 3. Upgrade pip

```bash
pip install --upgrade pip
```

This project currently uses only the Python standard library, so there are no external dependencies to install.

## 4. Configure the app

Edit `config.py` and set your values:

- `PRINTER_NAME`
- `HOST`
- `PORT`
- `API_KEY`

Example:

```python
PRINTER_NAME = "XP360B"
HOST = "0.0.0.0"
PORT = 8080
API_KEY = "replace-with-your-secret-api-key"
```

## 5. Run the server manually

With the virtual environment activated:

```bash
python server.py
```

You should see:

```text
Print API listening on http://0.0.0.0:8080
```

## 6. Test the API

Health check:

```bash
curl -H "X-API-Key: your-api-key" http://localhost:8080/health
```

Expected response:

```json
{"ok": true, "printer": "XP360B"}
```

Print a PDF:

```bash
curl -X POST \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/pdf" \
  --data-binary "@file.pdf" \
  http://localhost:8080/print
```

Print a JPG:

```bash
curl -X POST \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: image/jpeg" \
  --data-binary "@file.jpg" \
  http://localhost:8080/print
```

Print a PNG:

```bash
curl -X POST \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: image/png" \
  --data-binary "@file.png" \
  http://localhost:8080/print
```

## 7. Frontend

The app also serves `index.html` from:

```text
http://localhost:8080/
```

That page lets you:

- enter the API key
- choose a file
- send it to print
- view the server response

## 8. Running with systemd

Create the service file:

```bash
sudo nano /etc/systemd/system/print-api.service
```

Use this content:

```ini
[Unit]
Description=Print API
After=network.target cups.service
Wants=network.target

[Service]
Type=simple
User=agustin
WorkingDirectory=/home/agustin/print-api
ExecStart=/home/agustin/print-api/.venv/bin/python /home/agustin/print-api/server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Reload systemd:

```bash
sudo systemctl daemon-reload
```

Enable the service:

```bash
sudo systemctl enable print-api
```

Start it:

```bash
sudo systemctl start print-api
```

Check status:

```bash
sudo systemctl status print-api --no-pager
```

## 9. Logs

Live logs:

```bash
journalctl -u print-api -f
```

Last 100 lines:

```bash
journalctl -u print-api -n 100 --no-pager
```

Today's logs:

```bash
journalctl -u print-api --since today
```

## 10. Updating the code

After editing the project files, restart the service:

```bash
sudo systemctl restart print-api
```

Then check:

```bash
sudo systemctl status print-api --no-pager
```

## 11. Deactivate the virtual environment

When working manually in the shell:

```bash
deactivate
```

## Notes

- The API key is sent over HTTP unless you place the app behind HTTPS.
- Do not expose this publicly without understanding the risks.
- The printer must already be working through CUPS before using this app.
- The service uses `lp`, so test CUPS first from the command line.

## Useful manual CUPS test

```bash
lp -d XP360B -o PageSize=w4h6 file.pdf
```
