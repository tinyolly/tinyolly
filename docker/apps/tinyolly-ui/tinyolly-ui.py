"""TinyOlly UI - Entry Point

This is a thin wrapper that imports and runs the FastAPI application.
The actual application logic is in the app/ package.
"""

from app.main import app

if __name__ == '__main__':
    import uvicorn

    from app.config import settings
    
    # Port 5002 is the internal container port
    # Docker maps this to 5005 externally (see docker-compose-tinyolly-core.yml)
    # Kubernetes uses port 5002 directly (see k8s/tinyolly-ui.yaml)
    port = settings.port
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Starting TinyOlly UI...")
    logger.info(f"✓ HTTP mode: http://0.0.0.0:{port}")
    # uvloop is already installed via policy in app/main.py
    uvicorn.run(app, host='0.0.0.0', port=port)
