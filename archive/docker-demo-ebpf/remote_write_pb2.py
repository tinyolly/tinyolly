# Generated from Prometheus Remote Write v2 proto
# Simplified version for demonstration
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers

class Label(_message.Message):
    __slots__ = ('name', 'value')
    NAME_FIELD_NUMBER = 1
    VALUE_FIELD_NUMBER = 2
    name: str
    value: str
    
    def __init__(self, name: str = "", value: str = ""):
        self.name = name
        self.value = value


class Sample(_message.Message):
    __slots__ = ('value', 'timestamp')
    VALUE_FIELD_NUMBER = 1
    TIMESTAMP_FIELD_NUMBER = 2
    value: float
    timestamp: int
    
    def __init__(self, value: float = 0.0, timestamp: int = 0):
        self.value = value
        self.timestamp = timestamp


class TimeSeries(_message.Message):
    __slots__ = ('labels', 'samples')
    LABELS_FIELD_NUMBER = 1
    SAMPLES_FIELD_NUMBER = 2
    labels: _containers.RepeatedCompositeFieldContainer[Label]
    samples: _containers.RepeatedCompositeFieldContainer[Sample]
    
    def __init__(self):
        self.labels = []
        self.samples = []


class WriteRequest(_message.Message):
    __slots__ = ('timeseries',)
    TIMESERIES_FIELD_NUMBER = 1
    timeseries: _containers.RepeatedCompositeFieldContainer[TimeSeries]
    
    def __init__(self):
        self.timeseries = []
