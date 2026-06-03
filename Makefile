build:
	docker compose build

up:
	docker compose up

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	docker compose exec api python manage.py migrate
