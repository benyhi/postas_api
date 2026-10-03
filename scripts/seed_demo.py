"""Coordinate independent Django/SQLAlchemy demo seeds without sharing DB settings."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from demo_catalog import load_catalog
from demo_images import copy_images


ROOT = Path(__file__).resolve().parents[1]
DATASET = 'production-demo-v1'
TENANTS = [
    ('Kiko Store', 'business_ai'), ('Kiosco Pepito', 'starter'), ('FreeMarket', 'free'),
    ('Almacén Central', 'business'), ('Mercado Personalizado', 'custom'),
    ('Comercio Demo 1', 'test'), ('Comercio Demo 2', 'demo_2'), ('Comercio Demo 3', 'demo_3'),
]


def dotenv_values(path):
    """Read the repository's simple KEY=VALUE convention without extra dependencies."""
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.removeprefix('export ').split('=', 1)
        value = value.strip()
        if len(value) >= 2 and value[0] in {'"', "'"} and value[-1] == value[0]:
            value = value[1:-1]
        else:
            value = value.split(' #', 1)[0].strip()
        values[key.strip()] = value
    return values


def environment(repo, prefix):
    # DATABASE_URL inherited from the launching shell must not target both databases.
    env = {**{k: v for k, v in dotenv_values(repo / '.env').items() if v is not None},
           **{k: v for k, v in os.environ.items() if k != 'DATABASE_URL'}}
    override = os.environ.get(f'{prefix}_DEMO_DATABASE_URL')
    if override:
        env['DATABASE_URL'] = override
    env['PYTHONPATH'] = str(repo)
    return env


def make_manifest(csv_path, seed, as_of, tenant_numbers):
    now = datetime.fromisoformat(as_of.replace('Z', '+00:00')) if as_of else datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('--as-of debe incluir zona horaria.')
    if now > datetime.now(timezone.utc):
        raise ValueError('--as-of no puede estar en el futuro.')
    try:
        start = now.replace(year=now.year - 1)
    except ValueError:
        start = now.replace(year=now.year - 1, day=28)
    data = dict(version=1, dataset_id=DATASET, seed=seed, as_of=now.isoformat(),
                start_at=start.isoformat(), products=load_catalog(csv_path),
                tenants=[dict(id=f'00000000-0000-0000-0000-{i:012d}', name=name, plan_code=code)
                         for i, (name, code) in enumerate(TENANTS, 1) if i in tenant_numbers])
    data['fingerprint'] = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return data


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def run_child(command, cwd, env):
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        # Scripts report safe errors. Avoid dumping a traceback containing connection details.
        safe = '\n'.join(line for line in result.stderr.splitlines()
                         if line.startswith(('CommandError:', 'Error:', 'ERROR:')))
        raise RuntimeError(f'Falló {Path(command[1]).name} (código {result.returncode}). {safe}')
    try:
        return json.loads(result.stdout)
    except ValueError:
        # Django may emit migration/system check notices before JSON.
        for line in reversed(result.stdout.splitlines()):
            try:
                return json.loads(line)
            except ValueError:
                pass
        raise RuntimeError('El comando hijo no devolvió un informe JSON.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform-dir', type=Path, default=ROOT.parent / 'postas_platform_api')
    parser.add_argument('--postas-python', type=Path, default=Path(sys.executable))
    parser.add_argument('--platform-python', type=Path)
    parser.add_argument('--products-csv', type=Path, default=ROOT / 'openfoodfacts_products_clean.csv')
    parser.add_argument('--manifest', type=Path, default=ROOT / '.demo-seed' / 'manifest.json')
    parser.add_argument('--seed', type=int, default=20261002)
    parser.add_argument('--as-of')
    parser.add_argument('--tenants', default='1,2,3,4,5,6,7,8')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    args.platform_dir = args.platform_dir.resolve()
    args.manifest = args.manifest.resolve()
    selected = sorted({int(value) for value in args.tenants.split(',')})
    if not selected or any(i not in range(1, 9) for i in selected):
        raise ValueError('--tenants debe contener números entre 1 y 8.')
    old = json.loads(args.manifest.read_text(encoding='utf-8')) if args.manifest.exists() else None
    data = make_manifest(args.products_csv, args.seed, args.as_of or (old and old['as_of']), selected)
    if old and old.get('fingerprint') != data['fingerprint']:
        raise ValueError('El manifiesto existe con otros parámetros o catálogo. No se sobrescribirá.')
    if old:
        data = old
    platform_python = args.platform_python or args.platform_dir / 'env' / 'Scripts' / 'python.exe'
    for executable in (args.postas_python, platform_python):
        if not executable.is_file():
            raise ValueError(f'Intérprete no encontrado: {executable}')
    postas_env, platform_env = environment(ROOT, 'POSTAS'), environment(args.platform_dir, 'PLATFORM')
    postas_env['PYTHONIOENCODING'] = platform_env['PYTHONIOENCODING'] = 'utf-8'
    if not args.dry_run and len(postas_env.get('DEMO_SEED_PASSWORD', '')) < 12:
        raise ValueError('Definí DEMO_SEED_PASSWORD con al menos 12 caracteres antes de cargar usuarios.')
    with tempfile.TemporaryDirectory(prefix='postas-demo-') as temporary:
        work = Path(temporary) / 'manifest.json'
        save(work, data)

        def postas(phase):
            return run_child([str(args.postas_python), str(ROOT / 'manage.py'), 'seed_demo',
                              '--manifest', str(work), '--phase', phase], ROOT, postas_env)

        def platform(phase):
            return run_child([str(platform_python), str(args.platform_dir / 'scripts' / 'seed_demo.py'),
                              '--manifest', str(work), '--phase', phase], args.platform_dir, platform_env)

        print('Prevalidando ambas bases y límites...', flush=True)
        platform('preflight')
        postas('preflight')
        print('Verificando las 100 imágenes y R2...', flush=True)
        data['products'] = copy_images(data['products'], postas_env, dry_run=args.dry_run)
        if args.dry_run:
            print('Dry-run completo: sin escrituras en bases ni R2.')
            return
        save(work, data)
        save(args.manifest, data)
        print('Cargando catálogo y suscripciones...', flush=True)
        platform('subscriptions')
        print('Cargando operación e historial de Postas...', flush=True)
        result = postas('load')
        data['usage_events'] = result['usage_events']
        save(work, data)
        save(args.manifest, data)
        print('Conciliando consumos y verificando...', flush=True)
        platform('usage')
        platform_result = platform('verify')
        postas_result = postas('verify')
        data['completed'] = True
        save(args.manifest, data)
        print(json.dumps({'manifest': str(args.manifest), 'postas': postas_result.get('counts'),
                          'platform': platform_result}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        if isinstance(exc, (ValueError, RuntimeError)):
            print(f'Error: {exc}', file=sys.stderr)
        else:
            print(f'Error: {type(exc).__name__}; fase incompleta, se puede reintentar con el mismo manifiesto.', file=sys.stderr)
        sys.exit(1)
