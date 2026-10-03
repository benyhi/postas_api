"""Reviewed Spanish retail names keyed by the source CSV barcode.

Descriptions are retail summaries, not ingredient/allergen declarations.
"""
import csv
from decimal import Decimal
from pathlib import Path


CATALOG = """7795735000328|Bizcochos salados|Galletitas y bizcochos
7798151952332|Pasta de maní natural|Untables dulces
77940131|Turrón de maní|Golosinas y alfajores
7793913013993|Yogur natural sin azúcar agregada|Yogures
7793890258769|Pan blanco Lactal|Panes y tostadas
7791337006355|Yogur Yogurísimo natural|Yogures
7792200000159|Bizcochos 9 de Oro clásicos|Galletitas y bizcochos
7790742358608|Leche descremada Protein|Leches y bebidas vegetales
7790580138738|Polenta instantánea|Arroz y pastas
7790742373304|Queso Finlandia light 290 g|Quesos y mantecas
7794000006072|Mayonesa clásica rica y cremosa|Aderezos y caldos
7790742625205|Dulce de leche estilo colonial|Untables dulces
77980229|Alfajor de dulce de leche|Golosinas y alfajores
7790742333605|Leche sin lactosa|Leches y bebidas vegetales
7790040377806|Galletitas Criollitas paquete triple|Galletitas y bizcochos
7792799000011|Agua mineral|Aguas y gaseosas
7790387014624|Yerba mate Original|Café y yerba
7792540260138|Azúcar clásica|Azúcar y cacao
7790742324108|Queso Finlandia más liviano 290 g|Quesos y mantecas
7790040143234|Galletitas Chocolinas Original|Galletitas y bizcochos
7793890258752|Pan de molde Lactal|Panes y tostadas
7791337010017|Yogur Yogurísimo griego natural|Yogures
7790895000997|Gaseosa Coca-Cola|Aguas y gaseosas
77980212|Alfajor blanco de dulce de leche|Golosinas y alfajores
7790742625304|Dulce de leche clásico|Untables dulces
7793704000911|Yerba mate Playadito|Café y yerba
7793940054006|Manteca|Quesos y mantecas
7798113151322|Galletitas Pindy|Galletitas y bizcochos
7793913001822|Leche entera Tregar|Leches y bebidas vegetales
7790895645778|Agua mineralizada sin gas|Aguas y gaseosas
7798397444202|Alfajor Rasta negro|Golosinas y alfajores
7793913013726|Queso blanco Tregar light 290 g|Quesos y mantecas
7793323004802|Cacao amargo puro en polvo|Azúcar y cacao
7791866001364|Mayonesa Natura|Aderezos y caldos
7792200000128|Bizcochos 9 de Oro|Galletitas y bizcochos
7790742340306|Bebida de almendras sin azúcar|Leches y bebidas vegetales
7792180007315|Galletitas Paseo cinco semillas|Galletitas y bizcochos
7790360720115|Picadillo de carne|Conservas
7798200050019|Tostaditas de arroz|Panes y tostadas
7794000006478|Mostaza Savora|Aderezos y caldos
7794000008557|Caldo de verduras|Aderezos y caldos
7793360131530|Mermelada de frutilla|Untables dulces
7790040139015|Galletitas Criollitas paquete quíntuple|Galletitas y bizcochos
7791120031557|Arroz largo fino|Arroz y pastas
7791337061439|Queso descremado|Quesos y mantecas
7790070933652|Café Arlistán|Café y yerba
7791337007918|Bebida de almendras refrigerada sin azúcar|Leches y bebidas vegetales
7792540250450|Azúcar superior|Azúcar y cacao
7622201735883|Galletitas Pepitos con chispas de Cadbury paquete triple|Galletitas y bizcochos
7790040147720|Galletitas Surtido Bagley|Galletitas y bizcochos
7790040143586|Galletitas Lía Mediatarde clásicas paquete triple|Galletitas y bizcochos
7798128000707|Galletitas integrales de granola con avena, almendras y maní|Galletitas y bizcochos
7798128000691|Galletitas integrales de avena con chips de chocolate|Galletitas y bizcochos
7790272001005|Aceite de girasol|Aceites
7798128000684|Galletitas integrales de algarroba y cacao|Galletitas y bizcochos
7793704000928|Yerba mate Playadito presentación alternativa|Café y yerba
7790272001029|Aceite puro de girasol|Aceites
7622201735906|Galletitas Pepitos|Galletitas y bizcochos
7794000006065|Mayonesa clásica|Aderezos y caldos
7794000006188|Salsa kétchup|Aderezos y caldos
7790538009561|Arrocitas con sal, sésamo y lino|Panes y tostadas
7794000006485|Mostaza Savora 500 g|Aderezos y caldos
7793890258288|Rapiditas Bimbo integrales|Panes y tostadas
7622201736033|Galletitas Cerealitas|Galletitas y bizcochos
7622201735258|Galletitas Oreo 354 g|Galletitas y bizcochos
7790070335968|Fideos tirabuzón integrales|Arroz y pastas
7791337061361|Queso CasanCrem clásico|Quesos y mantecas
7799155000173|Agua Villavicencio sin gas|Aguas y gaseosas
7790742363008|Leche La Serenísima clásica|Leches y bebidas vegetales
7790040143005|Galletitas Lía Mediatarde sándwich paquete triple|Galletitas y bizcochos
7791337061507|Queso CasanCrem Balance|Quesos y mantecas
7793890260885|Pan Bimbo Artesano blanco|Panes y tostadas
7790045827535|Galletitas de cereal|Galletitas y bizcochos
7790150150573|Café instantáneo Selección granulado|Café y yerba
7795735000335|Bizcochos dulces|Galletitas y bizcochos
7790895000782|Coca-Cola sabor original 500 ml|Aguas y gaseosas
7790315058201|Agua Villavicencio Aventura|Aguas y gaseosas
7791866000381|Salsa kétchup Natura|Aderezos y caldos
7792931000039|Agua Glaciar|Aguas y gaseosas
7790036000466|Bebida Baggio multifruta|Jugos
7790742373809|Queso Cremón light 280 g|Quesos y mantecas
7793913012996|Leche descremada|Leches y bebidas vegetales
7790412000271|Tostadas de arroz clásicas|Panes y tostadas
7790742067005|Dulce de leche repostero La Serenísima|Untables dulces
7791866001579|Mayonesa con aceite de oliva|Aderezos y caldos
7792180001641|Aceite de girasol presentación alternativa|Aceites
7790580327415|Confites Rocklets|Golosinas y alfajores
7794000007109|Mayonesa Hellmann's liviana|Aderezos y caldos
7790742223005|Queso rallado 70 g|Quesos y mantecas
7791787000040|Galletitas Pepas Trío|Galletitas y bizcochos
7622201735296|Galletitas Oreo|Galletitas y bizcochos
7791337061422|Queso blanco clásico|Quesos y mantecas
7799155000197|Agua Villavicencio sin gas presentación alternativa|Aguas y gaseosas
7790070933638|Café Arlistán presentación alternativa|Café y yerba
7798060850026|Manteca Tonadita 200 g|Quesos y mantecas
7790150101773|Café instantáneo suave|Café y yerba
7790742363107|Leche larga vida descremada|Leches y bebidas vegetales
7798136870545|Yogur firme Dahi natural|Yogures
7794820902721|Yogur cremoso|Yogures
7791337061491|Queso crema CasanCrem|Quesos y mantecas"""


def load_catalog(csv_path):
    reviewed = dict((code, (name, category)) for code, name, category in
                    (line.split('|') for line in CATALOG.splitlines()))
    with Path(csv_path).open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 100 or {r['barcode'] for r in rows} != set(reviewed):
        raise ValueError('El CSV debe contener los 100 códigos del catálogo revisado.')
    result = []
    for index, row in enumerate(rows):
        name, category = reviewed[row['barcode']]
        price = Decimal(row['price']).quantize(Decimal('.01'))
        if not price.is_finite() or price <= 0:
            raise ValueError(f"Precio inválido: {row['barcode']}")
        result.append(dict(barcode=row['barcode'], name=name, category=category,
                           description=f'{name}. Categoría: {category}.',
                           price=str(price), cost=str((price * Decimal('.65')).quantize(Decimal('.01'))),
                           unit='U', stock='5.000' if index % 13 == 0 else str(30 + index % 71),
                           min_stock='10.000', image_url=row['image_url'],
                           source_image_url=row['image_url'],
                           source_url=f"https://world.openfoodfacts.org/product/{row['barcode']}",
                           attribution='Open Food Facts contributors; database ODbL; images CC BY-SA'))
    # Round-robin categories: small-plan subsets also contain a varied assortment.
    groups = {}
    for product in result:
        groups.setdefault(product['category'], []).append(product)
    return [group[i] for i in range(max(map(len, groups.values())))
            for group in groups.values() if i < len(group)]
