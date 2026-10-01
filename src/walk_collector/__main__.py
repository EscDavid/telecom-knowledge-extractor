"""CLI del recolector: ``py -m src.walk_collector [opciones]``.

Recolecta por SNMPv2c (SOLO LECTURA) los walks de una OLT y los publica en docs/walks/.
Códigos de salida: 0 completo · 1 con tareas failed/partial · 2 uso/config ·
3 detenido (reanudable) · 4 preflight/auth/modelo · 5 E/S · 130 interrumpido.
"""
from __future__ import annotations

import argparse
import dataclasses
import getpass
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Callable

from .collector import Collector, CollectorAbort
from .config import (DEFAULT_CONFIG, MAX_REPETITIONS_HARD_CAP, REPO_ROOT, CollectorConfig,
                     ConfigError, env_presence, load_collector_config, load_credentials,
                     lower_max_repetitions)
from .report import compute_result
from .secrets import Scrubber, install_scrubber
from .transport import SnmpTransport

log = logging.getLogger("tkc.walk_collector.cli")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="py -m src.walk_collector",
        description="Recolector de snmpwalks (SNMPv2c, solo lectura) para la Fase 2 de TKC.")
    p.add_argument("--config", default=str(DEFAULT_CONFIG), help="pipeline.yaml (default: config/pipeline.yaml)")
    p.add_argument("--dry-run", action="store_true",
                   help="valida config y presencia de credenciales, imprime el plan; NO usa la red")
    p.add_argument("--discover-only", action="store_true",
                   help="preflight + descubrimiento de ramas; guarda el plan y sale")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--resume", action="store_true", help="retoma la corrida guardada")
    g.add_argument("--fresh", action="store_true", help="archiva el estado previo y empieza de cero")
    p.add_argument("--only", action="append", default=[], metavar="X",
                   help="solo un output (enterprise|entities|ifnames) o un prefijo OID; repetible")
    p.add_argument("--retry-failed", action="store_true", help="con --resume: reintenta tareas failed")
    p.add_argument("--assemble-only", action="store_true",
                   help="re-ensambla/publica desde los fragmentos (sin red)")
    p.add_argument("--no-publish", action="store_true", help="ensambla pero no publica en docs/walks/")
    p.add_argument("--allow-incomplete", action="store_true",
                   help="publica también outputs incompletos (encabezado status:INCOMPLETE)")
    p.add_argument("--max-repetitions", type=int, metavar="N",
                   help=f"solo puede BAJAR max-repetitions (tope duro {MAX_REPETITIONS_HARD_CAP})")
    p.add_argument("--pace-ms", type=float, metavar="N", help="pausa entre PDUs en ms (aviso si < 20)")
    p.add_argument("--max-runtime", type=float, metavar="MIN", help="detiene (reanudable) tras N minutos")
    p.add_argument("--force-model", action="store_true", help="ignora expect_sysdescr_regex")
    p.add_argument("--force", action="store_true", help="reanuda aunque cambie target/config")
    p.add_argument("--no-prompt", action="store_true", help="falla en vez de pedir la community por prompt")
    p.add_argument("--redact", choices=["none", "prefixes"], help="redacción de PII al ensamblar")
    p.add_argument("--state-dir", help="directorio base del estado (default: paths.state_dir)")
    p.add_argument("--out-dir", help="directorio de publicación (default: paths.publish_dir)")
    p.add_argument("--simulate", action="store_true",
                   help="usa un agente FALSO en memoria (nunca toca la red ni docs/walks/)")
    v = p.add_mutually_exclusive_group()
    v.add_argument("-v", "--verbose", action="store_true")
    v.add_argument("-q", "--quiet", action="store_true")
    return p


def _setup_logging(verbose: bool, quiet: bool) -> None:
    level = logging.DEBUG if verbose else (logging.WARNING if quiet else logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    if not any(getattr(h, "_tkc_cli", False) for h in root.handlers):
        h = logging.StreamHandler(sys.stdout)
        h._tkc_cli = True
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        root.addHandler(h)


def _apply_args(cfg: CollectorConfig, args) -> CollectorConfig:
    if args.max_repetitions is not None:
        cfg = lower_max_repetitions(cfg, args.max_repetitions)
    if args.pace_ms is not None:
        if args.pace_ms < 20:
            log.warning("--pace-ms %.0f es agresivo (< 20 ms): riesgo de saturar la CPU de la OLT",
                        args.pace_ms)
        cfg = dataclasses.replace(cfg, pacing=dataclasses.replace(
            cfg.pacing, inter_request_delay_ms=max(0.0, args.pace_ms)))
    paths = cfg.paths
    if args.state_dir:
        paths = dataclasses.replace(paths, state_dir=Path(os.path.expandvars(args.state_dir)).expanduser())
    if args.out_dir:
        paths = dataclasses.replace(paths, publish_dir=Path(os.path.expandvars(args.out_dir)).expanduser())
    cfg = dataclasses.replace(cfg, paths=paths)
    if args.allow_incomplete:
        cfg = dataclasses.replace(cfg, allow_incomplete=True)
    if args.redact:
        cfg = dataclasses.replace(cfg, redaction=dataclasses.replace(cfg.redaction, mode=args.redact))
        if args.redact == "prefixes" and not cfg.redaction.prefixes:
            log.warning("--redact prefixes sin prefijos en walk_collector.redaction.prefixes: no se redacta nada")
    return cfg


def _print_dry_run(cfg: CollectorConfig, collector: Collector, only, env_ok: dict[str, bool]) -> None:
    p = print
    p(f"Modelo: {cfg.vendor} {cfg.model}  (sysDescr esperado: /{cfg.expect_sysdescr_regex}/)")
    p("Credenciales (solo presencia, nunca el valor):")
    for name, ok in env_ok.items():
        p(f"  {name}: {'presente' if ok else 'FALTA'}")
    p("Plan (las ramas con discover se expanden con GETNEXT durante la corrida):")
    for sp in collector.plan(only):
        p(f"  - {sp.output:<10} {'.' + '.'.join(map(str, sp.root))}")
    s, pc, r, o, sf = cfg.snmp, cfg.pacing, cfg.retry, cfg.outage, cfg.safety
    p("Ritmo y límites:")
    p(f"  una sola petición en vuelo; {pc.inter_request_delay_ms:g} ms entre PDUs; "
      f"{pc.inter_task_delay_s:g} s entre tareas")
    p(f"  max-repetitions {s.max_repetitions} (tope duro {MAX_REPETITIONS_HARD_CAP}); "
      f"timeout {s.timeout_s:g} s x {r.max_attempts_per_request} intentos; backoff "
      f"{r.backoff_base_s:g}..{r.backoff_max_s:g} s")
    p(f"  checkpoint cada {pc.checkpoint_every_requests} PDUs o {pc.checkpoint_every_s:g} s")
    p(f"  caída: esperas {list(o.wait_s)} s, máximo {o.max_outage_min:g} min; "
      f"kill-switch de latencia: x{sf.degrade_factor:g} (mín. {sf.degrade_min_ms:g} ms), "
      f"{sf.max_safety_pauses} pausas de {sf.pause_s:g} s")
    p(f"  estado: {cfg.run_dir}")
    p(f"  publicación: {cfg.paths.publish_dir}"
      f"{'  (incompletos permitidos)' if cfg.allow_incomplete else '  (solo outputs completos)'}")
    p("DRY-RUN: no se abrió ninguna conexión de red.")


def main(argv: list[str] | None = None,
         transport_factory: Callable[[], SnmpTransport] | None = None,
         *, load_env: bool = True, clock=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose, args.quiet)
    if args.retry_failed and not args.resume:
        print("error: --retry-failed requiere --resume", file=sys.stderr)
        return 2
    if load_env:
        try:
            from dotenv import load_dotenv
            load_dotenv(REPO_ROOT / ".env", override=False)
        except ImportError:
            log.warning("python-dotenv no instalado: se usan solo las variables del entorno")
    try:
        cfg = _apply_args(load_collector_config(args.config), args)
    except ConfigError as exc:
        print(f"error de configuración: {exc}", file=sys.stderr)
        return 2

    # clock inyectable (tests); --simulate usa un reloj virtual propio
    factory = transport_factory
    creds = None
    scrubber = Scrubber()
    if args.simulate:
        from .testing import FakeClock, FakeTransport, make_fake_agent
        clock = FakeClock()
        agent = make_fake_agent()
        factory = lambda: FakeTransport(agent, (), clock)   # noqa: E731
        base = cfg.paths.state_dir / "simulate"
        pub = Path(args.out_dir) if args.out_dir else base / "walks_out"
        cfg = dataclasses.replace(cfg, paths=dataclasses.replace(cfg.paths, state_dir=base, publish_dir=pub))
        print("SIMULACION: agente falso en memoria; no se usa la red y no se publica en docs/walks/.")

    if args.dry_run:
        def _never():  # el factory jamás debe invocarse en dry-run
            raise AssertionError("dry-run: no se abre transporte")
        collector = Collector(cfg, _never)
        env_ok = env_presence(cfg)
        _print_dry_run(cfg, collector, args.only, env_ok)
        return 0 if (env_ok[cfg.snmp.host_env] or args.simulate) else 2

    needs_network = not args.assemble_only and not args.simulate and transport_factory is None
    needs_creds = not args.assemble_only and not args.simulate
    try:
        if needs_creds:
            creds = load_credentials(cfg, no_prompt=args.no_prompt, getpass=getpass.getpass)
            scrubber = Scrubber([creds.community])
            install_scrubber(scrubber)
            print(f"Objetivo: {creds.masked_host()}:{creds.port} (SNMPv2c, solo lectura)")
        if needs_network:
            from .pysnmp_transport import PysnmpTransport
            factory = lambda: PysnmpTransport(   # noqa: E731
                creds.host, creds.port, creds.community, cfg.snmp.timeout_s, scrubber)
    except ConfigError as exc:
        print(f"error: {scrubber.scrub(str(exc))}", file=sys.stderr)
        return 2

    if factory is None:                                     # assemble-only: sin red
        def factory():
            raise AssertionError("assemble-only: no se abre transporte")
    collector = Collector(cfg, factory, clock, target_id=creds.target_id if creds else "simulated",
                          scrubber=scrubber, publish=not args.no_publish,
                          allow_incomplete=cfg.allow_incomplete)

    previous = None
    if threading_main():
        def on_sigint(signum, frame):
            if collector._stop_flag:
                raise KeyboardInterrupt
            print("\nCtrl+C: terminando el PDU en curso y guardando estado (otra vez para forzar)...")
            collector.request_stop()
        try:
            previous = signal.signal(signal.SIGINT, on_sigint)
        except (ValueError, OSError):
            previous = None
    try:
        if args.assemble_only:
            collector.assemble_only()
        else:
            max_runtime = args.max_runtime * 60 if args.max_runtime else None
            collector.run(resume=args.resume, fresh=args.fresh, only=args.only,
                          retry_failed=args.retry_failed, discover_only=args.discover_only,
                          force_model=args.force_model, force=args.force, max_runtime_s=max_runtime)
    except CollectorAbort as exc:
        print(f"ABORTADO (código {exc.exit_code}): {scrubber.scrub(str(exc))}", file=sys.stderr)
        return exc.exit_code
    except ConfigError as exc:
        print(f"error: {scrubber.scrub(str(exc))}", file=sys.stderr)
        return 2
    finally:
        if previous is not None:
            signal.signal(signal.SIGINT, previous)
    print_summary(collector)
    return collector.exit_code if collector.exit_code is not None else 0


def print_summary(collector: Collector) -> None:
    st = collector.state
    print(f"\nResultado: {compute_result(st)} (fase {st.phase}"
          + (f", motivo: {st.stop_reason}" if st.stop_reason else "") + ")")
    for a in collector.assemblies:
        estado = "COMPLETO" if a.complete else "INCOMPLETO"
        pub = f"publicado en {a.location}" if a.published else "NO publicado"
        print(f"  {a.output:<10} {estado:<10} {a.rows:>8} filas  {pub}")
    print(f"Estado y reportes en: {collector.store.dir}")
    if st.phase == "stopped":
        print("Para continuar: py -m src.walk_collector --resume")


def threading_main() -> bool:
    import threading
    return threading.current_thread() is threading.main_thread()


if __name__ == "__main__":
    raise SystemExit(main())
