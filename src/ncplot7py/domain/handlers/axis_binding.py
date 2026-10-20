"""Axis binding handler for mapping logical programmed axes to machine physical axes."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ncplot7py.domain.cnc_state import CNCState
from ncplot7py.domain.exec_chain import Handler
from ncplot7py.shared.nc_nodes import NCCommandNode
from ncplot7py.shared.point import Point


class AxisBindingHandler(Handler):
    """Maps programmed axes (X, Y, Z, B, C) to channel-specific physical axes (X1/X2, B1, C1/C2)."""

    def handle(self, node: NCCommandNode, state: CNCState) -> Tuple[Optional[List[Point]], Optional[float]]:
        self.apply_bindings(state, node=node)
        return super().handle(node, state)

    @classmethod
    def apply_bindings(cls, state: CNCState, node: Optional[NCCommandNode] = None) -> None:
        config = getattr(state, "machine_config", None)
        bindings = getattr(config, "axis_bindings", None)
        if not isinstance(bindings, dict) or not bindings:
            return

        channel_id = str(state.channel_state.path_number or 1)
        axis_map: Dict[str, str] = state.channel_state.axis_map
        target_carriers: Dict[str, str] = state.channel_state.target_carriers

        # Initialize defaults for this channel
        for logical_axis, binding in bindings.items():
            if logical_axis not in axis_map:
                defaults = binding.get("defaultByChannel", {})
                default = defaults.get(channel_id) or defaults.get(f"C{channel_id}")
                if isinstance(default, dict):
                    axis_id = default.get("axisId")
                    if axis_id:
                        axis_map[logical_axis] = axis_id
                        state.set_axis(axis_id, state.get_axis(axis_id))
                    carrier_id = default.get("targetCarrierId")
                    if carrier_id:
                        target_carriers[logical_axis] = carrier_id
                        if logical_axis == "C":
                            if state.star_state.target_carrier_id is None:
                                state.star_state.target_carrier_id = carrier_id
                            if state.star_state.target_axis is None:
                                state.star_state.target_axis = axis_id

        # Process dynamic M-code overrides
        if node is not None:
            m_codes = set()
            for code in getattr(node, "m_code", ()) or ():
                m_codes.add(str(code).strip().upper())
            m_val = getattr(node, "command_parameter", {}).get("M")
            if m_val is not None:
                m_str = str(m_val).strip().upper()
                m_codes.add(f"M{m_str}" if not m_str.startswith("M") else m_str)

            for m_code in m_codes:
                for logical_axis, binding in bindings.items():
                    overrides = binding.get("mcodeOverrides", {})
                    override = overrides.get(m_code)
                    if isinstance(override, dict):
                        axis_id = override.get("axisId")
                        if axis_id:
                            axis_map[logical_axis] = axis_id
                            state.set_axis(axis_id, state.get_axis(axis_id))
                        carrier_id = override.get("targetCarrierId")
                        if carrier_id:
                            target_carriers[logical_axis] = carrier_id
                            if logical_axis == "C":
                                state.star_state.target_carrier_id = carrier_id
                        if logical_axis == "C":
                            state.star_state.path_mode = m_code
                            if axis_id:
                                state.star_state.target_axis = axis_id


__all__ = ["AxisBindingHandler"]
