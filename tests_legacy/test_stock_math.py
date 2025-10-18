def test_stock_math(app):
    from app.slices.logistics import services as lg

    item = lg.ensure_item(category="med", name="gauze")
    loc = lg.ensure_location(code="W1")
    lg.adjust_stock(item["ulid"], loc["ulid"], delta=10)
    lg.adjust_stock(item["ulid"], loc["ulid"], delta=-3)
    s = lg.get_stock(item["ulid"], loc["ulid"])
    assert s["qty_on_hand"] == 7
