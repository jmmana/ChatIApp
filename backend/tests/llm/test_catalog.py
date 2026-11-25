import litellm

from app.llm.catalog import CATALOG, get_spec


def test_kinds_unicos() -> None:
    kinds = [spec.kind for spec in CATALOG]
    assert len(kinds) == len(set(kinds))


def test_categorias_cubiertas() -> None:
    assert {spec.category for spec in CATALOG} == {"api", "platform", "chinese", "local"}


def test_cada_prefijo_existe_en_litellm() -> None:
    providers = {str(p.value if hasattr(p, "value") else p) for p in litellm.provider_list}
    for spec in CATALOG:
        assert spec.litellm_prefix.endswith("/"), spec.kind
        assert spec.litellm_prefix.removesuffix("/") in providers, spec.kind


def test_campos_bien_formados() -> None:
    for spec in CATALOG:
        names = [f.name for f in spec.fields]
        assert len(names) == len(set(names)), spec.kind
        assert spec.docs_url.startswith("https://"), spec.kind
        for field in spec.fields:
            if field.type == "select":
                assert field.options, f"{spec.kind}.{field.name}"
            if field.options and field.default is not None:
                assert field.default in {o.value for o in field.options}


def test_chinos_ofrecen_api_base_con_opciones() -> None:
    for spec in (s for s in CATALOG if s.category == "chinese"):
        api_base = next(f for f in spec.fields if f.name == "api_base")
        assert api_base.type == "url"
        assert api_base.default is not None
        assert api_base.options, spec.kind


def test_get_spec() -> None:
    assert get_spec("deepseek") is not None
    assert get_spec("no-existe") is None
