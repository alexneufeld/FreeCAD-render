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
# This module handles all the external renderers implemented as Python modules.
# It will add all renderer modules specified below at FreeCAD launch, and
# create the necessary UI controls.

import sys
import os
import re
from os import path
from importlib import import_module
from tempfile import mkstemp
from types import SimpleNamespace
from operator import attrgetter

from PySide.QtGui import QAction, QIcon, QFileDialog
from PySide.QtCore import QT_TRANSLATE_NOOP, QObject, SIGNAL
import FreeCAD as App
import FreeCADGui as Gui
import Draft
import Part
import MeshPart
try:
    import ImageGui
except ImportError:
    pass
try:
    from draftutils.translate import translate  # 0.19
except ImportError:
    from Draft import translate  # 0.18

import camera



def importRenderer(rdrname):
    """Dynamically import a renderer module.
    Returns the module if import succeeds, None otherwise

    rdrname: renderer name (as a string)"""

    try:
        return import_module("renderers." + rdrname)
    except ImportError:
        errmsg = translate("Render","Error importing renderer '{}'\n").format(rdrname)
        App.Console.PrintError(errmsg)
        return None



class RenderProjectCommand:


    "Creates a rendering project. The renderer parameter must be a valid rendering module"

    def __init__(self,renderer):
        self.renderer = renderer

    def GetResources(self):
        return {'Pixmap'  : os.path.join(os.path.dirname(__file__),"icons",self.renderer+".svg"),
                'MenuText': QT_TRANSLATE_NOOP("Render", "%s Project") % self.renderer,
                'ToolTip' : QT_TRANSLATE_NOOP("Render", "Creates a %s project") % self.renderer}

    def Activated(self):
        if self.renderer:
            project = App.ActiveDocument.addObject("App::FeaturePython",self.renderer+"Project")
            Project(project)
            project.Label = self.renderer + " Project"
            project.Renderer = self.renderer
            ViewProviderProject(project.ViewObject)
            filename = QFileDialog.getOpenFileName(Gui.getMainWindow(),'Select template',os.path.join(os.path.dirname(__file__),"templates"),'*.*')
            if filename:
                project.Template = filename[0]
            App.ActiveDocument.recompute()



class RenderViewCommand:


    "Creates a Raytracing view of the selected object(s) in the selected project or the default project"

    def GetResources(self):
        return {'Pixmap'  : os.path.join(os.path.dirname(__file__),"icons","RenderView.svg"),
                'MenuText': QT_TRANSLATE_NOOP("Render", "Create View"),
                'ToolTip' : QT_TRANSLATE_NOOP("Render", "Creates a Render view of the selected object(s) in the selected project or the default project")}

    def Activated(self):
        project = None
        objs = []
        sel = Gui.Selection.getSelection()
        for o in sel:
            if "Renderer" in o.PropertiesList:
                project = o
            else:
                if o.isDerivedFrom("Part::Feature") or o.isDerivedFrom("Mesh::Feature"):
                    objs.append(o)
                if o.isDerivedFrom("App::FeaturePython") and o.Proxy.type in ['PointLight','Camera']:
                    objs.append(o)
        if not project:
            for o in App.ActiveDocument.Objects:
                if "Renderer" in o.PropertiesList:
                    project = o
                    break
        if not project:
            App.Console.PrintError(translate("Render","Unable to find a valid project in selection or document"))
            return

        for obj in objs:
            view = App.ActiveDocument.addObject("App::FeaturePython",obj.Name+"View")
            view.Label = "View of "+ obj.Name
            View(view)
            view.Source = obj
            project.addObject(view)
            ViewProviderView(view.ViewObject)
        App.ActiveDocument.recompute()



class RenderCommand:


    "Renders a selected Render project"


    def GetResources(self):
        return {'Pixmap'  : os.path.join(os.path.dirname(__file__),"icons","Render.svg"),
                'MenuText': QT_TRANSLATE_NOOP("Render", "Render"),
                'ToolTip' : QT_TRANSLATE_NOOP("Render", "Performs the render of a selected project or the default project")}

    def Activated(self):
        project = None
        sel = Gui.Selection.getSelection()
        for o in sel:
            if "Renderer" in o.PropertiesList:
                project = o
                break
        if not project:
            for o in App.ActiveDocument.Objects:
                if "Renderer" in o.PropertiesList:
                    project = o
                    break
        if not project:
            App.Console.PrintError(translate("Render","Unable to find a valid project in selection or document"))
            return
        img = project.Proxy.render(project)
        if img and hasattr(project,"OpenAfterRender") and project.OpenAfterRender:
            ImageGui.open(img)


class RenderExternalCommand:


    "Sends a selected Render project"


    def GetResources(self):

        return {'Pixmap'  : os.path.join(os.path.dirname(__file__),"icons","Render.svg"),
                'MenuText': QT_TRANSLATE_NOOP("Render", "Render"),
                'ToolTip' : QT_TRANSLATE_NOOP("Render", "Performs the render of a selected project or the default project")}

    def Activated(self):

        project = None
        sel = Gui.Selection.getSelection()
        for o in sel:
            if "Renderer" in o.PropertiesList:
                project = o
                break
        if not project:
            for o in App.ActiveDocument.Objects:
                if "Renderer" in o.PropertiesList:
                    project = o
                    break
        if not project:
            App.Console.PrintError(translate("Render","Unable to find a valid project in selection or document"))
            return
        img = project.Proxy.render(project,external=True)
        if img and hasattr(project,"OpenAfterRender") and project.OpenAfterRender:
            ImageGui.open(img)

class CameraCommand:

    "Create a Camera object"

    def GetResources(self):

        return {'Pixmap'  : ":/icons/camera-photo.svg",
                'MenuText': QT_TRANSLATE_NOOP("Render", "Create Camera"),
                'ToolTip' : QT_TRANSLATE_NOOP("Render", "Create a Camera object from the current camera position")}

    def Activated(self):
        camera.Camera.create()


class Project:


    "A rendering project"


    def __init__(self,obj):

        obj.Proxy = self
        self.setProperties(obj)


    def setProperties(self,obj):

        if not "Renderer" in obj.PropertiesList:
            obj.addProperty("App::PropertyString","Renderer","Render", QT_TRANSLATE_NOOP("App::Property","The name of the raytracing engine to use"))
        if not "DelayedBuild" in obj.PropertiesList:
            obj.addProperty("App::PropertyBool","DelayedBuild","Render", QT_TRANSLATE_NOOP("App::Property","If true, the views will be updated on render only"))
            obj.DelayedBuild = True
        if not "Template" in obj.PropertiesList:
            obj.addProperty("App::PropertyFile","Template","Render", QT_TRANSLATE_NOOP("App::Property","The template to be used by this rendering"))
        if not "PageResult" in obj.PropertiesList:
            obj.addProperty("App::PropertyFileIncluded", "PageResult","Render", QT_TRANSLATE_NOOP("App::Property","The result file to be sent to the renderer"))
        if not "Group" in obj.PropertiesList:
            obj.addExtension("App::GroupExtensionPython", self)
        if not "RenderWidth" in obj.PropertiesList:
            obj.addProperty("App::PropertyInteger","RenderWidth","Render", QT_TRANSLATE_NOOP("App::Property","The width of the rendered image in pixels"))
            obj.RenderWidth = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Render").GetInt("RenderWidth",800)
        if not "RenderHeight" in obj.PropertiesList:
            obj.addProperty("App::PropertyInteger","RenderHeight","Render", QT_TRANSLATE_NOOP("App::Property","The height of the rendered image in pixels"))
            obj.RenderHeight = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Render").GetInt("RenderHeight",600)
        if not "GroundPlane" in obj.PropertiesList:
            obj.addProperty("App::PropertyBool","GroundPlane","Render", QT_TRANSLATE_NOOP("App::Property","If true, a default ground plane will be added to the scene"))
            obj.GroundPlane = False
        if not "OutputImage" in obj.PropertiesList:
            obj.addProperty("App::PropertyFile","OutputImage","Render", QT_TRANSLATE_NOOP("App::Property","The image saved by this render"))
        if not "OpenAfterRender" in obj.PropertiesList:
            obj.addProperty("App::PropertyBool","OpenAfterRender","Render", QT_TRANSLATE_NOOP("App::Property","If true, the rendered image is opened in FreeCAD after the rendering is finished"))
            obj.GroundPlane = False
        obj.setEditorMode("PageResult",2)


    def onDocumentRestored(self,obj):

        self.setProperties(obj)


    def execute(self,obj):
        return True

    def onChanged(self,obj,prop):

        if prop == "DelayedBuild":
            if not obj.DelayedBuild:
                for view in obj.Group:
                    view.touch()

    def writeCamera(self, view, renderer):
        """Get a rendering string from a camera. Camera can be either a string in Coin
        format or a Camera object

        Parameters:
        view: a view of the camera to render.
        renderer: the renderer module to use

        Returns: a rendering string, obtained from the renderer module
        """

        cam = view.Source
        aspectRatio = cam.AspectRatio
        pos = cam.Placement.Base
        rot = cam.Placement.Rotation
        target = pos.add(rot.multVec(App.Vector(0, 0, -1)).multiply(aspectRatio))
        up = rot.multVec(App.Vector(0, 1, 0))

        return renderer.write_camera(pos, rot, up, target, "")

    def writePointLight(self,view,renderer):
        """Gets a rendering string for a point light object

           Parameters:
           view: the view of the point light (contains the point light data)
           renderer: the renderer module to use (callback)

           Returns: a rendering string, obtained from the renderer module
        """
        # get location, color, power
        pl = view.Source.PropertiesList

        try:
            location = view.Source.Location
            color = view.Source.Color
        except AttributeError:
            App.Console.PrintError(translate("Render","Cannot render Point Light: Missing location and/or color attributes"))
            return ""
        power = getattr(view.Source,"Power",60) # We accept missing Power (default value: 60)...

        # send everything to renderer module
        return renderer.write_pointlight(view,location,color,power)


    def writeMesh(self,view,renderer):
        """Get a rendering string for a mesh object"""

        # get color and alpha
        mat = None
        color = None
        alpha = None
        if view.Material:
            mat = view.Material
        else:
            if "Material" in view.Source.PropertiesList:
                if view.Source.Material:
                    mat = view.Source.Material
        if mat:
            if "Material" in mat.PropertiesList:
                if "DiffuseColor" in mat.Material:
                    color = mat.Material["DiffuseColor"].strip("(").strip(")").split(",")[:3]
                if "Transparency" in mat.Material:
                    if float(mat.Material["Transparency"]) > 0:
                        alpha = 1.0 - float(mat.Material["Transparency"])
                    else:
                        alpha = 1.0

        if view.Source.ViewObject:
            if not color:
                if hasattr(view.Source.ViewObject,"ShapeColor"):
                    color = view.Source.ViewObject.ShapeColor[:3]
            if not alpha:
                if hasattr(view.Source.ViewObject,"Transparency"):
                    if view.Source.ViewObject.Transparency > 0:
                        alpha = 1.0-(float(view.Source.ViewObject.Transparency)/100.0)
        if not color:
            color = (1.0, 1.0, 1.0)
        if not alpha:
            alpha = 1.0

        # get mesh
        mesh = None
        if hasattr(view.Source,"Group"):
            shps = [o.Shape for o in Draft.getGroupContents(view.Source) if hasattr(o,"Shape")]
            mesh = MeshPart.meshFromShape(Shape=Part.makeCompound(shps),
                                       LinearDeflection=0.1,
                                       AngularDeflection=0.523599,
                                       Relative=False)
        elif view.Source.isDerivedFrom("Part::Feature"):
            mesh = MeshPart.meshFromShape(Shape=view.Source.Shape,
                                       LinearDeflection=0.1,
                                       AngularDeflection=0.523599,
                                       Relative=False)
        elif view.Source.isDerivedFrom("Mesh::Feature"):
            mesh = view.Source.Mesh
        if not mesh:
            return ""

        return renderer.write_object(view,mesh,color,alpha)


    def writeObject(self,view,renderer):
        """Gets a rendering string for the view of an object

           Parameters:
           view: the view of the object (contains the object data)
           renderer: the renderer module to use (callback)
        """

        if not view.Source:
            return ""

        # Special objects: camera, lights etc.
        try:
            objtype = view.Source.Proxy.type
        except AttributeError:
            pass
        else:
            if objtype == "PointLight":
                return self.writePointLight(view, renderer)
            if objtype == "Camera":
                return self.writeCamera(view, renderer)

        # Mesh
        return self.writeMesh(view, renderer)



    def writeGroundPlane(self,obj,renderer):
        """Generate a ground plane rendering string for the scene

        For that purpose, dummy objects are temporaly added to the scenegraph and
        eventually deleted"""

        result = ""
        bbox = App.BoundBox()
        for view in obj.Group:
            if view.Source and hasattr(view.Source,"Shape") and hasattr(view.Source.Shape,"BoundBox"):
                bbox.add(view.Source.Shape.BoundBox)
        if bbox.isValid():
            margin = bbox.DiagonalLength/2
            p1 = App.Vector(bbox.XMin-margin,bbox.YMin-margin,0)
            p2 = App.Vector(bbox.XMax+margin,bbox.YMin-margin,0)
            p3 = App.Vector(bbox.XMax+margin,bbox.YMax+margin,0)
            p4 = App.Vector(bbox.XMin-margin,bbox.YMax+margin,0)

            # create temporary object. We do this to keep the renderers code as simple as possible:
            # they only need to deal with one type of object: RenderView objects
            dummy1 = App.ActiveDocument.addObject("Part::Feature","renderdummy1")
            dummy1.Shape = Part.Face(Part.makePolygon([p1,p2,p3,p4,p1]))
            dummy2 = App.ActiveDocument.addObject("App::FeaturePython","renderdummy2")
            View(dummy2)
            dummy2.Source = dummy1
            ViewProviderView(dummy2.ViewObject)
            App.ActiveDocument.recompute()

            result = self.writeObject(dummy2,renderer)

            # remove temp objects
            App.ActiveDocument.removeObject(dummy2.Name)
            App.ActiveDocument.removeObject(dummy1.Name)
            App.ActiveDocument.recompute()

        return result


    def render(self,obj,external=True):
        """Render the project, calling external renderer

            obj: the project view
            external: (for future use)"""

        # check some prerequisites...
        if not obj.Renderer:
            return
        if not obj.Template:
            return
        if not os.path.exists(obj.Template):
            return

        # get the renderer module
        renderer = importRenderer(obj.Renderer)
        if not renderer:
            return

        # get the rendering template
        template = None
        with open(obj.Template,"r") as f:
            template = f.read()
        if sys.version_info.major < 3:
            template = template.decode("utf8")
        if not template:
            return

        # get active camera (will be used if no camera is present in the scene)
        if App.GuiUp:
            dummycamview = SimpleNamespace()
            dummycamview.Source = SimpleNamespace()
            camera.set_cam_from_coin_string(dummycamview.Source,
                                            Gui.ActiveDocument.ActiveView.getCamera())
            cam = self.writeCamera(dummycamview,
                                   renderer)

        # get objects rendering strings (including lights objects)
        # and add a ground plane if required
        if obj.DelayedBuild:
            objstrings = [self.writeObject(view, renderer) for view in obj.Group]
        else:
            objstrings = [view.ViewResult for view in obj.Group]

        if hasattr(obj,"GroundPlane") and obj.GroundPlane:
            objstrings.append(self.writeGroundPlane(obj,renderer))

        renderobjs = ''.join(objstrings)

        # merge all strings (cam, objects, ground plane...) into rendering template
        if "RaytracingCamera" in template:
            template = re.sub("(.*RaytracingCamera.*)",cam,template)
            template = re.sub("(.*RaytracingContent.*)",renderobjs,template)
        else:
            template = re.sub("(.*RaytracingContent.*)",cam+"\n"+renderobjs,template)
        if sys.version_info.major < 3:
            template = template.encode("utf8")

        # write merger result into a temporary file
        fh, fp = mkstemp(  prefix=obj.Name,
                                    suffix=os.path.splitext(obj.Template)[-1])
        with open(fp,"w") as f:
            f.write(template)
        os.close(fh)
        obj.PageResult = fp
        os.remove(fp)
        if not obj.PageResult:
            App.Console.PrintError(translate("Render","Error: No page result"))
            return

        App.ActiveDocument.recompute()

        # fetch the rendering parameters
        p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Render")
        prefix = p.GetString("Prefix","")
        if prefix:
            prefix += " "
        output = os.path.splitext(obj.PageResult)[0]+".png"
        if hasattr(obj,"OutputImage") and obj.OutputImage:
            output = obj.OutputImage
        width = 800
        if hasattr(obj,"RenderWidth") and obj.RenderWidth:
            width = obj.RenderWidth
        height = 600
        if hasattr(obj,"RenderHeight") and obj.RenderHeight:
            height = obj.RenderHeight

        # run the renderer on the temp file
        return renderer.render(obj,prefix,external,output,width,height)

        App.Console.PrintError(translate("Render","Error while executing renderer")+" "+str(obj.Renderer) + ": " + traceback.format_exc()+"\n")


class ViewProviderProject:


    def __init__(self,vobj):
        vobj.Proxy = self

    def attach(self,vobj):
        self.Object = vobj.Object
        return True

    def __getstate__(self):
        return None

    def __setstate__(self,state):
        return None

    def getDisplayModes(self,vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def setDisplayMode(self,mode):
        return mode

    def isShow(self):
        return True

    def getIcon(self):
        return os.path.join(os.path.dirname(__file__),"icons","RenderProject.svg")

    def setupContextMenu(self,vobj,menu):
        action1 = QAction(QIcon(os.path.join(os.path.dirname(__file__),"icons","Render.svg")),"Render",menu)
        QObject.connect(action1,SIGNAL("triggered()"),self.render)
        menu.addAction(action1)

    def render(self):
        if hasattr(self,"Object"):
            self.Object.Proxy.render(self.Object)

    def claimChildren(self):
        if hasattr(self,"Object"):
            return self.Object.Group


class View:


    "A rendering view"

    def __init__(self,obj):

        obj.addProperty("App::PropertyLink",         "Source",     "Render", QT_TRANSLATE_NOOP("App::Property","The source object of this view"))
        obj.addProperty("App::PropertyLink",         "Material",   "Render", QT_TRANSLATE_NOOP("App::Property","The material of this view"))
        obj.addProperty("App::PropertyString",       "ViewResult", "Render", QT_TRANSLATE_NOOP("App::Property","The rendering output of this view"))
        obj.Proxy = self

    def execute(self,obj):

        # (re)write the ViewResult string if containing project is not 'delayed build'
        for proj in obj.InList:
            # only for projects with no delayed build...
            if not hasattr(proj,"DelayedBuild") or proj.DelayedBuild:
                continue

            # get the renderer module
            renderer = importRenderer(proj.Renderer)
            if not renderer:
                return

            # find the object and write its rendering string
            if hasattr(proj,"Group"):
                for c in proj.Group:
                    if c == obj:
                        obj.ViewResult = proj.Proxy.writeObject(obj,renderer)
                        break

        # TODO the above implementation ('linear search') is certainly very inefficient
        # when there are many objects: as execute() is triggered for each object,
        # the total complexity can be O(n²), if I'm not mistaken.
        # We should look for something more optimized in the future...


class ViewProviderView:


    def __init__(self,vobj):
        vobj.Proxy = self

    def attach(self,vobj):
        self.Object = vobj.Object

    def __getstate__(self):
        return None

    def __setstate__(self,state):
        return None

    def getDisplayModes(self,vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def setDisplayMode(self,mode):
        return mode

    def isShow(self):
        return True

    def getIcon(self):
        return os.path.join(os.path.dirname(__file__),"icons","RenderViewTree.svg")



# Load available renderers and create the FreeCAD commands



if App.GuiUp:


    RENDER_COMMANDS = []
    Renderers = os.listdir(os.path.dirname(__file__)+os.sep+"renderers")
    Renderers = [r for r in Renderers if not ".pyc" in r]
    Renderers = [r for r in Renderers if not "__" in r]
    Renderers = [os.path.splitext(r)[0] for r in Renderers]
    for renderer in Renderers:
        Gui.addCommand('Render_'+renderer, RenderProjectCommand(renderer))
        RENDER_COMMANDS.append('Render_'+renderer)
    Gui.addCommand('Render_Camera', CameraCommand())
    RENDER_COMMANDS.append('Render_Camera')
    Gui.addCommand('Render_View', RenderViewCommand())
    RENDER_COMMANDS.append('Render_View')
    Gui.addCommand('Render_Render', RenderCommand())
    RENDER_COMMANDS.append('Render_Render')

    # This is for InitGui.py because it cannot import os
    ICONPATH = os.path.join(os.path.dirname(__file__),"icons")
    PREFPAGE = os.path.join(os.path.dirname(__file__),"ui","RenderSettings.ui")
