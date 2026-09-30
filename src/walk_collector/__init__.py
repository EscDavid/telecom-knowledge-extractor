"""Walk collector — recolección automática de snmpwalks (SNMPv2c, SOLO LECTURA).

Genera ``docs/walks/{VENDOR}_{MODELO}[_tipo].txt`` en el formato de ``snmpbulkwalk -On``
para la Fase 2 del pipeline. Uso: ``py -m src.walk_collector --help``.
"""
from .collector import Collector, CollectorAbort
from .config import CollectorConfig, load_collector_config
from .transport import SnmpTransport

__all__ = ["Collector", "CollectorAbort", "CollectorConfig", "load_collector_config",
           "SnmpTransport"]
