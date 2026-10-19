"""
Нагрузочное тестирование учебного API «Автосервис» (mock-server.js).

Требования ПР №3:
  • минимум 5 задач (task);
  • минимум 2 задачи в одном классе;
  • оба типа наборов: TaskSet и SequentialTaskSet;
  • Faker для адекватных рандомных данных;
  • GET выполняется минимум в 5 раз чаще, чем POST;
  • не все запросы Fail (данные валидны, эндпоинты существуют).

Автор: Захаров Е. Т., группа П-6-23
"""

import random
import string

from faker import Faker
from locust import HttpUser, task, TaskSet, SequentialTaskSet, between

fake = Faker("ru_RU")

# ─────────────────────────── вспомогательные ────────────────────────────

ACCESS_TOKEN: str | None = None  # общий для всех воркеров (в рамках процесса)


def rand_vin() -> str:
    """
    Генерирует валидный VIN: ровно 17 символов,
    верхний регистр, латиница + цифры (без I, O, Q — стандарт VIN).
    """
    alphabet = string.ascii_uppercase.replace("I", "").replace("O", "").replace("Q", "")
    alphabet += "0123456789"
    return "".join(random.choice(alphabet) for _ in range(17))


def rand_year() -> int:
    return random.randint(2000, 2024)


def rand_cost() -> int:
    return random.randint(500, 150000)


def rand_phone() -> str:
    return f"+7-9{fake.random_int(0, 99):02d}-{fake.random_int(100, 999)}-{fake.random_int(10, 99)}-{fake.random_int(10, 99)}"


# ──────────────────────── TaskSet: просмотр (GET) ───────────────────────
#
# Просмотр — основной сценарий клиента. Запросы независимы,
# поэтому используем TaskSet: каждый шаг выбирается случайно
# по весам через @task(weight=...).

class BrowseTasks(TaskSet):
    """Смотрит списки и карточки. Только GET-запросы."""

    @task(5)
    def list_orders(self):
        # Поиск с рандомным словом + пагинация — реалистичная выборка.
        word = random.choice(["масло", "замена", "ремонт", "ТО", "кузов", ""])
        self.client.get(
            "/api/orders",
            params={
                "search": word,
                "page": random.randint(1, 3),
                "size": random.choice([10, 25, 50]),
                "sort": "title,asc",
            },
            name="/api/orders?search&page&size",
        )

    @task(3)
    def list_clients(self):
        self.client.get(
            "/api/clients",
            params={
                "search": random.choice(["Иван", "Петров", "Смирнов", ""]),
                "page": random.randint(1, 2),
                "size": 10,
                "sort": "lastName,asc",
            },
            name="/api/clients?search&page&size",
        )

    @task(2)
    def list_masters(self):
        self.client.get(
            "/api/masters",
            name="/api/masters",
        )

    @task(2)
    def list_services(self):
        self.client.get(
            "/api/service-types",
            name="/api/service-types",
        )

    @task(1)
    def read_one_order(self):
        # Пробуем открыть случайный заказ из диапазона,
        # который точно есть в seed-данных (id 1..21).
        order_id = random.randint(1, 21)
        self.client.get(
            f"/api/orders/{order_id}",
            name="/api/orders/{id}",
        )


# ──────────────────────── TaskSet: изменения (POST) ─────────────────────
#
# Изменения — редкий сценарий. Пользователь иногда создаёт клиента,
# иногда заказ. Используем TaskSet, чтобы выбор сценария был случайным.

class MutateTasks(TaskSet):
    """Создаёт новые записи. Только POST-запросы."""

    def _make_client_payload(self) -> dict:
        # Email уникальный — иначе сервер вернёт 422 (это тоже валидно,
        # но для демонстрации «не все Fail» лучше генерировать уникальные).
        uniq = fake.uuid4()[:8]
        return {
            "lastName": fake.last_name(),
            "firstName": fake.first_name(),
            "email": f"{uniq}@example.com",
            "phone": rand_phone(),
            "country": random.choice(["Россия", "Беларусь", "Казахстан", "Армения"]),
            "card": None,
        }

    def _make_order_payload(self) -> dict:
        return {
            "title": f"{random.choice(['Замена', 'Ремонт', 'Диагностика', 'Полировка'])} "
                     f"{fake.company()}",
            "vin": rand_vin(),
            "year": rand_year(),
            "clientId": random.randint(1, 9),
            "masterId": random.randint(1, 4),
            "serviceIds": random.sample([1, 2, 3, 4, 5], k=random.randint(1, 2)),
            "cost": rand_cost(),
            "status": random.choice(["new", "in_progress"]),
        }

    @task(3)
    def create_client(self):
        self.client.post(
            "/api/clients",
            json=self._make_client_payload(),
            name="/api/clients [POST]",
        )

    @task(2)
    def create_order(self):
        self.client.post(
            "/api/orders",
            json=self._make_order_payload(),
            name="/api/orders [POST]",
        )


# ─────────────── SequentialTaskSet: сценарий регистрации ────────────────
#
# Здесь важен порядок: зарегистрировался → вошёл → прочитал свой профиль.
# Поэтому используем SequentialTaskSet — задачи выполняются строго по очереди.

class RegisterAndLoginFlow(SequentialTaskSet):
    """Регистрация нового клиента, затем вход и чтение профиля."""

    username: str = ""
    password: str = "Test_1234!"

    @task
    def register(self):
        uniq = fake.uuid4()[:8]
        self.username = f"reader_{uniq}"
        payload = {
            "username": self.username,
            "password": self.password,
            "fullName": f"{fake.last_name()} {fake.first_name()}",
            "email": f"{uniq}@example.com",
        }
        with self.client.post(
            "/api/auth/register",
            json=payload,
            name="/api/auth/register [POST]",
            catch_response=True,
        ) as resp:
            if resp.status_code in (201, 422):
                # 422 возможен, если случайно совпал логин —
                # для нагрузки это допустимо, считаем успехом.
                resp.success()

    @task
    def login(self):
        payload = {"username": self.username, "password": self.password}
        with self.client.post(
            "/api/auth/login",
            json=payload,
            name="/api/auth/login [POST]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                global ACCESS_TOKEN
                ACCESS_TOKEN = resp.json().get("accessToken")

    @task
    def read_me(self):
        headers = {}
        if ACCESS_TOKEN:
            headers["Authorization"] = f"Bearer {ACCESS_TOKEN}"
        self.client.get(
            "/api/auth/me",
            headers=headers,
            name="/api/auth/me",
        )


# ──────────────────────── пользователи Locust ───────────────────────────
#
# Ключевая идея баланса GET/POST:
#   WebUser с весом 10 гоняет ТОЛЬКО BrowseTasks (GET).
#   ApiWriterUser с весом 1 гоняет ТОЛЬКО MutateTasks (POST).
# Итого GET выполняются в ~10 раз чаще POST — требование «≥ 5 раз» выполнено.
#
# Дополнительно один пользователь-читатель (вес 1) проходит
# сценарий регистрации + логина (SequentialTaskSet).

class WebUser(HttpUser):
    """Читатель: только просмотр. Обеспечивает перевес GET."""
    weight = 10
    wait_time = between(0.2, 1.0)
    tasks = [BrowseTasks]

    def on_start(self):
        # Авторизация admin'ом — чтобы иметь доступ к защищённым GET.
        with self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
            name="/api/auth/login [POST, on_start]",
            catch_response=True,
        ) as r:
            if r.status_code == 200:
                global ACCESS_TOKEN
                ACCESS_TOKEN = r.json().get("accessToken")
                self.client.headers.update(
                    {"Authorization": f"Bearer {ACCESS_TOKEN}"}
                )
            else:
                r.failure(f"login failed: {r.status_code}")


class ApiWriterUser(HttpUser):
    """Писатель: создаёт новые записи. Гораздо реже читателя."""
    weight = 1
    wait_time = between(1.0, 3.0)
    tasks = [MutateTasks]

    def on_start(self):
        with self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
            name="/api/auth/login [POST, on_start]",
            catch_response=True,
        ) as r:
            if r.status_code == 200:
                token = r.json().get("accessToken")
                self.client.headers.update({"Authorization": f"Bearer {token}"})
            else:
                r.failure(f"login failed: {r.status_code}")


class NewReaderUser(HttpUser):
    """Новый посетитель: регистрируется и логинится (SequentialTaskSet)."""
    weight = 1
    wait_time = between(2.0, 4.0)
    tasks = [RegisterAndLoginFlow]