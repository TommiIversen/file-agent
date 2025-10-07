# File Transfer Agent - FastAPI App

En simpel FastAPI applikation der følger best practices og er klar til at blive udvidet.

## Struktur

```
app/
├── __init__.py
├── main.py              # Hovedapplikation
├── routers/
│   ├── __init__.py
│   ├── api.py           # API endpoints
│   └── views.py         # HTML views
└── templates/
    └── hello.html       # Jinja2 template
```

## Installation

```cmd
pip install -r requirements.txt
```

## Kør applikationen

```cmd
run_app.bat
```

Eller manuelt:
```cmd
uvicorn app.main:app --reload
```
