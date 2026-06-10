"""Generic wrapper delegation: new adapter methods reach the inner adapter.

CircuitBreakerAdapter and ConnectionPoolAdapter inherit from
SolidWorksAdapter and historically delegated per-method, so any adapter
method added after the wrappers were written resolved to the base default
"not implemented by this adapter" error instead of the wrapped adapter.
These tests pin the generic instance-level delegates that close that gap.
"""

from __future__ import annotations

import pytest

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
    CreatePlaneParameters,
    MeasureEntityRef,
    MeasureParameters,
)
from solidworks_mcp.adapters.circuit_breaker import CircuitBreakerAdapter
from solidworks_mcp.adapters.connection_pool import ConnectionPoolAdapter


class _StubAdapter:
    """Inner adapter implementing methods the wrappers never wrap explicitly."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def connect(self):
        return None

    async def disconnect(self):
        return None

    async def measure(self, params):
        self.calls.append(("measure", params))
        return AdapterResult(status=AdapterResultStatus.SUCCESS, data={"length": 100.0})

    async def create_plane(self, params):
        self.calls.append(("create_plane", params))
        return AdapterResult(status=AdapterResultStatus.SUCCESS, data="Plane1")


def _measure_params() -> MeasureParameters:
    return MeasureParameters(
        entities=[MeasureEntityRef(entity_type="EDGE", point=[0.0, 0.0, 0.0])]
    )


@pytest.mark.asyncio
async def test_circuit_breaker_forwards_measure_to_inner_adapter() -> None:
    inner = _StubAdapter()
    wrapper = CircuitBreakerAdapter(adapter=inner)

    result = await wrapper.measure(_measure_params())

    assert result.is_success
    assert result.data == {"length": 100.0}
    assert inner.calls[0][0] == "measure"


@pytest.mark.asyncio
async def test_circuit_breaker_forwards_create_plane_to_inner_adapter() -> None:
    inner = _StubAdapter()
    wrapper = CircuitBreakerAdapter(adapter=inner)

    result = await wrapper.create_plane(
        CreatePlaneParameters(mode="offset", base_plane="Front Plane", offset=30.0)
    )

    assert result.is_success
    assert result.data == "Plane1"
    assert inner.calls[0][0] == "create_plane"


@pytest.mark.asyncio
async def test_circuit_breaker_counts_failures_through_generic_delegate() -> None:
    class _FailingAdapter(_StubAdapter):
        async def measure(self, params):
            raise Exception("COM boom")

    wrapper = CircuitBreakerAdapter(adapter=_FailingAdapter(), failure_threshold=1)

    result = await wrapper.measure(_measure_params())

    assert result.is_error
    assert wrapper.failure_count == 1


@pytest.mark.asyncio
async def test_connection_pool_forwards_measure_to_inner_adapter() -> None:
    inner = _StubAdapter()
    pool = ConnectionPoolAdapter(adapter_factory=lambda: inner, max_size=1)
    await pool.connect()

    result = await pool.measure(_measure_params())

    assert result.is_success
    assert result.data == {"length": 100.0}
    assert inner.calls[0][0] == "measure"
    await pool.disconnect()


@pytest.mark.asyncio
async def test_connection_pool_forwards_create_plane_to_inner_adapter() -> None:
    inner = _StubAdapter()
    pool = ConnectionPoolAdapter(adapter_factory=lambda: inner, max_size=1)
    await pool.connect()

    result = await pool.create_plane(
        CreatePlaneParameters(mode="offset", base_plane="Front Plane", offset=30.0)
    )

    assert result.is_success
    assert result.data == "Plane1"
    await pool.disconnect()


def test_explicit_wrapper_methods_are_not_replaced_by_delegates() -> None:
    """Methods the wrapper defines keep their class implementations."""
    breaker = CircuitBreakerAdapter(adapter=_StubAdapter())
    pool = ConnectionPoolAdapter(adapter_factory=_StubAdapter, max_size=1)

    for wrapper in (breaker, pool):
        instance_delegates = {
            name for name in vars(wrapper) if not name.startswith("_")
        }
        # New surface (no explicit wrapper) is delegated per instance...
        assert "measure" in instance_delegates
        assert "create_plane" in instance_delegates
        # ...while explicitly wrapped methods stay on the class.
        explicit = type(wrapper).__dict__
        assert "connect" in explicit
        assert "connect" not in instance_delegates
