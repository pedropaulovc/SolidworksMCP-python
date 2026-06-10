"""Parametric-variant tools for SolidWorks MCP Server (Phase 4).

Provides tools for equation-driven sketch curves, equation-manager global
variables and driving equations, and configuration management — the
building blocks for one-part/many-configurations workflows (e.g. a gear
part whose tooth count varies per configuration).
"""

from typing import Any

from fastmcp import FastMCP
from loguru import logger
from pydantic import BaseModel, Field

from ..adapters.base import (
    CreateConfigurationParameters,
    CreateEquationCurveParameters,
    CreateEquationParameters,
    SetGlobalVariableParameters,
    SolidWorksAdapter,
)
from .modeling import _normalize_input


class CreateEquationDrivenCurveInput(BaseModel):
    """Input schema for creating an equation-driven sketch curve.

    Attributes:
        x_expression (str): x(t) for parametric curves; empty for explicit.
        y_expression (str): y(t) (parametric) or f(x) (explicit).
        z_expression (str): z(t) for 3D parametric curves.
        range_start (str): Range start expression.
        range_end (str): Range end expression.
        is_angle_range (bool): Whether the range is an angle in radians.
        lock_start (bool): Lock the start point.
        lock_end (bool): Lock the end point.
    """

    x_expression: str = Field(
        default="",
        description=(
            "Equation for x in terms of t (parametric curve), e.g. "
            "'0.05*cos(t)'; leave empty for an explicit y = f(x) curve. "
            "Lengths evaluate in metres."
        ),
    )
    y_expression: str = Field(
        description=(
            "Equation for y — in terms of t for a parametric curve (e.g. "
            "'0.05*sin(t)') or in terms of x for an explicit curve (e.g. "
            "'0.01*sin(x/0.01)'). Lengths evaluate in metres."
        )
    )
    z_expression: str = Field(
        default="",
        description="Equation for z in terms of t (3D parametric curves only)",
    )
    range_start: str = Field(
        description=(
            "Start of the t (or x) range as a string expression, e.g. '0' or '-pi/2'"
        )
    )
    range_end: str = Field(description="End of the t (or x) range, e.g. '6.28' or 'pi'")
    is_angle_range: bool = Field(
        default=False,
        description="True when the range represents an angle in radians",
    )
    lock_start: bool = Field(default=True, description="Lock the curve's start point")
    lock_end: bool = Field(default=True, description="Lock the curve's end point")

    def model_post_init(self, __context: Any) -> None:
        """Validate expression requirements.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When required expressions are missing.
        """
        if not self.y_expression.strip():
            raise ValueError("y_expression is required")
        if not self.range_start.strip() or not self.range_end.strip():
            raise ValueError("range_start and range_end are required")
        if self.z_expression.strip() and not self.x_expression.strip():
            raise ValueError("3D curves (z_expression) require x_expression")


class SetGlobalVariableInput(BaseModel):
    """Input schema for adding or updating a global variable.

    Attributes:
        name (str): Variable name without quotes.
        expression (str): Right-hand-side expression.
        configuration (str): Configuration scope; empty for all.
    """

    name: str = Field(
        description="Global variable name without quotes, e.g. 'ToothCount'"
    )
    expression: str = Field(
        description=(
            "Right-hand side, e.g. '24' or '\"PitchDiameter\" / \"Module\"' "
            "(referenced names in embedded double quotes)"
        )
    )
    configuration: str = Field(
        default="",
        description=(
            "Configuration this assignment applies to; empty applies it to "
            "all configurations"
        ),
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate the variable name and expression.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the name is empty/quoted or expression empty.
        """
        if not self.name.strip():
            raise ValueError("name is required")
        if '"' in self.name:
            raise ValueError("name must not contain quotes (added automatically)")
        if not self.expression.strip():
            raise ValueError("expression is required")


class CreateEquationInput(BaseModel):
    """Input schema for adding or updating a driving equation.

    Attributes:
        equation (str): Full equation with quoted names.
        configuration (str): Configuration scope; empty for all.
    """

    equation: str = Field(
        description=(
            "Complete equation with dimension/variable names in embedded "
            'double quotes, e.g. \'"D1@Boss-Extrude1" = "ToothCount" / 2\''
        )
    )
    configuration: str = Field(
        default="",
        description=(
            "Configuration this equation applies to; empty applies it to "
            "all configurations"
        ),
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate the equation shape.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the equation has no '=' or no quoted LHS.
        """
        if "=" not in self.equation:
            raise ValueError("equation must contain '='")
        lhs = self.equation.partition("=")[0].strip()
        if not (lhs.startswith('"') and lhs.endswith('"') and len(lhs) > 2):
            raise ValueError(
                "equation left-hand side must be a double-quoted name, e.g. "
                "'\"D1@Sketch1\" = ...'"
            )


class CreateConfigurationInput(BaseModel):
    """Input schema for creating a configuration.

    Attributes:
        name (str): New configuration name.
        comment (str): Configuration comment.
        parent (str): Parent configuration name.
        description (str): Configuration description.
    """

    name: str = Field(description="New configuration name, e.g. 'T24'")
    comment: str = Field(
        default="", description="Comment shown in Configuration Properties"
    )
    parent: str = Field(
        default="",
        description=(
            "Parent configuration name for a derived configuration; empty "
            "for a top-level configuration"
        ),
    )
    description: str = Field(default="", description="Configuration description text")

    def model_post_init(self, __context: Any) -> None:
        """Validate the configuration name.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the name is empty.
        """
        if not self.name.strip():
            raise ValueError("name is required")


class SetActiveConfigurationInput(BaseModel):
    """Input schema for activating a configuration.

    Attributes:
        name (str): Configuration name to activate.
    """

    name: str = Field(description="Configuration name to activate")

    def model_post_init(self, __context: Any) -> None:
        """Validate the configuration name.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: When the name is empty.
        """
        if not self.name.strip():
            raise ValueError("name is required")


async def register_parametrics_tools(
    mcp: FastMCP, adapter: SolidWorksAdapter, config: Any
) -> int:
    """Register parametric-variant tools with the MCP server.

    Args:
        mcp (FastMCP): The mcp value.
        adapter (SolidWorksAdapter): Adapter instance used for the operation.
        config (Any): Configuration values for the operation.

    Returns:
        int: The number of tools registered.
    """

    @mcp.tool()
    async def create_equation_driven_curve(
        input_data: CreateEquationDrivenCurveInput,
    ) -> dict[str, Any]:
        """Create an equation-driven curve in the active sketch.

        Supports explicit curves (y = f(x), leave x_expression empty),
        2D parametric curves (x(t), y(t)) and 3D parametric curves
        (x(t), y(t), z(t)). Expressions use SolidWorks equation syntax and
        evaluate lengths in metres — the involute gear flank and harmonic
        cam profiles are the canonical uses.

        Args:
            input_data (CreateEquationDrivenCurveInput): Expressions, range.

        Returns:
            dict[str, Any]: Status and the registered curve entity ID.

        Example:
            ```python
            # Involute flank: t in [0, 0.6] rad on a 24 mm base circle
            result = await create_equation_driven_curve({
                "x_expression": "0.024*(cos(t)+t*sin(t))",
                "y_expression": "0.024*(sin(t)-t*cos(t))",
                "range_start": "0",
                "range_end": "0.6",
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, CreateEquationDrivenCurveInput)
            result = await adapter.create_equation_driven_curve(
                CreateEquationCurveParameters(
                    x_expression=input_data.x_expression,
                    y_expression=input_data.y_expression,
                    z_expression=input_data.z_expression,
                    range_start=input_data.range_start,
                    range_end=input_data.range_end,
                    is_angle_range=input_data.is_angle_range,
                    lock_start=input_data.lock_start,
                    lock_end=input_data.lock_end,
                )
            )
            if result.is_success:
                return {
                    "status": "success",
                    "message": f"Created equation-driven curve: {result.data}",
                    "entity_id": result.data,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": (
                        f"Failed to create equation-driven curve: {result.error}"
                    ),
                }
        except Exception as e:
            logger.error(f"Error in create_equation_driven_curve tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def set_global_variable(
        input_data: SetGlobalVariableInput,
    ) -> dict[str, Any]:
        """Add or update a global variable in the equation manager.

        Creates the assignment '"name" = expression'. When a global with the
        same name already exists its right-hand side is updated in place, so
        the tool is idempotent. Pass a configuration name to scope the value
        to one configuration (the backbone of config-driven parts) — that
        configuration is activated as a side effect.

        Args:
            input_data (SetGlobalVariableInput): Name, expression, scope.

        Returns:
            dict[str, Any]: Status and equation details.

        Example:
            ```python
            result = await set_global_variable({
                "name": "ToothCount",
                "expression": "24",
                "configuration": "T24",
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, SetGlobalVariableInput)
            result = await adapter.set_global_variable(
                SetGlobalVariableParameters(
                    name=input_data.name,
                    expression=input_data.expression,
                    configuration=input_data.configuration,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Set global variable: {payload.get('equation')}",
                    "global_variable": payload,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to set global variable: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in set_global_variable tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def create_equation(input_data: CreateEquationInput) -> dict[str, Any]:
        """Add or update a driving equation in the equation manager.

        The equation links dimensions to globals or other dimensions, e.g.
        '"D1@CirPattern1" = "ToothCount"'. When an equation with the same
        left-hand side already exists it is updated in place. Pass a
        configuration name to scope the equation to one configuration —
        that configuration is activated as a side effect.

        Args:
            input_data (CreateEquationInput): Equation text and scope.

        Returns:
            dict[str, Any]: Status and equation details.

        Example:
            ```python
            result = await create_equation({
                "equation": '"D1@CirPattern1" = "ToothCount"',
            })
            ```
        """
        try:
            input_data = _normalize_input(input_data, CreateEquationInput)
            result = await adapter.create_equation(
                CreateEquationParameters(
                    equation=input_data.equation,
                    configuration=input_data.configuration,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Created equation: {payload.get('equation')}",
                    "equation": payload,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create equation: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in create_equation tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def create_configuration(
        input_data: CreateConfigurationInput,
    ) -> dict[str, Any]:
        """Create a configuration on the active model.

        The new configuration becomes the active one. Combine with
        set_global_variable(configuration=...) to give each configuration
        its own parameter values, then switch between them with
        set_active_configuration.

        Args:
            input_data (CreateConfigurationInput): Name and metadata.

        Returns:
            dict[str, Any]: Status and configuration details.

        Example:
            ```python
            result = await create_configuration({"name": "T24"})
            ```
        """
        try:
            input_data = _normalize_input(input_data, CreateConfigurationInput)
            result = await adapter.create_configuration(
                CreateConfigurationParameters(
                    name=input_data.name,
                    comment=input_data.comment,
                    parent=input_data.parent,
                    description=input_data.description,
                )
            )
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Created configuration: {payload.get('name')}",
                    "configuration": payload,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to create configuration: {result.error}",
                }
        except Exception as e:
            logger.error(f"Error in create_configuration tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    async def set_active_configuration(
        input_data: SetActiveConfigurationInput,
    ) -> dict[str, Any]:
        """Activate a configuration by name and rebuild the model.

        Switches the active configuration and rebuilds so geometry driven by
        configured values reflects the new configuration — required before
        reading mass properties or exporting per configuration.

        Args:
            input_data (SetActiveConfigurationInput): Configuration name.

        Returns:
            dict[str, Any]: Status and activation details.

        Example:
            ```python
            result = await set_active_configuration({"name": "T24"})
            ```
        """
        try:
            input_data = _normalize_input(input_data, SetActiveConfigurationInput)
            result = await adapter.set_active_configuration(input_data.name)
            if result.is_success:
                payload = result.data or {}
                return {
                    "status": "success",
                    "message": f"Activated configuration: {payload.get('name')}",
                    "configuration": payload,
                    "execution_time": result.execution_time,
                }
            else:
                return {
                    "status": "error",
                    "message": (f"Failed to activate configuration: {result.error}"),
                }
        except Exception as e:
            logger.error(f"Error in set_active_configuration tool: {e}")
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    tool_count = 5  # Number of tools registered
    return tool_count
