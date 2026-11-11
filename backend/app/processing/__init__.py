from app.processing.backscatter import BackscatterProcessor, ChangeDetectionProcessor
from app.processing.base import InputProduct, ProcessContext, Processor, ProcessorOutput
from app.processing.insar import InSARProcessor
from app.processing.offsets import OffsetProcessor
from app.processing.polarimetric import PolarimetricProcessor
from app.processing.timeseries import TimeSeriesProcessor

PROCESSORS = {
    "backscatter": BackscatterProcessor,
    "change_detection": ChangeDetectionProcessor,
    "deformation": InSARProcessor,
    "polarimetric": PolarimetricProcessor,
    "offsets": OffsetProcessor,
    "timeseries": TimeSeriesProcessor,
}

__all__ = [
    "Processor",
    "ProcessContext",
    "ProcessorOutput",
    "InputProduct",
    "PROCESSORS",
    "BackscatterProcessor",
    "ChangeDetectionProcessor",
    "InSARProcessor",
    "PolarimetricProcessor",
    "OffsetProcessor",
    "TimeSeriesProcessor",
]
