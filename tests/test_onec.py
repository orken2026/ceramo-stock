import fake_1c
import httpx
import pytest
from conftest import onec_settings

from app.onec import OneCClient, OneCQueryError, OneCRejected, OneCUnavailable, odata_literal



async def test_exact_article_wins_and_stops_the_search(onec):
    result = await onec.search("cs-6060-gr")
    assert [item.id for item in result.items] == [fake_1c.TILE_GREY]
    assert result.items[0].unit == "м²"
    assert len(fake_1c.state.calls) == 1


async def test_partial_article_finds_several(onec):
    result = await onec.search("6060")
    assert [item.article for item in result.items] == ["CS-6060-GR", "CS-6060-SD"]


async def test_words_in_any_order_search_the_name(onec):
    result = await onec.search("сұр Алатау")
    assert [item.id for item in result.items] == [fake_1c.TILE_GREY]


async def test_deleted_items_and_groups_are_hidden(onec):
    assert (await onec.search("CS-DEL")).items == []
    assert (await onec.search("тобы")).items == []


async def test_truncation_is_reported(onec):
    result = await onec.search("Үлгі", limit=2)
    assert len(result.items) == 2
    assert result.truncated is True


async def test_quote_in_search_stays_inside_the_literal(onec):
    result = await onec.search("ON'1")
    assert [item.id for item in result.items] == [fake_1c.ODD_NAME]


@pytest.mark.parametrize(
    "attack",
    ["' or IsFolder eq false or Артикул eq '", "') or (Description eq 'x", "x' or 'a' eq 'a"],
)
async def test_filter_injection_finds_nothing(onec, attack):
    assert (await onec.search(attack)).items == []


def test_literal_escaping():
    assert odata_literal("a'b") == "'a''b'"


async def test_stock_is_summed_per_warehouse_without_float_noise(onec):
    report = await onec.stock(fake_1c.TILE_GREY)
    assert [(row.name, row.quantity) for row in report.warehouses] == [
        ("Негізгі қойма", 812.8),
        ("Шоурум", 36.0),
    ]
    assert report.total_quantity == 848.8
    assert report.total_reserved == 0


async def test_every_data_request_uses_allowed_only(onec):
    await onec.search("CS-6060-GR")
    await onec.stock(fake_1c.TILE_GREY)
    assert len(fake_1c.state.calls) >= 3
    assert all("allowedOnly=true" in call for call in fake_1c.state.calls)


async def test_configured_reserve_field_is_summed(onec_transport):
    client = OneCClient(onec_settings(reserve_field="КОтгрузкеBalance"), transport=onec_transport)
    report = await client.stock(fake_1c.TILE_GREY)
    assert [row.reserved for row in report.warehouses] == [40.0, 6.0]
    assert report.total_reserved == 46.0
    await client.aclose()


async def test_item_without_stock_is_empty(onec):
    report = await onec.stock(fake_1c.SOLD_OUT)
    assert report.warehouses == []
    assert report.total_quantity == 0


async def test_negative_stock_is_kept(onec):
    report = await onec.stock(fake_1c.ODD_NAME)
    assert report.total_quantity == -2


async def test_warehouse_names_are_cached(onec):
    await onec.stock(fake_1c.TILE_GREY)
    await onec.stock(fake_1c.MARBLE)
    assert sum("Catalog_" in call for call in fake_1c.state.calls) == 1


async def test_item_id_must_be_a_guid(onec):
    with pytest.raises(ValueError):
        await onec.stock("x' or '1' eq '1")


async def test_wrong_password_is_reported(onec_transport):
    client = OneCClient(onec_settings(password="wrong"), transport=onec_transport)
    with pytest.raises(OneCRejected):
        await client.search("CS-6060")
    await client.aclose()


async def test_missing_quantity_field_is_a_query_error(onec_transport):
    client = OneCClient(onec_settings(quantity_field="Нет"), transport=onec_transport)
    with pytest.raises(OneCQueryError):
        await client.stock(fake_1c.TILE_GREY)
    await client.aclose()


async def test_missing_reserve_field_shows_zero(onec_transport):
    client = OneCClient(onec_settings(reserve_field="Нет"), transport=onec_transport)
    assert (await client.stock(fake_1c.TILE_GREY)).total_reserved == 0
    await client.aclose()


async def test_iis_error_page_means_unavailable(onec):
    fake_1c.state.fail_with = (502, "<html>Bad Gateway</html>")
    with pytest.raises(OneCUnavailable):
        await onec.search("CS-6060")


async def test_odata_error_is_a_query_error(onec):
    fake_1c.state.fail_with = (500, '{"odata.error":{"code":"-1"}}')
    with pytest.raises(OneCQueryError):
        await onec.search("CS-6060")


async def test_html_with_status_200_means_unavailable(onec):
    fake_1c.state.fail_with = (200, "<html>login</html>")
    with pytest.raises(OneCUnavailable):
        await onec.search("CS-6060")


async def test_timeout_means_unavailable():
    def boom(request):
        raise httpx.ReadTimeout("slow", request=request)

    client = OneCClient(onec_settings(), transport=httpx.MockTransport(boom))
    with pytest.raises(OneCUnavailable):
        await client.search("CS-6060")
    await client.aclose()


async def test_dollar_signs_reach_1c_unencoded(onec):
    await onec.search("CS-6060-GR")
    assert "$filter=" in fake_1c.state.calls[0]
    assert "%24" not in fake_1c.state.calls[0]
