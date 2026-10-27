#!/usr/bin/env python
"""
Project Lead: Prof Rino Lovreglio — Massey University
Disclaimer:   No responsibility is taken for the use or output of these tools.

validate_fds.py - Static linter for FDS input (.fds) files.

Catches common configuration errors WITHOUT running FDS, in <1 s.
Each rule is a small named function so the rule set is easy to extend.

Usage:
    python validate_fds.py <path-to-.fds>            # validate one file
    python validate_fds.py                           # auto-detect most-recent .fds
    python validate_fds.py --all                     # validate every .fds under simulations/

Exit codes:
    0  - no errors (warnings and info OK)
    1  - one or more errors found
    2  - script invocation problem (file not found, etc.)

The set of checks is intentionally short and high-signal. A finding is one of:
    ERROR    - FDS will fail or produce wrong results
    WARNING  - Probably a mistake, but FDS will accept it
    INFO     - Style / good-practice suggestion
"""

from __future__ import annotations
import os
import re
import sys
import glob
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Parser
# ─────────────────────────────────────────────────────────────────────────────

# A namelist record collected from the file.
@dataclass
class Record:
    name: str                       # e.g. 'OBST', 'DEVC'
    line: int                       # 1-based line of the &NAME token
    raw: str                        # the body text between &NAME and /
    params: Dict[str, Any] = field(default_factory=dict)


def _strip_comments(line: str) -> str:
    """Strip Fortran-style ! comments, but only outside quoted strings."""
    out = []
    in_quote = None
    for ch in line:
        if in_quote:
            out.append(ch)
            if ch == in_quote:
                in_quote = None
        else:
            if ch in ("'", '"'):
                in_quote = ch
                out.append(ch)
            elif ch == '!':
                break
            else:
                out.append(ch)
    return ''.join(out)


_NAMELIST_HEAD = re.compile(r'&(\w+)')


def parse_records(text: str) -> List[Record]:
    """
    Parse FDS namelist records from raw file text.
    A record starts at '&NAME' and ends at the next '/' character (treating
    '/' inside quoted strings as literal).
    """
    # Build a (line_no, char_offset) map and a flat string with comments stripped
    lines = text.splitlines()
    flat_chars = []
    line_offsets = []  # parallel to flat_chars: source line for each char
    for ln_idx, raw_line in enumerate(lines, start=1):
        stripped = _strip_comments(raw_line)
        for ch in stripped:
            flat_chars.append(ch)
            line_offsets.append(ln_idx)
        flat_chars.append('\n')
        line_offsets.append(ln_idx)
    flat = ''.join(flat_chars)

    records: List[Record] = []
    i = 0
    n = len(flat)
    while i < n:
        m = _NAMELIST_HEAD.search(flat, i)
        if not m:
            break
        name = m.group(1)
        body_start = m.end()
        # Find the closing '/' at the same nesting level (FDS doesn't nest, but
        # we still need to skip '/' inside strings)
        j = body_start
        in_quote = None
        while j < n:
            ch = flat[j]
            if in_quote:
                if ch == in_quote:
                    in_quote = None
            else:
                if ch in ("'", '"'):
                    in_quote = ch
                elif ch == '/':
                    break
            j += 1
        body = flat[body_start:j]
        rec = Record(
            name=name,
            line=line_offsets[m.start()] if m.start() < len(line_offsets) else -1,
            raw=body,
        )
        rec.params = parse_params(body)
        records.append(rec)
        i = j + 1
    return records


# Match KEY = VALUE pairs.  VALUE may be a quoted string, a logical, a number,
# or a comma-separated list of any of these.  We capture VALUE as a raw substring
# from '=' up to the next ' KEY=' or end of body.
_KEY_RE = re.compile(r'(\b[A-Za-z_]\w*(?:\([^)]*\))?)\s*=', re.MULTILINE)


def parse_params(body: str) -> Dict[str, Any]:
    """Split a record body into key=value entries."""
    out: Dict[str, Any] = {}
    matches = list(_KEY_RE.finditer(body))
    for idx, m in enumerate(matches):
        key = m.group(1).upper()
        # Drop array-index suffixes like SURF_ID6(2)
        key_base = re.sub(r'\([^)]*\)$', '', key)
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        raw_val = body[start:end].strip().rstrip(',').strip()
        out[key_base] = _coerce(raw_val)
    return out


def _coerce(raw: str) -> Any:
    """Convert a value substring into a Python value."""
    raw = raw.strip().rstrip(',').strip()
    if not raw:
        return ''
    # Quoted string (single or list of strings)
    if raw.startswith(("'", '"')):
        items = _split_csv_respect_quotes(raw)
        items = [_unquote(it) for it in items]
        return items[0] if len(items) == 1 else items
    # Logical
    low = raw.upper().replace('.', '').strip(',')
    if low in ('T', 'TRUE'):
        return True
    if low in ('F', 'FALSE'):
        return False
    # Numbers / comma-separated numbers
    parts = [p.strip() for p in raw.split(',') if p.strip()]
    nums = []
    for p in parts:
        try:
            nums.append(float(p))
        except ValueError:
            return raw  # give up; return raw text
    return nums[0] if len(nums) == 1 else nums


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def _split_csv_respect_quotes(s: str) -> List[str]:
    out, cur, in_q = [], [], None
    for ch in s:
        if in_q:
            cur.append(ch)
            if ch == in_q:
                in_q = None
        else:
            if ch in ("'", '"'):
                in_q = ch
                cur.append(ch)
            elif ch == ',':
                out.append(''.join(cur).strip())
                cur = []
            else:
                cur.append(ch)
    if cur:
        out.append(''.join(cur).strip())
    return [x for x in out if x]


def as_list(v: Any) -> List[Any]:
    if v is None or v == '':
        return []
    return v if isinstance(v, list) else [v]


# ─────────────────────────────────────────────────────────────────────────────
# Findings
# ─────────────────────────────────────────────────────────────────────────────

ERROR, WARNING, INFO = 'ERROR', 'WARNING', 'INFO'

@dataclass
class Finding:
    severity: str
    message: str
    hint: str = ''
    line: int = 0
    rule: str = ''


# ─────────────────────────────────────────────────────────────────────────────
# Rules
# ─────────────────────────────────────────────────────────────────────────────
# Each rule is a function (records, findings) -> None.  Each finding gets the
# rule's name attached automatically via the @rule decorator.

RULES: List[Tuple[str, callable]] = []

def rule(name: str):
    def deco(fn):
        RULES.append((name, fn))
        return fn
    return deco


@rule('head-chid-required')
def _head_chid(records, findings):
    """&HEAD must define CHID (the base name for all output files)."""
    heads = [r for r in records if r.name == 'HEAD']
    if not heads:
        findings.append(Finding(ERROR,
            "&HEAD namelist is missing — CHID is required for FDS to produce output files.",
            hint="Add a line like: &HEAD CHID='my_sim', TITLE='...' /",
            line=1))
        return
    chid = heads[0].params.get('CHID', '')
    if not chid:
        findings.append(Finding(ERROR,
            "&HEAD has no CHID — required.",
            hint="Add CHID='<sim_name>' to the &HEAD line.",
            line=heads[0].line))
    elif ' ' in chid or any(c in chid for c in r'\/:*?"<>|'):
        findings.append(Finding(WARNING,
            f"CHID '{chid}' contains characters that may break Smokeview or output filenames.",
            hint="Use letters, digits, hyphens, and underscores only.",
            line=heads[0].line))


@rule('time-tend-required')
def _time_tend(records, findings):
    """&TIME T_END must be set; otherwise FDS exits immediately."""
    times = [r for r in records if r.name == 'TIME']
    if not times:
        findings.append(Finding(WARNING,
            "&TIME namelist missing; FDS will use default T_END=1.0 s (almost certainly not what you want).",
            hint="Add &TIME T_END=<seconds> /",
            line=1))
        return
    t_end = times[0].params.get('T_END', None)
    if t_end is None:
        findings.append(Finding(WARNING,
            "&TIME has no T_END; FDS will use 1.0 s by default.",
            line=times[0].line))


@rule('mesh-required')
def _mesh_required(records, findings):
    """At least one &MESH is required."""
    meshes = [r for r in records if r.name == 'MESH']
    if not meshes:
        findings.append(Finding(ERROR,
            "No &MESH defined — FDS needs at least one mesh.",
            line=1))


@rule('xb-ordered')
def _xb_ordered(records, findings):
    """For namelists using XB, require xmin<xmax, ymin<ymax, zmin<zmax."""
    for r in records:
        xb = r.params.get('XB')
        if isinstance(xb, list) and len(xb) == 6:
            xmin, xmax, ymin, ymax, zmin, zmax = xb
            if xmin > xmax or ymin > ymax or zmin > zmax:
                findings.append(Finding(ERROR,
                    f"&{r.name} XB has reversed bounds: ({xb}).",
                    hint="XB must be in the order x_min, x_max, y_min, y_max, z_min, z_max.",
                    line=r.line))


@rule('burn-away-with-surf-id6')
def _burn_away_surf_id6(records, findings):
    """
    BURN_AWAY=.TRUE. cannot be applied to a single face of a &OBST via
    SURF_ID6 — FDS rejects this with ERROR(101)/(607).  Move the cladding to
    its own thin OBST or remove BURN_AWAY.
    """
    surf_with_burn = {
        r.params.get('ID', ''): r
        for r in records if r.name == 'SURF' and r.params.get('BURN_AWAY') is True
    }
    if not surf_with_burn:
        return
    for obst in [r for r in records if r.name == 'OBST']:
        for s in as_list(obst.params.get('SURF_ID6')):
            if s in surf_with_burn:
                findings.append(Finding(ERROR,
                    f"&OBST at line {obst.line} uses SURF '{s}' (BURN_AWAY=.TRUE.) via SURF_ID6 — rejected by FDS.",
                    hint=f"Either remove BURN_AWAY from SURF '{s}' or move the combustible material to its own OBST.",
                    line=obst.line))


@rule('burn-away-needs-bulk-density')
def _burn_away_bulk_density(records, findings):
    """
    BURN_AWAY=.TRUE. on a SURF requires BULK_DENSITY (or a MATL with DENSITY)
    so FDS can track when the OBST has fully consumed (ERROR(607)).
    """
    matls = {r.params.get('ID', ''): r for r in records if r.name == 'MATL'}
    for surf in [r for r in records if r.name == 'SURF']:
        if surf.params.get('BURN_AWAY') is not True:
            continue
        if surf.params.get('BULK_DENSITY') is not None:
            continue
        # Resolve MATL_ID -> DENSITY
        matl_ids = as_list(surf.params.get('MATL_ID'))
        has_density = any(matls.get(mid, Record('', 0, '')).params.get('DENSITY') for mid in matl_ids)
        if not has_density:
            findings.append(Finding(ERROR,
                f"&SURF '{surf.params.get('ID')}' has BURN_AWAY=.TRUE. but no BULK_DENSITY and no MATL with DENSITY.",
                hint="Add BULK_DENSITY=<kg/m3> to the SURF, or reference a MATL that defines DENSITY.",
                line=surf.line))


# Quantity name conventions for &DEVC.  This is a non-exhaustive whitelist of
# the most common gas-phase, wall, and integrated quantities.  An unknown
# value raises a WARNING (not an error — the user might be using an FDS
# extension or a quantity we haven't catalogued).
_KNOWN_DEVC_QUANTITIES = {
    # Gas-phase
    'TEMPERATURE', 'VELOCITY', 'U-VELOCITY', 'V-VELOCITY', 'W-VELOCITY',
    'PRESSURE', 'DENSITY', 'HRRPUV', 'MIXTURE FRACTION', 'VISIBILITY',
    'EXTINCTION COEFFICIENT', 'OPTICAL DENSITY', 'MASS FRACTION',
    'VOLUME FRACTION', 'MOLE FRACTION', 'TIME', 'LAYER HEIGHT',
    'UPPER TEMPERATURE', 'LOWER TEMPERATURE', 'THERMOCOUPLE',
    'SPRINKLER LINK TEMPERATURE', 'CONTROL FUNCTION', 'CONTROL VALUE',
    # Wall / boundary (require IOR or surface)
    'WALL TEMPERATURE', 'INSIDE WALL TEMPERATURE', 'GAUGE HEAT FLUX',
    'NET HEAT FLUX', 'CONVECTIVE HEAT FLUX', 'RADIATIVE HEAT FLUX',
    'INCIDENT HEAT FLUX', 'BURNING RATE', 'WALL THICKNESS', 'BACK WALL TEMPERATURE',
    'ADIABATIC SURFACE TEMPERATURE', 'HEAT TRANSFER COEFFICIENT',
    # Integrated
    'HRR', 'MASS FLOW', 'VOLUME FLOW', 'HEAT FLOW',
    # Wildfire / vegetation
    'FIRE DEPTH', 'HRRPUA', 'PARTICLE TEMPERATURE', 'PARTICLE MASS',
    'INTEGRATED INTENSITY',
}

# Known-bad DEVC quantity strings (FDS rejects these with ERROR 1042)
_REJECTED_DEVC_QUANTITIES = {
    'HEAT RELEASE RATE': "Use QUANTITY='HRR' with XB for integrated HRR over a volume; total HRR is automatically written to <chid>_hrr.csv.",
    'SOOT MASS FRACTION':   "Not available when soot is implicit (SOOT_YIELD in &REAC). Use QUANTITY='VISIBILITY' instead.",
    'SOOT VOLUME FRACTION': "Not available when soot is implicit (SOOT_YIELD in &REAC). Use QUANTITY='VISIBILITY' instead.",
}

# Whitelist of valid &SLCF QUANTITY values.  Unknowns raise a WARNING.
_KNOWN_SLCF_QUANTITIES = {
    'TEMPERATURE', 'VELOCITY', 'U-VELOCITY', 'V-VELOCITY', 'W-VELOCITY',
    'PRESSURE', 'DENSITY', 'HRRPUV', 'MIXTURE FRACTION', 'VISIBILITY',
    'EXTINCTION COEFFICIENT', 'OPTICAL DENSITY', 'VOLUME FRACTION',
    'MASS FRACTION', 'MOLE FRACTION', 'DIVERGENCE', 'VORTICITY',
    'KINETIC ENERGY', 'TURBULENT KINETIC ENERGY', 'TURBULENT VISCOSITY',
    'RADIATIVE HEAT FLUX GAS', 'ABSORPTION COEFFICIENT', 'INTEGRATED INTENSITY',
}

# Known-bad SLCF quantity strings (FDS rejects these with ERROR 1042)
_REJECTED_SLCF_QUANTITIES = {
    'SOOT MASS FRACTION':   "Not available when soot is implicit (SOOT_YIELD in &REAC). Use QUANTITY='VISIBILITY' instead.",
    'SOOT VOLUME FRACTION': "Not available when soot is implicit (SOOT_YIELD in &REAC). Use QUANTITY='VISIBILITY' instead.",
    'HEAT RELEASE RATE':    "Not a valid SLCF quantity. Use QUANTITY='HRRPUV' for volumetric heat release rate slices.",
}

# Quantities (SLCF or DEVC) that reference a species via SPEC_ID
_SPEC_ID_QUANTITIES = {'VOLUME FRACTION', 'MASS FRACTION', 'MOLE FRACTION'}

# Wall-surface DEVC quantities — require IOR when measuring at a point (XYZ)
_WALL_DEVC_QUANTITIES = {
    'WALL TEMPERATURE', 'INSIDE WALL TEMPERATURE', 'BACK WALL TEMPERATURE',
    'GAUGE HEAT FLUX', 'NET HEAT FLUX', 'CONVECTIVE HEAT FLUX',
    'RADIATIVE HEAT FLUX', 'INCIDENT HEAT FLUX', 'BURNING RATE',
    'WALL THICKNESS', 'ADIABATIC SURFACE TEMPERATURE', 'HEAT TRANSFER COEFFICIENT',
}

# DEVC quantities that integrate over a volume — require XB, not XYZ
_ZONE_DEVC_QUANTITIES = {'LAYER HEIGHT', 'UPPER TEMPERATURE', 'LOWER TEMPERATURE', 'HRR'}

# Species implicitly present in every FDS simple-chemistry simulation (no &SPEC needed)
_BUILTIN_SPECIES = {
    'AIR', 'NITROGEN', 'OXYGEN', 'CARBON DIOXIDE', 'CARBON MONOXIDE',
    'WATER VAPOR', 'HYDROGEN', 'METHANE', 'ETHYLENE', 'PROPANE',
    'BUTANE', 'HEPTANE', 'ETHANOL', 'METHANOL', 'TOLUENE',
    'N2', 'O2', 'CO2', 'CO', 'H2O', 'H2',
    'PRODUCTS', 'FUEL',
}


def _defined_species(records) -> set:
    """Return upper-cased IDs of all species resolvable without explicit &SPEC."""
    ids = set(_BUILTIN_SPECIES)
    for r in records:
        if r.name == 'SPEC':
            sid = r.params.get('ID')
            if sid:
                ids.add(sid.upper())
        elif r.name == 'REAC':
            fuel = r.params.get('FUEL')
            if fuel:
                ids.add(fuel.upper())
    return ids


def _has_implicit_soot(records) -> bool:
    """True when soot is tracked implicitly (SOOT_YIELD in &REAC, no explicit &SPEC 'SOOT')."""
    has_yield = any(
        r.name == 'REAC' and r.params.get('SOOT_YIELD') is not None
        for r in records
    )
    has_spec = any(
        r.name == 'SPEC' and (r.params.get('ID') or '').upper() == 'SOOT'
        for r in records
    )
    return has_yield and not has_spec


@rule('devc-quantity')
def _devc_quantity(records, findings):
    """Catch invalid or rejected QUANTITY values on &DEVC."""
    for d in [r for r in records if r.name == 'DEVC']:
        q = d.params.get('QUANTITY')
        if not q:
            continue
        q_up = q.upper() if isinstance(q, str) else q
        if q_up in _REJECTED_DEVC_QUANTITIES:
            findings.append(Finding(ERROR,
                f"&DEVC '{d.params.get('ID', '?')}' uses QUANTITY='{q}' which FDS6 rejects (ERROR 1042).",
                hint=_REJECTED_DEVC_QUANTITIES[q_up],
                line=d.line))
        elif q_up not in _KNOWN_DEVC_QUANTITIES:
            findings.append(Finding(WARNING,
                f"&DEVC '{d.params.get('ID', '?')}' uses QUANTITY='{q}' which is not in the linter's known list.",
                hint="Verify spelling/case in the FDS User Guide; remove this warning by adding it to _KNOWN_DEVC_QUANTITIES if valid.",
                line=d.line))


@rule('spec-id-undefined')
def _spec_id_undefined(records, findings):
    """
    Catch SLCF and DEVC records that reference a SPEC_ID for species-dependent
    quantities (VOLUME FRACTION, MASS FRACTION, MOLE FRACTION) where the species
    is not defined.  Special case: SPEC_ID='SOOT' with implicit soot crashes FDS
    at startup with ERROR 1042.
    """
    known = _defined_species(records)
    implicit_soot = _has_implicit_soot(records)

    for r in records:
        if r.name not in ('SLCF', 'DEVC'):
            continue
        q = r.params.get('QUANTITY')
        if not isinstance(q, str) or q.upper() not in _SPEC_ID_QUANTITIES:
            continue
        spec_id = r.params.get('SPEC_ID')
        if not isinstance(spec_id, str):
            continue
        spec_up = spec_id.upper()

        if spec_up == 'SOOT' and implicit_soot:
            findings.append(Finding(ERROR,
                f"&{r.name} uses QUANTITY='{q}', SPEC_ID='SOOT' but soot is implicit "
                f"(SOOT_YIELD in &REAC, no explicit &SPEC 'SOOT'). FDS will abort with ERROR 1042.",
                hint="Use QUANTITY='VISIBILITY' (always available with implicit soot), or define "
                     "&SPEC ID='SOOT' explicitly if you need the raw soot fraction.",
                line=r.line))
        elif spec_up not in known:
            findings.append(Finding(WARNING,
                f"&{r.name} references SPEC_ID='{spec_id}' which is not defined via &SPEC.",
                hint=f"Define &SPEC ID='{spec_id}', FORMULA='...' / or fix the SPEC_ID spelling.",
                line=r.line))


@rule('devc-wall-ior')
def _devc_wall_ior(records, findings):
    """
    Wall-surface DEVC quantities (WALL TEMPERATURE, BURNING RATE, etc.) measured
    at a single point (XYZ) without IOR have no surface normal to resolve — FDS
    picks an arbitrary face, which is almost always wrong.
    """
    for d in [r for r in records if r.name == 'DEVC']:
        q = d.params.get('QUANTITY')
        if not isinstance(q, str) or q.upper() not in _WALL_DEVC_QUANTITIES:
            continue
        has_ior = d.params.get('IOR') is not None
        has_xyz = isinstance(d.params.get('XYZ'), list)
        has_xb  = isinstance(d.params.get('XB'),  list)
        if has_xyz and not has_ior and not has_xb:
            findings.append(Finding(WARNING,
                f"&DEVC '{d.params.get('ID', '?')}' measures '{q}' at a point (XYZ) without IOR.",
                hint="Add IOR=±1/±2/±3 to specify which surface face to measure "
                     "(e.g. IOR=1 for the +X face). Without it FDS chooses arbitrarily.",
                line=d.line))


@rule('devc-zone-needs-xb')
def _devc_zone_needs_xb(records, findings):
    """
    Zone-integrated DEVC quantities (LAYER HEIGHT, UPPER TEMPERATURE, LOWER
    TEMPERATURE, HRR) must be given an XB volume — using XYZ gives zero or
    nonsense because there is no extent to integrate over.
    """
    for d in [r for r in records if r.name == 'DEVC']:
        q = d.params.get('QUANTITY')
        if not isinstance(q, str) or q.upper() not in _ZONE_DEVC_QUANTITIES:
            continue
        has_xb  = isinstance(d.params.get('XB'),  list) and len(d.params['XB']) == 6
        has_xyz = isinstance(d.params.get('XYZ'), list)
        if has_xyz and not has_xb:
            findings.append(Finding(ERROR,
                f"&DEVC '{d.params.get('ID', '?')}' uses QUANTITY='{q}' with XYZ instead of XB.",
                hint=f"'{q}' integrates over a volume — replace XYZ with XB=x0,x1,y0,y1,z0,z1 "
                     f"defining the zone (e.g. the whole room).",
                line=d.line))


@rule('slcf-quantity')
def _slcf_quantity(records, findings):
    """Catch SLCF quantities that FDS6 rejects (ERROR 1042) or are unrecognised."""
    for s in [r for r in records if r.name == 'SLCF']:
        q = s.params.get('QUANTITY')
        if not q:
            continue
        q_up = q.upper() if isinstance(q, str) else q
        if q_up in _REJECTED_SLCF_QUANTITIES:
            findings.append(Finding(ERROR,
                f"&SLCF uses QUANTITY='{q}' which FDS6 rejects (ERROR 1042).",
                hint=_REJECTED_SLCF_QUANTITIES[q_up],
                line=s.line))
        elif q_up not in _KNOWN_SLCF_QUANTITIES:
            findings.append(Finding(WARNING,
                f"&SLCF uses QUANTITY='{q}' which is not in the linter's known list.",
                hint="Verify spelling/case in the FDS User Guide; add it to _KNOWN_SLCF_QUANTITIES if valid.",
                line=s.line))


@rule('devc-in-hole')
def _devc_in_hole(records, findings):
    """A &DEVC with XYZ inside a &HOLE region usually loses its target surface."""
    holes = []
    for h in [r for r in records if r.name == 'HOLE']:
        xb = h.params.get('XB')
        if isinstance(xb, list) and len(xb) == 6:
            holes.append((h, xb))
    if not holes:
        return
    for d in [r for r in records if r.name == 'DEVC']:
        xyz = d.params.get('XYZ')
        ior = d.params.get('IOR')
        if not isinstance(xyz, list) or len(xyz) != 3:
            continue
        x, y, z = xyz
        for h, xb in holes:
            x0, x1, y0, y1, z0, z1 = xb
            if x0 <= x <= x1 and y0 <= y <= y1 and z0 <= z <= z1:
                if ior is not None:
                    findings.append(Finding(ERROR,
                        f"&DEVC '{d.params.get('ID', '?')}' XYZ=({x},{y},{z}) is inside &HOLE at line {h.line} and uses IOR={ior}.",
                        hint="The wall the device is supposed to measure has been carved away. Move the device to a position where the surface still exists.",
                        line=d.line))
                else:
                    findings.append(Finding(WARNING,
                        f"&DEVC '{d.params.get('ID', '?')}' XYZ=({x},{y},{z}) is inside &HOLE at line {h.line}.",
                        hint="Verify this is intentional; gas-phase quantities can be measured here, but solid-surface quantities cannot.",
                        line=d.line))


@rule('devc-outside-domain')
def _devc_outside_domain(records, findings):
    """Flag DEVC XYZ that fall outside the union of all &MESH domains."""
    meshes = []
    for m in [r for r in records if r.name == 'MESH']:
        xb = m.params.get('XB')
        if isinstance(xb, list) and len(xb) == 6:
            meshes.append(xb)
    if not meshes:
        return
    def in_any_mesh(p):
        x, y, z = p
        for x0, x1, y0, y1, z0, z1 in meshes:
            if x0 - 1e-6 <= x <= x1 + 1e-6 and y0 - 1e-6 <= y <= y1 + 1e-6 and z0 - 1e-6 <= z <= z1 + 1e-6:
                return True
        return False
    for d in [r for r in records if r.name == 'DEVC']:
        xyz = d.params.get('XYZ')
        if isinstance(xyz, list) and len(xyz) == 3 and not in_any_mesh(xyz):
            findings.append(Finding(WARNING,
                f"&DEVC '{d.params.get('ID', '?')}' XYZ={tuple(xyz)} is outside every &MESH.",
                hint="The device will be silently dropped or relocated. Move it inside a mesh.",
                line=d.line))


@rule('vent-undefined-surf')
def _vent_undefined_surf(records, findings):
    """Reference to a SURF_ID that isn't defined anywhere."""
    builtin = {'OPEN', 'MIRROR', 'INERT', 'PERIODIC', 'INTERPOLATED', 'HVAC'}
    defined = {r.params.get('ID') for r in records if r.name == 'SURF'} | builtin
    for r in records:
        if r.name not in ('VENT', 'OBST'):
            continue
        ids = []
        ids += as_list(r.params.get('SURF_ID'))
        ids += as_list(r.params.get('SURF_IDS'))
        ids += as_list(r.params.get('SURF_ID6'))
        for s in ids:
            if s and s not in defined:
                findings.append(Finding(ERROR,
                    f"&{r.name} at line {r.line} references SURF_ID '{s}' which is not defined.",
                    hint=f"Define &SURF ID='{s}', ... / earlier in the file, or fix the reference.",
                    line=r.line))


@rule('visibility-needs-spec-id-soot')
def _visibility_spec_id(records, findings):
    """&SLCF/&DEVC with QUANTITY='VISIBILITY' must include SPEC_ID='SOOT'.

    FDS 6.8+ enforces this with ERROR(1004): "SPEC_ID SOOT is not explicitly
    specified for QUANTITY VISIBILITY". Older FDS versions defaulted SPEC_ID
    to SOOT automatically, but newer versions require it on the namelist.

    Additionally, without a &REAC carrying SOOT_YIELD (or an explicit &SPEC
    ID='SOOT'), the SOOT species doesn't exist at all and VISIBILITY can't
    be computed.
    """
    has_reac_soot = any(
        r.name == 'REAC' and r.params.get('SOOT_YIELD') is not None
        for r in records
    )
    has_spec_soot = any(
        r.name == 'SPEC' and (r.params.get('ID') or '').upper() == 'SOOT'
        for r in records
    )
    soot_available = has_reac_soot or has_spec_soot

    for r in records:
        if r.name not in ('SLCF', 'DEVC'):
            continue
        q = r.params.get('QUANTITY')
        if not isinstance(q, str) or q.upper() != 'VISIBILITY':
            continue
        if not soot_available:
            findings.append(Finding(ERROR,
                f"&{r.name} QUANTITY='VISIBILITY' but no SOOT species in the scene.",
                hint=("VISIBILITY computes light extinction from soot. Add a &REAC with "
                      "SOOT_YIELD=… (auto-creates SOOT), or define &SPEC ID='SOOT' explicitly, "
                      "or remove this slice."),
                line=r.line))
            continue
        spec_id = r.params.get('SPEC_ID')
        if not isinstance(spec_id, str) or spec_id.upper() != 'SOOT':
            findings.append(Finding(ERROR,
                f"&{r.name} QUANTITY='VISIBILITY' is missing SPEC_ID='SOOT'.",
                hint=("FDS 6.8+ rejects this with ERROR(1004). Append SPEC_ID='SOOT' "
                      "to the namelist."),
                line=r.line))


@rule('misc-surf-default-invalid')
def _misc_surf_default(records, findings):
    """&MISC SURF_DEFAULT must reference a user-defined SURF, not a built-in.

    FDS6 rejects SURF_DEFAULT pointing at built-in surfaces (INERT, OPEN,
    MIRROR, PERIODIC, INTERPOLATED, HVAC) with ERROR(101) "Problem with MISC
    line." INERT is the implicit default already; the cleanest fix is to drop
    SURF_DEFAULT entirely. If you do want a custom default, point it at a
    user-defined &SURF (e.g. SURF_DEFAULT='CONCRETE').
    """
    builtin = {'INERT', 'OPEN', 'MIRROR', 'PERIODIC', 'INTERPOLATED', 'HVAC'}
    defined = {r.params.get('ID') for r in records if r.name == 'SURF'}
    for m in [r for r in records if r.name == 'MISC']:
        sd = m.params.get('SURF_DEFAULT')
        if not isinstance(sd, str) or not sd:
            continue
        if sd.upper() in builtin:
            findings.append(Finding(ERROR,
                f"&MISC SURF_DEFAULT='{sd}' references a built-in surface — "
                "FDS6 rejects this with ERROR(101) 'Problem with MISC line.'",
                hint=("Drop the SURF_DEFAULT keyword (INERT is already the implicit default), "
                      "or point it at a user-defined &SURF like SURF_DEFAULT='CONCRETE'."),
                line=m.line))
        elif sd not in defined:
            findings.append(Finding(ERROR,
                f"&MISC SURF_DEFAULT='{sd}' references a SURF that isn't defined.",
                hint=f"Add &SURF ID='{sd}', ... / earlier, or remove SURF_DEFAULT.",
                line=m.line))


@rule('matl-id-undefined')
def _matl_undefined(records, findings):
    """SURF references a MATL_ID that doesn't exist."""
    defined = {r.params.get('ID') for r in records if r.name == 'MATL'}
    for r in [x for x in records if x.name == 'SURF']:
        for m in as_list(r.params.get('MATL_ID')):
            if m and m not in defined:
                findings.append(Finding(ERROR,
                    f"&SURF '{r.params.get('ID')}' references MATL_ID '{m}' which is not defined.",
                    hint=f"Define &MATL ID='{m}', ... / earlier in the file.",
                    line=r.line))


@rule('geom-faces-stride')
def _geom_faces_stride(records, findings):
    """GEOM FACES must have 4 integers per face: (v1, v2, v3, surf_id_idx).

    Per FDS User Guide Sec. 7.3.2, every face record needs the 4th integer
    (the boundary-condition / SURF_ID index, 0..N). Writing stride 3 (just
    v1,v2,v3) makes FDS read pairs of faces with shifted offsets and
    eventually fail with ERROR(701) 'local SURF_ID index for FACE n out of
    bounds'. The visualization/ viewer also renders garbled triangles for
    such files because it falls back to a stride-4 heuristic on ambiguous
    inputs.
    """
    for r in records:
        if r.name != 'GEOM':
            continue
        faces = as_list(r.params.get('FACES'))
        if not faces:
            continue
        # FACES values come through as floats in _coerce; cast to int count.
        n = len(faces)
        if n < 4:
            continue
        if n % 4 != 0:
            # Strongest signal: not stride-4 at all.
            findings.append(Finding(ERROR,
                f"&GEOM '{r.params.get('ID')}' has FACES with {n} integers, "
                "which is not a multiple of 4.",
                hint=("Each FACE record is (v1, v2, v3, surf_id_idx) -> 4 integers. "
                      "Append the SURF_ID index (1 if you have a single SURF_ID) "
                      "to every face. See FDS User Guide Sec. 7.3.2."),
                line=r.line))
        elif n % 3 == 0 and n % 4 == 0:
            # Ambiguous (length is a multiple of 12). Could be stride 3 (invalid)
            # written by hand, or stride 4 that happens to have 3k triangles.
            # Check: if the 4th value of each face triplet (under stride-3
            # interpretation) is consistently 1..max_vert, that's a smell.
            verts = as_list(r.params.get('VERTS'))
            max_vert = max(1, len(verts) // 3)
            # SID values (under stride-4) at positions 3, 7, 11...
            sids = [int(faces[i]) for i in range(3, n, 4)]
            # If every SID is 0 or a small positive int <= max_vert, it could
            # be either. We only flag when SIDs LOOK like vertex indices
            # AND every face's first three values are valid vertex indices --
            # which is the precise stride-3-by-mistake pattern.
            looks_like_stride3 = (
                all(0 < s <= max_vert for s in sids) and
                all(0 < int(faces[i]) <= max_vert for i in range(n) if i % 4 != 3)
            )
            if looks_like_stride3:
                findings.append(Finding(WARNING,
                    f"&GEOM '{r.params.get('ID')}' FACES length {n} divides both "
                    "by 3 and by 4 -- stride may be ambiguous.",
                    hint=("FDS requires 4 ints per face (v1,v2,v3,surf_id_idx). "
                          "If you wrote stride-3 FACES by mistake, FDS will read "
                          "them shifted and abort with ERROR(701) on FACE 2. "
                          "Append a SURF_ID index (typically 1) to every face."),
                    line=r.line))


@rule('vel-sign-convention')
def _vel_sign(records, findings):
    """Flag SURF VEL/VOLUME_FLOW sign that contradicts the SURF's name.

    FDS convention (User Guide Sec. 17.1):
       VEL > 0  -> flow drawn OUT of the domain (exhaust / extraction)
       VEL < 0  -> flow blown INTO the domain (supply / intake)
       Same sign rule applies to VOLUME_FLOW and MASS_FLUX.

    Common bug: a SURF named 'EXTRACTION' or 'EXHAUST' set with negative VEL
    blows air into the domain instead of extracting it. The plume gets pushed
    back down and Smokeview shows "smoke that won't get captured by the hood".
    """
    EXHAUST_TOKENS = ('EXHAUST', 'EXTRACT', 'OUTLET', 'OUTFLOW',
                      'EXIT', 'EXPEL', 'SUCTION', 'DRAW')
    SUPPLY_TOKENS  = ('SUPPLY', 'INTAKE', 'INLET', 'INFLOW',
                      'BLOW', 'INJECT', 'FAN_IN')

    surfs = [r for r in records if r.name == 'SURF']
    for s in surfs:
        sid = (s.params.get('ID') or '').upper()
        if not sid:
            continue
        # Numeric flow parameter on this SURF (only one is typically set).
        flow_val = None
        flow_key = None
        for key in ('VEL', 'VEL_T', 'VOLUME_FLOW', 'MASS_FLUX',
                    'MASS_FLOW_RATE'):
            v = s.params.get(key)
            if isinstance(v, (int, float)) and v != 0:
                flow_val, flow_key = float(v), key
                break
        if flow_val is None:
            continue

        is_exhaust = any(tok in sid for tok in EXHAUST_TOKENS)
        is_supply  = any(tok in sid for tok in SUPPLY_TOKENS)

        if is_exhaust and flow_val < 0:
            findings.append(Finding(WARNING,
                f"&SURF '{s.params.get('ID')}' has {flow_key}={flow_val:g} (negative). "
                "Name implies EXHAUST, but a negative value supplies flow INTO the domain.",
                hint=("FDS convention: positive {0} draws flow OUT of the domain, "
                      "negative {0} pushes flow IN. Flip the sign to {1:g} for "
                      "extraction.").format(flow_key, -flow_val),
                line=s.line))
        elif is_supply and flow_val > 0:
            findings.append(Finding(WARNING,
                f"&SURF '{s.params.get('ID')}' has {flow_key}={flow_val:g} (positive). "
                "Name implies SUPPLY, but a positive value draws flow OUT of the domain.",
                hint=("FDS convention: negative {0} pushes flow INTO the domain. "
                      "Flip the sign to {1:g} for a supply vent.").format(
                      flow_key, -flow_val),
                line=s.line))


@rule('mesh-balance')
def _mesh_balance(records, findings):
    """Style note: heavily imbalanced mesh decomposition slows MPI runs."""
    meshes = [r for r in records if r.name == 'MESH']
    if len(meshes) < 2:
        return
    cells = []
    for m in meshes:
        ijk = m.params.get('IJK')
        if isinstance(ijk, list) and len(ijk) == 3:
            cells.append(int(ijk[0] * ijk[1] * ijk[2]))
    if not cells:
        return
    if max(cells) > 4 * min(cells):
        findings.append(Finding(INFO,
            f"Mesh cell counts are imbalanced (max {max(cells)} vs min {min(cells)}).",
            hint="With one MPI rank per mesh, the slowest mesh dominates wall time. Aim for cell counts within 2x of each other.",
            line=meshes[0].line))


@rule('many-wall-devcs')
def _many_wall_devcs(records, findings):
    """Suggest &BNDF when many wall-quantity DEVCs exist."""
    wall_q = {'WALL TEMPERATURE', 'GAUGE HEAT FLUX', 'NET HEAT FLUX',
              'CONVECTIVE HEAT FLUX', 'RADIATIVE HEAT FLUX', 'BURNING RATE'}
    counts: Dict[str, int] = {}
    for d in [r for r in records if r.name == 'DEVC']:
        q = d.params.get('QUANTITY')
        if isinstance(q, str) and q.upper() in wall_q:
            counts[q.upper()] = counts.get(q.upper(), 0) + 1
    bndf_q = {(r.params.get('QUANTITY') or '').upper() for r in records if r.name == 'BNDF'}
    for q, n in counts.items():
        if n >= 3 and q not in bndf_q:
            findings.append(Finding(INFO,
                f"{n} &DEVCs measure {q} as point devices.",
                hint=f"Consider replacing with &BNDF QUANTITY='{q}' / for full surface coverage.",
                line=0))


# ─────────────────────────────────────────────────────────────────────────────
# Reporter
# ─────────────────────────────────────────────────────────────────────────────

# ANSI colour codes (Windows 10+ supports these in modern terminals)
COLOURS = {
    ERROR:   '\033[31m',  # red
    WARNING: '\033[33m',  # yellow
    INFO:    '\033[36m',  # cyan
    'reset': '\033[0m',
    'dim':   '\033[2m',
    'bold':  '\033[1m',
}

def _supports_colour() -> bool:
    if os.environ.get('NO_COLOR'):
        return False
    if not sys.stdout.isatty():
        return False
    return True


def report(path: str, findings: List[Finding]) -> int:
    # Best-effort UTF-8 stdout on Windows; fall back to ASCII otherwise.
    try:
        sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[attr-defined]
    except Exception:
        pass
    use_colour = _supports_colour()
    def c(code, s):
        return f"{COLOURS[code]}{s}{COLOURS['reset']}" if use_colour else s

    counts = {ERROR: 0, WARNING: 0, INFO: 0}
    findings_sorted = sorted(findings, key=lambda f: (f.line, f.severity))

    print(c('bold', f"validate_fds: {path}"))
    if not findings_sorted:
        print(c('bold', "  No issues found."))
        return 0

    for f in findings_sorted:
        counts[f.severity] += 1
        sev = c(f.severity, f.severity.ljust(7))
        loc = c('dim', f"line {f.line}".rjust(8) if f.line else "        ")
        print(f"  {sev} {loc}  {f.message}")
        if f.hint:
            print(f"  {' ' * 9}          {c('dim', '-> ' + f.hint)}")
        if f.rule:
            print(f"  {' ' * 9}          {c('dim', f'[rule: {f.rule}]')}")

    summary = "  " + ", ".join(
        f"{counts[s]} {s.lower()}{'s' if counts[s] != 1 else ''}"
        for s in (ERROR, WARNING, INFO) if counts[s]
    )
    print(c('bold', summary))
    return 1 if counts[ERROR] else 0


# ─────────────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────────────

def validate_one(path: str) -> int:
    if not os.path.exists(path):
        print(f"validate_fds: file not found: {path}", file=sys.stderr)
        return 2
    with open(path, encoding='utf-8', errors='replace') as f:
        text = f.read()
    records = parse_records(text)
    # Follow &CATF OTHER_FILES references so included files contribute MATL/SURF/SPEC
    base_dir = os.path.dirname(os.path.abspath(path))
    for r in [x for x in records if x.name == 'CATF']:
        other = r.params.get('OTHER_FILES')
        for fname in ([other] if isinstance(other, str) else (other or [])):
            inc_path = os.path.join(base_dir, fname)
            if os.path.exists(inc_path):
                with open(inc_path, encoding='utf-8', errors='replace') as f:
                    records += parse_records(f.read())
    findings: List[Finding] = []
    for name, fn in RULES:
        try:
            before = len(findings)
            fn(records, findings)
            for fd in findings[before:]:
                if not fd.rule:
                    fd.rule = name
        except Exception as e:
            findings.append(Finding(WARNING,
                f"internal: rule '{name}' raised {type(e).__name__}: {e}",
                rule=name))
    return report(path, findings)


def find_default() -> Optional[str]:
    """Return the path of the most recently modified .fds under simulations/."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pattern = os.path.join(root, 'simulations', '**', '*.fds')
    files = glob.glob(pattern, recursive=True)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def main(argv):
    if '--all' in argv:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pattern = os.path.join(root, 'simulations', '**', '*.fds')
        files = sorted(glob.glob(pattern, recursive=True))
        if not files:
            print("validate_fds: no .fds files under simulations/", file=sys.stderr)
            return 2
        rc = 0
        for f in files:
            rc |= validate_one(f)
            print()
        return rc

    if len(argv) < 2:
        target = find_default()
        if not target:
            print("Usage: python validate_fds.py <path-to-.fds>", file=sys.stderr)
            return 2
        print(f"(auto-detected: {target})")
        return validate_one(target)

    return validate_one(argv[1])


if __name__ == '__main__':
    sys.exit(main(sys.argv))
