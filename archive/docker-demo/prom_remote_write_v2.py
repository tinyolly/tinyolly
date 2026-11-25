"""
Prometheus Remote Write v2 Protocol Implementation
Sends metrics to OpenTelemetry Collector's prometheusremotewrite receiver

This implements the v2 protocol (io.prometheus.write.v2.Request) which uses
symbol tables for label names and values.
"""
import snappy
import requests
import struct
from typing import List, Dict, Any


def encode_varint(value: int) -> bytes:
    """Encode an integer as a protobuf varint"""
    result = bytearray()
    while value > 0x7f:
        result.append((value & 0x7f) | 0x80)
        value >>= 7
    result.append(value & 0x7f)
    return bytes(result)


def encode_string(field_num: int, value: str) -> bytes:
    """Encode a string field (wire type 2)"""
    encoded_value = value.encode('utf-8')
    return (encode_varint((field_num << 3) | 2) +
            encode_varint(len(encoded_value)) +
            encoded_value)


def encode_double(field_num: int, value: float) -> bytes:
    """Encode a double field (wire type 1)"""
    return (encode_varint((field_num << 3) | 1) +
            struct.pack('<d', value))


def encode_int64(field_num: int, value: int) -> bytes:
    """Encode an int64 field as varint (wire type 0)"""
    return encode_varint((field_num << 3) | 0) + encode_varint(value)


def encode_uint32(field_num: int, value: int) -> bytes:
    """Encode a uint32 field as varint (wire type 0)"""
    return encode_varint((field_num << 3) | 0) + encode_varint(value)


def encode_message(field_num: int, data: bytes) -> bytes:
    """Encode a nested message field (wire type 2)"""
    return (encode_varint((field_num << 3) | 2) +
            encode_varint(len(data)) +
            data)


def encode_sample_v2(value: float, timestamp: int) -> bytes:
    """
    Encode a v2 Sample message:
    message Sample {
      double value = 1;
      int64 timestamp = 2;
    }
    """
    result = bytearray()
    result.extend(encode_double(1, value))
    result.extend(encode_int64(2, timestamp))
    return bytes(result)


def encode_timeseries_v2(labels_refs: List[int], samples: List[Dict[str, Any]]) -> bytes:
    """
    Encode a v2 TimeSeries message:
    message TimeSeries {
      repeated uint32 labels_refs = 1;  // indices into symbols array
      repeated Sample samples = 2;
    }
    """
    result = bytearray()

    # Encode labels_refs (field 1) - packed repeated uint32
    if labels_refs:
        # For packed encoding, we encode all values together
        packed = bytearray()
        for ref in labels_refs:
            packed.extend(encode_varint(ref))
        result.extend(encode_varint((1 << 3) | 2))  # Field 1, wire type 2 (length-delimited for packed)
        result.extend(encode_varint(len(packed)))
        result.extend(packed)

    # Encode samples (field 2)
    for sample in samples:
        sample_bytes = encode_sample_v2(sample['value'], sample['timestamp'])
        result.extend(encode_message(2, sample_bytes))

    return bytes(result)


def encode_write_request_v2(timeseries_list: List[Dict[str, Any]]) -> bytes:
    """
    Encode a v2 WriteRequest message:
    message Request {
      reserved 1 to 3;
      repeated string symbols = 4;  // de-duplicated string table
      repeated TimeSeries timeseries = 5;
    }

    In v2, labels are stored as indices into the symbols array.
    The symbols array MUST start with an empty string.
    """
    result = bytearray()

    # Build symbol table from all labels
    symbols = [""]  # Must start with empty string
    symbol_to_idx = {"": 0}

    def get_or_add_symbol(s: str) -> int:
        if s in symbol_to_idx:
            return symbol_to_idx[s]
        idx = len(symbols)
        symbols.append(s)
        symbol_to_idx[s] = idx
        return idx

    # First pass: collect all symbols and build label refs
    timeseries_data = []
    for ts in timeseries_list:
        labels = ts['labels']
        # Sort labels lexicographically by name (required by spec)
        sorted_labels = sorted(labels.items(), key=lambda x: x[0])

        # Build label refs (alternating name_ref, value_ref)
        labels_refs = []
        for name, value in sorted_labels:
            labels_refs.append(get_or_add_symbol(name))
            labels_refs.append(get_or_add_symbol(value))

        timeseries_data.append({
            'labels_refs': labels_refs,
            'samples': ts['samples']
        })

    # Encode symbols (field 4)
    for symbol in symbols:
        result.extend(encode_string(4, symbol))

    # Encode timeseries (field 5)
    for ts_data in timeseries_data:
        ts_bytes = encode_timeseries_v2(ts_data['labels_refs'], ts_data['samples'])
        result.extend(encode_message(5, ts_bytes))

    return bytes(result)


class PrometheusRemoteWriteV2Client:
    """Client for sending metrics via Prometheus Remote Write v2 protocol"""

    def __init__(self, url: str):
        self.url = url
        self.session = requests.Session()

    def send(self, timeseries: List[Dict[str, Any]]) -> requests.Response:
        """
        Send time series data via Remote Write v2

        Args:
            timeseries: List of dicts with 'labels' and 'samples' keys
                       labels: Dict[str, str] - metric labels including '__name__'
                       samples: List[Dict] - each with 'value' (float) and 'timestamp' (int, milliseconds)

        Returns:
            Response object from the HTTP POST
        """
        # Encode the protobuf message (v2 format with symbol table)
        proto_data = encode_write_request_v2(timeseries)

        # Compress with snappy (block format, not framed)
        compressed_data = snappy.compress(proto_data)

        # Set headers for Remote Write v2 (io.prometheus.write.v2.Request)
        headers = {
            'Content-Encoding': 'snappy',
            'Content-Type': 'application/x-protobuf;proto=io.prometheus.write.v2.Request',
            'User-Agent': 'tinyolly-demo/1.0',
            'X-Prometheus-Remote-Write-Version': '2.0.0',
        }

        # Send the request
        response = self.session.post(self.url, headers=headers, data=compressed_data)
        response.raise_for_status()
        return response
