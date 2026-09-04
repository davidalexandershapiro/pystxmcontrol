"""One registry of agent tools, and the emitters that advertise them per surface.

The tool implementations are shared (see instrument_client and agent_ports for the
collaborators they run on), but each surface advertises them differently: the task
agent's loop wants OpenAI function schemas, the MCP server wants ``@mcp.tool()``
registrations.  Both are DERIVED here from the one decorated function, because the
alternative — which this replaces — was three hand-maintained lists that had already
drifted: a 900-line block of OpenAI schemas, the MCP server's decorators, and
``sdk_agent.AUTO_ALLOW``.

What is derived versus declared
-------------------------------
Parameter names, JSON types and the required list are DERIVED from the signature.
Hand-writing those is exactly where drift becomes dangerous — a schema can promise a
parameter the function does not accept, and nothing fails until an agent tries it.

Prose is DECLARED, in the docstring: the summary before ``Args:`` becomes the tool
description, and the ``Args:`` entries become parameter descriptions.  Units live
there ("µm", "ms per pixel") and matter to the model, so a docstring that omits them
is a real regression, not a cosmetic one.

Gating
------
Three independent axes, all resolved by the emitters rather than by the tools:

* ``requires`` — capabilities the tool needs ("frames", "logbook").  A surface
  advertises only the tools whose requirements it can satisfy, which is what makes
  tiering a property of the tool instead of thirteen scattered None-checks.
* ``mutates_hardware`` — commands the instrument.  Read-only MCP mode does not
  advertise these at all, which is stronger than a permission rule the user can edit.
* ``feature`` — advertised only when a named config feature is on (the logbook-context
  read tools are off by default so they cost no tokens).
"""

from __future__ import annotations

import inspect
import types
import typing
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolSpec:
    """One agent tool: the function plus how each surface should advertise it."""

    name: str
    fn: typing.Callable
    requires: tuple[str, ...] = ()
    mutates_hardware: bool = False
    feature: str | None = None
    schema_override: dict | None = None
    params: dict = field(default_factory=dict)
    hidden_params: tuple[str, ...] = ()

    def available(self, have: typing.Iterable[str], features: typing.Iterable[str]) -> bool:
        """True when a surface with these capabilities and features may advertise it."""
        return set(self.requires) <= set(have) and (
            self.feature is None or self.feature in set(features))


_SPEC_ATTR = "_tool_spec"


def tool(*, requires: typing.Sequence[str] = (), mutates_hardware: bool = False,
         feature: str | None = None, schema: dict | None = None,
         params: dict | None = None, hidden_params: typing.Sequence[str] = ()):
    """Mark a ToolSet method as an agent tool.

    :param requires: capabilities the tool needs, e.g. ``("frames",)``.
    :param mutates_hardware: True if it commands the instrument (moves a motor,
        starts or cancels a scan).  Read-only surfaces do not advertise these.
    :param feature: advertise only when this named config feature is enabled.
    :param schema: complete parameters schema, for a function whose signature cannot
        be introspected (a ``**kwargs`` tool).  Prefer a real signature.
    :param params: per-parameter descriptions, when they cannot live in an ``Args:``
        block.  The docstring is the better home; this is the escape hatch.
    :param hidden_params: parameters the function accepts but does NOT advertise —
        a deprecated argument kept for backward compatibility should still work when
        passed, without inviting the model to use it.
    """
    def deco(fn):
        setattr(fn, _SPEC_ATTR, dict(
            requires=tuple(requires), mutates_hardware=mutates_hardware,
            feature=feature, schema_override=schema, params=dict(params or {}),
            hidden_params=tuple(hidden_params)))
        return fn
    return deco


def specs_for(cls) -> list[ToolSpec]:
    """Every ``@tool``-decorated method on *cls*, in definition order.

    Definition order is the advertised order, so moving a method moves it in the
    schema list — keep that in mind when splitting this file by domain.
    """
    specs = []
    for name, member in vars(cls).items():
        meta = getattr(member, _SPEC_ATTR, None)
        if meta is not None:
            specs.append(ToolSpec(name=name, fn=member, **meta))
    return specs


# ---------------------------------------------------------------------------
# Signature -> JSON Schema
# ---------------------------------------------------------------------------

_JSON_TYPES = {
    str: "string", int: "integer", float: "number", bool: "boolean",
    dict: "object", list: "array",
}


def _unwrap_optional(annotation):
    """``X | None`` -> ``(X, True)``; anything else -> ``(annotation, False)``.

    Optionality is expressed by leaving the parameter out of ``required``, not by a
    null type, which is what the hand-written schemas did and what models expect.
    """
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def _json_schema_for(annotation) -> dict:
    """JSON Schema fragment for one parameter annotation."""
    annotation, _ = _unwrap_optional(annotation)
    if annotation is inspect.Parameter.empty:
        return {}                                  # untyped: accept anything
    origin = typing.get_origin(annotation)
    if origin in (list, typing.List):
        args = typing.get_args(annotation)
        item = _json_schema_for(args[0]) if args else {}
        return {"type": "array", "items": item} if item else {"type": "array"}
    if origin in (dict, typing.Dict):
        return {"type": "object"}
    return {"type": _JSON_TYPES.get(annotation, "string")}


# ---------------------------------------------------------------------------
# Docstring -> prose
# ---------------------------------------------------------------------------

_SECTIONS = ("Args:", "Arguments:", "Returns:", "Raises:", "Yields:", "Note:")


def parse_docstring(doc: str | None) -> tuple[str, dict[str, str]]:
    """``(summary, {param: description})`` from a Google-style docstring.

    The summary is everything before the first section header, whitespace-collapsed.
    ``Args:`` entries are ``name: description``, continued on more-indented lines.
    """
    if not doc:
        return "", {}
    lines = inspect.cleandoc(doc).splitlines()

    summary, i = [], 0
    while i < len(lines) and not lines[i].strip().startswith(_SECTIONS):
        summary.append(lines[i])
        i += 1
    summary_text = " ".join(" ".join(summary).split())

    params: dict[str, str] = {}
    if i < len(lines) and lines[i].strip().startswith(("Args:", "Arguments:")):
        i += 1
        current = None
        for line in lines[i:]:
            if line.strip().startswith(_SECTIONS):
                break
            if not line.strip():
                continue
            stripped = line.strip()
            # A new entry looks like "name: text" (or "name (type): text") at the
            # shallower indent; anything deeper continues the previous entry.
            head, sep, tail = stripped.partition(":")
            token = head.split("(")[0].strip()
            if sep and token.isidentifier() and not line.startswith(" " * 8):
                current = token
                params[current] = tail.strip()
            elif current:
                params[current] = (params[current] + " " + stripped).strip()
    return summary_text, {k: " ".join(v.split()) for k, v in params.items()}


# ---------------------------------------------------------------------------
# Emitter: OpenAI function schemas
# ---------------------------------------------------------------------------

def parameters_schema(spec: ToolSpec) -> dict:
    """The ``parameters`` object for *spec*, derived from its signature."""
    if spec.schema_override is not None:
        return spec.schema_override

    _, doc_params = parse_docstring(spec.fn.__doc__)
    descriptions = {**doc_params, **spec.params}

    hints = typing.get_type_hints(spec.fn)
    properties, required = {}, []
    for name, param in inspect.signature(spec.fn).parameters.items():
        if (name == "self" or name in spec.hidden_params
                or param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD)):
            continue
        prop = _json_schema_for(hints.get(name, param.annotation))
        if descriptions.get(name):
            prop["description"] = descriptions[name]
        properties[name] = prop
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": properties, "required": required}


def openai_schema(spec: ToolSpec) -> dict:
    """One OpenAI function schema for *spec*."""
    summary, _ = parse_docstring(spec.fn.__doc__)
    return {"type": "function",
            "function": {"name": spec.name,
                         "description": summary,
                         "parameters": parameters_schema(spec)}}


def openai_schemas(specs: typing.Sequence[ToolSpec], *,
                   have: typing.Iterable[str] = (),
                   features: typing.Iterable[str] = ()) -> list[dict]:
    """OpenAI function schemas for the tools this surface can advertise."""
    return [openai_schema(s) for s in specs if s.available(have, features)]


# ---------------------------------------------------------------------------
# Emitter: FastMCP registration
# ---------------------------------------------------------------------------

_PY_TYPES = {"string": str, "integer": int, "number": float,
             "boolean": bool, "array": list, "object": dict}


def _mcp_callable(spec: ToolSpec, get_toolset, schema: dict):
    """A wrapper over ``get_toolset().<spec.name>`` carrying an explicit signature.

    FastMCP builds its argument validation from ``inspect.signature``, which two of
    our tools defeat: a ``**kwargs`` tool becomes a single required string parameter
    named "kwargs", and hidden parameters would be advertised.  Synthesising the
    signature from the registry's schema fixes both, and keeps ONE derivation of the
    parameter set behind both surfaces.

    Arguments the caller omitted arrive as None and are dropped, so the underlying
    method applies its own defaults rather than being handed a None it never expects.

    The toolset is resolved per call, not captured: a host may connect lazily on first
    use, or swap in a new connection (a reconnect), and tools bound to the old one
    would keep talking to a dead socket.
    """
    params = []
    for name, prop in schema["properties"].items():
        annotation = _PY_TYPES.get(prop.get("type"), str)
        if name in schema.get("required", ()):
            params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY,
                                            annotation=annotation))
        else:
            params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY,
                                            default=None, annotation=annotation | None))

    def call(**kwargs):
        method = getattr(get_toolset(), spec.name)
        return method(**{k: v for k, v in kwargs.items() if v is not None})

    call.__signature__ = inspect.Signature(params)
    call.__name__ = spec.name
    call.__doc__ = spec.fn.__doc__
    return call


def register_mcp(mcp, get_toolset: typing.Callable[[], typing.Any],
                 specs: typing.Sequence[ToolSpec], *,
                 have: typing.Iterable[str] = (),
                 features: typing.Iterable[str] = (),
                 readonly: bool = False) -> list[str]:
    """Register the tools this MCP surface can serve.  Returns the names registered.

    *get_toolset* is a zero-argument callable returning the live ToolSet, called on
    each tool invocation rather than once here, so the host can connect lazily.

    *readonly* drops every hardware-mutating tool.  They are not registered at all, so
    they are invisible to the agent rather than merely denied — a stronger guarantee
    than a permission rule the user can edit.

    FastMCP's own schema derivation is weaker than this module's: it ignores ``Args:``
    descriptions entirely, so units ("µm", "ms per pixel") would be lost.  The tool's
    ``parameters`` is therefore overwritten with the registry's schema after
    registration, which is also what keeps the two surfaces advertising the same text.
    """
    registered = []
    for spec in specs:
        if not spec.available(have, features) or (readonly and spec.mutates_hardware):
            continue
        schema = parameters_schema(spec)
        summary, _ = parse_docstring(spec.fn.__doc__)
        mcp.tool(name=spec.name,
                 description=summary)(_mcp_callable(spec, get_toolset, schema))
        mcp._tool_manager.get_tool(spec.name).parameters = schema
        registered.append(spec.name)
    return registered
