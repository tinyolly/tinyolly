"""OpenTelemetry Collector configuration validation"""

import re


def format_otelcol_errors(error_msg: str) -> dict:
    """Parse and format otelcol-contrib validation errors for better readability"""
    errors = []
    lines = error_msg.split('\n')
    
    # Remove duplicate error blocks (otelcol sometimes repeats errors)
    # Look for timestamp patterns and remove everything after them
    cleaned_lines = []
    seen_timestamp = False
    for line in lines:
        # Check if this line contains a timestamp (indicates duplicate section)
        if re.search(r'\d{2}:\d{2}:\d{2}', line):
            seen_timestamp = True
            break
        if not seen_timestamp:
            cleaned_lines.append(line)
    
    if cleaned_lines:
        error_msg = '\n'.join(cleaned_lines)
        lines = error_msg.split('\n')

    # Common otelcol error patterns
    # Pattern 1: "'section' has invalid keys: key1, key2, ..."
    invalid_keys_pattern = r"'([^']+)' has invalid keys:\s*(.+)$"
    
    # Pattern 2: "error reading configuration for "component": ..."
    component_error_pattern = r'error reading configuration for\s+"([^"]+)":\s*(.+)$'
    
    # Pattern 3: "error decoding 'section': message"
    error_decoding_pattern = r"error decoding '([^']+)':\s*(.+?)(?:\s*\(valid values:\s*\[([^\]]+)\]\))?$"
    
    # Pattern 4: "unknown type: "type" for id: "id""
    unknown_type_pattern = r'unknown type:\s*"([^"]+)"\s*for id:\s*"([^"]+)"'
    
    # Pattern 5: "invalid character(s) in type "type""
    invalid_char_pattern = r'invalid character\(s\) in type\s+"([^"]+)"'
    
    # Track current component type and name for context
    current_component_type = None
    current_component_name = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Track component type (receivers:, exporters:, etc.) - can be at start of line
        # Pattern: "receivers: error reading configuration"
        match = re.match(r'^(\w+):\s*error reading configuration', line, re.IGNORECASE)
        if match:
            current_component_type = match.group(1)
            # Also try to extract component name from same line if present
            name_match = re.search(r'error reading configuration for\s+"([^"]+)"', line, re.IGNORECASE)
            if name_match:
                current_component_name = name_match.group(1)
            continue

        # Pattern 2: "error reading configuration for "component": ..." (standalone)
        match = re.search(component_error_pattern, line, re.IGNORECASE)
        if match:
            current_component_name = match.group(1)
            # The error details will be on subsequent lines
            continue

        # Pattern 1: "configuration: 'section' has invalid keys: key1, key2"
        # Or just: "'section' has invalid keys: key1, key2"
        # This is the actual error we want to capture
        match = re.search(invalid_keys_pattern, line, re.IGNORECASE)
        if match:
            section = match.group(1)
            invalid_keys = match.group(2).strip()
            
            # Build full section path
            if current_component_type and current_component_name:
                if section:
                    # Handle nested paths like 'protocols.http' - remove quotes
                    section_path = section.strip("'\"")
                    full_section = f"{current_component_type}.{current_component_name}.{section_path}"
                else:
                    full_section = f"{current_component_type}.{current_component_name}"
            elif current_component_type:
                section_path = section.strip("'\"") if section else ""
                full_section = f"{current_component_type}.{section_path}" if section_path else current_component_type
            else:
                section_path = section.strip("'\"") if section else ""
                full_section = section_path if section_path else "configuration"
            
            errors.append({
                "section": full_section,
                "message": f"Invalid keys: {invalid_keys}"
            })
            continue

        # Pattern 3: "error decoding 'section': message"
        match = re.search(error_decoding_pattern, line, re.IGNORECASE)
        if match:
            section = match.group(1)
            message = match.group(2).strip()
            valid_values_str = match.group(3) if match.group(3) else None
            
            # Build full section path
            if current_component_type and current_component_name:
                full_section = f"{current_component_type}.{current_component_name}.{section}" if section else f"{current_component_type}.{current_component_name}"
            elif current_component_type:
                full_section = f"{current_component_type}.{section}" if section else current_component_type
            else:
                full_section = section if section else "configuration"
            
            # Clean up message
            message = message.rstrip().rstrip('(').strip()
            
            if message and len(message.strip()) > 1:
                error_entry = {
                    "section": full_section,
                    "message": message
                }
                
                if valid_values_str:
                    values_list = [v.strip().strip('"\'') for v in valid_values_str.split(',')]
                    error_entry["valid_values"] = values_list[:10]
                    error_entry["total_valid"] = len(values_list)
                
                errors.append(error_entry)
            continue

        # Pattern 4: "unknown type: "type" for id: "id""
        match = re.search(unknown_type_pattern, line, re.IGNORECASE)
        if match:
            component_type = match.group(1)
            component_id = match.group(2)
            
            # Determine section based on context or component type
            if current_component_type:
                section = f"{current_component_type}.{component_id}"
            else:
                # Try to infer from component type name
                if any(t in component_type.lower() for t in ['processor', 'exporter', 'receiver', 'connector']):
                    section = component_type
                else:
                    section = "service.pipelines"
            
            errors.append({
                "section": section,
                "message": f"Unknown type '{component_type}' for component '{component_id}'"
            })
            continue

        # Pattern 5: "invalid character(s) in type "type""
        match = re.search(invalid_char_pattern, line, re.IGNORECASE)
        if match:
            invalid_type = match.group(1)
            errors.append({
                "section": "service.pipelines",
                "message": f"Invalid pipeline name: '{invalid_type}' (contains invalid characters)"
            })
            continue

        # Skip generic error lines that are just context
        if any(skip in line.lower() for skip in ['decoding failed', 'due to the following', 'error(s):']):
            continue

    # If no structured errors found, return the raw message cleaned up
    if not errors:
        # Clean up the message - remove timestamps and duplicate content
        clean_msg = re.sub(r'\d{4}[/-]\d{2}[/-]\d{2}.*?\s+', '', error_msg).strip()
        clean_msg = re.sub(r'^Error:\s*', '', clean_msg, flags=re.IGNORECASE)
        # Remove generic error wrapper messages
        clean_msg = re.sub(r'^failed to get config:\s*', '', clean_msg, flags=re.IGNORECASE)
        clean_msg = re.sub(r'^cannot unmarshal the configuration:\s*', '', clean_msg, flags=re.IGNORECASE)
        clean_msg = re.sub(r'decoding failed due to the following error\(s\):\s*', '', clean_msg, flags=re.IGNORECASE)
        # Take first meaningful line
        for line in clean_msg.split('\n'):
            line = line.strip()
            if line and len(line) > 3 and not any(skip in line.lower() for skip in ['error(s):', 'decoding failed']):
                errors.append({
                    "section": "configuration",
                    "message": line[:200]
                })
                break

    # Build summary
    if len(errors) == 1:
        summary = f"{errors[0]['section']}: {errors[0]['message']}"
    elif len(errors) > 1:
        summary = f"{len(errors)} configuration errors found"
    else:
        summary = "Configuration validation failed"

    return {
        "summary": summary,
        "errors": errors
    }


def basic_validation(parsed: dict):
    """Fallback basic validation when otelcol validate is not available"""
    if not isinstance(parsed, dict):
        return {"valid": False, "error": "Configuration must be a YAML mapping"}

    # Check for required top-level sections
    required_sections = ['receivers', 'exporters', 'service']
    missing = [section for section in required_sections if section not in parsed]
    
    if missing:
        return {
            "valid": False,
            "error": f"Missing required sections: {', '.join(missing)}"
        }
    
    # Check service.pipelines structure
    if 'service' in parsed:
        service = parsed['service']
        if not isinstance(service, dict) or 'pipelines' not in service:
            return {
                "valid": False,
                "error": "Service section is missing 'pipelines'"
            }
        
        pipelines = service.get('pipelines', {})
        if not pipelines or not isinstance(pipelines, dict):
            return {
                "valid": False,
                "error": "No pipelines defined in service section"
            }
        
        # Check each pipeline has required fields
        for pipeline_name, pipeline_config in pipelines.items():
            if not isinstance(pipeline_config, dict):
                return {
                    "valid": False,
                    "error": f"Pipeline '{pipeline_name}' has invalid structure"
                }
            
            # Receivers and exporters are required, processors are optional
            required_pipeline_fields = ['receivers', 'exporters']
            for field in required_pipeline_fields:
                if field not in pipeline_config:
                    return {
                        "valid": False,
                        "error": f"Pipeline '{pipeline_name}' is missing '{field}'"
                    }
            
            # Processors are optional, but if present should be a list
            if 'processors' in pipeline_config and not isinstance(pipeline_config['processors'], list):
                return {
                    "valid": False,
                    "error": f"Pipeline '{pipeline_name}' has invalid 'processors' field (must be a list)"
                }
    
    return {
        "valid": True,
        "error": None,
        "warning": "Using basic validation (otelcol validate not available)"
    }
