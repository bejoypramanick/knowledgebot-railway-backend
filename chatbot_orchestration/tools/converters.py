"""
Tool converters for transforming Pydantic AI tools to Gemini native format.

This module enables tools to be included in Gemini cached content, which is required
per Gemini API: "CachedContent can not be used with GenerateContent request setting tools."
"""

import inspect
import logging
from shared.otel_logger import get_otel_logger
from shared.otel_logger import get_otel_logger
from typing import Any, Callable, List, get_args, get_origin, get_type_hints
from google.genai import types

logger = get_otel_logger(__name__, "chatbot-orchestration")


def convert_python_type_to_json_schema_type(python_type: Any) -> str:
    """Convert Python type annotation to JSON Schema type string."""
    # Handle string annotations (forward references)
    if isinstance(python_type, str):
        python_type_lower = python_type.lower()
        if 'int' in python_type_lower:
            return 'integer'
        elif 'float' in python_type_lower or 'number' in python_type_lower:
            return 'number'
        elif 'bool' in python_type_lower:
            return 'boolean'
        elif 'list' in python_type_lower or 'array' in python_type_lower:
            return 'array'
        elif 'dict' in python_type_lower or 'object' in python_type_lower:
            return 'object'
        return 'string'

    # Get the origin type (for generics like List[str])
    origin = get_origin(python_type)

    # Handle generic types
    if origin is list or origin is List:
        return 'array'
    if origin is dict:
        return 'object'

    # Handle basic types
    if python_type == int:
        return 'integer'
    if python_type == float:
        return 'number'
    if python_type == bool:
        return 'boolean'
    if python_type == str:
        return 'string'
    if python_type == list:
        return 'array'
    if python_type == dict:
        return 'object'

    # Default to string for unknown types
    return 'string'


def extract_tool_metadata(func: Callable) -> dict:
    """
    Extract metadata from a Pydantic AI tool function.

    Returns:
        dict with keys: name, description, parameters, required
    """
    # Get function name
    name = func.__name__

    # Get function description from docstring
    description = inspect.getdoc(func) or f"Function {name}"
    # Clean up description - take first line or first sentence
    description = description.split('\n')[0].strip()
    if len(description) > 200:
        description = description[:197] + "..."

    # Get type hints
    try:
        type_hints = get_type_hints(func, include_extras=True)
    except Exception as e:
        logger.warning(f"Failed to get type hints for {name}: {e}")
        type_hints = {}

    # Get function signature
    sig = inspect.signature(func)

    # Build parameters schema
    properties = {}
    required = []

    for param_name, param in sig.parameters.items():
        # Skip 'self', 'cls', and 'deps' parameters
        if param_name in ('self', 'cls', 'deps'):
            continue

        param_type = type_hints.get(param_name, str)
        param_description = f"Parameter {param_name}"

        # Extract description from Annotated type
        if get_origin(param_type) is type(Annotated):
            args = get_args(param_type)
            if len(args) >= 2:
                # First arg is the actual type, second is the description
                param_type = args[0]
                param_description = args[1] if isinstance(args[1], str) else param_description

        # Convert type to JSON Schema type
        json_type = convert_python_type_to_json_schema_type(param_type)

        properties[param_name] = {
            "type": json_type,
            "description": param_description
        }

        # Check if parameter is required (no default value)
        if param.default == inspect.Parameter.empty:
            required.append(param_name)

    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required
        } if properties else {"type": "object", "properties": {}}
    }


def convert_pydantic_ai_tool_to_gemini(func: Callable) -> types.FunctionDeclaration:
    """
    Convert a Pydantic AI tool (Python function) to Gemini FunctionDeclaration.

    Args:
        func: Python function decorated as a Pydantic AI tool

    Returns:
        types.FunctionDeclaration for use in Gemini API
    """
    try:
        metadata = extract_tool_metadata(func)

        return types.FunctionDeclaration(
            name=metadata["name"],
            description=metadata["description"],
            parameters=metadata["parameters"]
        )
    except Exception as e:
        logger.error(f"Failed to convert tool {func.__name__} to Gemini format: {e}")
        raise


def convert_tools_to_gemini_format(tools: List[Callable]) -> List[types.Tool]:
    """
    Convert a list of Pydantic AI tools to Gemini Tool format.

    Args:
        tools: List of Python functions (Pydantic AI tools)

    Returns:
        List of types.Tool objects for Gemini API
    """
    if not tools:
        return []

    function_declarations = []

    for tool in tools:
        try:
            func_decl = convert_pydantic_ai_tool_to_gemini(tool)
            function_declarations.append(func_decl)
            logger.info(f"✅ Converted tool: {func_decl.name}")
        except Exception as e:
            logger.error(f"❌ Failed to convert tool {tool.__name__}: {e}")
            # Continue with other tools
            continue

    if not function_declarations:
        logger.warning("⚠️ No tools successfully converted")
        return []

    # Wrap all function declarations in a single Tool
    return [types.Tool(function_declarations=function_declarations)]


# For compatibility with imports
__all__ = [
    'convert_tools_to_gemini_format',
    'convert_pydantic_ai_tool_to_gemini',
    'extract_tool_metadata'
]
