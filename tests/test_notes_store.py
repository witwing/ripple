from ripple.notes import store


def test_write_and_load_roundtrip(tmp_path):
    n = store.write(
        body="今天调研了 600519 渠道情况，动销偏弱。",
        tickers=["600519"],
        themes=["白酒"],
        tags=["渠道"],
        source="自己",
        confidence=0.6,
    )
    assert n.path.exists()
    loaded = store.load(n.path)
    assert loaded.id == n.id
    assert loaded.tickers == ["600519"]
    assert loaded.themes == ["白酒"]
    assert loaded.tags == ["渠道"]
    assert loaded.source == "自己"
    assert abs((loaded.confidence or 0) - 0.6) < 1e-9
    assert "动销" in loaded.body


def test_ids_are_unique_within_second(tmp_path):
    ids = {store.write(body=f"n{i}").id for i in range(20)}
    # 20 条同秒也不能撞
    assert len(ids) == 20


def test_iter_notes(tmp_path):
    for i in range(3):
        store.write(body=f"note {i}")
    all_ = list(store.iter_notes())
    assert len(all_) == 3
