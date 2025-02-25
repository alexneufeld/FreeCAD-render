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

"""This module implements RendererHandler class.

RendererHandler is a simplified and unified accessor to renderers plugins.

Among important things, RendererHandler:
- allows to get a rendering string for a given object
- allows to run a renderer onto a scene
- generates a ground plane on-the-fly, if needed

Caveat about units:
Please note that RendererHandler converts distance units from FreeCAD internals
(millimeters) to standard (meters) before sending objects to renderers, as
usual renderers expects meters as base unit.
"""


# ===========================================================================
#                                   Imports
# ===========================================================================

import sys
import functools
import traceback
from importlib import import_module
from types import SimpleNamespace

import FreeCAD as App
import MeshPart
import Mesh

from Render.utils import translate, debug, getproxyattr, clamp
from Render import renderables
import Render.rdrmaterials as materials


# ===========================================================================
#                                  Constants
# ===========================================================================

# Scale from FreeCAD internal distance unit (mm) to renderers ones (m)
SCALE = 0.001


# ===========================================================================
#                            Renderer Handler
# ===========================================================================


class RendererHandler:
    """This class provides simplified access to external renderers modules.

    This class implements a simplified interface to external renderer module
    (façade design pattern).
    It requires a valid external renderer name for initialization, and
    provides:
    - a method to run the external renderer on a renderer-format file
    - a method to get a rendering string from an object's View, taking care of
      selecting the right method in renderer module according to
    view object's type.
    """

    def __init__(self, rdrname, **kwargs):
        """Initialize RendererHandler class.

        Args:
            rdrname -- renderer name (str). Must match a renderer plugin name.

        Keyword args:
            linear_deflection -- linear deflection (float) to be passed to
                mesher
            angular_deflection -- angular deflection (float) to be passed to
                mesher.
            transparency_boost -- an integer to augment transparency in
                implicit material computation
        """
        self.renderer_name = str(rdrname)
        self.linear_deflection = float(kwargs.get("linear_deflection", 0.1))
        self.angular_deflection = float(
            kwargs.get("angular_deflection", 0.524)
        )
        self.transparency_boost = float(kwargs.get("transparency_boost", 0))

        try:
            module_name = f"Render.renderers.{rdrname}"
            self.renderer_module = import_module(module_name)
        except ModuleNotFoundError:
            raise RendererNotFoundError(rdrname) from None

    def render(self, project, prefix, external, output, width, height):
        """Run the external renderer.

        This method merely calls external renderer's 'render' method.

        Params:
        - project:  the project to render
        - prefix:   a prefix string for call (will be inserted before path to
                    renderer)
        - external: a boolean indicating whether to call UI (true) or console
                    (false) version of renderer
        - width:    rendered image width, in pixels
        - height:   rendered image height, in pixels

        Return:     path to image file generated, or None if no image has been
                    issued by external renderer
        """
        return self.renderer_module.render(
            project, prefix, external, output, width, height
        )

    @staticmethod
    def is_renderable(obj):
        """Determine if an object is renderable.

        This is a weak test: we just check if the object belongs to a
        class we would know how to handle - no further verification
        is made on the consistency of the object data against
        get_rendering_string requirements.
        """
        try:
            res = (
                obj.isDerivedFrom("Part::Feature")
                or obj.isDerivedFrom("App::Link")
                or obj.isDerivedFrom("App::Part")
                or obj.isDerivedFrom("Mesh::Feature")
                or (
                    obj.isDerivedFrom("App::FeaturePython")
                    and getproxyattr(obj, "type", "")
                    in [
                        "PointLight",
                        "Camera",
                        "AreaLight",
                        "SunskyLight",
                        "ImageLight",
                    ]
                )
                or (
                    obj.isDerivedFrom("App::GeometryPython")
                    and getproxyattr(obj, "type", "")
                    in [
                        "PointLight",
                        "Camera",
                        "AreaLight",
                        "SunskyLight",
                        "ImageLight",
                    ]
                )
            )
        except AttributeError:
            res = False

        return res

    @staticmethod
    def is_project(obj):
        """Determine if an object is a rendering project.

        This is a weak test: we just check if the object looks like
        something we could know how to handle - no further verification
        is made on the consistency of the object data against
        render requirements.
        """
        try:
            res = (
                obj.isDerivedFrom("App::FeaturePython")
                and "Renderer" in obj.PropertiesList
            )
        except AttributeError:
            res = False

        return res

    def get_template_file_filter(self):
        """Get file filter for templates of the renderer.

        Args:
            rdr -- renderer name (str)

        Returns:
            A string containing a file filter for renderer's templates.
        """
        return str(getattr(self.renderer_module, "TEMPLATE_FILTER", ""))

    def get_rendering_string(self, view):
        """Provide a rendering string for the view of an object.

        This method selects the specialized rendering method adapted for
        'view', according to its source object type, and calls it.

        Parameters:
        view -- the view of the object to render

        Returns: a rendering string in the format of the external renderer
        for the supplied 'view'
        """
        try:
            source = view.Source

            objtype = getproxyattr(source, "type", "Object")

            name = str(source.Name)

            switcher = {
                "Object": RendererHandler._render_object,
                "PointLight": RendererHandler._render_pointlight,
                "Camera": RendererHandler._render_camera,
                "AreaLight": RendererHandler._render_arealight,
                "SunskyLight": RendererHandler._render_sunskylight,
                "ImageLight": RendererHandler._render_imagelight,
            }

            res = switcher[objtype](self, name, view)

        except (AttributeError, TypeError, AssertionError) as err:
            msg = (
                translate(
                    "Render",
                    "[Render] Cannot render view '{0}': {1} (file {2}, "
                    "line {3} in {4}). Skipping...",
                )
                + "\n"
            )
            _, _, exc_traceback = sys.exc_info()
            framestack = traceback.extract_tb(exc_traceback)[-1]
            App.Console.PrintWarning(
                msg.format(
                    getattr(view, "Label", "<No label>"),
                    err,
                    framestack.filename,
                    framestack.lineno,
                    framestack.name,
                )
            )
            return ""

        else:
            return res

    def get_groundplane_string(self, bbox, zpos, color, sizefactor):
        """Get a rendering string for a ground plane.

        The resulting ground plane is a horizontal plane at 'zpos' vertical
        position.
        The X and Y coordinates are computed from a scene bounding box.

        Args:
        bbox -- Bounding box for the scene (FreeCAD.BoundBox)
        zpos -- Z position of the ground plane (float)
        color -- Color of the ground plane (rgb tuple)

        Returns:
        A rendering string
        """
        margin = bbox.DiagonalLength / 2 * sizefactor
        verts2d = (
            (bbox.XMin - margin, bbox.YMin - margin),
            (bbox.XMax + margin, bbox.YMin - margin),
            (bbox.XMax + margin, bbox.YMax + margin),
            (bbox.XMin - margin, bbox.YMax + margin),
        )
        vertices = [
            App.Vector(clamp(v[0]), clamp(v[1]), zpos) for v in verts2d
        ]  # Clamp to avoid huge dimensions...
        mesh = Mesh.Mesh()
        mesh.addFacet(vertices[0], vertices[1], vertices[2])
        mesh.addFacet(vertices[0], vertices[2], vertices[3])

        mat = materials.get_rendering_material(None, "", color)

        # Rescale to meters
        scalemat = App.Matrix()
        scalemat.scale(SCALE, SCALE, SCALE)
        mesh.transform(scalemat)
        mesh.Placement.Base.multiply(SCALE)  # pylint: disable=no-member

        res = self.renderer_module.write_mesh("ground_plane", mesh, mat)

        return res

    def get_camsource_string(self, camsource):
        """Get a rendering string from a camera in 'view.Source' format."""
        return self._render_camera(
            "Default_Camera", SimpleNamespace(Source=camsource)
        )

    def _render_object(self, name, view):
        """Get a rendering string for a generic FreeCAD object.

        This method follows EAFP idiom and will raise exceptions if something
        goes wrong (missing attribute, inconsistent data...).

        Parameters:
        name -- the name of the object
        view -- a view of the object to render

        Returns: a rendering string, obtained from the renderer module
        """

        def mesher(shape):
            """Mesh a shape."""
            # Generate mesh
            mesh = MeshPart.meshFromShape(
                Shape=shape,
                LinearDeflection=self.linear_deflection,
                AngularDeflection=self.angular_deflection,
                Relative=False,
            )
            # Harmonize normals
            mesh.harmonizeNormals()
            return mesh

        source = view.Source
        label = getattr(source, "Label", name)
        debug("Object", label, "Processing")

        # Build a list of renderables from the object
        material = view.Material
        tpboost = self.transparency_boost
        rends = renderables.get_renderables(
            source, name, material, mesher, transparency_boost=tpboost
        )

        # Check renderables
        renderables.check_renderables(rends)

        # Rescale to meters
        scalemat = App.Matrix()
        scalemat.scale(SCALE, SCALE, SCALE)
        for rend in rends:
            rend.mesh.transform(scalemat)
            rend.mesh.Placement.Base.multiply(SCALE)

        # Call renderer on renderables, concatenate and return
        write_mesh = functools.partial(
            RendererHandler._call_renderer, self, "write_mesh"
        )

        get_mat = materials.get_rendering_material
        rdrname = self.renderer_name

        res = [
            write_mesh(
                r.name, r.mesh, get_mat(r.material, rdrname, r.defcolor)
            )
            for r in rends
        ]
        return "".join(res)

    def _render_camera(self, name, view):
        """Provide a rendering string for a camera.

        This method follows EAFP idiom and will raise exceptions if something
        goes wrong (missing attribute, inconsistent data...).

        Parameters:
        name -- the name of the camera
        view -- a view of the camera to render

        Returns: a rendering string, obtained from the renderer module
        """
        source = view.Source
        a_ratio = float(source.AspectRatio)
        pos = App.Base.Placement(source.Placement)
        target = pos.Base.add(
            pos.Rotation.multVec(App.Vector(0, 0, -1)).multiply(a_ratio)
        )
        updir = pos.Rotation.multVec(App.Vector(0, 1, 0))
        field_of_view = float(getattr(source, "HeightAngle", 60))
        # Rescale
        pos.Base.multiply(SCALE)
        target.multiply(SCALE)
        updir.multiply(SCALE)

        return self._call_renderer(
            "write_camera", name, pos, updir, target, field_of_view
        )

    def _render_pointlight(self, name, view):
        """Get a rendering string for a point light object.

        This method follows EAFP idiom and will raise exceptions if something
        goes wrong (missing attribute, inconsistent data...).

        Parameters:
        name -- the name of the point light
        view -- the view of the point light (contains the light data)

        Returns: a rendering string, obtained from the renderer module
        """
        debug("PointLight", name, "Processing")

        source = view.Source

        # Get location, color
        location = App.Base.Vector(source.Location)
        color = source.Color

        # Rescale
        location.multiply(SCALE)

        # We accept missing Power (default value: 60)...
        power = getattr(source, "Power", 60)

        # Send everything to renderer module
        return self._call_renderer(
            "write_pointlight", name, location, color, power
        )

    def _render_arealight(self, name, view):
        """Get a rendering string for an area light object.

        This method follows EAFP idiom and will raise exceptions if something
        goes wrong (missing attribute, inconsistent data...)

        Parameters:
        name -- the name of the area light
        view -- the view of the area light (contains the light data)

        Returns: a rendering string, obtained from the renderer module
        """
        debug("AreaLight", name, "Processing")

        # Get properties
        source = view.Source
        placement = App.Base.Placement(source.Placement)
        placement.Base.multiply(SCALE)  # Rescale
        color = source.Color
        power = float(source.Power)
        size_u = float(source.SizeU) * SCALE
        size_v = float(source.SizeV) * SCALE
        transparent = bool(source.Transparent)

        # Send everything to renderer module
        return self._call_renderer(
            "write_arealight",
            name,
            placement,
            size_u,
            size_v,
            color,
            power,
            transparent,
        )

    def _render_sunskylight(self, name, view):
        """Get a rendering string for a sunsky light object.

        This method follows EAFP idiom and will raise exceptions if something
        goes wrong (missing attribute, inconsistent data...).

        Parameters:
        name -- the name of the sunsky light
        view -- the view of the sunsky light (contains the light data)

        Returns: a rendering string, obtained from the renderer module
        """
        debug("SunskyLight", name, "Processing")
        src = view.Source
        direction = App.Vector(src.SunDirection)
        turbidity = float(src.Turbidity)
        albedo = float(src.GroundAlbedo)
        # Distance from the sun:
        distance = App.Units.parseQuantity("151000000 km").Value

        assert turbidity >= 0, "Negative turbidity"

        assert albedo >= 0, "Negative albedo"

        assert direction.Length, "Sun direction is null"

        return self._call_renderer(
            "write_sunskylight", name, direction, distance, turbidity, albedo
        )

    def _render_imagelight(self, name, view):
        """Get a rendering string for an image light object.

        This method follows EAFP idiom and will raise exceptions if something
        goes wrong (missing attribute, inconsistent data...).

        Parameters:
        name -- the name of the image light
        view -- the view of the image light (contains the light data)

        Returns: a rendering string, obtained from the renderer module
        """
        debug("ImageLight", name, "Processing")
        src = view.Source
        image = src.ImageFile

        return self._call_renderer("write_imagelight", name, image)

    def _call_renderer(self, method, *args):
        """Call a render method of the renderer module.

        Parameters:
        -----------
        method -- the method to call (as a string)
        args -- the arguments to pass to the method

        Returns: a rendering string, obtained from the renderer module
        """
        renderer_method = getattr(self.renderer_module, method)
        return renderer_method(*args)


# ===========================================================================
#                          Renderer Handler Exceptions
# ===========================================================================


class RendererNotFoundError(Exception):
    """Exception raised when attempted an access to an unfoundable renderer.

    Attributes:
        renderer -- the unfound renderer (str)
    """

    def __init__(self, renderer):
        """Initialize exception."""
        super().__init__()
        self.renderer = str(renderer)

    def message(self):
        """Give error message."""
        msg = (
            translate("Render", "[Render] Error: Renderer '%s' not found")
            % self.renderer
        )
        return msg
