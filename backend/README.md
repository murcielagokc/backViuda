# Backend — viuda

FastAPI + WebSockets nativos. Todo el estado vive en memoria (sin base de datos).

## Requisitos

- Python 3.11+
- (Recomendado) Entorno virtual

## Instalación

```bash
cd backend
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
```

## Arranque

```bash
uvicorn app.main:app --reload --port 8000
```

El servidor queda disponible en `http://localhost:8000`.  
El endpoint WebSocket está en `ws://localhost:8000/ws`.
