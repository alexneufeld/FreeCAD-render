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

"""LuxCore renderer for FreeCAD"""

# Suggested links to renderer documentation:
# https://wiki.luxcorerender.org/LuxCore_SDL_Reference_Manual_v2.3

import os
import shlex
from tempfile import mkstemp
from subprocess import Popen
from textwrap import dedent
import configparser

import FreeCAD as App


# ===========================================================================
#                             Write functions
# ===========================================================================


def write_object(name, mesh, color, alpha):
    """Compute a string in the format of LuxCore, that represents a FreeCAD
    object
    """

    points = ["{0.x} {0.y} {0.z}".format(v) for v in mesh.Topology[0]]
    tris = ["{} {} {}".format(*t) for t in mesh.Topology[1]]

    snippet = """
    scene.materials.{n}.type = matte
    scene.materials.{n}.kd = {c[0]} {c[1]} {c[2]}
    scene.materials.{n}.transparency = {t}
    scene.objects.{n}.type = inlinedmesh
    scene.objects.{n}.vertices = {p}
    scene.objects.{n}.faces = {f}
    scene.objects.{n}.material = {n}
    scene.objects.{n}.transformation = 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1
    """
    return dedent(snippet).format(n=name,
                                  c=color,
                                  t=alpha if alpha < 1.0 else 1.0,
                                  p=" ".join(points),
                                  f=" ".join(tris))


def write_camera(name, pos, updir, target):
    """Compute a string in the format of LuxCore, that represents a camera"""
    snippet = """
    # Generated by FreeCAD (http://www.freecadweb.org/)
    # Camera '{n}'
    scene.camera.lookat.orig = {o.x} {o.y} {o.z}
    scene.camera.lookat.target = {t.x} {t.y} {t.z}
    scene.camera.up = {u.x} {u.y} {u.z}
    """
    return dedent(snippet).format(n=name, o=pos.Base, t=target, u=updir)


def write_pointlight(name, pos, color, power):
    """Compute a string in the format of LuxCore, that represents a
    PointLight object
    """
    # From LuxCore doc:
    # power is in watts
    # efficency (sic) is in lumens/watt
    efficency = 15  # incandescent light bulb ratio (average)
    gain = 10  # Guesstimated! (don't hesitate to propose more sensible values)

    snippet = """
    scene.lights.{n}.type = point
    scene.lights.{n}.position = {o.x} {o.y} {o.z}
    scene.lights.{n}.color = {c[0]} {c[1]} {c[2]}
    scene.lights.{n}.power = {p}
    scene.lights.{n}.gain = {g} {g} {g}
    scene.lights.{n}.efficency = {e}
    """
    return dedent(snippet).format(n=name,
                                  o=pos,
                                  c=color,
                                  p=power,
                                  g=gain,
                                  e=efficency)


def write_arealight(name, pos, size_u, size_v, color, power):
    """Compute a string in the format of LuxCore, that represents an
    Area Light object
    """
    efficency = 15
    gain = 10  # Guesstimated!

    # We have to transpose 'pos' to make it fit for Lux
    # As 'transpose' method is in-place, we first make a copy
    placement = App.Matrix(pos.toMatrix())
    placement.transpose()
    trans = ' '.join([str(a) for a in placement.A])

    snippet = """
    scene.materials.{n}.type = matte
    scene.materials.{n}.emission = {c[0]} {c[1]} {c[2]}
    scene.materials.{n}.emission.gain = {g} {g} {g}
    scene.materials.{n}.emission.power = {p}
    scene.materials.{n}.emission.efficency = {e}
    scene.materials.{n}.transparency = 0
    scene.objects.{n}.type = inlinedmesh
    scene.objects.{n}.vertices = -{u} -{v} 0 {u} -{v} 0 {u} {v} 0 -{u} {v} 0
    scene.objects.{n}.faces = 0 1 2 0 2 3
    scene.objects.{n}.material = {n}
    scene.objects.{n}.transformation = {t}
    """

    return dedent(snippet).format(n=name,
                                  t=trans,
                                  c=color,
                                  p=power,
                                  e=efficency,
                                  g=gain,
                                  u=size_u / 2,
                                  v=size_v / 2,
                                  )


def write_sunskylight(name, direction, distance, turbidity):
    """Compute a string in the format of LuxCore, that represents an
    Sunsky Light object (Hosek-Wilkie)
    """
    snippet = """
    scene.lights.{n}_sun.type = sun
    scene.lights.{n}_sun.turbidity = {t}
    scene.lights.{n}_sun.dir = {d.x} {d.y} {d.z}
    scene.lights.{n}_sky.type = sky2
    scene.lights.{n}_sky.turbidity = {t}
    scene.lights.{n}_sky.dir = {d.x} {d.y} {d.z}
    """
    return dedent(snippet).format(n=name,
                                  t=turbidity,
                                  d=direction)


# ===========================================================================
#                              Render function
# ===========================================================================


def render(project, prefix, external, output, width, height):
    """Run LuxCore

    Params:
    - project:  the project to render
    - prefix:   a prefix string for call (will be inserted before path to Lux)
    - external: a boolean indicating whether to call UI (true) or console
                (false) version of Lux
    - width:    rendered image width, in pixels
    - height:   rendered image height, in pixels

    Return: void
    """
    def export_section(section, prefix, suffix):
        """Export a section to a temporary file"""
        f_handle, f_path = mkstemp(prefix=prefix, suffix='.' + suffix)
        os.close(f_handle)
        result = ["{} = {}".format(k, v) for k, v in dict(section).items()]
        with open(f_path, "w") as output:
            output.write("\n".join(result))
        return f_path

    # LuxCore requires 2 files:
    # - a configuration file, with rendering parameters (engine, sampler...)
    # - a scene file, with the scene objects (camera, lights, meshes...)
    # So we have to generate both...

    # Get page result content (ie what the calling module baked for us)
    pageresult = configparser.ConfigParser(strict=False)  # Allow dupl. keys
    pageresult.optionxform = lambda option: option  # Case sensitive keys
    pageresult.read(project.PageResult)

    # Export configuration
    config = pageresult["Configuration"]
    config["film.width"] = str(width)
    config["film.height"] = str(height)
    cfg_path = export_section(config, project.Name, "cfg")

    # Export scene
    scene = pageresult["Scene"]
    scn_path = export_section(scene, project.Name, "scn")

    # Get rendering parameters
    params = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Render")
    args = params.GetString("LuxCoreParameters", "")
    rpath = params.GetString(
        "LuxCorePath" if external else "LuxCoreConsolePath", "")
    if not rpath:
        msg = "Unable to locate renderer executable. Please set the correct "\
              "path in Edit -> Preferences -> Render\n"
        App.Console.PrintError(msg)
        return

    # Prepare command line and call LuxCore
    cmd = """{p}{r} {a} -o "{c}" -f "{s}"\n""".format(
        p=prefix, r=rpath, a=args, c=cfg_path, s=scn_path)
    App.Console.PrintMessage(cmd)
    try:
        Popen(shlex.split(cmd))
    except OSError as err:
        msg = "LuxCore call failed: '" + err.strerror + "'\n"
        App.Console.PrintError(msg)

    return


# TODO
# Deprecate luxrender (icons, warnings etc.)
