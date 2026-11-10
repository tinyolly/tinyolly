"""
OpenTelemetry Protocol (OTLP) utility functions for parsing attributes and resources.
Centralized to avoid code duplication across trace, log, and metric processing.
"""
import base64
import binascii
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


def normalize_id(value: Any, nbytes: int) -> str:
    """Return a trace/span id as lowercase hex, or "" when absent or malformed.

    OTLP/JSON from protobuf (MessageToDict) carries ids as base64, but the OTLP/JSON spec and many
    non-protobuf clients send hex. The two are told apart by length (16-byte ids: 32 hex vs 24 base64
    chars; 8-byte ids: 16 hex vs 12 base64 chars), so decoding unconditionally turned hex ids into garbage
    and a malformed id raised and failed the whole batch. All-zero ids are treated as absent.
    """
    if not value:
        return ""
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        return raw.hex() if len(raw) == nbytes and any(raw) else ""
    if not isinstance(value, str):
        return ""
    v = value.strip()
    if len(v) == nbytes * 2:
        try:
            raw = bytes.fromhex(v)
        except ValueError:
            raw = None
        if raw is not None:
            return raw.hex() if any(raw) else ""
    try:
        raw = base64.b64decode(v, validate=True)
    except (binascii.Error, ValueError):
        return ""
    return raw.hex() if len(raw) == nbytes and any(raw) else ""


def get_attr_value(obj: Dict[str, Any], keys: List[str]) -> Optional[Union[str, int, bool, float]]:
    """Extract an attribute value from a span/log object, trying key names in order of preference.

    Handles both the OTLP list format and the normalized dict format. The first *key* in `keys` that is
    present wins (previously the first *attribute* in the span whose key was in `keys` won, so a less
    preferred key could shadow the preferred one).

    Example:
        get_attr_value(span, ['http.method', 'http.request.method'])
    """
    attributes = obj.get('attributes', [])

    if isinstance(attributes, list):
        by_key: Dict[str, Any] = {}
        for attr in attributes:
            if not isinstance(attr, dict):
                continue
            k = attr.get('key')
            if k in keys and k not in by_key:
                val = attr.get('value', {})
                if isinstance(val, dict):
                    for vk in ('stringValue', 'intValue', 'boolValue', 'doubleValue'):
                        if vk in val:
                            by_key[k] = val[vk]
                            break
        for key in keys:
            if key in by_key:
                return by_key[key]
    elif isinstance(attributes, dict):
        for key in keys:
            if key in attributes:
                return attributes[key]

    return None


def exponential_to_explicit(dp: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an OTLP exponential-histogram datapoint to the explicit-bucket form TinyOlly stores/charts.

    Bucket i of the positive range covers (base^(offset+i), base^(offset+i+1)] with base = 2^(2^-scale).
    Result: explicitBounds = the bucket edges; bucketCounts[0] = zero + negative values (below the first
    edge), then one count per positive bucket, then a final empty overflow bucket. Counts arrive as strings
    from protobuf JSON, so everything is coerced to int/float.
    """
    scale = int(dp.get("scale", 0) or 0)
    base = 2.0 ** (2.0 ** -scale)
    pos = dp.get("positive") or {}
    offset = int(pos.get("offset", 0) or 0)
    pos_counts = [int(c) for c in (pos.get("bucketCounts") or [])]
    neg_total = sum(int(c) for c in ((dp.get("negative") or {}).get("bucketCounts") or []))
    below = int(dp.get("zeroCount", 0) or 0) + neg_total

    # trim empty edge buckets, keep interior zeros so the shape is preserved
    while pos_counts and pos_counts[-1] == 0:
        pos_counts.pop()
    lead = 0
    while lead < len(pos_counts) and pos_counts[lead] == 0:
        lead += 1
    pos_counts = pos_counts[lead:]
    offset += lead

    try:
        bounds = [base ** (offset + i) for i in range(len(pos_counts) + 1)]
    except OverflowError:
        bounds, pos_counts = [], []
    return {
        "count": int(dp.get("count", 0) or 0),
        "sum": float(dp.get("sum", 0) or 0),
        "bucketCounts": [below, *pos_counts, 0] if bounds else [below],
        "explicitBounds": bounds,
        "exponential": {"scale": scale, "zeroCount": int(dp.get("zeroCount", 0) or 0)},
        "min": dp.get("min"),
        "max": dp.get("max"),
    }
