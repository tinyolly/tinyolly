"""
OpenTelemetry Protocol (OTLP) utility functions for parsing attributes and resources.
Centralized to avoid code duplication across trace, log, and metric processing.
"""
from typing import Any, Dict, List, Optional, Union


def parse_attributes(attrs_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Parse OTLP attributes list into a dictionary.
    
    Converts OTLP attribute format (list of {key, value} objects) into a simple
    dictionary mapping attribute keys to their values.
    
    Args:
        attrs_list: List of OTLP attribute objects with 'key' and 'value' fields
        
    Returns:
        Dictionary mapping attribute keys to their parsed values
        
    Example:
        Input: [{'key': 'http.method', 'value': {'stringValue': 'GET'}}]
        Output: {'http.method': 'GET'}
    """
    if not attrs_list:
        return {}
    
    result = {}
    for attr in attrs_list:
        key = attr.get('key', '')
        value_obj = attr.get('value', {})
        
        # Extract the actual value from OTLP value object
        if 'stringValue' in value_obj:
            result[key] = value_obj['stringValue']
        elif 'intValue' in value_obj:
            result[key] = value_obj['intValue']
        elif 'doubleValue' in value_obj:
            result[key] = value_obj['doubleValue']
        elif 'boolValue' in value_obj:
            result[key] = value_obj['boolValue']
        else:
            result[key] = str(value_obj)
    
    return result


def extract_resource_attributes(resource: Dict[str, Any]) -> Dict[str, Any]:
    """Extract resource attributes from OTLP resource object.
    
    Args:
        resource: OTLP resource object containing 'attributes' field
        
    Returns:
        Dictionary of resource attributes
    """
    if not resource:
        return {}
    
    attributes = resource.get('attributes', [])
    return parse_attributes(attributes)


def is_error_status(status: Any) -> bool:
    """True if an OTLP span status is an error.

    OTLP JSON from protobuf carries the enum name (``STATUS_CODE_ERROR``) or the number (2), depending on the
    path the data took, so accept both.
    """
    if not isinstance(status, dict):
        return False
    code = status.get("code")
    return code == 2 or code == "2" or code in ("STATUS_CODE_ERROR", "ERROR")


def get_attr_value(obj: Dict[str, Any], keys: List[str]) -> Optional[Union[str, int, bool, float]]:
    """Extract attribute value from span/log object by trying multiple key names.
    
    Handles both OTLP list format and normalized dict format for attributes.
    Tries keys in order and returns the first match found.
    
    Args:
        obj: Span or log object containing attributes
        keys: List of attribute keys to try (in order of preference)
        
    Returns:
        First matching attribute value or None if not found
        
    Example:
        get_attr_value(span, ['http.method', 'http.request.method'])
        # Returns 'GET' if either key exists
    """
    attributes = obj.get('attributes', [])
    
    # Handle OTLP list of dicts format
    if isinstance(attributes, list):
        for attr in attributes:
            if attr.get('key') in keys:
                val = attr.get('value', {})
                # Return the first non-null value found
                for k in ['stringValue', 'intValue', 'boolValue', 'doubleValue']:
                    if k in val:
                        return val[k]
    
    # Handle dict format (if normalized)
    elif isinstance(attributes, dict):
        for key in keys:
            if key in attributes:
                return attributes[key]
    
    return None

