"""OpAMP endpoints for managing OpenTelemetry Collector configuration"""

import logging
import os
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


class ConfigValidateRequest(BaseModel):
    """Request body for validating OTel Collector configuration"""
    config: str = Field(..., description="YAML configuration to validate")


class ConfigUpdateRequest(BaseModel):
    """Request body for updating OTel Collector configuration"""
    config: str = Field(..., description="YAML configuration for the OTel Collector")
    instance_id: Optional[str] = Field(default=None, description="Target specific agent instance")


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
    except aiohttp.ClientError as e:
        raise HTTPException(
            status_code=503,
            detail=f"OpAMP server unavailable: {str(e)}"
        ) from e


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
    instance_id: Optional[str] = Query(default=None, description="Specific agent instance ID")
):
    """
    Get the current effective configuration of the OTel Collector.

    If no agents are connected, returns the last known configuration.
    Optionally specify instance_id to get config from a specific collector.
    """
    try:
        url = f"{settings.opamp_server_url}/config"
        if instance_id:
            url += f"?instance_id={instance_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise HTTPException(
                        status_code=response.status,
                        detail=f"OpAMP server returned {response.status}"
                    )
    except aiohttp.ClientError as e:
        raise HTTPException(
            status_code=503,
            detail=f"OpAMP server unavailable: {str(e)}"
        ) from e


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
    # First do basic YAML syntax check
    try:
        parsed = yaml.safe_load(request.config)
        if parsed is None:
            return {
                "valid": False,
                "error": "Configuration is empty or invalid"
            }
    except yaml.YAMLError as e:
        return {
            "valid": False,
            "error": f"YAML syntax error: {str(e)}"
        }
    
    # Use local otelcol-contrib binary for validation
    # The binary is installed in the container at /usr/local/bin/otelcol-contrib
    otelcol_binary = "/usr/local/bin/otelcol-contrib"

    # Write config to temporary file (delete=False so subprocess can read it, cleanup in finally)
    tmp_file_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp_file:
            tmp_file.write(request.config)
            tmp_file_path = tmp_file.name

        # Run otelcol-contrib validate command
        validate_cmd = [otelcol_binary, "validate", f"--config={tmp_file_path}"]

        validate_result = subprocess.run(
            validate_cmd,
            capture_output=True,
            text=True,
            timeout=10
        )

        if validate_result.returncode == 0:
            return {
                "valid": True,
                "error": None
            }
        else:
            # Extract error message from stderr
            error_msg = validate_result.stderr.strip() or validate_result.stdout.strip()
            if not error_msg:
                error_msg = "Configuration validation failed"

            # Parse and format the error message for better readability
            formatted_errors = format_otelcol_errors(error_msg)

            return {
                "valid": False,
                "error": formatted_errors["summary"],
                "errors": formatted_errors["errors"]
            }

    except subprocess.TimeoutExpired:
        logger.warning("Validation command timed out")
        return basic_validation(parsed)
    except FileNotFoundError:
        # otelcol-contrib binary not found, fall back to basic validation
        logger.warning("otelcol-contrib binary not available, using basic validation")
        return basic_validation(parsed)
    except Exception as e:
        logger.warning(f"Error running otelcol-contrib validate: {e}, falling back to basic validation")
        return basic_validation(parsed)
    finally:
        # Clean up temp file
        if tmp_file_path:
            try:
                os.unlink(tmp_file_path)
            except (OSError, FileNotFoundError):
                pass


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
    # Validate YAML syntax
    try:
        yaml.safe_load(request.config)
    except yaml.YAMLError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid YAML configuration: {str(e)}"
        ) from e

    try:
        async with aiohttp.ClientSession() as session:
            payload = {"config": request.config}
            if request.instance_id:
                payload["instance_id"] = request.instance_id

            async with session.post(
                f"{settings.opamp_server_url}/config",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    raise HTTPException(
                        status_code=response.status,
                        detail=f"OpAMP server error: {error_text}"
                    )
    except aiohttp.ClientError as e:
        raise HTTPException(
            status_code=503,
            detail=f"OpAMP server unavailable: {str(e)}"
        ) from e


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
    except aiohttp.ClientError as e:
        raise HTTPException(
            status_code=503,
            detail=f"OpAMP server unavailable: {str(e)}"
        ) from e


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
