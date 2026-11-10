"""OpAMP endpoints for managing OpenTelemetry Collector configuration"""

import asyncio
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import aiohttp
import yaml
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import settings
from ..services.validation import basic_validation, format_otelcol_errors

router = APIRouter(prefix="/api/opamp", tags=["OpAMP"])

logger = logging.getLogger(__name__)


MAX_CONFIG_CHARS = 1_000_000          # matches the OpAMP server's 1 MiB body limit
INSTANCE_ID_PATTERN = r"^[A-Za-z0-9._-]{1,128}$"
# Collector config providers that read local files or fetch URLs when the config is loaded. The validator runs
# the collector binary inside the UI container, so these would read the UI container's files / make requests
# from it and echo the result in error output.
_FORBIDDEN_PROVIDER = re.compile(r"\$\{\s*(file|http|https)\s*:", re.IGNORECASE)


class ConfigValidateRequest(BaseModel):
    """Request body for validating OTel Collector configuration"""
    config: str = Field(..., max_length=MAX_CONFIG_CHARS, description="YAML configuration to validate")


class ConfigUpdateRequest(BaseModel):
    """Request body for updating OTel Collector configuration"""
    config: str = Field(..., max_length=MAX_CONFIG_CHARS, description="YAML configuration for the OTel Collector")
    instance_id: Optional[str] = Field(default=None, pattern=INSTANCE_ID_PATTERN, description="Target specific agent instance")


@router.get(
    '/status',
    operation_id="opamp_status",
    summary="Get OpAMP server and agent status",
    responses={
        200: {"description": "OpAMP server status with connected agents"},
        503: {"description": "OpAMP server unavailable"}
    }
)
async def opamp_status():
    """
    Get the status of the OpAMP server and connected OTel Collector agents.

    Returns information about:
    - Connected collector instances
    - Agent health status
    - Last seen timestamps
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{settings.opamp_server_url}/status",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise HTTPException(
                        status_code=response.status,
                        detail=f"OpAMP server returned {response.status}"
                    )
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.warning("OpAMP server request failed: %s", e)
        raise HTTPException(status_code=503, detail="OpAMP server unavailable") from e


@router.get(
    '/config',
    operation_id="opamp_get_config",
    summary="Get current OTel Collector configuration",
    responses={
        200: {"description": "Current collector configuration"},
        503: {"description": "OpAMP server unavailable"}
    }
)
async def opamp_get_config(
    instance_id: Optional[str] = Query(default=None, pattern=INSTANCE_ID_PATTERN, description="Specific agent instance ID")
):
    """
    Get the current effective configuration of the OTel Collector.

    If no agents are connected, returns the last known configuration.
    Optionally specify instance_id to get config from a specific collector.
    """
    try:
        params = {"instance_id": instance_id} if instance_id else None

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{settings.opamp_server_url}/config",
                params=params,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise HTTPException(
                        status_code=response.status,
                        detail=f"OpAMP server returned {response.status}"
                    )
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.warning("OpAMP server request failed: %s", e)
        raise HTTPException(status_code=503, detail="OpAMP server unavailable") from e


@router.post(
    '/validate',
    operation_id="opamp_validate_config",
    summary="Validate OTel Collector configuration",
    responses={
        200: {"description": "Validation result"},
        400: {"description": "Invalid request"}
    }
)
async def opamp_validate_config(request: ConfigValidateRequest):
    """
    Validate an OTel Collector configuration using the official otelcol validate command.

    Uses the OpenTelemetry Collector's built-in validation which checks:
    - Valid YAML syntax
    - Component configurations
    - Pipeline references
    - Component-specific validation rules
    """
    return await _validate_config_text(request.config)


def _run_otelcol_validate(config_text: str) -> subprocess.CompletedProcess:
    """Run `otelcol-contrib validate` on config_text (blocking; call via a worker thread)."""
    otelcol_binary = "/usr/local/bin/otelcol-contrib"
    tmp_file_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp_file:
            tmp_file.write(config_text)
            tmp_file_path = tmp_file.name
        return subprocess.run(
            [otelcol_binary, "validate", f"--config={tmp_file_path}"],
            capture_output=True,
            text=True,
            timeout=10,
            # Minimal environment: the collector expands ${env:VAR} in configs and may echo values in errors,
            # so do not hand it this process's environment (which can hold secrets).
            env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
        )
    finally:
        if tmp_file_path:
            try:
                os.unlink(tmp_file_path)
            except OSError:
                pass


async def _validate_config_text(config_text: str) -> dict:
    """Validate collector config text; returns {"valid": bool, "error": str|None, ...}.

    Fails closed: anything other than a successful validation (including a timeout) is reported as invalid,
    except when the otelcol binary is not installed, where a structural check is used instead.
    """
    try:
        parsed = yaml.safe_load(config_text)
    except yaml.YAMLError as e:
        return {"valid": False, "error": f"YAML syntax error: {e}"}
    if not isinstance(parsed, dict) or not parsed:
        return {"valid": False, "error": "Configuration must be a non-empty YAML mapping"}
    if _FORBIDDEN_PROVIDER.search(config_text):
        return {"valid": False, "error": "Config providers that read files or URLs (${file:...}, ${http:...}, ${https:...}) are not allowed"}

    try:
        # Blocking subprocess: run it in a worker thread so the event loop (ingest, queries) is not frozen.
        result = await asyncio.to_thread(_run_otelcol_validate, config_text)
    except subprocess.TimeoutExpired:
        logger.warning("Validation command timed out")
        return {"valid": False, "error": "Validation timed out"}
    except FileNotFoundError:
        logger.warning("otelcol-contrib binary not available, using basic validation")
        return basic_validation(parsed)
    except Exception:
        logger.exception("Unexpected error running otelcol-contrib validate")
        return {"valid": False, "error": "Validation could not be completed"}

    if result.returncode == 0:
        return {"valid": True, "error": None}

    error_msg = result.stderr.strip() or result.stdout.strip() or "Configuration validation failed"
    formatted_errors = format_otelcol_errors(error_msg)
    return {"valid": False, "error": formatted_errors["summary"], "errors": formatted_errors["errors"]}


@router.post(
    '/config',
    operation_id="opamp_update_config",
    summary="Update OTel Collector configuration",
    responses={
        200: {"description": "Configuration update queued"},
        400: {"description": "Invalid configuration"},
        503: {"description": "OpAMP server unavailable"}
    }
)
async def opamp_update_config(request: ConfigUpdateRequest):
    """
    Push a new configuration to the OTel Collector via OpAMP.

    The configuration is queued and will be applied when the collector
    next communicates with the OpAMP server (typically within seconds).

    **Example:**
    ```yaml
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
    # ... rest of config
    ```
    """
    # Validate before pushing: this config goes to every connected collector, so a config that is not a mapping or
    # fails the collector's own validation must never be queued.
    validation = await _validate_config_text(request.config)
    if not validation.get("valid"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid collector configuration: {validation.get('error') or 'validation failed'}"
        )

    try:
        async with aiohttp.ClientSession() as session:
            payload = {"config": request.config}
            if request.instance_id:
                payload["instance_id"] = request.instance_id

            async with session.post(
                f"{settings.opamp_server_url}/config",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=5),
                **({"headers": {"Authorization": f"Bearer {settings.opamp_api_token}"}} if settings.opamp_api_token else {}),
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    raise HTTPException(
                        status_code=response.status,
                        detail=f"OpAMP server error: {error_text}"
                    )
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.warning("OpAMP server request failed: %s", e)
        raise HTTPException(status_code=503, detail="OpAMP server unavailable") from e


@router.get(
    '/health',
    operation_id="opamp_health",
    summary="Check OpAMP server health",
    responses={
        200: {"description": "OpAMP server is healthy"},
        503: {"description": "OpAMP server unavailable"}
    }
)
async def opamp_health():
    """
    Health check for the OpAMP server.

    Returns 200 if the OpAMP server is reachable and healthy.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{settings.opamp_server_url}/health",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise HTTPException(
                        status_code=503,
                        detail="OpAMP server unhealthy"
                    )
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.warning("OpAMP server request failed: %s", e)
        raise HTTPException(status_code=503, detail="OpAMP server unavailable") from e


@router.get(
    '/templates',
    operation_id="opamp_list_templates",
    summary="List available OTel Collector configuration templates",
    responses={
        200: {"description": "List of available templates with metadata"}
    }
)
async def opamp_list_templates():
    """
    List all available OTel Collector configuration templates.

    The default configuration is always returned first, followed by all presets
    from the templates directory (top level only; `examples/` is not listed). Each template includes
    metadata extracted from YAML comments.
    """
    templates = []
    
    # First, add the default configuration as the first option
    default_config_path = Path(settings.otelcol_default_config)
    if default_config_path.exists():
        try:
            content = default_config_path.read_text()
            lines = content.split('\n')
            name = "Default Configuration"
            description = "Default OpenTelemetry Collector configuration with OTLP receivers, OpAMP extension, batch processing, and spanmetrics connector"

            # Extract description from first comment line
            for line in lines:
                if line.startswith('#'):
                    comment = line.lstrip('#').strip()
                    if comment:
                        # Use the first comment line as description
                        description = comment
                        break
                elif line.strip():
                    break

            templates.append({
                "id": "default",
                "name": name,
                "description": description,
                "filename": "config.yaml"
            })
        except Exception as e:
            logger.warning(f"Failed to read default config {default_config_path}: {e}")
    
    # Then, add all templates (presets) from the templates directory
    templates_dir = Path(settings.otelcol_templates_dir)
    if templates_dir.exists():
        for yaml_file in sorted(templates_dir.glob("*.yaml")):
            try:
                content = yaml_file.read_text()
                # Extract description from first comment line
                lines = content.split('\n')
                name = yaml_file.stem.replace('_', ' ').replace('-', ' ').title()
                description = ""

                # First non-empty comment line is the description
                for line in lines:
                    if line.startswith('#'):
                        comment = line.lstrip('#').strip()
                        if comment:
                            description = comment
                            break
                    elif line.strip():
                        # Hit non-comment content
                        break

                templates.append({
                    "id": yaml_file.stem,
                    "name": name,
                    "description": description,
                    "filename": yaml_file.name
                })
            except Exception as e:
                logger.warning(f"Failed to read template {yaml_file}: {e}")

    return {"templates": templates}


@router.get(
    '/templates/{template_id}',
    operation_id="opamp_get_template",
    summary="Get a specific OTel Collector configuration template",
    responses={
        200: {"description": "Template content"},
        404: {"description": "Template not found"}
    }
)
async def opamp_get_template(template_id: str):
    """
    Get the content of a specific configuration template.

    The template_id 'default' returns the default configuration.
    Other template_ids correspond to filenames without extension in the templates directory.
    """
    # Handle default template
    if template_id == "default":
        default_config_path = Path(settings.otelcol_default_config)
        if not default_config_path.exists():
            raise HTTPException(
                status_code=404,
                detail="Default configuration not found"
            )
        try:
            content = default_config_path.read_text()
            return {
                "id": "default",
                "filename": "config.yaml",
                "config": content
            }
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to read default config: {str(e)}"
            ) from e
    
    # Handle other templates
    templates_dir = Path(settings.otelcol_templates_dir)
    template_file = templates_dir / f"{template_id}.yaml"

    if not template_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Template '{template_id}' not found"
        )

    try:
        content = template_file.read_text()
        return {
            "id": template_id,
            "filename": template_file.name,
            "config": content
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read template: {str(e)}"
        ) from e
