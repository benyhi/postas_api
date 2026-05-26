import uuid
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.products.importer import MAX_UPLOAD_BYTES
from apps.products.models import Category, Product
from apps.users.models import User


class ProductPermissionTests(TestCase):
    def setUp(self):
        self.tenant_id = uuid.uuid4()
        self.employee = User.objects.create_user(
            tenant_id=self.tenant_id,
            username="employee",
            email="employee@example.com",
            password="employee1234",
            role=User.Role.EMPLOYEE,
        )
        self.product = Product.objects.create(
            tenant_id=self.tenant_id,
            name="Coca Cola 500ml",
            price=Decimal("1500.00"),
            cost=Decimal("900.00"),
            stock=Decimal("10.000"),
        )
        self.category = Category.objects.create(
            tenant_id=self.tenant_id,
            name="Bebidas",
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._access_token(self.employee)}")

    def test_employee_can_list_categories(self):
        response = self.client.get("/api/v1/categories/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_employee_can_retrieve_category(self):
        response = self.client.get(f"/api/v1/categories/{self.category.uuid}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["uuid"], str(self.category.uuid))

    def test_employee_cannot_create_category(self):
        response = self.client.post(
            "/api/v1/categories/",
            {"name": "Golosinas"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_employee_can_list_products(self):
        response = self.client.get("/api/v1/products/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_employee_can_retrieve_product(self):
        response = self.client.get(f"/api/v1/products/{self.product.uuid}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["uuid"], str(self.product.uuid))

    def test_employee_cannot_create_product(self):
        response = self.client.post(
            "/api/v1/products/",
            {
                "name": "Sprite 500ml",
                "price": "1500.00",
                "cost": "900.00",
                "stock": "10.000",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    @staticmethod
    def _access_token(user):
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        access["tenant_id"] = str(user.tenant_id)
        access["role"] = user.role
        return str(access)


class ProductImportTests(TestCase):
    def setUp(self):
        self.tenant_id = uuid.uuid4()
        self.admin = User.objects.create_user(
            tenant_id=self.tenant_id,
            username="admin",
            email="admin@example.com",
            password="admin1234",
            role=User.Role.ADMIN,
        )
        self.employee = User.objects.create_user(
            tenant_id=self.tenant_id,
            username="import_employee",
            email="import-employee@example.com",
            password="employee1234",
            role=User.Role.EMPLOYEE,
        )
        self.client = APIClient()
        self.authenticate(self.admin)

    def test_admin_imports_csv_and_creates_products(self):
        response = self.client.post(
            "/api/v1/products/import/",
            {"file": self.csv_file(
                "nombre,precio,costo,unidad,stock,stock_minimo,codigo_barras,categoria,descripcion\n"
                "Yerba Mate,1200.50,800,U,12,3,7790001,Almacen,Suave\n"
                "Manzana,500,300,KG,4.5,1.2,,Frutas,Fresca\n"
            )},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["result"], "OK")
        self.assertEqual(response.data["summary"]["created"], 2)
        self.assertEqual(response.data["summary"]["updated"], 0)
        self.assertEqual(response.data["summary"]["failed"], 0)
        self.assertEqual(Product.objects.filter(tenant_id=self.tenant_id).count(), 2)
        self.assertTrue(Category.objects.filter(tenant_id=self.tenant_id, name="Almacen").exists())
        self.assertTrue(Category.objects.filter(tenant_id=self.tenant_id, name="Frutas").exists())

    def test_admin_imports_xlsx_and_creates_product(self):
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["name", "price", "barcode"])
        sheet.append(["Cafe molido", "2500.00", "7790002"])
        stream = BytesIO()
        workbook.save(stream)
        workbook.close()

        response = self.client.post(
            "/api/v1/products/import/",
            {
                "file": SimpleUploadedFile(
                    "products.xlsx",
                    stream.getvalue(),
                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["result"], "OK")
        self.assertEqual(response.data["summary"]["created"], 1)
        self.assertTrue(Product.objects.filter(tenant_id=self.tenant_id, name="Cafe molido").exists())

    def test_admin_import_updates_matching_product_by_barcode(self):
        product = Product.objects.create(
            tenant_id=self.tenant_id,
            name="Yerba vieja",
            price=Decimal("100.00"),
            barcode="7790001",
        )

        response = self.client.post(
            "/api/v1/products/import/",
            {"file": self.csv_file(
                "name,price,barcode,stock\n"
                "Yerba nueva,1500.00,7790001,8\n"
            )},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["result"], "OK")
        self.assertEqual(response.data["summary"]["created"], 0)
        self.assertEqual(response.data["summary"]["updated"], 1)
        self.assertEqual(response.data["summary"]["matches"], 1)
        self.assertEqual(response.data["matches"][0]["match_type"], "barcode")
        product.refresh_from_db()
        self.assertEqual(product.name, "Yerba nueva")
        self.assertEqual(product.price, Decimal("1500.00"))
        self.assertEqual(product.stock, Decimal("8.000"))

    def test_admin_import_updates_matching_product_by_name(self):
        product = Product.objects.create(
            tenant_id=self.tenant_id,
            name="Yerba Mate",
            price=Decimal("100.00"),
            stock=Decimal("2.000"),
        )

        response = self.client.post(
            "/api/v1/products/import/",
            {"file": self.csv_file(
                "name,price,stock\n"
                "Yerba Mate,1800.00,6\n"
            )},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["result"], "OK")
        self.assertEqual(response.data["summary"]["created"], 0)
        self.assertEqual(response.data["summary"]["updated"], 1)
        self.assertEqual(response.data["summary"]["matches"], 1)
        self.assertEqual(response.data["matches"][0]["match_type"], "name")
        product.refresh_from_db()
        self.assertEqual(product.price, Decimal("1800.00"))
        self.assertEqual(product.stock, Decimal("6.000"))

    def test_import_does_not_match_products_from_another_tenant(self):
        other_tenant_id = uuid.uuid4()
        other_product = Product.objects.create(
            tenant_id=other_tenant_id,
            name="Producto compartido",
            price=Decimal("100.00"),
            stock=Decimal("2.000"),
            barcode="7799999",
        )

        response = self.client.post(
            "/api/v1/products/import/",
            {"file": self.csv_file(
                "name,price,stock,barcode\n"
                "Producto compartido,250.00,7,7799999\n"
            )},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["result"], "OK")
        self.assertEqual(response.data["summary"]["created"], 1)
        self.assertEqual(response.data["summary"]["updated"], 0)
        self.assertEqual(response.data["summary"]["matches"], 0)

        other_product.refresh_from_db()
        self.assertEqual(other_product.price, Decimal("100.00"))
        self.assertEqual(other_product.stock, Decimal("2.000"))
        self.assertTrue(
            Product.objects.filter(
                tenant_id=self.tenant_id,
                name="Producto compartido",
                barcode="7799999",
                price=Decimal("250.00"),
            ).exists()
        )

    def test_import_returns_partial_result_for_row_errors(self):
        response = self.client.post(
            "/api/v1/products/import/",
            {"file": self.csv_file(
                "name,price,barcode\n"
                "Producto valido,100.00,111\n"
                "Producto invalido,-50.00,222\n"
            )},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["result"], "PARTIAL")
        self.assertEqual(response.data["summary"]["created"], 1)
        self.assertEqual(response.data["summary"]["failed"], 1)
        self.assertEqual(response.data["errors"][0]["row"], 3)
        self.assertEqual(response.data["errors"][0]["field"], "price")
        self.assertEqual(Product.objects.filter(tenant_id=self.tenant_id).count(), 1)

    def test_invalid_row_does_not_create_or_reactivate_category(self):
        inactive_category = Category.all_objects.create(
            tenant_id=self.tenant_id,
            name="Inactiva",
            active=False,
        )

        response = self.client.post(
            "/api/v1/products/import/",
            {"file": self.csv_file(
                "name,price,category\n"
                "Producto invalido,-50.00,Nueva categoria\n"
                "Producto invalido 2,abc,Inactiva\n"
            )},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["result"], "FAILED")
        self.assertEqual(response.data["summary"]["failed"], 2)
        self.assertFalse(Category.objects.filter(tenant_id=self.tenant_id, name="Nueva categoria").exists())
        inactive_category.refresh_from_db()
        self.assertFalse(inactive_category.active)

    def test_import_rejects_non_finite_and_oversized_decimals(self):
        response = self.client.post(
            "/api/v1/products/import/",
            {"file": self.csv_file(
                "name,price,stock\n"
                "Producto NaN,NaN,1\n"
                "Producto Infinity,Infinity,1\n"
                "Producto Grande,10000000000.00,1\n"
            )},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["result"], "FAILED")
        self.assertEqual(response.data["summary"]["failed"], 3)
        self.assertEqual(
            [(error["row"], error["field"], error["code"]) for error in response.data["errors"]],
            [
                (2, "price", "invalid_decimal"),
                (3, "price", "invalid_decimal"),
                (4, "price", "max_digits"),
            ],
        )
        self.assertEqual(Product.objects.filter(tenant_id=self.tenant_id).count(), 0)

    def test_import_rejects_missing_required_columns(self):
        response = self.client.post(
            "/api/v1/products/import/",
            {"file": self.csv_file(
                "nombre,costo\n"
                "Producto sin precio,10\n"
            )},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["result"], "FAILED")
        self.assertEqual(response.data["errors"][0]["code"], "missing_columns")
        self.assertEqual(response.data["errors"][0]["field"], "price")

    def test_import_rejects_unsupported_file_extension(self):
        response = self.client.post(
            "/api/v1/products/import/",
            {
                "file": SimpleUploadedFile(
                    "products.txt",
                    b"name,price\nProducto,10\n",
                    content_type="text/plain",
                )
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["result"], "FAILED")
        self.assertEqual(response.data["errors"][0]["code"], "unsupported_file_type")

    def test_import_rejects_too_large_file(self):
        response = self.client.post(
            "/api/v1/products/import/",
            {
                "file": SimpleUploadedFile(
                    "products.csv",
                    b"x" * (MAX_UPLOAD_BYTES + 1),
                    content_type="text/csv",
                )
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["result"], "FAILED")
        self.assertEqual(response.data["errors"][0]["code"], "file_too_large")

    def test_employee_cannot_import_products(self):
        self.authenticate(self.employee)

        response = self.client.post(
            "/api/v1/products/import/",
            {"file": self.csv_file("name,price\nProducto,10\n")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 403)

    def authenticate(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token(user)}")

    @staticmethod
    def csv_file(content):
        return SimpleUploadedFile(
            "products.csv",
            content.encode("utf-8"),
            content_type="text/csv",
        )

    @staticmethod
    def access_token(user):
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        access["tenant_id"] = str(user.tenant_id)
        access["role"] = user.role
        return str(access)
