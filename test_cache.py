"""Тесты кеша: все 6 сценариев из задания."""

import pytest

import cache as cache_mod
from cache import Cache, CacheStats, MainMemory


def _run(cache: Cache) -> None:
    """Прокрутить tick() до завершения запроса."""
    while cache.is_busy():
        cache.tick()


def make_cache() -> tuple[Cache, MainMemory]:
    """Свежий кеш с памятью 256 слов, заполненной 0..255."""
    ram = MainMemory(size=256)
    for i in range(256):
        ram.write(i, i)
    return Cache(ram), ram


def test_cold_read_miss_then_hit() -> None:
    cache, _ = make_cache()

    cache.request(0, "read")
    _run(cache)
    assert cache.response() == 0
    assert cache.stats == CacheStats(hits=0, misses=1, writebacks=0)

    cache.request(0, "read")
    _run(cache)
    assert cache.response() == 0
    assert cache.stats == CacheStats(hits=1, misses=1, writebacks=0)


def test_line_fill_first_miss_rest_hits() -> None:
    cache, _ = make_cache()

    cache.request(0, "read")
    _run(cache)
    assert cache.response() == 0
    assert cache.stats.misses == 1

    for addr in (1, 2, 3):
        cache.request(addr, "read")
        _run(cache)
        assert cache.response() == addr

    assert cache.stats == CacheStats(hits=3, misses=1, writebacks=0)


def test_eviction_clean_no_writeback() -> None:
    cache, _ = make_cache()

    cache.request(0, "read")
    _run(cache)
    assert cache.stats.misses == 1

    cache.request(16, "read")
    _run(cache)
    assert cache.response() == 16
    assert cache.stats == CacheStats(hits=0, misses=2, writebacks=0)


def test_eviction_dirty_writeback() -> None:
    cache, ram = make_cache()

    cache.request(0, "write", data=42)
    _run(cache)
    assert cache.stats == CacheStats(hits=0, misses=1, writebacks=0)

    cache.request(16, "read")
    _run(cache)
    assert cache.response() == 16
    assert cache.stats == CacheStats(hits=0, misses=2, writebacks=1)

    assert ram.read(0) == 42


def test_write_allocate_on_miss() -> None:
    cache, ram = make_cache()

    cache.request(4, "write", data=77)
    _run(cache)
    assert cache.stats == CacheStats(hits=0, misses=1, writebacks=0)

    cache.request(5, "read")
    _run(cache)
    assert cache.response() == 5
    assert cache.stats == CacheStats(hits=1, misses=1, writebacks=0)

    cache.request(20, "read")
    _run(cache)
    assert ram.read(4) == 77
    assert cache.stats == CacheStats(hits=1, misses=2, writebacks=1)


def test_write_hit_after_write_allocate() -> None:
    cache, _ = make_cache()

    cache.request(0, "write", data=10)
    _run(cache)
    assert cache.stats == CacheStats(hits=0, misses=1, writebacks=0)

    cache.request(0, "write", data=20)
    _run(cache)
    assert cache.stats == CacheStats(hits=1, misses=1, writebacks=0)

    cache.request(0, "read")
    _run(cache)
    assert cache.response() == 20
    assert cache.stats == CacheStats(hits=2, misses=1, writebacks=0)


def test_mmio_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    # Патчим MMIO_BASE на маленький адрес чтобы не аллоцировать гигантскую RAM
    mmio_addr = 200
    monkeypatch.setattr(cache_mod, "MMIO_BASE", mmio_addr)

    ram = MainMemory(size=256)
    ram.write(mmio_addr, 255)
    c = Cache(ram)
    c.request(mmio_addr, "read")
    _run(c)
    assert c.response() == 255
    assert c.stats == CacheStats(hits=0, misses=0, writebacks=0)


def test_timing_miss_ticks() -> None:
    cache, _ = make_cache()

    cache.request(0, "read")
    ticks = 0
    while cache.is_busy():
        cache.tick()
        ticks += 1
    assert ticks == 10  # 9 stall + 1 execute


def test_timing_dirty_eviction_ticks() -> None:
    cache, _ = make_cache()

    cache.request(0, "write", data=1)
    _run(cache)

    cache.request(16, "read")
    ticks = 0
    while cache.is_busy():
        cache.tick()
        ticks += 1
    assert ticks == 19  # 18 stall + 1 execute


def test_timing_hit_ticks() -> None:
    cache, _ = make_cache()

    cache.request(0, "read")
    _run(cache)

    # HIT завершается внутри request() - кеш не busy, 0 дополнительных тиков
    cache.request(0, "read")
    assert not cache.is_busy()
    ticks = 0
    while cache.is_busy():
        cache.tick()
        ticks += 1
    assert ticks == 0


@pytest.mark.parametrize("addr", [0, 1, 2, 3, 7, 15])
def test_split_roundtrip(addr: int) -> None:
    from cache import _split

    tag, index, offset = _split(addr)
    reconstructed = (tag << 4) | (index << 2) | offset
    assert reconstructed == addr
