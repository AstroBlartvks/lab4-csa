"""Тесты кеша: все 6 сценариев из задания.

Адресация байтовая: адреса кратны 4, слово n лежит по байтовому адресу n*4.
Память заполнена так, что слово по адресу a содержит значение a >> 2.
"""

import pytest

import cache as cache_mod
from cache import Cache, CacheStats, MainMemory


def _run(cache: Cache) -> None:
    """Прокрутить tick() до завершения запроса."""
    while cache.is_busy():
        cache.tick()


def make_cache() -> tuple[Cache, MainMemory]:
    """Свежий кеш с памятью 256 слов; слово по адресу a*4 содержит a."""
    ram = MainMemory(size=256)
    for i in range(256):
        ram.write(i * 4, i)
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

    # Остальные 3 слова той же строки (байтовые адреса 4, 8, 12) — HIT.
    for word_idx in (1, 2, 3):
        cache.request(word_idx * 4, "read")
        _run(cache)
        assert cache.response() == word_idx

    assert cache.stats == CacheStats(hits=3, misses=1, writebacks=0)


def test_eviction_clean_no_writeback() -> None:
    cache, _ = make_cache()

    cache.request(0, "read")
    _run(cache)
    assert cache.stats.misses == 1

    # Адрес 64 (слово 16) попадает в ту же строку, что и 0 — вытеснение.
    cache.request(64, "read")
    _run(cache)
    assert cache.response() == 16
    assert cache.stats == CacheStats(hits=0, misses=2, writebacks=0)


def test_eviction_dirty_writeback() -> None:
    cache, ram = make_cache()

    cache.request(0, "write", data=42)
    _run(cache)
    assert cache.stats == CacheStats(hits=0, misses=1, writebacks=0)

    cache.request(64, "read")
    _run(cache)
    assert cache.response() == 16
    assert cache.stats == CacheStats(hits=0, misses=2, writebacks=1)

    assert ram.read(0) == 42


def test_write_allocate_on_miss() -> None:
    cache, ram = make_cache()

    # Запись по байту 16 (слово 4, строка index=1) — write-allocate (MISS).
    cache.request(16, "write", data=77)
    _run(cache)
    assert cache.stats == CacheStats(hits=0, misses=1, writebacks=0)

    # Байт 20 (слово 5) — та же строка → HIT, значение слова 5.
    cache.request(20, "read")
    _run(cache)
    assert cache.response() == 5
    assert cache.stats == CacheStats(hits=1, misses=1, writebacks=0)

    # Байт 80 (слово 20, та же строка index=1, другой tag) — вытеснение грязной.
    cache.request(80, "read")
    _run(cache)
    assert ram.read(16) == 77
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

    cache.request(64, "read")
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


@pytest.mark.parametrize("byte_addr", [0, 4, 8, 12, 28, 60])
def test_split_roundtrip(byte_addr: int) -> None:
    from cache import _split

    tag, index, offset = _split(byte_addr)
    # Реконструкция: собираем адрес слова, затем обратно в байтовый (<<2).
    reconstructed = ((tag << 4) | (index << 2) | offset) << 2
    assert reconstructed == byte_addr
