"""Import Word (.docx) files into drafting views as editable text notes."""
import os

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
from System.Windows import TextTrimming, Thickness
from System.Windows.Controls import CheckBox, TextBlock
from System.Windows.Input import Cursors, Mouse
from pyrevit import revit, DB, forms, script
from pyrevit.revit import query
import word_notes

VIEW_SCALE = 12
XAML = os.path.join(os.path.dirname(__file__), "ImportWordDoc.xaml")


class ImportForm(forms.WPFWindow):
    """One dialog for every choice: the Word files, which pages of each, the text type and
    the column size. After ShowDialog, `result` holds the choices, or None if cancelled."""

    def __init__(self, type_names, default_type, config):
        forms.WPFWindow.__init__(self, XAML)
        self.config = config
        self.docs = []
        self.result = None
        self._syncing = False
        self.text_type.ItemsSource = type_names
        saved = config.get_option("text_type", default_type)
        self.text_type.SelectedItem = saved if saved in type_names else default_type
        self.col_width.Text = str(config.get_option("col_width_in", 6))
        self.col_height.Text = str(config.get_option("col_height_in", 30))
        self.show_pages(None)

    def current(self):
        i = self.files_list.SelectedIndex
        return self.docs[i] if 0 <= i < len(self.docs) else None

    def update_label(self, entry):
        entry["label"].Text = u"{}   ({} of {} pages)".format(
            os.path.basename(entry["path"]), len(entry["pages"]), entry["count"])

    def refresh_files(self, select):
        self.files_list.Items.Clear()
        for entry in self.docs:
            self.files_list.Items.Add(entry["label"])
        if self.docs:
            self.files_list.SelectedIndex = max(0, min(select, len(self.docs) - 1))
        else:
            self.show_pages(None)

    def add_files(self, sender, args):
        paths = forms.pick_file(file_ext="docx", multi_file=True, title="Word documents to import")
        if not paths:
            return
        known = set(os.path.normcase(e["path"]) for e in self.docs)
        problems = []
        Mouse.OverrideCursor = Cursors.Wait
        try:
            for path in paths:
                if os.path.normcase(path) in known:
                    continue
                try:
                    items, how = word_notes.load(path)
                except Exception as ex:
                    problems.append(u"{}: could not read it ({})".format(os.path.basename(path), ex))
                    continue
                if not any(getattr(it, "runs", True) for it in items):
                    problems.append(u"{}: no text found".format(os.path.basename(path)))
                    continue
                count = word_notes.page_count(items)
                entry = {"path": path, "items": items, "how": how, "count": count,
                         "pages": set(range(1, count + 1)), "previews": word_notes.page_previews(items),
                         "label": TextBlock()}
                self.update_label(entry)
                self.docs.append(entry)
                known.add(os.path.normcase(path))
        finally:
            Mouse.OverrideCursor = None
        self.refresh_files(len(self.docs) - 1)
        self.status.Text = u"\n".join(problems)

    def remove_file(self, sender, args):
        i = self.files_list.SelectedIndex
        if 0 <= i < len(self.docs):
            del self.docs[i]
            self.refresh_files(i)

    def file_selected(self, sender, args):
        self.show_pages(self.current())

    def show_pages(self, entry):
        self._syncing = True
        try:
            self.pages_list.Items.Clear()
            if entry is None:
                self.pages_title.Text = "Pages"
                self.pages_source.Text = "Add a Word document, then choose the pages to import."
                self.pages_text.Text = ""
                return
            self.pages_title.Text = u"Pages in {}".format(os.path.basename(entry["path"]))
            self.pages_source.Text = entry["how"]
            for n in range(1, entry["count"] + 1):
                text = TextBlock()
                text.Text = u"Page {}    {}".format(n, entry["previews"][n])
                text.TextTrimming = TextTrimming.CharacterEllipsis
                box = CheckBox()
                box.Content = text
                box.Tag = n
                box.IsChecked = n in entry["pages"]
                box.Margin = Thickness(2)
                box.Checked += self.page_toggled
                box.Unchecked += self.page_toggled
                self.pages_list.Items.Add(box)
            self.pages_text.Text = word_notes.format_pages(entry["pages"])
        finally:
            self._syncing = False

    def page_toggled(self, sender, args):
        entry = self.current()
        if self._syncing or entry is None:
            return
        if sender.IsChecked:
            entry["pages"].add(sender.Tag)
        else:
            entry["pages"].discard(sender.Tag)
        self.pages_text.Text = word_notes.format_pages(entry["pages"])
        self.update_label(entry)

    def set_pages(self, pages):
        entry = self.current()
        if entry is None:
            return
        entry["pages"] = set(pages)
        self.update_label(entry)
        self.show_pages(entry)

    def select_all(self, sender, args):
        entry = self.current()
        if entry is not None:
            self.set_pages(range(1, entry["count"] + 1))

    def select_none(self, sender, args):
        self.set_pages([])

    def apply_range(self, sender, args):
        entry = self.current()
        if entry is None:
            return
        try:
            self.set_pages(word_notes.parse_pages(self.pages_text.Text, entry["count"]))
            self.status.Text = ""
        except ValueError as ex:
            self.status.Text = str(ex)

    def read_inches(self, box, name):
        try:
            value = float(box.Text.replace('"', "").strip())
        except ValueError:
            raise ValueError(u"{} must be a number of inches.".format(name))
        if value <= 0:
            raise ValueError(u"{} must be greater than zero.".format(name))
        return value

    def do_import(self, sender, args):
        if not self.docs:
            self.status.Text = "Add at least one Word document."
            return
        empty = [os.path.basename(e["path"]) for e in self.docs if not e["pages"]]
        if empty:
            self.status.Text = u"No pages chosen for: " + u", ".join(empty)
            return
        if self.text_type.SelectedItem is None:
            self.status.Text = "Choose a text type."
            return
        try:
            width = self.read_inches(self.col_width, "Column width")
            height = self.read_inches(self.col_height, "Column height")
        except ValueError as ex:
            self.status.Text = str(ex)
            return
        self.config.text_type = self.text_type.SelectedItem
        self.config.col_width_in = width
        self.config.col_height_in = height
        script.save_config()
        self.result = {"docs": self.docs, "text_type": self.text_type.SelectedItem,
                       "col_width": width / 12.0, "col_height": height / 12.0}
        self.Close()

    def cancel(self, sender, args):
        self.Close()


doc = revit.doc
types = dict((query.get_name(t), t) for t in DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType))
default = query.get_name(doc.GetElement(doc.GetDefaultElementTypeId(DB.ElementTypeGroup.TextNoteType)))
names = [default] + sorted(n for n in types if n != default)

form = ImportForm(names, default, script.get_config())
form.ShowDialog()
choice = form.result
if not choice:
    script.exit()

text_type = types[choice["text_type"]]
size_param = text_type.get_Parameter(DB.BuiltInParameter.TEXT_SIZE)
block_gap = size_param.AsDouble() if size_param is not None else 0.1 / 12.0

existing = set(v.Name for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewDrafting) if not v.IsTemplate)
replacing = [word_notes.view_name(e["path"]) for e in choice["docs"] if word_notes.view_name(e["path"]) in existing]
if replacing and not forms.alert("These drafting views already exist. Their text notes and lines will be replaced:\n\n"
                                 + "\n".join(replacing), yes=True, no=True):
    script.exit()

done, last_view = [], None
for entry in choice["docs"]:
    items = word_notes.select_pages(entry["items"], entry["pages"])
    with revit.Transaction("Import Word Doc"):
        view = word_notes.drafting_view(doc, word_notes.view_name(entry["path"]), VIEW_SCALE)
        notes, lines, tables = word_notes.place(doc, view, items, text_type.Id,
                                                choice["col_width"], choice["col_height"], block_gap)
    done.append(u"{} (pages {}): {} text notes, {} tables".format(
        view.Name, word_notes.format_pages(entry["pages"]), len(notes), tables))
    last_view = view

if last_view is not None:
    revit.uidoc.ActiveView = last_view
forms.alert(u"Imported:\n" + u"\n".join(done))
