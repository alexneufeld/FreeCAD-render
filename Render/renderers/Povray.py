# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2017 Yorik van Havre <yorik@uncreated.net>              *
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

"""POV-Ray renderer plugin for FreeCAD Render workbench."""

# Suggested documentation link:
# https://www.povray.org/documentation/3.7.0/r3_0.html#r3_1

# NOTE:
# Please note that POV-Ray coordinate system appears to be different from
# FreeCAD's one (z and y permuted)
# See here: https://www.povray.org/documentation/3.7.0/t2_2.html#t2_2_1_1

import os
import re
from textwrap import dedent, indent

import FreeCAD as App

TEMPLATE_FILTER = "Povray templates (povray_*.pov)"

# ===========================================================================
#                             Write functions
# ===========================================================================


def write_mesh(name, mesh, material):
    """Compute a string in renderer SDL to represent a FreeCAD mesh."""
    # POV-Ray has a lot of reserved keywords, so we suffix name with a '_' to
    # avoid any collision
    name = name + "_"

    snippet = """
    // Generated by FreeCAD (http://www.freecadweb.org/)
    // Declares object '{name}'
    #declare {name} = mesh2 {{
        vertex_vectors {{
            {len_vertices},
            {vertices}
        }}
        face_indices {{
            {len_indices},
            {indices}
        }}
    }}  // {name}

    // Instance to render {name}
    object {{
        {name}
        {texture}
    }}  // {name}\n"""

    material = _write_material(name, material)
    vrts = [f"<{v.x},{v.z},{v.y}>" for v in mesh.Topology[0]]
    inds = [f"<{i[0]},{i[1]},{i[2]}>" for i in mesh.Topology[1]]

    return dedent(snippet).format(
        name=name,
        vertices="\n        ".join(vrts),
        len_vertices=len(vrts),
        indices="\n        ".join(inds),
        len_indices=len(inds),
        texture=material,
    )


def write_camera(name, pos, updir, target, fov):
    """Compute a string in renderer SDL to represent a camera."""
    # POV-Ray has a lot of reserved keywords, so we suffix name with a '_' to
    # avoid any collision
    name = name + "_"

    snippet = """
    // Generated by FreeCAD (http://www.freecadweb.org/)
    // Declares camera '{n}'
    #declare cam_location = <{p.x},{p.z},{p.y}>;
    #declare cam_look_at  = <{t.x},{t.z},{t.y}>;
    #declare cam_sky      = <{u.x},{u.z},{u.y}>;
    #declare cam_angle    = {f};
    camera {{
        perspective
        location  cam_location
        look_at   cam_look_at
        sky       cam_sky
        angle     cam_angle
        right     x*800/600
    }}\n"""

    return dedent(snippet).format(n=name, p=pos.Base, t=target, u=updir, f=fov)


def write_pointlight(name, pos, color, power):
    """Compute a string in renderer SDL to represent a point light."""
    # Note: power is of no use for POV-Ray, as light intensity is determined
    # by RGB (see POV-Ray documentation), therefore it is ignored.

    # POV-Ray has a lot of reserved keywords, so we suffix name with a '_' to
    # avoid any collision
    name = name + "_"

    snippet = """
    // Generated by FreeCAD (http://www.freecadweb.org/)
    // Declares point light {0}
    light_source {{
        <{1.x},{1.z},{1.y}>
        color rgb<{2[0]},{2[1]},{2[2]}>
    }}\n"""

    return dedent(snippet).format(name, pos, color)


def write_arealight(name, pos, size_u, size_v, color, power, transparent):
    """Compute a string in renderer SDL to represent an area light."""
    # POV-Ray has a lot of reserved keywords, so we suffix name with a '_' to
    # avoid any collision
    name = name + "_"

    # Dimensions of the point sources array
    # (area light is treated as point sources array, see POV-Ray documentation)
    size_1 = 20
    size_2 = 20

    # Prepare area light axes
    rot = pos.Rotation
    axis1 = rot.multVec(App.Vector(size_u, 0.0, 0.0))
    axis2 = rot.multVec(App.Vector(0.0, size_v, 0.0))

    # Prepare shape points for 'look_like'
    points = [
        (+axis1 + axis2) / 2,
        (+axis1 - axis2) / 2,
        (-axis1 - axis2) / 2,
        (-axis1 + axis2) / 2,
        (+axis1 + axis2) / 2,
    ]
    points = [f"<{p.x},{p.z},{p.y}>" for p in points]
    points = ", ".join(points)

    snippet = """
    // Generated by FreeCAD (http://www.freecadweb.org/)
    // Declares area light {n}
    #declare {n}_shape = polygon {{
        5, {p}
        texture {{ pigment{{ color rgb <{c[0]},{c[1]},{c[2]}>}}
                  finish {{ ambient 1 }}
                }} // end of texture
    }}
    light_source {{
        <{o.x},{o.z},{o.y}>
        color rgb <{c[0]},{c[1]},{c[2]}>
        area_light <{u.x},{u.z},{u.y}>, <{v.x},{v.z},{v.y}>, {a}, {b}
        adaptive 1
        looks_like {{ {n}_shape }}
        jitter
    }}\n"""
    return dedent(snippet).format(
        n=name,
        o=pos.Base,
        c=color,
        u=axis1,
        v=axis2,
        a=size_1,
        b=size_2,
        s=(size_u, size_v, 1),
        p=points,
    )


def write_sunskylight(name, direction, distance, turbidity, albedo):
    """Compute a string in renderer SDL to represent a sunsky light.

    Since POV-Ray does not provide a built-in Hosek-Wilkie feature, sunsky is
    modeled by a white parallel light, with a simple gradient skysphere.
    Please note it is a very approximate and limited model (works better for
    sun high in the sky...)
    """
    # POV-Ray has a lot of reserved keywords, so we suffix name with a '_' to
    # avoid any collision
    name = name + "_"

    location = direction.normalize()
    location.Length = distance

    snippet = """
    // Generated by FreeCAD (http://www.freecadweb.org/)
    // Declares sunsky light {n}
    // sky ------------------------------------
    sky_sphere{{
        pigment{{ gradient y
           color_map{{
               [0.0 color rgb<1,1,1> ]
               [0.8 color rgb<0.18,0.28,0.75>]
               [1.0 color rgb<0.75,0.75,0.75>]}}
               //[1.0 color rgb<0.15,0.28,0.75>]}}
               scale 2
               translate -1
        }} // end pigment
    }} // end sky_sphere
    // sun -----------------------------------
    global_settings {{ ambient_light rgb<1, 1, 1> }}
    light_source {{
        <{o.x},{o.z},{o.y}>
        color rgb <1,1,1>
        parallel
        point_at <0,0,0>
        adaptive 1
    }}\n"""

    return dedent(snippet).format(n=name, o=location)


def write_imagelight(name, image):
    """Compute a string in renderer SDL to represent an image-based light."""
    # POV-Ray has a lot of reserved keywords, so we suffix name with a '_' to
    # avoid any collision
    name = name + "_"

    snippet = """
    // Generated by FreeCAD (http://www.freecadweb.org/)
    // Declares image-based light {n}
    // hdr environment -----------------------
    sky_sphere{{
        matrix < -1, 0, 0,
                  0, 1, 0,
                  0, 0, 1,
                  0, 0, 0 >
        pigment{{
            image_map{{ hdr "{f}"
                       gamma 1
                       map_type 1 interpolate 2}}
        }} // end pigment
    }} // end sphere with hdr image\n"""

    return dedent(snippet).format(n=name, f=image)


# ===========================================================================
#                              Material implementation
# ===========================================================================


def _write_material(name, material):
    """Compute a string in the renderer SDL, to represent a material.

    This function should never fail: if the material is not recognized,
    a fallback material is provided.
    """
    try:
        snippet_mat = MATERIALS[material.shadertype](name, material)
    except KeyError:
        msg = (
            "'{}' - Material '{}' unknown by renderer, using fallback "
            "material\n"
        )
        App.Console.PrintWarning(msg.format(name, material.shadertype))
        snippet_mat = _write_material_fallback(name, material.default_color)
    return snippet_mat


def _write_material_passthrough(name, material):
    """Compute a string in the renderer SDL for a passthrough material."""
    assert material.passthrough.renderer == "Povray"
    snippet = indent(material.passthrough.string, "    ")
    return snippet.format(n=name, c=material.default_color)


def _write_material_glass(name, material):
    """Compute a string in the renderer SDL for a glass material."""
    snippet = """
    texture {{
        pigment {{color rgbf <{c.r}, {c.g}, {c.b}, 0.7>}}
        finish {{
            specular 1
            roughness 0.001
            ambient 0
            diffuse 0
            reflection 0.1
            }}
        }}
    interior {{
        ior {i}
        caustics 1
        }}"""
    return snippet.format(n=name, c=material.glass.color, i=material.glass.ior)


def _write_material_disney(name, material):
    """Compute a string in the renderer SDL for a Disney material.

    Caveat: this is a very rough implementation, as the Disney shader does not
    exist at all in Pov-Ray.
    """
    snippet = """
    texture {{
        pigment {{ color rgb <{c.r}, {c.g}, {c.b}> }}
        finish {{
            diffuse albedo 0.8
            specular {sp}
            roughness {r}
            conserve_energy
            reflection {{
                {sp}
                metallic
                }}
            {subsurface}
            irid {{ {ccg} }}
            }}

    }}"""
    # If disney.subsurface is 0, we just omit the subsurface statement,
    # as it is very slow to render
    subsurface = (
        f"subsurface {{ translucency {material.disney.subsurface} }}"
        if material.disney.subsurface > 0
        else ""
    )
    return snippet.format(
        n=name,
        c=material.disney.basecolor,
        subsurface=subsurface,
        m=material.disney.metallic,
        sp=material.disney.specular,
        spt=material.disney.speculartint,
        r=material.disney.roughness,
        a=material.disney.anisotropic,
        sh=material.disney.sheen,
        sht=material.disney.sheentint,
        cc=material.disney.clearcoat,
        ccg=material.disney.clearcoatgloss,
    )


def _write_material_diffuse(name, material):
    """Compute a string in the renderer SDL for a Diffuse material."""
    snippet = """    texture {{
        pigment {{rgb <{c.r}, {c.g}, {c.b}>}}
        finish {{
            diffuse albedo 1
            }}
        }}"""
    return snippet.format(n=name, c=material.diffuse.color)


def _write_material_mixed(name, material):
    """Compute a string in the renderer SDL for a Mixed material."""
    snippet = """
    texture {{
        pigment {{ rgbf <{k.r}, {k.g}, {k.b}, 0.7> }}
        finish {{
            phong 1
            roughness 0.001
            ambient 0
            diffuse 0
            reflection 0.1
            }}
    }}
    interior {{ior {i} caustics 1}}
    texture {{
        pigment {{ rgbt <{c.r}, {c.g}, {c.b}, {t}> }}
        finish {{ diffuse 1 }}
    }}"""
    return snippet.format(
        n=name,
        t=material.mixed.transparency,
        c=material.mixed.diffuse.color,
        k=material.mixed.glass.color,
        i=material.mixed.glass.ior,
    )


def _write_material_carpaint(name, material):
    """Compute a string in the renderer SDL for a carpaint material."""
    snippet = """
    texture {{
        pigment {{ rgb <{c.r}, {c.g}, {c.b}> }}
        finish {{
            diffuse albedo 0.7
            phong albedo 0
            specular albedo 0.6
            roughness 0.001
            reflection {{ 0.05 }}
            irid {{ 0.5 }}
            conserve_energy
        }}
    }}"""
    return snippet.format(n=name, c=material.carpaint.basecolor)


def _write_material_fallback(name, material):
    """Compute a string in the renderer SDL for a fallback material.

    Fallback material is a simple Diffuse material.
    """
    try:
        red = float(material.default_color.r)
        grn = float(material.default_color.g)
        blu = float(material.default_color.b)
        assert (0 <= red <= 1) and (0 <= grn <= 1) and (0 <= blu <= 1)
    except (AttributeError, ValueError, TypeError, AssertionError):
        red, grn, blu = 1, 1, 1
    snippet = """    texture {{
        pigment {{rgb <{r}, {g}, {b}>}}
        finish {{
            diffuse albedo 1
            }}
        }}"""
    return snippet.format(n=name, r=red, g=grn, b=blu)


MATERIALS = {
    "Passthrough": _write_material_passthrough,
    "Glass": _write_material_glass,
    "Disney": _write_material_disney,
    "Diffuse": _write_material_diffuse,
    "Mixed": _write_material_mixed,
    "Carpaint": _write_material_carpaint,
}


# ===========================================================================
#                              Render function
# ===========================================================================


def render(project, prefix, external, output, width, height):
    """Generate renderer command.

    Args:
        project -- The project to render
        prefix -- A prefix string for call (will be inserted before path to
            renderer)
        external -- A boolean indicating whether to call UI (true) or console
            (false) version of renderder
        width -- Rendered image width, in pixels
        height -- Rendered image height, in pixels

    Returns:
        The command to run renderer (string)
        A path to output image file (string)
    """
    params = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Render")

    prefix = params.GetString("Prefix", "")
    if prefix:
        prefix += " "

    rpath = params.GetString("PovRayPath", "")
    if not rpath:
        App.Console.PrintError(
            "Unable to locate renderer executable. "
            "Please set the correct path in "
            "Edit -> Preferences -> Render\n"
        )
        return None, None

    args = params.GetString("PovRayParameters", "")
    if args:
        args += " "
    if "+W" in args:
        args = re.sub(r"\+W[0-9]+", f"+W{width}", args)
    else:
        args = args + f"+W{width} "
    if "+H" in args:
        args = re.sub(r"\+H[0-9]+", f"+H{height}", args)
    else:
        args = args + f"+H{height} "
    if output:
        args = args + f"+O{output} "

    filepath = f'"{project.PageResult}"'

    cmd = prefix + rpath + " " + args + " " + filepath

    output = (
        output if output else os.path.splitext(project.PageResult)[0] + ".png"
    )

    return cmd, output
