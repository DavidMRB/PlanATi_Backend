"""Copias de seguridad locales de PostgreSQL (MVP local; plan de la fase 2, sección 9.4.1).

Uso (desde la carpeta PlanATi_Backend, con la base levantada con `docker compose up -d`):

    python -m scripts.backup_db create [--tag pre-0010]   # nueva copia
    python -m scripts.backup_db list                      # copias disponibles, con fecha y tamaño
    python -m scripts.backup_db restore backups/planati-20261112-1830-pre-0010.dump [--target planati_restore]
    python -m scripts.backup_db prune [--keep 10]         # borra las más antiguas sin etiqueta

- `create` ejecuta `pg_dump -Fc --no-owner` dentro del contenedor de Docker Compose y guarda el
  volcado en `backups/planati-AAAAMMDD-HHMM[-etiqueta].dump` (fuera del volumen de Docker). Si
  Docker no está disponible pero `pg_dump` sí, usa la conexión de DATABASE_URL. Al terminar
  ejecuta `prune`.
- `restore` usa `pg_restore --clean --if-exists --no-owner`. Sin `--target` sobrescribe la base
  principal y pide escribir RESTAURAR; con `--target` crea esa base (si no existe) y restaura ahí,
  sin tocar la actual. Al terminar muestra la revisión de Alembic y el conteo de filas.
- `prune` conserva las BACKUP_KEEP copias sin etiqueta más recientes y **todas** las etiquetadas.

Variables (entorno o `.env`): BACKUP_DIR=backups, BACKUP_KEEP=10,
BACKUP_DOCKER_CONTAINER=planati-postgres. Usuario, contraseña y base salen de DATABASE_URL.

Cuándo hacer copia: antes de `alembic upgrade head` (`create --tag pre-<revisión>`), antes de
`seed_demo down` o de pruebas destructivas (`--tag pre-pruebas`), antes de `docker compose down -v`
(`--tag pre-docker`) y una vez por semana si hay datos que costó crear. Las copias contienen datos
personales de cuentas de prueba: `backups/` está en `.gitignore`.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKUP_PREFIX = "planati"
BACKUP_NAME_RE = re.compile(
    rf"^{BACKUP_PREFIX}-(?P<date>\d{{8}})-(?P<time>\d{{4}}|\d{{6}})(?:-(?P<tag>[a-z0-9][a-z0-9._-]*))?\.dump$"
)
DATABASE_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
CONFIRMATION_WORD = "RESTAURAR"


class BackupError(Exception):
    """Error con un mensaje claro para el usuario; el script termina con código 1."""


class BackupConfig(BaseSettings):
    """Variables propias del script (no forman parte de los Settings de la API)."""

    dir: str = "backups"
    keep: int = 10
    docker_container: str = "planati-postgres"

    model_config = SettingsConfigDict(env_prefix="BACKUP_", env_file=PROJECT_ROOT / ".env", extra="ignore")

    @property
    def backup_dir(self) -> Path:
        path = Path(self.dir)
        return path if path.is_absolute() else PROJECT_ROOT / path


# --- Nombres y retención (funciones puras, probadas en tests/test_backup_retention.py) ---------


@dataclass(frozen=True)
class BackupName:
    filename: str
    created_at: datetime
    tag: str | None


def normalize_tag(tag: str) -> str:
    """Etiqueta segura para un nombre de archivo: minúsculas, dígitos, '.', '_' y '-'."""
    normalized = re.sub(r"[^a-z0-9._-]+", "-", tag.strip().lower()).strip("-._")
    if not normalized:
        raise BackupError("La etiqueta debe contener letras o números (por ejemplo: pre-0010).")
    return normalized


def build_backup_name(created_at: datetime, tag: str | None = None, *, with_seconds: bool = False) -> str:
    stamp = created_at.strftime("%Y%m%d-%H%M%S" if with_seconds else "%Y%m%d-%H%M")
    suffix = f"-{normalize_tag(tag)}" if tag else ""
    return f"{BACKUP_PREFIX}-{stamp}{suffix}.dump"


def parse_backup_name(filename: str) -> BackupName | None:
    """Interpreta un nombre generado por este script; cualquier otro archivo devuelve None."""
    match = BACKUP_NAME_RE.match(filename)
    if match is None:
        return None
    time_format = "%H%M%S" if len(match["time"]) == 6 else "%H%M"
    try:
        created_at = datetime.strptime(f"{match['date']}{match['time']}", f"%Y%m%d{time_format}")
    except ValueError:
        return None
    return BackupName(filename=filename, created_at=created_at, tag=match["tag"])


def select_backups_to_delete(filenames: Iterable[str], keep: int) -> list[str]:
    """Copias que sobran: todas las sin etiqueta salvo las `keep` más recientes.

    Las etiquetadas (pre-0010, pre-docker...) nunca se borran automáticamente, y los archivos que
    no siguen el patrón de nombres se ignoran.
    """
    untagged = [backup for name in filenames if (backup := parse_backup_name(name)) and backup.tag is None]
    untagged.sort(key=lambda backup: (backup.created_at, backup.filename), reverse=True)
    return sorted(backup.filename for backup in untagged[max(keep, 0):])


# --- Conexión con PostgreSQL -------------------------------------------------------------------


@dataclass(frozen=True)
class Database:
    user: str
    password: str | None
    host: str
    port: int
    name: str


def database_from_settings() -> Database:
    from sqlalchemy.engine import make_url

    from app.core.config import settings

    url = make_url(settings.database_url)
    if not url.username or not url.database:
        raise BackupError("DATABASE_URL debe incluir usuario y nombre de la base.")
    return Database(
        user=url.username,
        password=url.password,
        host=url.host or "localhost",
        port=url.port or 5432,
        name=url.database,
    )


class PgRunner:
    """Ejecuta las herramientas de PostgreSQL dentro del contenedor o, si no hay Docker, en local."""

    def __init__(self, config: BackupConfig, database: Database) -> None:
        self.config = config
        self.database = database
        self.mode = self._detect_mode()

    def _detect_mode(self) -> str:
        container = self.config.docker_container
        has_local_tools = shutil.which("pg_dump") is not None
        if shutil.which("docker"):
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", container],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip() == "true":
                return "docker"
            if has_local_tools:
                return "local"
            if result.returncode != 0:
                raise BackupError(
                    f"No se encontró el contenedor '{container}' o Docker no está corriendo. "
                    "Abre Docker Desktop y ejecuta: docker compose up -d"
                )
            raise BackupError(f"El contenedor '{container}' no está corriendo. Inícialo con: docker compose up -d")
        if has_local_tools:
            return "local"
        raise BackupError("No se encontró Docker ni pg_dump. Instala Docker Desktop (recomendado) o las herramientas de PostgreSQL.")

    @property
    def env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.database.password:
            # En modo Docker, `-e PGPASSWORD` sin valor lo toma de este entorno: no aparece en la línea de comandos.
            env["PGPASSWORD"] = self.database.password
        return env

    def command(self, tool: str, *args: str, stdin: bool = False) -> list[str]:
        if self.mode == "docker":
            prefix = ["docker", "exec"]
            if stdin:
                prefix.append("-i")
            if self.database.password:
                prefix += ["-e", "PGPASSWORD"]
            return [*prefix, self.config.docker_container, tool, "-U", self.database.user, *args]
        return [tool, "-h", self.database.host, "-p", str(self.database.port), "-U", self.database.user, *args]

    def psql(self, database: str, sql: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.command("psql", "-d", database, "-v", "ON_ERROR_STOP=1", "-X", "-A", "-t", "-F", "|", "-c", sql),
            capture_output=True,
            text=True,
            env=self.env,
        )


# --- Comandos ----------------------------------------------------------------------------------


def _format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size} B"


def _existing_backups(config: BackupConfig) -> list[Path]:
    if not config.backup_dir.is_dir():
        return []
    return [path for path in config.backup_dir.iterdir() if path.is_file() and parse_backup_name(path.name)]


def create_backup(config: BackupConfig, tag: str | None) -> Path:
    database = database_from_settings()
    runner = PgRunner(config, database)
    config.backup_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    target = config.backup_dir / build_backup_name(now, tag)
    if target.exists():
        target = config.backup_dir / build_backup_name(now, tag, with_seconds=True)
    partial = target.with_name(target.name + ".partial")

    print(f"Creando copia de '{database.name}' ({'Docker: ' + config.docker_container if runner.mode == 'docker' else 'pg_dump local'})...")
    with partial.open("wb") as output:
        result = subprocess.run(
            runner.command("pg_dump", "--format=custom", "--no-owner", f"--dbname={database.name}"),
            stdout=output,
            stderr=subprocess.PIPE,
            env=runner.env,
        )
    if result.returncode != 0 or partial.stat().st_size == 0:
        partial.unlink(missing_ok=True)
        detail = result.stderr.decode("utf-8", errors="replace").strip() or "el volcado quedó vacío"
        raise BackupError(f"pg_dump falló: {detail}")
    partial.replace(target)
    print(f"Copia creada: {target.relative_to(PROJECT_ROOT) if target.is_relative_to(PROJECT_ROOT) else target} "
          f"({_format_size(target.stat().st_size)})")
    prune_backups(config, config.keep)
    return target


def list_backups(config: BackupConfig) -> None:
    backups = sorted(
        ((parse_backup_name(path.name), path) for path in _existing_backups(config)),
        key=lambda item: item[0].created_at,
        reverse=True,
    )
    if not backups:
        print(f"No hay copias en {config.backup_dir}.")
        return
    print(f"Copias en {config.backup_dir}:")
    for info, path in backups:
        tag = info.tag or "-"
        print(f"  {info.created_at:%Y-%m-%d %H:%M}  {_format_size(path.stat().st_size):>9}  {tag:<16} {path.name}")


def prune_backups(config: BackupConfig, keep: int) -> list[str]:
    names = [path.name for path in _existing_backups(config)]
    to_delete = select_backups_to_delete(names, keep)
    for name in to_delete:
        (config.backup_dir / name).unlink()
        print(f"Eliminada copia antigua: {name}")
    return to_delete


def _resolve_backup_file(config: BackupConfig, file: str) -> Path:
    candidates = [Path(file), PROJECT_ROOT / file, config.backup_dir / file]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise BackupError(f"No se encontró la copia '{file}'. Usa `python -m scripts.backup_db list` para ver las disponibles.")


def restore_backup(config: BackupConfig, file: str, target: str | None) -> None:
    backup = _resolve_backup_file(config, file)
    database = database_from_settings()
    runner = PgRunner(config, database)
    target_db = (target or database.name).strip()

    if target_db == database.name:
        print(f"ATENCIÓN: esto reemplaza el contenido de la base '{database.name}' con {backup.name}.")
        print("Detén el backend (uvicorn) antes de continuar y, si quieres conservar el estado actual, haz antes una copia.")
        answer = input(f"Escribe {CONFIRMATION_WORD} para continuar: ")
        if answer.strip() != CONFIRMATION_WORD:
            raise BackupError("Restauración cancelada.")
    else:
        if not DATABASE_NAME_RE.match(target_db):
            raise BackupError("El nombre de la base destino solo puede tener minúsculas, números y '_' (ej. planati_restore).")
        exists = runner.psql("postgres", f"SELECT 1 FROM pg_database WHERE datname = '{target_db}'")
        if exists.returncode != 0:
            raise BackupError(f"No se pudo consultar PostgreSQL: {exists.stderr.strip()}")
        if exists.stdout.strip() == "1":
            print(f"La base '{target_db}' ya existe: se restaurará encima (--clean).")
        else:
            created = runner.psql("postgres", f'CREATE DATABASE "{target_db}"')
            if created.returncode != 0:
                raise BackupError(f"No se pudo crear la base '{target_db}': {created.stderr.strip()}")
            print(f"Base '{target_db}' creada.")

    print(f"Restaurando {backup.name} en '{target_db}'...")
    restore_args = ["--clean", "--if-exists", "--no-owner", f"--dbname={target_db}"]
    if runner.mode == "docker":
        with backup.open("rb") as source:
            result = subprocess.run(
                runner.command("pg_restore", *restore_args, stdin=True),
                stdin=source,
                capture_output=True,
                env=runner.env,
            )
    else:
        result = subprocess.run(
            runner.command("pg_restore", *restore_args, str(backup)), capture_output=True, env=runner.env
        )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise BackupError(f"pg_restore terminó con errores:\n{detail}")
    print("Restauración completada.")
    _print_summary(runner, target_db)


def _alembic_head() -> str | None:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
        return ScriptDirectory.from_config(config).get_current_head()
    except Exception:  # noqa: BLE001  (solo informativo)
        return None


def _print_summary(runner: PgRunner, database: str) -> None:
    summary = runner.psql(
        database,
        "SELECT (SELECT string_agg(version_num, ',') FROM alembic_version),"
        " (SELECT count(*) FROM users), (SELECT count(*) FROM establishments), (SELECT count(*) FROM reviews)",
    )
    if summary.returncode != 0:
        print(f"No se pudo leer el resumen de '{database}': {summary.stderr.strip()}")
        return
    revision, users, establishments, reviews = summary.stdout.strip().split("|")
    head = _alembic_head()
    marker = " (head)" if head and revision == head else (f" (head del código: {head})" if head else "")
    print(f"  alembic current: {revision or 'sin revisión'}{marker}")
    print(f"  users: {users} · establishments: {establishments} · reviews: {reviews}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    create = sub.add_parser("create", help="Crea una copia nueva")
    create.add_argument("--tag", help="Etiqueta (p. ej. pre-0010); las copias etiquetadas no se podan")
    sub.add_parser("list", help="Lista las copias disponibles")
    restore = sub.add_parser("restore", help="Restaura una copia")
    restore.add_argument("file", help="Archivo .dump (ruta o nombre dentro de BACKUP_DIR)")
    restore.add_argument("--target", help="Base destino; si no se indica, sobrescribe la principal")
    prune = sub.add_parser("prune", help="Borra las copias sin etiqueta más antiguas")
    prune.add_argument("--keep", type=int, help="Cuántas copias sin etiqueta conservar (BACKUP_KEEP)")
    args = parser.parse_args(argv)

    config = BackupConfig()
    try:
        if args.cmd == "create":
            create_backup(config, args.tag)
        elif args.cmd == "list":
            list_backups(config)
        elif args.cmd == "restore":
            restore_backup(config, args.file, args.target)
        else:
            deleted = prune_backups(config, args.keep if args.keep is not None else config.keep)
            if not deleted:
                print("No hay copias que borrar.")
    except BackupError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelado.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
