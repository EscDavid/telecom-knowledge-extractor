"""Destinos de publicación de walks ensamblados.

``FileSink`` publica en ``docs/walks/`` (lo que lee la Fase 2 de ``main.py``) con
reemplazo atómico: jamás queda un ``.txt`` parcial en el directorio de publicación.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Protocol


class WalkSink(Protocol):
    def write_output(self, model_key: str, output: str, lines: Iterable[str], meta: dict) -> str:
        """Publica el output completo y devuelve su ubicación."""
        ...


class FileSink:
    def __init__(self, publish_dir: Path):
        self.publish_dir = Path(publish_dir)

    def write_output(self, model_key: str, output: str, lines: Iterable[str], meta: dict) -> str:
        name = meta.get("filename") or f"{model_key}.txt"
        self.publish_dir.mkdir(parents=True, exist_ok=True)
        final = self.publish_dir / name
        tmp = self.publish_dir / (name + ".tmp")     # *.tmp: ignorado por git y por main.py (*.txt)
        try:
            with open(tmp, "wb") as f:
                for ln in lines:
                    f.write(ln.encode("utf-8") + b"\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, final)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        return str(final)


class DbSink:
    """NO IMPLEMENTADO — diseño previsto para persistir walks en base de datos.

    Cuando se necesite, debe ser un esquema APARTE (por ejemplo ``tkc_walks``) y NUNCA
    ``ispm_tkc`` ni tablas de isp-management. Volumen esperado: ~800 mil filas por walk
    enterprise (usar carga por lotes). Los walks contienen PII de la red (seriales,
    nombres de ONU, descripciones): grants restringidos (solo INSERT/SELECT para el
    usuario del recolector) y aplicar ``redaction`` si el destino es compartido.
    """

    def write_output(self, model_key: str, output: str, lines: Iterable[str], meta: dict) -> str:
        raise NotImplementedError("DbSink no está implementado (ver docstring)")
