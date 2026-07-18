"""Application composition root.

Provider selection and runtime wiring happen here, not in workflow modules.
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class DianpingComposition:
    capability_registry: Any
    capability_executor: Any
    enable_slidex: bool = False


def _require_capabilities():
    try:
        from automation_core.capabilities import (
            CapabilityExecutor,
            CapabilityRegistry,
        )
    except ImportError as exc:
        raise ImportError(
            "automation-kit capability contracts are required; "
            "install automation-kit with capability platform support"
        ) from exc

    try:
        from automation_core.capabilities import CapabilityResolver
    except ImportError:
        CapabilityResolver = None
    return CapabilityRegistry, CapabilityExecutor, CapabilityResolver


def _build_executor(CapabilityExecutor, CapabilityResolver, registry):
    if CapabilityResolver is not None:
        # V2 style: executor(resolver)
        try:
            return CapabilityExecutor(CapabilityResolver(registry))
        except TypeError:
            pass
    # V1 style: executor(registry)
    return CapabilityExecutor(registry)


def build_composition(
    *,
    enable_slidex: bool = False,
    visual_solver: Optional[Any] = None,
    capability_registry=None,
    capability_executor=None,
) -> DianpingComposition:
    """Build an isolated app composition.

    - Registry/executor are created here unless injected for tests.
    - Slidex is optional and only imported when explicitly enabled.
    - No global singleton is used.
    """
    CapabilityRegistry, CapabilityExecutor, CapabilityResolver = _require_capabilities()

    registry = capability_registry if capability_registry is not None else CapabilityRegistry()
    if enable_slidex:
        try:
            from slidex.integrations.automation_kit import SlidexVisualCapability
        except ImportError as exc:
            raise ImportError(
                "enable_slidex=True requires slidex to be installed"
            ) from exc
        if visual_solver is not None:
            provider = SlidexVisualCapability(visual_solver=visual_solver)
        else:
            provider = SlidexVisualCapability()
        try:
            registry.register(provider)
        except TypeError:
            # Some registry APIs require replace=True when re-registering.
            registry.register(provider, replace=True)

    if capability_executor is not None:
        executor = capability_executor
    else:
        executor = _build_executor(CapabilityExecutor, CapabilityResolver, registry)

    return DianpingComposition(
        capability_registry=registry,
        capability_executor=executor,
        enable_slidex=enable_slidex,
    )


def create_workflow_from_composition(composition, session_factory, context, options):
    from automation_app_dianping.workflow import create_workflow

    return create_workflow(
        session_factory=session_factory,
        context=context,
        options=options,
        capability_executor=composition.capability_executor,
    )
