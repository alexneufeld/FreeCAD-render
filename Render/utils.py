# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2020 Howetuft <howetuft@gmail.com>                      *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

"""This module implements some helpers for Render workbench."""

import collections
import ast
import sys
import importlib
import csv
import itertools

try:
    from draftutils.translate import translate as _translate  # 0.19
except ImportError:
    from Draft import translate as _translate  # 0.18

import FreeCAD as App


translate = _translate


def debug(domain, object_name, msg):
    """Print debug message."""
    msg = f"[Render][{domain}] '{object_name}': {msg}\n"
    App.Console.PrintLog(msg)


def warn(domain, object_name, msg):
    """Print warning message."""
    msg = f"[Render][{domain}] '{object_name}': {msg}\n"
    App.Console.PrintWarning(msg)


def getproxyattr(obj, name, default):
    """Get attribute on object's proxy.

    Behaves like getattr, but on Proxy property, and with mandatory default...
    """
    try:
        res = getattr(obj.Proxy, name, default)
    except AttributeError:
        res = default
    return res


RGB = collections.namedtuple("RGB", "r g b")
RGBA = collections.namedtuple("RGBA", "r g b a")


def str2rgb(string):
    """Convert a ({r},{g},{b})-like string into RGB object."""
    float_tuple = map(float, ast.literal_eval(string))
    return RGB._make(float_tuple)


def parse_csv_str(string, delimiter=";"):
    """Parse a csv string, with ";" as default delimiter.

    Multiline strings are accepted (but maybe should be avoided).
    Returns: a list of strings (one for each field)
    """
    if not string:
        return []
    rows = csv.reader(string.splitlines(), delimiter=delimiter)
    return list(itertools.chain(*rows))


def clamp(value, maxval=1e10):
    """Clamp value between -maxval and +maxval."""
    res = value
    res = res if res <= maxval else maxval
    res = res if res >= -maxval else -maxval
    return res


def reload(module_name=None):
    """Reload Render modules."""
    mods = (
        (
            "Render.base",
            "Render.camera",
            "Render.commands",
            "Render.constants",
            "Render.lights",
            "Render.imageviewer",
            "Render.rdrmaterials",
            "Render.rdrhandler",
            "Render.rdrexecutor",
            "Render.renderables",
            "Render.taskpanels",
            "Render.utils",
            "Render.view",
            "Render.material",
            "Render.project",
            "Render.renderers.Appleseed",
            "Render.renderers.Cycles",
            "Render.renderers.Luxcore",
            "Render.renderers.Luxrender",
            "Render.renderers.Ospray",
            "Render.renderers.Pbrt",
            "Render.renderers.Povray",
            "Render.renderers.utils.sunlight",
            "Render",
        )
        if not module_name
        else (module_name,)
    )
    for mod in mods:
        try:
            module = sys.modules[mod]
        except KeyError:
            print(f"Skip '{mod}'")
        else:
            print(f"Reload '{mod}'")
            importlib.import_module(mod)
            importlib.reload(module)
