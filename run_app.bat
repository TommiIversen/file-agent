@echo off
echo Starter FastAPI File Transfer Agent...
echo.
echo Applikation vil være tilgængelig på:
echo - http://127.0.0.1:8000 (Hello World view)
echo - http://127.0.0.1:8000/api/hello (API endpoint)
echo - http://127.0.0.1:8000/docs (FastAPI dokumentation)
echo.

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000