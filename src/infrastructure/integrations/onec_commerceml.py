"""1С CommerceML 2.0 XML Adapter.

Exports recipes to 1С format and imports raw materials catalog from 1С.

CommerceML 2.0 is the standard Russian e-commerce/ERP interchange format,
supported by 1С:Предприятие 8.x and Битрикс.

Documentation:
- CommerceML 2.0 standard: https://v8.1c.ru/edi/edi_stnd/90/92.htm
- Schema files: https://1c.ru/rus/products/1c/predpr/commerceml/

We implement:
- Export: Recipe → 1С product (Номенклатура) with composition (Спецификация)
- Import: 1С raw materials catalog (Номенклатура + Остатки) → our RawMaterial entities
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from xml.etree import ElementTree as ET
from xml.dom import minidom

if TYPE_CHECKING:
    from domain.entities.recipe import Recipe


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OneCNomenclatureItem:
    """Номенклатурная позиция (товар/сырьё) из 1С."""

    guid: str  # 1С internal GUID
    name: str
    article: str
    unit: str  # Единица измерения
    category: str
    description: str = ""
    price: float | None = None
    stock_quantity: float | None = None


class OneCCommerceMlExporter:
    """Exports recipes to 1С CommerceML 2.0 XML.

    Output: XML file with
    - Каталог (catalog) with product cards
    - Спецификация (specification) with composition per product
    """

    COMMERCEML_VERSION = "2.0.8"
    NAMESPACE = ""

    def __init__(self, company_name: str = "Formulation Workbench") -> None:
        self._company_name = company_name

    def export_recipe(
        self,
        recipe: Recipe,
        output_path: Path,
    ) -> Path:
        """Export single recipe to CommerceML 2.0 XML.

        Args:
            recipe: Recipe entity.
            output_path: Output XML file path.

        Returns:
            Path to the generated XML file.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        root = ET.Element("КоммерческаяИнформация")
        root.set("ВерсияФормата", self.COMMERCEML_VERSION)
        root.set("ДатаФормирования", datetime.now(timezone.utc).isoformat())

        # Catalog container
        catalog = ET.SubElement(root, "Каталог")
        catalog.set("СодержитТолькоИзменения", "false")

        # Classifier (basic)
        classifier = ET.SubElement(catalog, "Классификатор")
        self._add_classifier(classifier)

        # Product card
        products = ET.SubElement(catalog, "Товары")
        product = ET.SubElement(products, "Товар")
        self._add_product_card(product, recipe)

        # Specifications (composition)
        specifications = ET.SubElement(root, "Спецификации")
        spec = ET.SubElement(specifications, "Спецификация")
        self._add_specification(spec, recipe)

        # Format and save
        xml_bytes = self._prettify(root)
        with open(output_path, "wb") as f:
            f.write(xml_bytes)

        logger.info("Exported recipe to 1С: %s", output_path)
        return output_path

    def export_recipes(
        self,
        recipes: tuple["Recipe", ...],
        output_path: Path,
    ) -> Path:
        """Export multiple recipes to CommerceML 2.0 XML."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        root = ET.Element("КоммерческаяИнформация")
        root.set("ВерсияФормата", self.COMMERCEML_VERSION)
        root.set("ДатаФормирования", datetime.now(timezone.utc).isoformat())

        catalog = ET.SubElement(root, "Каталог")
        catalog.set("СодержитТолькоИзменения", "false")
        classifier = ET.SubElement(catalog, "Классификатор")
        self._add_classifier(classifier)

        products = ET.SubElement(catalog, "Товары")
        for recipe in recipes:
            product = ET.SubElement(products, "Товар")
            self._add_product_card(product, recipe)

        specifications = ET.SubElement(root, "Спецификации")
        for recipe in recipes:
            spec = ET.SubElement(specifications, "Спецификация")
            self._add_specification(spec, recipe)

        xml_bytes = self._prettify(root)
        with open(output_path, "wb") as f:
            f.write(xml_bytes)

        logger.info("Exported %d recipes to 1С: %s", len(recipes), output_path)
        return output_path

    def _add_classifier(self, classifier: ET.Element) -> None:
        """Add product categories to classifier."""
        # Standard units
        units = ET.SubElement(classifier, "ЕдиницыИзмерения")
        for unit_code, unit_name in [
            ("166", "кг"),
            ("168", "т"),
            ("113", "л"),
            ("796", "шт"),
        ]:
            unit = ET.SubElement(units, "ЕдиницаИзмерения")
            unit.set("Код", unit_code)
            unit.set("Наименование", unit_name)

        # Categories (groups)
        groups = ET.SubElement(classifier, "Группы")
        for category_name in [
            "Лаки",
            "Краски",
            "Колеры и пигментные пасты",
            "Клеи",
            "Герметики",
            "Мастики",
            "Грунтовки, шпатлёвки, штукатурки",
            "Антикоррозионные покрытия",
        ]:
            group = ET.SubElement(groups, "Группа")
            group.set("Наименование", category_name)

    def _add_product_card(self, product: ET.Element, recipe: Recipe) -> None:
        """Add product card for recipe."""
        product.set("Артикул", recipe.id[:10])
        product.set("Наименование", self._build_product_name(recipe))
        product.set("Единица", "166")  # кг
        product.set("Группа", recipe.category)
        product.set("КлассПродукта", recipe.product_class.value)

        # Description
        desc = ET.SubElement(product, "Описание")
        desc.text = (
            f"{recipe.intended_use}. "
            f"Связующее: {recipe.binder_type}. "
            f"Степень блеска: {recipe.finish or '—'}."
        )

        # Verification status
        status = ET.SubElement(product, "СтатусВерификации")
        status.text = recipe.status.state.value

        # Source reference
        sources = ET.SubElement(product, "Источники")
        source = ET.SubElement(sources, "Источник")
        source.set("Авторы", recipe.primary_source.authors)
        source.set("ГодИздания", str(recipe.primary_source.year))
        if recipe.primary_source.isbn:
            source.set("ISBN", str(recipe.primary_source.isbn))
        source.set("Страница", recipe.primary_source.page_or_formula)
        source.text = recipe.primary_source.title

    def _add_specification(self, spec: ET.Element, recipe: Recipe) -> None:
        """Add composition specification."""
        spec.set("ПродуктАртикул", recipe.id[:10])
        spec.set("ПродуктНаименование", self._build_product_name(recipe))
        spec.set("Версия", str(recipe.version))
        spec.set("ДатаСоздания", recipe.created_at.isoformat())

        # Composition
        composition = ET.SubElement(spec, "Состав")
        composition.set("ЕдиницаИзмерения", "проценты")

        for stage in recipe.stages:
            stage_el = ET.SubElement(composition, "Стадия")
            stage_el.set("Номер", str(stage.stage_number))
            stage_el.set("Наименование", stage.name)

            for comp in stage.components:
                comp_el = ET.SubElement(stage_el, "Ингредиент")
                comp_el.set("Наименование", comp.name)
                comp_el.set("CAS", comp.cas_number)
                comp_el.set("Функция", comp.function)
                comp_el.set("МассоваяДоля", f"{comp.mass_percent:.4f}")
                comp_el.set("Допуск", f"{comp.tolerance_percent:.4f}")

        # Process
        process = ET.SubElement(spec, "ТехнологическийПроцесс")
        for stage in recipe.stages:
            if stage.process:
                stage_proc = ET.SubElement(process, "СтадияПроцесса")
                stage_proc.set("Номер", str(stage.stage_number))
                stage_proc.set("Оборудование", stage.process.equipment)
                if stage.process.rotational_speed_rpm:
                    stage_proc.set("СкоростьОбМин", str(stage.process.rotational_speed_rpm))
                if stage.process.temperature_c:
                    stage_proc.set("Температура", f"{stage.process.temperature_c:.0f}")
                if stage.process.duration_min:
                    stage_proc.set("ДлительностьМин", str(stage.process.duration_min))

    def _build_product_name(self, recipe: Recipe) -> str:
        """Build 1С product name."""
        return f"{recipe.category} / {recipe.subcategory} / {recipe.binder_type}"

    def _prettify(self, elem: ET.Element) -> bytes:
        """Return a pretty-printed XML bytes."""
        rough_string = ET.tostring(elem, encoding="utf-8")
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ", encoding="utf-8")


class OneCCommerceMlImporter:
    """Imports raw materials catalog from 1С CommerceML 2.0 XML.

    Reads Номенклатура (nomenclature) entries with their groups and units.
    """

    def __init__(self) -> None:
        pass

    def import_catalog(
        self,
        input_path: Path,
    ) -> tuple[OneCNomenclatureItem, ...]:
        """Import raw materials catalog from 1С CommerceML XML.

        Args:
            input_path: Path to 1С CommerceML XML file.

        Returns:
            Tuple of imported nomenclature items.
        """
        if not input_path.exists():
            raise FileNotFoundError(f"1С file not found: {input_path}")

        logger.info("Importing 1С catalog: %s", input_path)

        tree = ET.parse(input_path)
        root = tree.getroot()

        items: list[OneCNomenclatureItem] = []

        # Find all product elements (CommerceML 2.0 uses Russian names)
        for product in root.iter("Товар"):
            try:
                item = OneCNomenclatureItem(
                    guid=product.get("Ид", ""),
                    name=product.get("Наименование", ""),
                    article=product.get("Артикул", ""),
                    unit=self._map_unit(product.get("Единица", "166")),
                    category=product.get("Группа", ""),
                    description=self._get_text(product, "Описание"),
                    price=self._get_float(product, "Цена"),
                    stock_quantity=self._get_float(product, "Остаток"),
                )
                items.append(item)
            except Exception as e:
                logger.warning("Failed to import product: %s", e)

        logger.info("Imported %d items from 1С", len(items))
        return tuple(items)

    def _map_unit(self, code: str) -> str:
        """Map 1С unit code to readable name."""
        mapping = {
            "166": "кг",
            "168": "т",
            "113": "л",
            "796": "шт",
        }
        return mapping.get(code, code)

    def _get_text(self, element: ET.Element, tag: str) -> str:
        """Get text of child element."""
        child = element.find(tag)
        return child.text if child is not None and child.text else ""

    def _get_float(self, element: ET.Element, tag: str) -> float | None:
        """Get float from child element."""
        text = self._get_text(element, tag)
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
