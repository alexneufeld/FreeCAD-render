# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2017 Yorik van Havre <yorik@uncreated.net>              *
# *   Copyright (c) 2021 Howetuft <howetuft@gmail.com>                      *
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

"""This module implements GUI task panels for Render workbench."""


import os

from PySide.QtGui import (
    QPushButton,
    QCheckBox,
    QColor,
    QColorDialog,
    QPixmap,
    QIcon,
    QFormLayout,
    QComboBox,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QLayout,
    QHBoxLayout,
    QWidget,
    QListView,
    QLineEdit,
    QDoubleValidator,
)
from PySide.QtCore import (
    QT_TRANSLATE_NOOP,
    QObject,
    SIGNAL,
    Qt,
    QLocale,
    QSize,
)

import FreeCAD as App
import FreeCADGui as Gui

from ArchMaterial import _ArchMaterialTaskPanel

from Render.constants import (
    TASKPAGE,
    VALID_RENDERERS,
    ICONDIR,
    WBMATERIALDIR,
    FCDMATERIALDIR,
    USERMATERIALDIR,
)
from Render.utils import str2rgb, translate, parse_csv_str
from Render.rdrmaterials import (
    STD_MATERIALS,
    STD_MATERIALS_PARAMETERS,
    is_valid_material,
    passthrough_keys,
)


class ColorPicker(QPushButton):
    """A color picker widget.

    This widget provides a button, with a colored square icon, which triggers
    a color dialog when it is pressed.
    """

    def __init__(self, color=QColor(127, 127, 127)):
        """Initialize ColorPicker.

        Args:
            color -- The default color of the picker
        """
        super().__init__()
        self.color = QColor(color)
        self._set_icon(self.color)
        QObject.connect(self, SIGNAL("clicked()"), self.on_button_clicked)

    def on_button_clicked(self):
        """Respond to button clicked event (callback)."""
        color = QColorDialog.getColor(initial=self.color)
        if color.isValid():
            self.color = color
            self._set_icon(color)

    def _set_icon(self, color):
        """Set the colored square icon."""
        colorpix = QPixmap(16, 16)
        colorpix.fill(color)
        self.setIcon(QIcon(colorpix))

    def set_color(self, color):
        """Set widget color value."""
        self.color = QColor(color)
        self._set_icon(self.color)

    def get_color_text(self):
        """Get widget color value, in text format."""
        color = self.color
        return f"({color.redF()},{color.greenF()},{color.blueF()})"


class ColorPickerExt(QWidget):
    """An extended color picker widget.

    This widget provides a color picker, and also a checkbox that allows to
    specify to use object color in lieu of color selected in the picker.
    """

    def __init__(self, color=QColor(127, 127, 127), use_object_color=False):
        """Initialize widget.

        Args:
            color -- RGB color used to initialize the color picker
            use_object_color -- boolean used to initialize the 'use object
                color' checkbox
        """
        super().__init__()
        self.use_object_color = use_object_color
        self.colorpicker = ColorPicker(color)
        self.checkbox = QCheckBox()
        self.checkbox.setText(translate("Render", "Use object color"))
        self.setLayout(QHBoxLayout())
        self.layout().addWidget(self.colorpicker)
        self.layout().addWidget(self.checkbox)
        self.layout().setContentsMargins(0, 0, 0, 0)
        QObject.connect(
            self.checkbox,
            SIGNAL("stateChanged(int)"),
            self.on_object_color_change,
        )
        self.checkbox.setChecked(use_object_color)

    def get_color_text(self):
        """Get color picker value, in text format."""
        return self.colorpicker.get_color_text()

    def get_use_object_color(self):
        """Get 'use object color' checkbox value."""
        return self.checkbox.isChecked()

    def get_value(self):
        """Get widget output value."""
        res = ["Object"] if self.get_use_object_color() else []
        res += [self.get_color_text()]
        return ";".join(res)

    def setToolTip(self, desc):
        """Set widget tooltip."""
        self.colorpicker.setToolTip(desc)

    def on_object_color_change(self, state):
        """Respond to checkbox change event."""
        self.colorpicker.setEnabled(not state)


class MaterialSettingsTaskPanel:
    """Task panel to edit Material render settings."""

    NONE_MATERIAL_TYPE = QT_TRANSLATE_NOOP(
        "MaterialSettingsTaskPanel", "<None>"
    )

    def __init__(self, obj=None):
        """Initialize task panel."""
        self.form = Gui.PySideUic.loadUi(TASKPAGE)
        self.tabs = self.form.RenderTabs
        self.tabs.setCurrentIndex(0)
        self.layout = self.tabs.findChild(QFormLayout, "FieldsLayout")
        self.material_type_combo = self.form.findChild(
            QComboBox, "MaterialType"
        )

        # Initialize material name combo
        self.material_combo = self.form.MaterialNameLayout.itemAt(0).widget()
        self.existing_materials = {
            obj.Label: obj
            for obj in App.ActiveDocument.Objects
            if is_valid_material(obj)
        }
        self.material_combo.addItems(list(self.existing_materials.keys()))
        self.material_combo.currentTextChanged.connect(
            self.on_material_name_changed
        )

        # Initialize material type combo
        # Note: itemAt(0) is label, itemAt(1) is combo
        self.material_type_combo = self.form.findChild(
            QComboBox, "MaterialType"
        )
        material_type_set = [
            MaterialSettingsTaskPanel.NONE_MATERIAL_TYPE
        ] + list(STD_MATERIALS)
        self.material_type_combo.addItems(material_type_set)
        self.material_type_combo.currentTextChanged.connect(
            self.on_material_type_changed
        )
        self._set_layout_visible("FieldsLayout", False)
        self.fields = []

        # Initialize Father layout
        self._set_layout_visible("FatherLayout", False)
        self.father_field = self.form.FatherLayout.itemAt(1).widget()

        # Initialize Passthru Renderers selector
        rdrwidget = self.form.findChild(QListWidget, "Renderers")
        for rdr in VALID_RENDERERS:
            item = QListWidgetItem()
            item.setText(rdr)
            item.setIcon(QIcon(os.path.join(ICONDIR, f"{rdr}.svg")))
            rdrwidget.addItem(item)
        rdrwidget.setViewMode(QListView.IconMode)
        rdrwidget.setIconSize(QSize(48, 48))
        rdrwidget.setMaximumWidth(96)
        rdrwidget.setSpacing(6)
        rdrwidget.setMovement(QListView.Static)
        rdrwidget.currentTextChanged.connect(
            self.on_passthrough_renderer_changed
        )
        self.passthru_rdr = rdrwidget
        self.passthru = self.form.findChild(QPlainTextEdit, "PassthroughEdit")
        self.passthru.textChanged.connect(self.on_passthrough_text_changed)
        self.passthru_cache = {}
        self._set_layout_visible("PassthruLayout", False)

        # Get selected material and initialize material type combo with it
        selection = {obj.Label for obj in Gui.Selection.getSelection()}
        selected_materials = selection & self.existing_materials.keys()
        try:
            selected_material = selected_materials.pop()
        except KeyError:
            pass
        else:
            self.material_combo.setCurrentText(selected_material)

    def on_material_name_changed(self, material_name):
        """Respond to material name changed event."""
        # Clear passthrough cache
        self.passthru_cache = {}

        # Find material
        try:
            material = self.existing_materials[material_name]
        except KeyError:
            # Unknown material: disable everything
            self._set_layout_visible("FieldsLayout", False)
            self._set_layout_visible("FatherLayout", False)
            self._set_layout_visible("PassthruLayout", False)
            return

        # Retrieve material type
        self._set_layout_visible("FieldsLayout", True)
        material_type_combo = self.form.findChild(QComboBox, "MaterialType")
        try:
            material_type = material.Material["Render.Type"]
        except KeyError:
            material_type_combo.setCurrentIndex(0)
        else:
            if not material_type:
                material_type = MaterialSettingsTaskPanel.NONE_MATERIAL_TYPE
            material_type_combo.setCurrentText(material_type)

        # Retrieve passthrough
        self._set_layout_visible("PassthruLayout", True)
        try:
            renderer = self.passthru_rdr.currentItem().text()
        except AttributeError:
            renderer = None
        self._populate_passthru(renderer, material)

        # Retrieve material father
        self._set_layout_visible("FatherLayout", True)
        try:
            father = material.Material["Father"]
        except KeyError:
            father = ""
        finally:
            self.father_field.setText(father)

    def on_material_type_changed(self, material_type):
        """Respond to material type changed event."""
        # Get parameters list
        try:
            params = STD_MATERIALS_PARAMETERS[material_type]
        except KeyError:
            self._delete_fields()
        else:
            self._delete_fields()
            mat_name = self.material_combo.currentText()
            for param in params:
                value = self.existing_materials[mat_name].Material.get(
                    f"Render.{material_type}.{param.name}"
                )
                self._add_field(param, value)

    def on_passthrough_renderer_changed(self, renderer):
        """Respond to passthrough renderer changed event."""
        mat_name = self.material_combo.currentText()
        material = self.existing_materials[mat_name]
        self._populate_passthru(renderer, material)

    def on_passthrough_text_changed(self):
        """Respond to passthrough renderer changed event."""
        rdr = self.passthru_rdr.currentItem()
        if not rdr:
            return
        text = self.passthru.toPlainText()
        self.passthru_cache[rdr.text()] = text

    PASSTHROUGH_KEYS = {r: passthrough_keys(r) for r in VALID_RENDERERS}

    def _populate_passthru(self, renderer, material):
        """Populate passthrough edit field."""
        # If no renderer or no material provided, disable field and quit
        if not renderer or not material:
            self.passthru.setPlainText("")
            self.passthru.setEnabled(False)
            return

        self.passthru.setEnabled(True)

        # If renderer passthrough is already in cache (and possibly modified),
        # use the cache; otherwise, retrieve it from 'material'.
        try:
            text = self.passthru_cache[renderer]
        except KeyError:
            keys = self.PASSTHROUGH_KEYS[renderer]
            common_keys = keys & material.Material.keys()
            lines = [material.Material[k] for k in sorted(common_keys)]
            text = "\n".join(lines)

        self.passthru.setPlainText(text)

    def _set_layout_visible(self, layout_name, flag):
        """Make a layout visible/invisible, according to flag."""
        layout = self.form.findChild(QLayout, layout_name)
        for index in range(layout.count()):
            item = layout.itemAt(index)
            item.widget().setVisible(flag)

    def _add_field(self, param, value):
        """Add a field to the task panel."""
        name = param.name
        if param.type == "float":
            widget = QLineEdit()
            widget.setAlignment(Qt.AlignRight)
            widget.setValidator(QDoubleValidator())
            try:
                value = QLocale().toString(float(value))
            except (ValueError, TypeError):
                value = None
            widget.setText(value)
            self.fields.append(
                (name, lambda: QLocale().toDouble(widget.text())[0])
            )
        elif param.type == "RGB":
            if value:
                parsedvalue = parse_csv_str(value)
                if "Object" not in parsedvalue:
                    color = str2rgb(parsedvalue[0])
                    use_object_color = False
                else:
                    use_object_color = True
                    if len(parsedvalue) > 1:
                        color = str2rgb(parsedvalue[1])
                    else:
                        color = (0.8, 0.8, 0.8)
                qcolor = QColor.fromRgbF(*color)
                widget = ColorPickerExt(qcolor, use_object_color)
            else:
                widget = ColorPickerExt()
            self.fields.append((name, widget.get_value))
        else:
            widget = QLineEdit()
            self.fields.append((name, widget.text))
        widget.setToolTip(param.desc)
        layout = self.form.findChild(QLayout, "FieldsLayout")
        layout.addRow(f"{param.name}:", widget)

    def _delete_fields(self):
        """Delete all fields, except the first one (MaterialType selector)."""
        layout = self.form.findChild(QLayout, "FieldsLayout")
        for i in reversed(range(layout.count())):
            widget = layout.itemAt(i).widget()
            if widget.objectName() not in (
                "MaterialType",
                "MaterialTypeLabel",
            ):
                widget.setParent(None)
        self.fields = []

    def _write_fields(self):
        """Write task panel fields to FreeCAD material."""
        # Find material
        mat_name = self.material_combo.currentText()
        try:
            material = self.existing_materials[mat_name]
        except KeyError:
            return
        tmp_mat = material.Material.copy()

        # Set render type and associated fields
        if self.material_type_combo.currentIndex():
            render_type = self.material_type_combo.currentText()
            if render_type == MaterialSettingsTaskPanel.NONE_MATERIAL_TYPE:
                render_type = ""
            tmp_mat["Render.Type"] = str(render_type)

            # Set fields
            for field in self.fields:
                field_name, get_value = field
                param_name = f"Render.{render_type}.{field_name}"
                tmp_mat[param_name] = str(get_value())

        # Set passthru
        pthr_keys = self.PASSTHROUGH_KEYS
        for rdr, text in self.passthru_cache.items():
            # Clear existing lines for rdr
            for key in pthr_keys[rdr]:
                tmp_mat.pop(key, None)
            # Fill with new lines for rdr
            lines = dict(zip(sorted(pthr_keys[rdr]), text.splitlines()))
            tmp_mat.update(lines)

        # Set father
        father = self.father_field.text()
        if father:
            tmp_mat["Father"] = str(father)

        # Write to material
        material.Material = tmp_mat

    def accept(self):
        """Respond to user acceptation (OK button).

        Write all task panel fields to material
        """
        self._write_fields()
        Gui.ActiveDocument.resetEdit()
        Gui.Control.closeDialog()
        # Modifying material may require projects recomputation:
        App.ActiveDocument.recompute()
        return True


class MaterialTaskPanel(_ArchMaterialTaskPanel):
    """Task panel to create and edit Material.

    Essentially derived from Arch Material Task Panel, except for
    material cards directory.
    """

    def __init__(self, obj=None):
        super().__init__(obj)
        self.form.setWindowTitle("Render Material")

    def fillMaterialCombo(self):
        """Fill Material combo box.

        Look for cards in both Workbench directory and Materials sub-folder
        in the user folder.
        User cards with same name will override system cards.
        """
        paths = [
            ("USER", USERMATERIALDIR),
            ("RENDER", WBMATERIALDIR),
        ]
        params = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Render")
        if params.GetBool("UseFCDMaterials", False):
            paths.append(("FREECAD", FCDMATERIALDIR))
        self.cards = {
            f"{d} - {os.path.splitext(f)[0]}": os.path.join(p, f)
            for d, p in paths
            if os.path.exists(p)
            for f in os.listdir(p)
            if os.path.splitext(f)[1].upper() == ".FCMAT"
        }
        for k in sorted(self.cards.keys()):
            self.form.comboBox_MaterialsInDir.addItem(k)
