"""Stage only the two APIs' runtime files for an isolated Railway seed service.

The bundle excludes local env files, credentials, databases, tests and Git state.
Never deploy the source repository root as the seed service context.
"""
from pathlib import Path
import shutil
import subprocess


POSTAS = Path(__file__).resolve().parents[1]
PLATFORM = POSTAS.parent / 'postas_platform_api'
DEST = POSTAS / '.demo-seed' / 'railway_bundle_v2'
ALLOWED_SUFFIXES = {'.py', '.html', '.txt', '.json', '.yaml', '.yml', '.ini'}


def selected_files(repo, areas):
    result = subprocess.run(['rg', '--files', *areas], cwd=repo, capture_output=True,
                            text=True, check=True, encoding='utf-8')
    for name in result.stdout.splitlines():
        path = Path(name)
        if (path.suffix.lower() in ALLOWED_SUFFIXES and
                not any(part in {'__pycache__', 'tests'} for part in path.parts) and
                not path.name.startswith('test_') and path.name != 'tests.py' and
                not path.name.startswith('.')):
            yield path


def copy_file(repo, relative, root):
    source = (repo / relative).resolve()
    if not source.is_file() or not source.is_relative_to(repo.resolve()):
        raise ValueError(f'Archivo fuera del repo o inexistente: {relative}')
    target = root / repo.name / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def build(destination=DEST):
    destination = destination.resolve()
    if not destination.is_relative_to((POSTAS / '.demo-seed').resolve()):
        raise ValueError('El bundle debe quedar bajo .demo-seed/')
    if destination.exists():
        raise FileExistsError(f'El bundle ya existe: {destination}')
    if not PLATFORM.is_dir():
        raise ValueError(f'No se encontró el repo Platform: {PLATFORM}')
    destination.mkdir(parents=True)
    for relative in selected_files(POSTAS, ['apps', 'config', 'core']):
        copy_file(POSTAS, relative, destination)
    for relative in ('manage.py', 'requirements.txt', 'openfoodfacts_products_clean.csv',
                     'scripts/demo_catalog.py', 'scripts/demo_images.py', 'scripts/seed_demo.py'):
        copy_file(POSTAS, Path(relative), destination)
    for relative in selected_files(PLATFORM, ['app', 'alembic']):
        copy_file(PLATFORM, relative, destination)
    for relative in ('alembic.ini', 'requirements.txt', 'scripts/seed_demo.py'):
        copy_file(PLATFORM, Path(relative), destination)
    shutil.copyfile(POSTAS / 'scripts' / 'Dockerfile.seed_demo', destination / 'Dockerfile')
    print(f'Bundle preparado: {destination}')


if __name__ == '__main__':
    build()
