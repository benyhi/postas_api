from datetime import date

from apps.suppliers.models import ProductSupplier


def switch_supplier(product, new_supplier, price=None):
    """
    Desactiva todos los proveedores activos del producto y asigna el nuevo.
    Retorna el ProductSupplier creado.
    """
    today = date.today()
    ProductSupplier.objects.filter(
        product=product,
        is_current=True,
    ).update(is_current=False, until=today)

    return ProductSupplier.objects.create(
        product=product,
        supplier=new_supplier,
        price=price,
    )
